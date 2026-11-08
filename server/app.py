"""Porchlight server: the box (real or simulated), the demo screen, the
coordinator dashboard and the volunteer page all talk to this one API.

Run from the repo root: python -m uvicorn server.app:app --host 0.0.0.0 --port 8000"""
import asyncio
import hashlib
import hmac
import json
import secrets
import time as _time
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta
from pathlib import Path

import httpx
from fastapi import Body, Depends, FastAPI, Header, HTTPException, Request
from fastapi.staticfiles import StaticFiles

from . import auth, explain, grid, settings
from .rules import ESCALATE_AFTER, ESCALATE_HELP_AFTER, WAVE_WAIT, Engine, Resident, hm
from .store import MemoryStore, PgStore

ROOT = Path(__file__).resolve().parent.parent
PEOPLE = json.loads((ROOT / "data" / "demo_people.json").read_text())
PLACE = {r["id"]: (r.get("lat"), r.get("lon")) for r in PEOPLE["residents"]}
REPLAY_START = datetime(2024, 1, 13, 15, 15, tzinfo=grid.TZ)   # 15 minutes before the AESO's alert
DEFAULT_SPEED = 30
SETUP_CODE = secrets.token_hex(3).upper()   # printed in the server window; needed to change keys remotely
last_poll = {}   # resident -> real time.monotonic() of the box's last poll


class Clock:
    """Live time, or Jan 13 2024 running `speed` times faster than real time."""

    def __init__(self):
        self.mode, self.speed = "live", 1.0

    def replay(self, start, speed):
        self.mode, self.base, self.real0, self.speed = "replay", start, _time.monotonic(), speed

    def live(self):
        self.mode, self.speed = "live", 1.0

    def now(self):
        if self.mode == "live":
            return datetime.now(grid.TZ)
        return self.base + timedelta(seconds=(_time.monotonic() - self.real0) * self.speed)

    def set_speed(self, speed):
        if self.mode == "replay":
            self.base, self.real0 = self.now(), _time.monotonic()
            self.speed = speed

    def jump(self, to):
        self.base, self.real0 = to, _time.monotonic()


clock = Clock()
engine = Engine([Resident.from_json(r) for r in PEOPLE["residents"]], PEOPLE["volunteers"])
replay, live = grid.Replay(), grid.Live()
store = MemoryStore()
store_error = None
http: httpx.AsyncClient = None


def token_for(vid):
    secret = settings.get("PORCHLIGHT_LINK_SECRET")
    if secret:
        return hmac.new(secret.encode(), vid.encode(), hashlib.sha256).hexdigest()[:16]
    return next(v["token"] for v in PEOPLE["volunteers"] if v["id"] == vid)


def volunteer_for(token):
    for v in PEOPLE["volunteers"]:
        if hmac.compare_digest(token_for(v["id"]), token):
            return v
    raise HTTPException(404, "Unknown volunteer link")


def device(x_device_key: str = Header(default="")):
    key = settings.get("PORCHLIGHT_DEVICE_KEY")
    if key and not hmac.compare_digest(x_device_key, key):
        raise HTTPException(401, "Bad device key")


def setup_access(request: Request, x_setup_code: str = Header(default="")):
    """Keys can be changed from the computer running the server, or from
    anywhere with the code printed in its window."""
    if request.client and request.client.host in ("127.0.0.1", "::1"):
        return True
    if hmac.compare_digest(x_setup_code.strip().upper(), SETUP_CODE):
        return True
    raise HTTPException(403, "Enter the setup code shown in the server window")


def conditions(now):
    return replay.conditions(now) if clock.mode == "replay" else live.conditions(now)


async def connect_store():
    """Switch to Postgres / Tiger Data when a database URL is set, or back to
    memory when it is cleared. A failed connection keeps the current store."""
    global store, store_error
    url = settings.get("DATABASE_URL")
    new = PgStore(url) if url else MemoryStore()
    try:
        await new.init()
        for start in sorted(replay.hours):
            await new.add_grid(start, "aeso_ets_2024", replay.conditions(start))
    except Exception as e:
        store_error = f"{type(e).__name__}: {e}"[:300]
        if "ProactorEventLoop" in store_error:  # Windows: psycopg's async mode needs the selector loop
            store_error = "On Windows, start the server with --loop asyncio:SelectorEventLoop (see the README), then save again."
        return False
    old, store, store_error = store, new, None
    if isinstance(old, PgStore) and old.conn:
        await old.conn.close()
    return True


