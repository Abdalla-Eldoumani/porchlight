"""Manual wellness checks are separate from the existing automatic alerts."""
import asyncio
from datetime import timedelta
import importlib

import pytest
from fastapi.testclient import TestClient

from server.rules import Engine, Resident
from server.store import MemoryStore
from test_rules import COLD, MILD, T0, VOLS, engine


def test_caregiver_request_tracks_identity_and_notifies_once():
    e = engine()
    check = e.request_checkin("m", T0, "nurse-1")
    assert (check.resident_id, check.requested_at, check.requested_by) == ("m", T0, "nurse-1")
    assert check.status == "pending" and check.deadline == T0 + timedelta(minutes=5)
    assert check.received_at is None and e.current_alert("m") is None
    assert e.state["m"].buzz == 1 and e.state["m"].buzz_pattern == "wellness"
    repeated = e.request_checkin("m", T0 + timedelta(minutes=2), "nurse-2")
    assert repeated is check and repeated.requested_by == "nurse-1"
    assert repeated.deadline == T0 + timedelta(minutes=5) and e.state["m"].buzz == 1


def test_ok_confirms_pending_check_but_motion_does_not():
    e = engine()
    check = e.request_checkin("m", T0, "nurse")
    last_ok = e.state["m"].last_ok
    e.device_event("m", "motion", T0 + timedelta(seconds=20))
    assert check.status == "pending" and e.state["m"].last_ok == last_ok
    at = T0 + timedelta(minutes=1)
    e.device_event("m", "ok", at)
    assert check.status == "confirmed" and check.response_at == at
    assert e.state["m"].last_ok == at
    e.tick(T0 + timedelta(minutes=6), MILD)
    assert e.state["m"].manual_check is check and check.status == "confirmed"


def test_timeout_preserves_activity_and_opens_no_help():
    e = engine()
    e.state["m"].last_motion = T0
    check = e.request_checkin("m", T0, "nurse")
    previous = (e.state["m"].last_ok, e.state["m"].last_motion)
    assert e.tick(T0 + timedelta(minutes=4, seconds=59), MILD) == []
    assert check.status == "pending"
    assert e.tick(T0 + timedelta(minutes=5), MILD) == []
    assert check.status == "unanswered" and check.response_at is None
    assert (e.state["m"].last_ok, e.state["m"].last_motion) == previous
    assert e.current_alert("m") is None
    # A late OK still records activity, but does not rewrite the unanswered result.
    e.device_event("m", "ok", T0 + timedelta(minutes=6))
    assert check.status == "unanswered" and check.response_at is None
    new = e.request_checkin("m", T0 + timedelta(minutes=7), "nurse")
    assert new.id != check.id and new.status == "pending"


def test_ok_at_deadline_is_unanswered_even_before_next_tick():
    e = engine()
    check = e.request_checkin("m", T0, "nurse")
    e.device_event("m", "ok", check.deadline)
    assert check.status == "unanswered"


def test_manual_check_does_not_resolve_help_or_change_its_escalation():
    e = engine()
    help_alert = e.device_event("m", "help", T0, MILD)
    check = e.request_checkin("m", T0, "nurse")
    e.device_event("m", "ok", T0 + timedelta(minutes=1))
    assert check.status == "confirmed" and help_alert.closed_at is None
    assert e.state["m"].display == "help"
    e.tick(T0 + timedelta(minutes=5), MILD)
    assert help_alert.responder == "sam"
    before = e.state["m"].buzz
    assert e.volunteer_action("sam", help_alert.id, "going", T0 + timedelta(minutes=6), 10)
    assert e.state["m"].buzz == before + 1
    assert e.state["m"].buzz_pattern == "acknowledged"
    e.tick(T0 + timedelta(minutes=30), MILD)
    assert help_alert.responder == "sam" and help_alert.closed_at is None


def test_automatic_cold_response_does_not_fabricate_manual_confirmation():
    e = engine(simulated=True, script={"wave_reply_min": 1})
    check = e.request_checkin("m", T0, "nurse")
    e.tick(T0, COLD)
    e.tick(T0 + timedelta(minutes=1), COLD)
    assert e.state["m"].wave_at is None  # original scripted response still runs
    assert check.status == "pending"  # it was not a physical/manual response


def test_receipt_requires_matching_pending_request():
    e = engine()
    check = e.request_checkin("m", T0, "nurse")
    e.checkin_received("m", check.id + 1, T0)
    assert check.received_at is None
    e.checkin_received("m", check.id, T0 + timedelta(seconds=1))
    e.checkin_received("m", check.id, T0 + timedelta(seconds=2))
    assert check.received_at == T0 + timedelta(seconds=1)
    e.tick(check.deadline, MILD)
    new = e.request_checkin("m", check.deadline, "nurse")
    e.checkin_received("m", check.id, check.deadline)
    assert new.received_at is None


