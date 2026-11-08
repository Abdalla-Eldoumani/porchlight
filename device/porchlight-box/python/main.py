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
seen = {"display": None, "buzz": None}
next_poll = 0.0


def request(method, path, body=None):
    req = urllib.request.Request(
        CONFIG["server"].rstrip("/") + path, method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Content-Type": "application/json", "X-Device-Key": CONFIG.get("key", "")})
    with urllib.request.urlopen(req, timeout=5) as res:
        return json.loads(res.read())


def apply(box):
    if box["display"] != seen["display"]:
        Bridge.call("show", FRAME.get(box["display"], 0))
        seen["display"] = box["display"]
    if seen["buzz"] is not None and box["buzz"] > seen["buzz"]:
        Bridge.call("buzz", 700)
    seen["buzz"] = box["buzz"]


def loop():
    global next_poll
    bits = Bridge.call("read_inputs") or 0
    outbox.extend(kind for bit, kind in KINDS if bits & bit)
    while outbox:
        try:
            apply(request("POST", f"/api/device/{CONFIG['resident']}/event", {"kind": outbox[0]}))
            outbox.pop(0)
        except Exception as e:
            print("send failed, will retry:", e)
            break
    if time.monotonic() >= next_poll:
        next_poll = time.monotonic() + 1.0
        try:
            apply(request("GET", f"/api/device/{CONFIG['resident']}"))
        except Exception as e:
            print("poll failed:", e)
    time.sleep(0.15)


App.run(user_loop=loop)