# ---- background work --------------------------------------------------------
async def write_messages(a):
    langs = {"en"} | {engine.volunteers[v]["language"] for v in a.chain if v in engine.volunteers}
    for lang in sorted(langs):
        text, source = await explain.write(http, a.rule, a.reason, a.facts, lang)
        a.messages[lang] = text
        a.message_source = source


async def after_opened(alerts, now):
    for a in alerts:
        await store.add_alert_log(now, a.id, a.resident_id, "opened", a.reason)
        asyncio.create_task(write_messages(a))


async def ticker():
    last = clock.now()
    while True:
        await asyncio.sleep(0.5)
        now = clock.now()
        if clock.mode == "replay":
            for e in replay.passed_events(last, now):
                engine.log(e["time"], "grid", f"AESO: {e['text']}")
        last = now
        limit = 60 if clock.mode == "replay" else 20 * 60   # real seconds of silence
        quiet = {rid for rid, t in last_poll.items() if _time.monotonic() - t >= limit}
        await after_opened(engine.tick(now, conditions(now), quiet), now)


async def live_poller():
    while True:
        if clock.mode == "live":
            row = await live.refresh(http, settings.get("AESO_API_KEY"))
            if row.get("ail_mw") is not None:
                await store.add_grid(datetime.now(grid.TZ), "aeso_api", row)
        await asyncio.sleep(60)


@asynccontextmanager
async def lifespan(app):
    global http
    http = httpx.AsyncClient()
    settings.load_remembered()
    await connect_store()
    start_replay(DEFAULT_SPEED)
    print(f"\n  Porchlight is running. Open http://localhost:8000\n"
          f"  Setup code (to change keys from another device): {SETUP_CODE}\n", flush=True)
    tasks = [asyncio.create_task(ticker()), asyncio.create_task(live_poller())]
    yield
    for t in tasks:
        t.cancel()
    await http.aclose()


app = FastAPI(title="Porchlight", lifespan=lifespan)


def start_replay(speed):
    engine.reset()
    clock.replay(REPLAY_START, speed)
    last_poll.clear()       # a box that isn't open for this run shouldn't count as offline
    engine.seed_morning(REPLAY_START)
    engine.log(REPLAY_START, "mode", f"Replaying Saturday, January 13, 2024 at {speed:g}x.")


# ---- views --------------------------------------------------------------------
def alert_view(a, lang="en"):
    if not a:
        return None
    return {"id": a.id, "rule": a.rule, "reason": a.reason, "opened_at": a.opened_at.isoformat(),
            "asking": engine.name(a.responder), "asking_id": a.responder,
            "chain": [engine.name(v) for v in a.chain], "step": a.step,
            "going": engine.name(a.ack_by) if a.ack_by else None,
            "eta": hm(a.eta) if a.eta else None,
            "message": a.messages.get(lang) or a.messages.get("en"),
            "message_source": getattr(a, "message_source", None)}


def resident_view(rid):
    r, s = engine.residents[rid], engine.state[rid]
    a = engine.current_alert(rid)
    if a:
        status = "visitor" if a.ack_by else ("help" if a.rule == "help" else "alert")
    elif s.wave_at:
        status = "asked"
    elif s.last_ok and s.last_ok.date() == clock.now().date():
        status = "ok"
    else:
        status = "waiting"
    lang = engine.volunteers.get(a.responder, {}).get("language", "en") if a else "en"
    seen = last_poll.get(rid)
    return {"id": rid, "name": r.name, "community": r.community, "simulated": r.simulated,
            "lat": PLACE[rid][0], "lon": PLACE[rid][1],
            "status": status, "last_ok": hm(s.last_ok) if s.last_ok else None,
            "last_motion": hm(s.last_motion) if s.last_motion else None,
            "cutoff": hm(datetime.combine(date.today(), r.cutoff)), "alert": alert_view(a, lang),
            "box": box(rid), "box_online": seen is not None and _time.monotonic() - seen < 10}


