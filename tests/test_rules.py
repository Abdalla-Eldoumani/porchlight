from datetime import datetime, time, timedelta

from server import explain, grid
from server.rules import Engine, Resident

T0 = datetime(2024, 1, 13, 14, 45, tzinfo=grid.TZ)
COLD = {"temp_c": -30.0, "level": "alert"}
MILD = {"temp_c": -5.0, "level": "normal"}
VOLS = [{"id": "priya", "name": "Priya", "language": "en"}, {"id": "sam", "name": "Sam", "language": "en"}]


def engine(**kw):
    r = Resident("m", "Margaret", "Forest Lawn", "addr", time(10, 0), ["priya", "sam"], **kw)
    e = Engine([r], VOLS)
    e.state["m"].last_ok = T0.replace(hour=8)
    return e


def test_help_escalates_to_next_volunteer_then_coordinator_and_stops():
    e = engine()
    a = e.device_event("m", "help", T0, MILD)
    assert a.rule == "help" and a.responder == "priya"
    e.tick(T0 + timedelta(minutes=4), MILD)
    assert a.responder == "priya"
    e.tick(T0 + timedelta(minutes=5), MILD)
    assert a.responder == "sam"
    e.tick(T0 + timedelta(minutes=10), MILD)
    e.tick(T0 + timedelta(minutes=30), MILD)
    assert a.responder == "coordinator"


def test_ok_closes_a_missed_checkin_but_not_a_help_call():
    e = engine()
    e.state["m"].last_ok = None
    [a] = e.tick(T0, MILD)
    assert a.rule == "missed_checkin"
    e.device_event("m", "ok", T0 + timedelta(minutes=1))
    assert a.closed_at is not None
    h = e.device_event("m", "help", T0 + timedelta(minutes=2), MILD)
    e.device_event("m", "ok", T0 + timedelta(minutes=3))
    assert h.closed_at is None


def test_missed_checkin_fires_once_per_day():
    e = engine()
    e.state["m"].last_ok = None
    assert len(e.tick(T0, MILD)) == 1
    e.volunteer_action("priya", 1, "resolved", T0 + timedelta(minutes=5))
    e.state["m"].last_ok = None
    assert e.tick(T0 + timedelta(minutes=6), MILD) == []


def test_cold_wave_asks_and_opens_alert_after_30_minutes_without_reply():
    e = engine()
    e.tick(T0, COLD)
    s = e.state["m"]
    assert s.display == "ask" and s.buzz == 1
    assert e.tick(T0 + timedelta(minutes=29), COLD) == []
    [a] = e.tick(T0 + timedelta(minutes=30), COLD)
    assert a.rule == "no_reply_cold"


def test_reply_to_wave_in_time_opens_nothing():
    e = engine()
    e.tick(T0, COLD)
    e.device_event("m", "ok", T0 + timedelta(minutes=10))
    assert e.tick(T0 + timedelta(minutes=40), COLD) == []


def test_wave_needs_both_cold_and_grid_stress():
    e = engine()
    e.tick(T0, {"temp_c": -30.0, "level": "normal"})
    e.tick(T0, {"temp_c": -10.0, "level": "emergency"})
    assert e.state["m"].wave_at is None


def test_simulated_resident_answers_after_its_scripted_delay():
    e = engine(simulated=True, script={"wave_reply_min": 6})
    e.tick(T0, COLD)
    e.tick(T0 + timedelta(minutes=5), COLD)
    assert e.state["m"].wave_at is not None
    e.tick(T0 + timedelta(minutes=6), COLD)
    assert e.state["m"].wave_at is None and e.state["m"].display == "ok"


def test_volunteer_going_tells_the_box_and_only_the_asked_volunteer_can_act():
    e = engine()
    a = e.device_event("m", "help", T0, MILD)
    assert not e.volunteer_action("sam", a.id, "going", T0, 20)
    assert e.volunteer_action("priya", a.id, "going", T0, 20)
    s = e.state["m"]
    assert s.display == "visitor" and s.buzz == 2 and "3:05 PM" in s.text
    e.tick(T0 + timedelta(minutes=30), MILD)
    assert a.responder == "priya"           # acknowledged alerts don't escalate


def test_cant_go_moves_to_next_person():
    e = engine()
    a = e.device_event("m", "help", T0, MILD)
    e.volunteer_action("priya", a.id, "cant", T0)
    assert a.responder == "sam"


def test_no_motion_for_six_hours_in_the_daytime():
    e = engine(has_motion=True)
    morning = T0.replace(hour=8)
    e.state["m"].last_motion = morning
    assert e.tick(morning + timedelta(hours=5, minutes=59), MILD) == []
    [a] = e.tick(morning + timedelta(hours=6), MILD)
    assert a.rule == "no_motion"


def test_replay_uses_the_real_jan_13_record():
    r = grid.Replay()
    at = lambda h, m: r.conditions(T0.replace(hour=h, minute=m))
    assert at(15, 29)["level"] in ("normal", "watch")
    assert at(15, 30)["level"] == "alert"
    assert at(18, 44)["level"] == "emergency"
    assert at(16, 30)["price"] == 999.99          # hour ending 17
    assert at(15, 0)["temp_c"] == -27.5


def test_help_template_always_mentions_911():
    text = explain.template("help", "Pressed the help button",
                            {"name": "M", "community": "X", "time": "3:00 PM", "outdoor_c": -30, "grid": "alert"})
    assert "911" in text and "-30 °C" in text


def test_quiet_box_raises_one_alert_until_it_checks_in_again():
    e = engine()
    [a] = e.tick(T0, MILD, quiet={"m"})
    assert a.rule == "box_offline"
    e.close(a, T0 + timedelta(minutes=1), "priya", "checked")
    assert e.tick(T0 + timedelta(minutes=2), MILD, quiet={"m"}) == []
    e.box_seen("m")
    [b] = e.tick(T0 + timedelta(minutes=3), MILD, quiet={"m"})
    assert b.rule == "box_offline"
