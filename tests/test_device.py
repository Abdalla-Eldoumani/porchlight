"""Host tests execute the actual sketch with fake GPIO/Bridge, never real hardware."""
import json
from pathlib import Path
import shutil
import subprocess
import sys
import types

import pytest

ROOT = Path(__file__).resolve().parents[1]
SKETCH = ROOT / "device/porchlight-box/sketch/sketch.ino"
BRIDGE = ROOT / "device/porchlight-box/python/main.py"


@pytest.fixture(scope="module", params=[0, 1], ids=["motor-disabled", "motor-enabled"])
def sketch_binary(request, tmp_path_factory):
    compiler = shutil.which("g++") or shutil.which("c++")
    if not compiler:
        pytest.skip("C++ compiler unavailable; use the README physical test procedure")
    directory = tmp_path_factory.mktemp("uno-q-host")
    (directory / "Arduino_RouterBridge.h").write_text("""
struct FakeBridge {
  void begin() {}
  template<typename F> void provide_safe(const char *, F) {}
} Bridge;
""")
    (directory / "Arduino_LED_Matrix.h").write_text("""
struct Arduino_LED_Matrix {
  uint8_t *last = nullptr;
  void begin() {}
  void setGrayscaleBits(int) {}
  void draw(uint8_t *frame) { last = frame; }
};
""")
    harness = r'''
#include <cassert>
#include <cstdint>
#include <climits>
#include <string>
#include <vector>
const int HIGH=1, LOW=0, INPUT=0, INPUT_PULLUP=2, OUTPUT=1;
unsigned long nowMs=0;
int pins[32]={}, modes[32];
std::vector<int> motorWrites;
unsigned long millis() { return nowMs; }
int digitalRead(int pin) { return pins[pin]; }
void pinMode(int pin,int mode) { modes[pin]=mode; }
void digitalWrite(int pin,int value) {
  pins[pin]=value;
  if (pin==5) motorWrites.push_back(value);
}
#include SKETCH_PATH
void advance(unsigned long ms) { for(unsigned long i=0;i<ms;i++){ nowMs++; loop(); } }
void tap() {
  pins[3]=LOW; loop(); advance(31);
  pins[3]=HIGH; loop(); advance(31);
}
void help() { tap(); advance(601); assert(read_inputs()==2); }
void motor(bool on) {
#if PORCHLIGHT_MOTOR_ENABLED
  assert(pins[5]==(on?HIGH:LOW));
#else
  assert(modes[5]==-1 && motorWrites.empty());
#endif
}
int main(int argc,char **argv) {
  assert(argc==2);
  for(auto &m:modes) m=-1;
  pins[3]=HIGH;
  setup();
  assert(modes[2]==INPUT && modes[3]==INPUT_PULLUP);
  assert(modes[8]==OUTPUT && modes[9]==OUTPUT);
  assert(pins[8]==LOW && pins[9]==LOW);
  std::string scenario=argv[1];
  if(scenario=="single") {
    tap(); advance(500); assert(read_inputs()==0);
    advance(101); assert(read_inputs()==2);
    assert(pins[9]==HIGH && pins[8]==LOW);
    advance(1000); assert(read_inputs()==0);
  } else if(scenario=="double") {
    tap(); advance(100); tap();
    assert(read_inputs()==1 && pins[8]==HIGH && pins[9]==LOW);
    advance(601); assert(read_inputs()==0);
    advance(5000); assert(pins[8]==LOW);
  } else if(scenario=="bounce") {
    pins[3]=LOW; loop(); advance(4);
    pins[3]=HIGH; loop(); advance(4);
    pins[3]=LOW; loop(); advance(31);
    pins[3]=HIGH; loop(); advance(4);
    pins[3]=LOW; loop(); advance(4);
    pins[3]=HIGH; loop(); advance(31);
    advance(601); assert(read_inputs()==2);
    advance(1000); assert(read_inputs()==0);
  } else if(scenario=="motion") {
    pins[2]=HIGH; loop(); assert(read_inputs()==4 && pins[8]==HIGH);
    advance(100); pins[2]=LOW; loop(); pins[2]=HIGH; loop();
    assert(read_inputs()==0); // noisy transitions are rate-limited
    advance(2000); pins[2]=LOW; loop(); pins[2]=HIGH; loop();
    assert(read_inputs()==4);
    advance(5001); assert(read_inputs()==0 && pins[8]==LOW);
  } else if(scenario=="priority") {
    help(); help_state(1|4);
    pins[2]=HIGH; loop(); assert(read_inputs()==4 && pins[8]==LOW);
    tap(); advance(100); tap(); assert(read_inputs()==1);
    assert(pins[9]==HIGH && pins[8]==LOW);
    assert(matrix.last==FRAMES[HELP]);
    help_state(2); loop(); assert(pins[9]==HIGH);
    show(OK); assert(matrix.last==FRAMES[4]);
    help_state(3); loop(); assert(pins[9]==LOW);
  } else if(scenario=="offline") {
    help();
    help_state(3); loop(); assert(helpPending && pins[9]==HIGH);
    help_state(0); loop(); assert(helpPending && pins[9]==HIGH);
    show(4); assert(matrix.last==FRAMES[HELP]); // no false acknowledgment
    help_state(1|4); assert(!helpPending && helpActive);
    help_state(2); show(4); assert(matrix.last==FRAMES[4]);
    help_state(3); loop(); assert(pins[9]==LOW);
  } else if(scenario=="patterns") {
    motorWrites.clear();
    buzz_pattern(1); motor(true);
    advance(200); motor(false); advance(150); motor(true);
    advance(200); motor(false); advance(150); motor(true);
    advance(600); motor(false); assert(vibrationLength==0);
    motorWrites.clear();
    buzz_pattern(2); motor(true);
    advance(200); motor(false); advance(150); motor(true);
    advance(200); motor(false); assert(vibrationLength==0);
#if PORCHLIGHT_MOTOR_ENABLED
    assert((motorWrites==std::vector<int>{HIGH,LOW,HIGH,LOW}));
#endif
  } else if(scenario=="overlap") {
    buzz_pattern(1); buzz_pattern(2);
    assert(queuedPattern==2);
    advance(1300); assert(vibrationLength==3 && queuedPattern==0);
    advance(550); assert(vibrationLength==0); motor(false);
  } else if(scenario=="held") {
    pins[3]=LOW; loop(); advance(31); advance(601);
    assert(read_inputs()==2); advance(3000); assert(read_inputs()==0);
  } else if(scenario=="rollover") {
    nowMs=ULONG_MAX-300;
    tap(); advance(100); tap(); assert(read_inputs()==1);
    advance(6000); assert(read_inputs()==0 && pins[8]==LOW);
  } else { assert(false); }
}
'''
    source = directory / "harness.cpp"
    source.write_text(harness.replace("SKETCH_PATH", json.dumps(str(SKETCH))))
    binary = directory / "sketch-test"
    result = subprocess.run([compiler, "-std=c++17", f"-DPORCHLIGHT_MOTOR_ENABLED={request.param}",
                             "-I", str(directory), str(source), "-o", str(binary)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    return binary


@pytest.mark.parametrize("scenario", ["single", "double", "bounce", "motion", "priority", "offline", "patterns", "overlap", "held", "rollover"])
def test_actual_sketch_with_simulated_gpio(sketch_binary, scenario):
    result = subprocess.run([str(sketch_binary), scenario], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


@pytest.fixture
def bridge(monkeypatch):
    calls = []
    utils = types.ModuleType("arduino.app_utils")
    utils.Bridge = types.SimpleNamespace(call=lambda *args: calls.append(args) or 0)
    utils.App = types.SimpleNamespace(run=lambda **kwargs: None)
    utils.__all__ = ["Bridge", "App"]
    monkeypatch.setitem(sys.modules, "arduino", types.ModuleType("arduino"))
    monkeypatch.setitem(sys.modules, "arduino.app_utils", utils)
    read_text = Path.read_text
    monkeypatch.setattr(Path, "read_text", lambda p, *a, **kw:
                        json.dumps({"server": "https://example.invalid", "resident": "m", "key": ""})
                        if p.name == "device_config.json" else read_text(p, *a, **kw))
    namespace = {"__file__": str(BRIDGE)}
    exec(compile(BRIDGE.read_text(), str(BRIDGE), "exec"), namespace)
    monkeypatch.setattr(namespace["time"], "sleep", lambda _: None)
    return namespace, calls


def test_bridge_notifies_first_pending_poll_and_reports_receipt(bridge):
    ns, calls = bridge
    box = {"display": "ask", "buzz": 1, "buzz_pattern": "wellness", "help_status": "none",
           "manual_check": {"id": 7, "status": "pending"}}
    ns["apply"](box)
    assert ("buzz_pattern", 1) in calls and ns["received_checkin"] == 7
    ns["apply"](box)
    assert calls.count(("buzz_pattern", 1)) == 1
    requests = []
    ns["request"] = lambda method, path, body=None: requests.append((method, path, body)) or box
    ns["loop"]()
    assert requests[0][1] == "/api/device/m?checkin_received=7"
    box.update(display="visitor", buzz=2, buzz_pattern="acknowledged", help_status="acknowledged")
    ns["apply"](box)
    assert ("buzz_pattern", 2) in calls


def test_bridge_receipt_waits_for_successful_command_application(bridge):
    ns, _ = bridge
    def unavailable(*args):
        raise RuntimeError("MCU disconnected")
    ns["Bridge"].call = unavailable
    with pytest.raises(RuntimeError):
        ns["apply"]({"display": "ask", "buzz": 1, "help_status": "none",
                      "manual_check": {"id": 7, "status": "pending"}})
    assert ns["received_checkin"] is None


def test_bridge_retries_help_without_unlocking_local_latch_on_stale_poll(bridge):
    ns, calls = bridge
    ns["outbox"].append("help")
    attempts = []
    reachable = False
    def request(method, path, body=None):
        attempts.append((method, body))
        if method == "POST" and not reachable:
            raise OSError("offline")
        return {"display": "help" if method == "POST" else "ok", "buzz": 1,
                "help_status": "requested" if method == "POST" else "resolved"}
    ns["request"] = request
    ns["loop"]()
    assert ns["outbox"] == ["help"] and ("help_state", 3) in calls
    assert ("help_state", 5) not in calls
    reachable = True
    ns["loop"]()
    assert ns["outbox"] == [] and ("help_state", 5) in calls
    assert [body for method, body in attempts if method == "POST"] == [{"kind": "help"}, {"kind": "help"}]


def test_bridge_keeps_original_event_bits_and_legacy_state_support(bridge):
    ns, calls = bridge
    assert ns["KINDS"] == [(1, "ok"), (2, "help"), (4, "motion")]
    ns["apply"]({"display": "idle", "buzz": 0})
    ns["apply"]({"display": "ok", "buzz": 1})
    assert ("buzz", 700) in calls


def test_overlapping_requests_keep_distinct_notifications(bridge):
    ns, calls = bridge
    # A single latest-pattern field must not hide the other pending workflow.
    ns["apply"]({"display": "visitor", "buzz": 3, "buzz_pattern": "wellness",
                  "help_status": "acknowledged", "manual_check": {"id": 9, "status": "pending"}})
    assert [(name, value) for name, value in calls if name == "buzz_pattern"] == [
        ("buzz_pattern", 1), ("buzz_pattern", 2)]


def test_bridge_does_not_replay_an_expired_wellness_prompt_after_outage(bridge):
    ns, calls = bridge
    ns["apply"]({"display": "ok", "buzz": 0})
    ns["apply"]({"display": "ok", "buzz": 1, "buzz_pattern": "wellness",
                  "help_status": "none", "manual_check": {"id": 7, "status": "unanswered"}})
    assert not any(call[0] in ("buzz", "buzz_pattern") for call in calls)
    assert ns["received_checkin"] is None


def test_bridge_does_not_replay_withdrawn_acknowledgment(bridge):
    ns, calls = bridge
    ns["apply"]({"display": "help", "buzz": 1, "help_status": "requested"})
    ns["apply"]({"display": "help", "buzz": 2, "buzz_pattern": "acknowledged", "help_status": "requested"})
    assert ("buzz_pattern", 2) not in calls