# ---- coordinator API --------------------------------------------------------------
@app.get("/api/config")
async def config():
    return {"auth0": auth.public_config(), "store": store.kind, "store_error": store_error,
            "gemini": bool(settings.get("GEMINI_API_KEY")), "aeso_key": bool(settings.get("AESO_API_KEY"))}


@app.get("/api/state")
async def state(who: str = Depends(auth.coordinator)):
    now = clock.now()
    return {"now": now.isoformat(), "clock": f"{now:%a %b} {now.day}, {now.year} · {hm(now)}",
            "time": hm(now), "date": f"{now:%A, %B} {now.day}, {now.year}",
            "mode": clock.mode, "speed": clock.speed, "conditions": conditions(now),
            "wave": engine.wave_active, "residents": [resident_view(rid) for rid in engine.residents],
            "feed": engine.feed[-60:][::-1], "who": who}


@app.get("/api/grid/day/{day}")
async def grid_day(day: date, who: str = Depends(auth.coordinator)):
    start = datetime.combine(day, datetime.min.time(), grid.TZ)
    source = "aeso_ets_2024" if day.year == 2024 else "aeso_api"
    rows = await store.grid_hourly(start, start + timedelta(days=1), source)
    events = [{"time": e["time"].isoformat(), "text": e["text"], "level": e["level"]}
              for e in replay.events if e["time"].date() == day]
    return {"source": source, "store": store.kind,
            "rows": [dict(r, time=r["time"].isoformat()) for r in rows], "events": events}


@app.get("/api/residents/{rid}/events")
async def resident_events(rid: str, who: str = Depends(auth.coordinator)):
    if rid not in engine.residents:
        raise HTTPException(404)
    await store.add_access(who, f"viewed what {engine.residents[rid].name}'s box sent")
    rows = await store.recent_events(rid, 15)
    return [dict(r, time=r["time"].isoformat()) for r in rows]


@app.get("/api/access-log")
async def access_log(who: str = Depends(auth.coordinator)):
    rows = await store.recent_access(20)
    return [dict(r, time=r["time"].isoformat()) for r in rows]


@app.post("/api/access")
async def access(what: str = Body(embed=True), who: str = Depends(auth.coordinator)):
    await store.add_access(who, what[:200])
    return {"ok": True}


@app.post("/api/mode")
async def mode(mode: str = Body(embed=True), speed: float = Body(DEFAULT_SPEED, embed=True),
               who: str = Depends(auth.coordinator)):
    if mode == "replay":
        start_replay(max(1.0, min(speed, 600.0)))
    elif mode == "live":
        engine.reset()
        last_poll.clear()
        clock.live()
        engine.log(clock.now(), "mode", "Live: AESO and weather now.")
        asyncio.create_task(live.refresh(http, settings.get("AESO_API_KEY")))
    else:
        raise HTTPException(400, "mode is live or replay")
    return {"ok": True}


@app.post("/api/speed")
async def speed(speed: float = Body(embed=True), who: str = Depends(auth.coordinator)):
    clock.set_speed(max(0.0, min(speed, 600.0)))
    return {"ok": True}


def next_moment(now):
    """The next time something happens on its own: an AESO event, a check-in
    running out, or an unanswered request moving to the next person."""
    times = [e["time"] for e in replay.events]
    for s in engine.state.values():
        if s.wave_at:
            times.append(s.wave_at + WAVE_WAIT)
    for a in engine.alerts.values():
        if not a.closed_at and not a.ack_by and a.step < len(a.chain) - 1:
            times.append(a.step_at + (ESCALATE_HELP_AFTER if a.rule == "help" else ESCALATE_AFTER))
    later = [t for t in times if t > now + timedelta(seconds=5)]
    return min(later) if later else now + timedelta(minutes=15)


@app.post("/api/skip")
async def skip(who: str = Depends(auth.coordinator)):
    if clock.mode != "replay":
        raise HTTPException(400, "Skipping only works in the replay")
    to = next_moment(clock.now())
    clock.jump(to + timedelta(seconds=1))
    return {"to": hm(to)}