@pytest.fixture
def api(monkeypatch):
    module = importlib.import_module("server.app")
    monkeypatch.setattr(module, "engine", Engine([Resident.from_json(r) for r in module.PEOPLE["residents"]], module.PEOPLE["volunteers"]))
    monkeypatch.setattr(module, "clock", module.Clock())
    monkeypatch.setattr(module, "last_poll", {})
    monkeypatch.setattr(module, "store", MemoryStore())
    values = {}
    monkeypatch.setattr(module.settings, "get", lambda name, default=None: values.get(name, default))
    module.start_replay(0)
    # No lifespan: isolated tests use the replay/memory store, without keyring or live feeds.
    client = TestClient(module.app)
    yield module, client, values
    client.close()


def test_api_offline_receipt_and_ok_roundtrip(api):
    module, client, _ = api
    request = client.post("/api/residents/margaret/check-in").json()
    assert request["status"] == "pending" and request["requested_by"] == "dev-mode"
    person = client.get("/api/state").json()["residents"][0]
    assert not person["box_online"] and person["box"]["manual_check"]["received_at"] is None
    polled = client.get("/api/device/margaret").json()
    assert polled["display"] == "ask" and polled["buzz_pattern"] == "wellness"
    assert polled["manual_check"]["received_at"] is None  # poll alone is not receipt
    polled = client.get(f"/api/device/margaret?checkin_received={request['id']}").json()
    assert polled["manual_check"]["received_at"] is not None
    confirmed = client.post("/api/device/margaret/event", json={"kind": "ok"}).json()
    assert confirmed["manual_check"]["status"] == "confirmed"
    assert confirmed["manual_check"]["response_at"] is not None
    assert confirmed["display"] == "ok"
    assert module.engine.state["margaret"].last_ok == module.clock.now()


def test_api_request_is_authorized_and_timeout_configurable(api):
    module, client, values = api
    assert client.post("/api/residents/missing/check-in").status_code == 404
    values["AUTH0_DOMAIN"] = "example.invalid"
    assert client.post("/api/residents/margaret/check-in").status_code == 401
    assert module.engine.state["margaret"].manual_check is None
    values.pop("AUTH0_DOMAIN")
    values["PORCHLIGHT_CHECKIN_TIMEOUT_SECONDS"] = "45"
    data = client.post("/api/residents/margaret/check-in").json()
    assert data["remaining_seconds"] == 45
    assert client.post("/api/residents/margaret/check-in").json() == data
    values["PORCHLIGHT_DEVICE_KEY"] = "test-only-device-key"
    assert client.get(f"/api/device/margaret?checkin_received={data['id']}").status_code == 401
    assert module.engine.state["margaret"].manual_check.received_at is None
    values["PORCHLIGHT_CHECKIN_TIMEOUT_SECONDS"] = "0"
    assert client.post("/api/residents/margaret/check-in").status_code == 500


def test_api_caregiver_acknowledgment_and_resolution_control_box(api):
    module, client, _ = api
    # Existing volunteer response path remains available too (covered by original tests).
    help_box = client.post("/api/device/margaret/event", json={"kind": "help"}).json()
    assert help_box["help_status"] == "requested"
    alert = module.engine.current_alert("margaret")
    assert client.post(f"/api/alerts/{alert.id}/going").status_code == 200
    box = client.get("/api/device/margaret").json()
    assert box["help_status"] == "acknowledged" and box["buzz_pattern"] == "acknowledged"
    client.post("/api/residents/margaret/check-in")
    box = client.post("/api/device/margaret/event", json={"kind": "ok"}).json()
    assert box["manual_check"]["status"] == "confirmed"
    assert box["help_status"] == "acknowledged" and box["display"] == "visitor"
    assert client.post(f"/api/alerts/{alert.id}/resolved").status_code == 200
    assert client.get("/api/device/margaret").json()["help_status"] == "resolved"
    assert client.get("/api/state").json()["residents"][0]["help_resolved_at"] is not None


def test_existing_ticker_expires_manual_request(api, monkeypatch):
    module, client, _ = api
    client.post("/api/residents/margaret/check-in")
    calls = 0

    async def one_tick(_):
        nonlocal calls
        calls += 1
        if calls > 1:
            raise asyncio.CancelledError
        module.clock.jump(module.REPLAY_START + timedelta(minutes=5))

    monkeypatch.setattr(module.asyncio, "sleep", one_tick)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(module.ticker())
    assert module.engine.state["margaret"].manual_check.status == "unanswered"


def test_withdrawn_acknowledgment_does_not_leave_stale_reassurance(api):
    module, client, _ = api
    client.post("/api/device/margaret/event", json={"kind": "help"})
    alert = module.engine.current_alert("margaret")
    token = module.token_for(alert.responder)
    path = f"/api/v/{token}/alerts/{alert.id}"
    assert client.post(path, json={"action": "going"}).status_code == 200
    assert client.post(path, json={"action": "cant"}).status_code == 200
    box = client.get("/api/device/margaret").json()
    assert box["help_status"] == "requested" and box["display"] == "help"
    assert "awaiting a caregiver response" in box["text"]
