# Porchlight box, Linux side of the UNO Q. Sends button presses to the
# server over Wi-Fi and tells the sketch what to show and when to buzz.
# Standard library only, so the app needs no extra packages.
import json
import time
import urllib.request
from pathlib import Path

from arduino.app_utils import *

# device_config.json sits next to this file and is not committed:
# {"server": "https://your-domain", "resident": "margaret", "key": "..."}
CONFIG = json.loads((Path(__file__).parent / "device_config.json").read_text())
FRAME = {"idle": 0, "ok": 1, "ask": 2, "help": 3, "visitor": 4}
KINDS = [(1, "ok"), (2, "help"), (4, "motion")]

outbox = []          # events not yet delivered; a help press must never be lost
seen = {"display": None, "buzz": None, "manual_check": None, "help_status": None}
next_poll = 0.0
received_checkin = None


def request(method, path, body=None):
    req = urllib.request.Request(
        CONFIG["server"].rstrip("/") + path, method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Content-Type": "application/json", "X-Device-Key": CONFIG.get("key", "")})
    with urllib.request.urlopen(req, timeout=5) as res:
        return json.loads(res.read())


def apply(box, help_sent=False):
    global received_checkin
    if "help_status" in box:
        state = {"none": 0, "requested": 1, "acknowledged": 2, "resolved": 3}[box["help_status"]]
        # Only the successful Help POST may release the MCU's local pending latch.
        Bridge.call("help_state", state | (4 if help_sent else 0))
    if box["display"] != seen["display"]:
        Bridge.call("show", FRAME.get(box["display"], 0))
        seen["display"] = box["display"]
    check = box.get("manual_check")
    pending_check = check and check["status"] == "pending"
    new_check = pending_check and check["id"] != seen["manual_check"]
    changed_buzz = seen["buzz"] is not None and box["buzz"] > seen["buzz"]
    acknowledged = box.get("help_status") == "acknowledged" and (
        seen["help_status"] != "acknowledged" or changed_buzz and box.get("buzz_pattern") == "acknowledged")
    if new_check:
        Bridge.call("buzz_pattern", 1)
    if acknowledged:
        Bridge.call("buzz_pattern", 2)
    elif changed_buzz and not new_check and box.get("buzz_pattern") != "wellness":
        if box.get("buzz_pattern") == "acknowledged":
            if box["display"] == "visitor":
                Bridge.call("buzz_pattern", 2)
        else:
            Bridge.call("buzz", 700)
    seen["buzz"] = box["buzz"]
    seen["manual_check"] = check["id"] if check else None
    seen["help_status"] = box.get("help_status")
    received_checkin = check["id"] if pending_check else None


def loop():
    global next_poll
    bits = Bridge.call("read_inputs") or 0
    outbox.extend(kind for bit, kind in KINDS if bits & bit)
    while outbox:
        try:
            apply(request("POST", f"/api/device/{CONFIG['resident']}/event", {"kind": outbox[0]}),
                  help_sent=outbox[0] == "help")
            outbox.pop(0)
        except Exception as e:
            print("send failed, will retry:", e)
            break
    if time.monotonic() >= next_poll:
        next_poll = time.monotonic() + 1.0
        try:
            receipt = f"?checkin_received={received_checkin}" if received_checkin is not None else ""
            apply(request("GET", f"/api/device/{CONFIG['resident']}" + receipt))
        except Exception as e:
            print("poll failed:", e)
    time.sleep(0.15)


App.run(user_loop=loop)