@app.post("/api/residents/{rid}/press")
async def screen_press(rid: str, kind: str = Body(embed=True), who: str = Depends(auth.coordinator)):
    """The demo screen's box: the same as the real box pressing a button."""
    return await device_event(rid, kind)


@app.post("/api/alerts/{alert_id}/{action}")
async def coordinator_action(alert_id: int, action: str, who: str = Depends(auth.coordinator)):
    if action not in ("resolved", "cant"):
        raise HTTPException(400)
    if not engine.volunteer_action("coordinator", alert_id, action, clock.now()):
        raise HTTPException(409, "Alert already closed")
    await store.add_alert_log(clock.now(), alert_id, engine.alerts[alert_id].resident_id, action, who)
    return {"ok": True}


@app.get("/api/volunteer-links")
async def volunteer_links(who: str = Depends(auth.coordinator)):
    return [{"id": v["id"], "name": v["name"], "language": v["language"], "token": token_for(v["id"]),
             "path": f"/volunteer.html?v={token_for(v['id'])}"} for v in PEOPLE["volunteers"]]


# ---- setup: keys typed in the browser -------------------------------------------------
LABELS = {
    "GEMINI_API_KEY": "Gemini API key", "GEMINI_MODEL": "Gemini model (optional)",
    "AESO_API_KEY": "AESO API key", "DATABASE_URL": "Tiger Data connection string",
    "AUTH0_DOMAIN": "Auth0 domain", "AUTH0_CLIENT_ID": "Auth0 client ID", "AUTH0_AUDIENCE": "Auth0 API audience",
    "PORCHLIGHT_DEVICE_KEY": "Box key", "PORCHLIGHT_LINK_SECRET": "Volunteer link secret",
}


@app.get("/api/setup")
async def setup_state(request: Request):
    local = bool(request.client and request.client.host in ("127.0.0.1", "::1"))
    return {"local": local, "can_remember": settings.can_remember(), "store": store.kind,
            "store_error": store_error,
            "fields": setup_fields()}


def setup_fields():
    return {name: dict(settings.describe(name), label=LABELS[name]) for name in settings.FIELDS}


@app.post("/api/setup", dependencies=[Depends(setup_access)])
async def setup_save(values: dict = Body(embed=True), remember: bool = Body(False, embed=True)):
    unknown = set(values) - set(settings.FIELDS)
    if unknown:
        raise HTTPException(400, f"Unknown setting {sorted(unknown)}")
    db_before = settings.get("DATABASE_URL")
    for name, value in values.items():
        settings.put(name, value if isinstance(value, str) else "", remember)
    if settings.get("DATABASE_URL") != db_before:
        await connect_store()
    if clock.mode == "live":
        asyncio.create_task(live.refresh(http, settings.get("AESO_API_KEY")))
    return {"store": store.kind, "store_error": store_error, "fields": setup_fields()}


