"""Check-in rules and escalation. No I/O here: every function takes `now`,
so the same code runs live, in the Jan 2024 replay, and in tests."""
from dataclasses import dataclass, field
from datetime import datetime, time, timedelta
import itertools

ESCALATE_AFTER = timedelta(minutes=15)
ESCALATE_HELP_AFTER = timedelta(minutes=5)
WAVE_WAIT = timedelta(minutes=30)       # how long a cold-weather check-in waits for "I'm OK"
WAVE_REPEAT = timedelta(hours=3)
RECENT_OK = timedelta(hours=1)          # an OK this recent counts as already checked in
NO_MOTION = timedelta(hours=6)
COLD_C = -25.0
STRESSED = ("alert", "emergency")

def hm(dt):
    """3:05 PM. strftime's %-I does not work on Windows."""
    return dt.strftime("%I:%M %p").lstrip("0")


REASONS = {
    "help": "Pressed the help button",
    "missed_checkin": "No \"I'm OK\" by {cutoff}",
    "no_motion": "No movement at home for 6 hours",
    "no_reply_cold": "No answer to the cold-weather check-in after 30 minutes",
    "box_offline": "The box stopped checking in (power or Wi-Fi may be out)",
}


@dataclass
class Resident:
    id: str
    name: str
    community: str
    address: str
    cutoff: time
    volunteers: list
    has_motion: bool = False
    simulated: bool = False
    script: dict = field(default_factory=dict)

    @staticmethod
    def from_json(d):
        h, m = map(int, d["cutoff"].split(":"))
        return Resident(d["id"], d["name"], d["community"], d["address"], time(h, m),
                        d["volunteers"], d.get("has_motion", False), d.get("simulated", False),
                        d.get("script", {}))


@dataclass
class Alert:
    id: int
    resident_id: str
    rule: str
    reason: str
    facts: dict
    opened_at: datetime
    chain: list                 # responders in order; the last one is the coordinator
    step: int = 0
    step_at: datetime = None
    ack_by: str = None
    eta: datetime = None
    closed_at: datetime = None
    closed_by: str = None
    messages: dict = field(default_factory=dict)   # language -> text for volunteers

    @property
    def responder(self):
        return self.chain[self.step]


@dataclass
class State:
    last_ok: datetime = None
    last_motion: datetime = None
    wave_at: datetime = None
    missed_for: object = None    # date the missed check-in alert already fired for
    motion_alert_for: datetime = None
    offline_alerted: bool = False
    alert_id: int = None
    display: str = "idle"        # idle | ok | ask | help | visitor
    text: str = ""
    buzz: int = 0                # the box buzzes whenever this number goes up


class Engine:
    def __init__(self, residents, volunteers):
        self.residents = {r.id: r for r in residents}
        self.volunteers = {v["id"]: v for v in volunteers}
        self.reset()

    def reset(self):
        self.state = {rid: State() for rid in self.residents}
        self.alerts = {}
        self.feed = []
        self.wave_active = False
        self.wave_last = None
        self._ids = itertools.count(1)

    # ---- helpers -------------------------------------------------------
    def log(self, now, kind, text, rid=None):
        self.feed.append({"t": now.isoformat(), "kind": kind, "text": text, "rid": rid})
        del self.feed[:-200]

    def name(self, who):
        if who == "coordinator":
            return "the coordinator"
        return self.volunteers.get(who, {}).get("name", who)

    def open_alert(self, rid, rule, now, facts):
        r, s = self.residents[rid], self.state[rid]
        reason = REASONS[rule].format(cutoff=hm(r.cutoff))
        a = Alert(next(self._ids), rid, rule, reason, facts, now,
                  chain=list(r.volunteers) + ["coordinator"], step_at=now)
        self.alerts[a.id] = a
        s.alert_id = a.id
        self.log(now, "alert", f"{r.name}: {reason}. Asking {self.name(a.responder)}.", rid)
        return a

    def box_seen(self, rid):
        self.state[rid].offline_alerted = False

    def current_alert(self, rid):
        a = self.alerts.get(self.state[rid].alert_id)
        return a if a and not a.closed_at else None

    def close(self, a, now, by, why):
        a.closed_at, a.closed_by = now, by
        s = self.state[a.resident_id]
        s.alert_id = None
        s.display, s.text = "ok", ""
        self.log(now, "resolved", f"{self.residents[a.resident_id].name}: {why}.", a.resident_id)

    # ---- inputs ----------------------------------------------------------
    def device_event(self, rid, kind, now, conditions=None, simulated=False):
        """kind is ok, help or motion. Returns a newly opened alert, if any."""
        r, s = self.residents[rid], self.state[rid]
        tag = " (simulated)" if simulated else ""
        a = self.current_alert(rid)
        if kind == "motion":
            s.last_motion = now
            return None
        if kind == "ok":
            s.last_ok, s.wave_at = now, None
            s.display, s.text = "ok", ""
            if a and a.rule != "help":
                self.close(a, now, rid, f"pressed I'm OK{tag}")
            else:
                self.log(now, "ok", f"{r.name} pressed I'm OK{tag}.", rid)
            return None
        if kind == "help":
            s.display, s.text = "help", "Help is being called"
            s.buzz += 1
            facts = self.facts(rid, now, conditions)
            if a:                       # upgrade whatever was open to a help alert
                a.rule, a.reason, a.facts = "help", REASONS["help"], facts
                a.step_at, a.messages = now, {}
                self.log(now, "alert", f"{r.name} pressed HELP{tag}.", rid)
                return a
            return self.open_alert(rid, "help", now, facts)
        raise ValueError(f"unknown event {kind}")

    def volunteer_action(self, vid, alert_id, action, now, eta_min=None):
        a = self.alerts.get(alert_id)
        if not a or a.closed_at:
            return False
        if vid != "coordinator" and vid not in (a.responder, a.ack_by):
            return False
        r, s = self.residents[a.resident_id], self.state[a.resident_id]
        if action == "going":
            a.ack_by, a.eta = vid, now + timedelta(minutes=int(eta_min or 20))
            s.display = "visitor"
            s.text = f"{self.name(vid)} is coming, about {hm(a.eta)}"
            s.buzz += 1
            self.log(now, "going", f"{self.name(vid)} is going to {r.name}, there by {hm(a.eta)}.", r.id)
        elif action == "cant":
            if a.ack_by == vid:
                a.ack_by, a.eta = None, None
            self.log(now, "cant", f"{self.name(vid)} can't go to {r.name}.", r.id)
            self.escalate(a, now)
        elif action == "resolved":
            self.close(a, now, vid, f"{self.name(vid)} checked in, all good")
        else:
            raise ValueError(f"unknown action {action}")
        return True

    # ---- the clock ---------------------------------------------------------
    def escalate(self, a, now):
        if a.step < len(a.chain) - 1:
            a.step, a.step_at = a.step + 1, now
            self.log(now, "escalated", f"{self.residents[a.resident_id].name}: now asking {self.name(a.responder)}.", a.resident_id)

    def facts(self, rid, now, conditions):
        r, s = self.residents[rid], self.state[rid]
        c = conditions or {}
        return {"name": r.name, "community": r.community, "time": hm(now),
                "last_ok": hm(s.last_ok) if s.last_ok else None,
                "outdoor_c": c.get("temp_c"), "grid": c.get("level")}

    def tick(self, now, conditions, quiet=()):
        """Run every rule once. `quiet` holds residents whose box has stopped
        checking in; the caller measures that in real time. Returns alerts
        opened during this tick."""
        opened = []
        cold = (conditions.get("temp_c") is not None and conditions["temp_c"] <= COLD_C
                and conditions.get("level") in STRESSED)
        if cold and (not self.wave_active or now - self.wave_last >= WAVE_REPEAT):
            self.wave_last = now
            self.log(now, "wave", f"Cold-weather check-in: {conditions['temp_c']:.0f} °C outside and the grid is on {conditions['level']}. Every box is asking.")
            for rid, s in self.state.items():
                recent = s.last_ok and now - s.last_ok < RECENT_OK
                if not self.current_alert(rid) and not recent:
                    s.wave_at, s.display, s.text = now, "ask", "Please press I'm OK"
                    s.buzz += 1
        self.wave_active = cold

        for rid, r in self.residents.items():
            s, a = self.state[rid], self.current_alert(rid)
            if r.simulated and s.wave_at and r.script.get("wave_reply_min") is not None:
                if now >= s.wave_at + timedelta(minutes=r.script["wave_reply_min"]):
                    self.device_event(rid, "ok", now, simulated=True)
                    continue
            if a:
                wait = ESCALATE_HELP_AFTER if a.rule == "help" else ESCALATE_AFTER
                if not a.ack_by and now - a.step_at >= wait:
                    self.escalate(a, now)
                continue
            if rid in quiet and not s.offline_alerted:
                s.offline_alerted = True
                opened.append(self.open_alert(rid, "box_offline", now, self.facts(rid, now, conditions)))
                continue
            if s.wave_at and now - s.wave_at >= WAVE_WAIT:
                s.wave_at = None
                opened.append(self.open_alert(rid, "no_reply_cold", now, self.facts(rid, now, conditions)))
                continue
            checked_today = s.last_ok and s.last_ok.date() == now.date()
            if now.time() >= r.cutoff and not checked_today and s.missed_for != now.date():
                s.missed_for = now.date()
                opened.append(self.open_alert(rid, "missed_checkin", now, self.facts(rid, now, conditions)))
                continue
            if r.has_motion and 8 <= now.hour < 22:
                active = max([t for t in (s.last_ok, s.last_motion) if t], default=None)
                if active and now - active >= NO_MOTION and s.motion_alert_for != active:
                    s.motion_alert_for = active
                    opened.append(self.open_alert(rid, "no_motion", now, self.facts(rid, now, conditions)))
        return opened

    def seed_morning(self, start):
        """Before a replay starts, give each resident the morning their script describes."""
        for rid, r in self.residents.items():
            ok_at = r.script.get("ok_at")
            if ok_at:
                h, m = map(int, ok_at.split(":"))
                t = start.replace(hour=h, minute=m, second=0, microsecond=0)
                if t <= start:
                    self.state[rid].last_ok = t
            if r.has_motion:
                self.state[rid].last_motion = start - timedelta(minutes=20)