@app.post("/api/setup/test/{service}", dependencies=[Depends(setup_access)])
async def setup_test(service: str, values: dict = Body(default={}, embed=True)):
    """Try a service with the value typed in the form (or the saved one)."""
    val = lambda name: (values.get(name) or "").strip() or settings.get(name)
    try:
        if service == "gemini":
            key = val("GEMINI_API_KEY")
            if not key:
                return {"ok": False, "detail": "No key entered"}
            text = await explain.ask(http, key, "Reply with exactly: Porchlight is connected.",
                                     system="Reply with only the requested words.")
            return {"ok": True, "detail": f"Gemini answered: {text[:80]}"}
        if service == "aeso":
            key = val("AESO_API_KEY")
            if not key:
                return {"ok": False, "detail": "No key entered"}
            row = await grid.fetch_aeso(http, key)
            return {"ok": True, "detail": f"Alberta's demand right now: {row['ail_mw']:,.0f} MW"}
        if service == "database":
            url = val("DATABASE_URL")
            if not url:
                return {"ok": False, "detail": "No connection string entered"}
            import psycopg
            async with await psycopg.AsyncConnection.connect(url, connect_timeout=8) as conn:
                cur = await conn.execute("SELECT 1 FROM pg_available_extensions WHERE name = 'timescaledb'")
                ts = await cur.fetchone() is not None
            return {"ok": True, "detail": "Connected. TimescaleDB is available." if ts
                    else "Connected, but TimescaleDB isn't on this database (plain Postgres still works)."}
        if service == "auth0":
            domain = val("AUTH0_DOMAIN")
            if not domain:
                return {"ok": False, "detail": "No domain entered"}
            r = await http.get(f"https://{domain}/.well-known/openid-configuration", timeout=8)
            r.raise_for_status()
            missing = [n for n in ("AUTH0_CLIENT_ID", "AUTH0_AUDIENCE") if not val(n)]
            if missing:
                return {"ok": False, "detail": "Domain works. Still needed: client ID and API audience."}
            return {"ok": True, "detail": f"Auth0 tenant found: {r.json()['issuer']}"}
        if service == "weather":
            return {"ok": True, "detail": f"Calgary is {await grid.fetch_temp(http):.0f} °C right now"}
    except httpx.HTTPStatusError as e:
        hint = {401: "the key was refused", 403: "the key was refused", 404: "not found (check the spelling or model name)",
                429: "rate limited, try again in a minute"}.get(e.response.status_code, "")
        return {"ok": False, "detail": f"HTTP {e.response.status_code} {hint}".strip()}
    except Exception as e:
        return {"ok": False, "detail": f"{type(e).__name__}: {str(e)[:160]}"}
    raise HTTPException(404, "Unknown service")


# ---- volunteer API (secret link, no account) ----------------------------------------
@app.get("/api/v/{token}")
async def volunteer_home(token: str):
    v = volunteer_for(token)
    tasks = []
    for a in engine.alerts.values():
        if a.closed_at or v["id"] not in (a.responder, a.ack_by):
            continue
        r = engine.residents[a.resident_id]
        view = alert_view(a, v["language"])
        view.update(name=r.name, community=r.community,
                    address=r.address if a.ack_by == v["id"] else None, mine=a.ack_by == v["id"])
        tasks.append(view)
    c = conditions(clock.now())
    return {"name": v["name"], "language": v["language"], "clock": hm(clock.now()),
            "temp_c": c.get("temp_c"), "level": c.get("level"), "tasks": tasks}


@app.post("/api/v/{token}/alerts/{alert_id}")
async def volunteer_act(token: str, alert_id: int, action: str = Body(embed=True),
                        eta_min: int = Body(20, embed=True)):
    v = volunteer_for(token)
    if action not in ("going", "cant", "resolved"):
        raise HTTPException(400)
    now = clock.now()
    if not engine.volunteer_action(v["id"], alert_id, action, now, eta_min):
        raise HTTPException(409, "This request was already handled")
    a = engine.alerts[alert_id]
    await store.add_alert_log(now, alert_id, a.resident_id, action, v["id"])
    if action == "going":
        await store.add_access(v["id"], f"saw {engine.residents[a.resident_id].name}'s address")
    return {"ok": True}


# ---- the box ----------------------------------------------------------------------------
@app.post("/api/device/{rid}/event", dependencies=[Depends(device)])
async def device_event(rid: str, kind: str = Body(embed=True)):
    if rid not in engine.residents:
        raise HTTPException(404)
    if kind not in ("ok", "help", "motion"):
        raise HTTPException(400, "kind is ok, help or motion")
    now = clock.now()
    a = engine.device_event(rid, kind, now, conditions(now))
    await store.add_event(now, rid, kind, False)
    if kind == "help" and clock.mode == "replay" and clock.speed > 1:
        clock.set_speed(1)      # a real person pressed help: the demo now runs in real time
        engine.log(now, "mode", "Replay slowed to real time so the help call plays out live.")
    if a:
        await after_opened([a], now)
    return box(rid)


@app.get("/api/device/{rid}", dependencies=[Depends(device)])
async def device_poll(rid: str):
    if rid not in engine.residents:
        raise HTTPException(404)
    last_poll[rid] = _time.monotonic()
    engine.box_seen(rid)
    return box(rid)


def box(rid):
    s = engine.state[rid]
    return {"display": s.display, "text": s.text, "buzz": s.buzz}


app.mount("/", StaticFiles(directory=ROOT / "web", html=True), name="web")
