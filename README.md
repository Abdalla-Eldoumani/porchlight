# Porchlight

**Porchlight — A connected wellness monitoring and assistance system that helps nurses and caregivers stay informed about vulnerable individuals and respond when assistance is needed.** It supports older people living independently, people with disabilities, and others needing occasional help. Nurses, home-care workers, family caregivers, and authorized caregivers use the existing coordinator dashboard and responder network.

The physical prototype has one button: **single press requests assistance** after a 600 ms double-press window; **double press confirms I'm OK**. Caregivers can also request a wellness check from a resident's dashboard card. Daily check-ins, inactivity, offline-device alerts, and the existing volunteer/coordinator escalation model remain available. Cold-weather and electricity-grid checks remain secondary features, including the historical Calgary replay.

Porchlight is not a diagnostic system or fall detector, does not guarantee safety, and does not replace 911. Motion is recorded separately from a resident's manually confirmed OK.

## Why the grid matters

On Saturday, January 13, 2024, it was -27 to -34 °C in Calgary. At 3:30 pm the AESO declared an Energy Emergency Alert, and at 6:44 pm every phone in Alberta got an emergency alert asking people to cut their electricity use. If the power had gone out, the people at most risk were the ones home alone in the cold. Porchlight replays that day from the published record:

| Data | Source | How it's used |
|---|---|---|
| Hourly pool price and Alberta demand, Jan 12-14, 2024 | AESO pool price report (ets.aeso.ca), `data/aeso_pool_price_2024-01-12_to_14.csv` | Chart and stats in the replay |
| Hourly temperature, Calgary International Airport | Environment Canada climate data, station 50430, `data/calgary_weather_2024-01-12_to_14.csv` | The "cold" half of the trigger |
| Times of the EEA, reserve directives and the Alberta Emergency Alert | Market Surveillance Administrator, January and April 2024 Event Report, section 1, `data/jan13_2024_timeline.json` | The "grid strained" half of the trigger |
| Live supply and demand | AESO Current Supply Demand API (v2) | Live mode |
| Live temperature | Open-Meteo | Live mode |

In live mode there's no feed of EEA declarations, so the grid level comes from the supply cushion: generating capability not yet in use. Under 1,000 MW counts as tight and under 500 MW as an alert. These thresholds are our own, not the AESO's.

## How it works

```
 box (UNO Q) ──┐                      ┌── coordinator dashboard (Auth0 sign-in)
 box simulator ┼── HTTPS ── server ───┼── volunteer phone page (secret link)
               │            │         │
               │      rules engine    └── Gemini writes the message wording
               │            │
               └────── Tiger Data (Postgres + TimescaleDB)
```

- **The demo screen** (`/`) shows the box, the map and a volunteer's phone side by side, all driven by the same API that the real box, the coordinator page (`/dashboard.html`) and volunteers' phones use.
- **The box.** An Arduino UNO Q. The microcontroller reads one button and a PIR sensor, controls red/green LEDs and the 8x13 matrix, and schedules vibration commands. Motor output is gated pending electrical verification (see below). Linux sends events over Wi-Fi and polls for backend state. A recognized gesture gives local LED feedback even offline; Help is retried and its red indication stays latched until the server has received it and explicitly reports resolution. The browser simulator (`/box.html`) keeps its two separate OK/Help controls and uses the same API without requiring hardware.
- **The rules decide; Gemini only words.** `server/rules.py` holds every rule: help pressed, no I'm OK by the person's cutoff time, no movement for 6 hours during the day, a box that stops checking in (20 minutes live, 60 real seconds in a replay; its power or Wi-Fi may be out, which is the reason to check), and the cold-weather check-in (at or below -25 °C *and* the grid on alert or emergency). Each alert asks the person's first volunteer, then the next one after 15 minutes (5 for help), then the coordinator. Gemini turns the facts into one or two plain sentences in the volunteer's language. Without a key, or if the call fails, a template is used.
- **Tiger Data** stores the grid readings and device events in hypertables, and the chart reads them back through `time_bucket`. With no `DATABASE_URL` the server keeps everything in memory.

## Privacy

- The box sends three things: I'm OK, Help, and "someone moved". It has no camera, no microphone and no temperature log. The dashboard shows exactly what each box sent.
- Volunteers don't need an account. A volunteer only sees a person's address after saying they're going, and that is written to the access log.
- Every time a coordinator opens the dashboard or looks at a box's events, the access log records it.

## Run it

Python 3.12 or newer. In Git Bash:

```bash
python -m venv .venv && source .venv/Scripts/activate   # macOS/Linux: .venv/bin/activate
pip install -r requirements.txt
python -m uvicorn server.app:app --host 0.0.0.0 --port 8000 --loop asyncio:SelectorEventLoop
```

Open http://localhost:8000. The demo screen replays January 13, 2024 from 3:15 pm at 30 times real speed, with Margaret's box on the left, a map of Calgary in the middle and a volunteer's phone on the right. The bar under the clock says what is happening and what to try next; **Skip ahead** jumps to the next thing that happens. When anyone presses Help, the replay drops to real time so the call plays out live.

**Pitch** is a six-slide deck (arrow keys to move, F for full screen) that hands off to the demo. **How it works** explains the idea in plain words, with the Calgary numbers and their sources. Every page has a bigger-text and a high-contrast button in the top bar, remembered in that browser, and the logo always leads back to the demo.

To switch services on, open **Keys** in the top bar, paste a key, press Test, then Save. Everything there is optional. Keys typed there are kept in memory, or in the computer's own password store (Windows Credential Manager) if "Remember on this computer" is ticked; nothing is written into the project. From another device the Keys page asks for the setup code printed in the server window. Environment variables (see `.env.example`) still work and are the way to configure a server you deploy.

Tests: `python -m pytest -q`

### Caregiver wellness checks (no API keys needed)

Open `/dashboard.html`, select **Request Check-In** on a resident card, and open `/box.html` for that resident (Margaret by default). The device polls for the request, shows a question-mark prompt, and schedules a short-short-long vibration pattern. On the physical box, double press to confirm; in the browser simulator, press **I'm OK**. The dashboard records **Check-In Confirmed** and the response time. The demo's embedded box can also submit OK, but only the standalone simulator/updated UNO Q bridge reports device receipt.

A request is **Pending** for five application-clock minutes, then **Unanswered** without creating a Help alert or making a medical conclusion. A repeated request while pending returns the same request without extending its deadline. **Request Assistance** on an unanswered card uses the existing Help/escalation workflow; **Acknowledge Assistance** accepts a Help request through the existing coordinator action route. The box keeps red on until Help is resolved, even if an OK confirms a separate wellness check. PIR motion and scripted replay responses do not confirm a manual request.

The card separates manual OK, motion, last activity, responder, Help status, request timestamp/requester, countdown, and receipt status. "Device receipt confirmed" means the simulator/bridge applied the software command and acknowledged its ID on a subsequent poll; it does not prove that the person noticed it or that the motor moved. Offline/unseen devices remain awaiting receipt. The response deadline starts when the caregiver requests the check, even if the device is offline.

Set `PORCHLIGHT_CHECKIN_TIMEOUT_SECONDS=300` in the environment or local `.env` to change the positive-integer timeout; no Keys-page change or service is required. Timers use the existing clock: five minutes is about ten real seconds at 30× replay, and pausing also pauses the timeout. Use 1× to test physical responses. The existing ticker evaluates expiry; replay Skip ahead also considers pending manual deadlines.

The new `POST /api/residents/{rid}/check-in` uses the existing coordinator authorization (Auth0 when configured, open development mode otherwise), recording the available identity. It adds no caregiver roles or resident-specific authorization. Device responses retain `display`, `text`, and `buzz` and add `manual_check`, `help_status`, and `buzz_pattern`. The existing device GET optionally accepts `?checkin_received=<request-id>` after successful application; the device-key requirement is unchanged.

The latest completed manual result remains visible until a new request, replay restart, mode reset, or server restart. Like existing operational state, this prototype feature is in memory, even with a history database. The device outbox is also in memory: network retry survives a temporary disconnection, not a Linux-process restart. No new notification service, database table, or API key is required. Gemini templates, historical data, development authentication, and memory storage still work with every key unset.

The demo, pitch, About page, shared navigation labels, and Keys-page hardware copy retain the earlier community presentation. Their broader wording updates are deferred; the caregiver dashboard and this README describe the updated physical prototype.

## The box

Verified prototype connections (preserve the existing electrical setup):

| Component | Pin / behavior |
|---|---|
| Adafruit Mini Basic PIR BL412 | D2 digital input; rising-edge motion events, at most once per 2 seconds |
| Single tactile button | D3 to GND, `INPUT_PULLUP`; approximately 30 ms debounce |
| Vibration motor control | D5, existing driver/module control: LOW off, HIGH on; gated as described below |
| Green LED, with existing series resistor | D8; five seconds after double-press OK or motion, then off |
| Red LED, with existing series resistor | D9; active Help takes priority over green, including while awaiting network delivery |

One valid press requests Help **only after** the 600 ms double-press window. Two presses within the window produce OK only, never an initial Help. Holding the button does not repeat requests. PIR only records activity: no repeated events while HIGH, no identity/fall detection, and no automatic OK. The LED priority is active Help (red on, green off), recent OK/motion (green for five seconds), then idle (both off). Acknowledgment keeps red on; backend resolution turns it off. The matrix retains its existing symbols; the firmware does not render the browser's name/ETA text.

**Motor:** D5 HIGH/LOW control was reported tested on the assembled prototype. Before enabling output, verify the actual module/driver's voltage, current, pinout, supply and protection; do not connect a bare motor directly to a GPIO. `PORCHLIGHT_MOTOR_ENABLED` defaults to `0`, so no motor GPIO output is configured. After electrical verification, set it to `1` in the sketch/build. Preserve the existing wiring; this repository does not specify an unverified motor supply or driver. Manual checks schedule 200 ms on / 150 ms off / 200 ms on / 150 ms off / 600 ms on; Help acknowledgment schedules **two 200 ms pulses** separated by 150 ms. Both use `millis()` without blocking input processing. Their command/state handling works with motor output disabled; physical vibration has not been verified by these tests.

The Bridge retains `read_inputs` (OK=1, Help=2, motion=4), `show`, and legacy `buzz(ms)`. It adds `buzz_pattern(1=wellness, 2=acknowledged)` and `help_state`: low two bits are 0=none, 1=requested, 2=acknowledged, 3=resolved; bit 2 (value 4) confirms a successful Help POST and releases the local pending latch. Polls alone cannot release that latch. Overlapping wellness/acknowledgment patterns run sequentially. Deploy the updated sketch and Linux bridge together; old browser clients still ignore the optional API fields.

In Arduino App Lab, create a new app, paste `device/porchlight-box/sketch/sketch.ino` into the sketch and `device/porchlight-box/python/main.py` into the Python part, and put a `device_config.json` beside `main.py` (see the example file). The `key` must match the Box key on the Keys page. On Windows, allow Python through the firewall on public networks too, or the board can't reach a laptop on a phone hotspot.

Set the private device config's `server` to your reachable local server URL, `resident` to the intended existing resident ID, and `key` to the server's device key if configured. The example address is a placeholder from the original demo, not a discovered server address.

### Standalone Wi-Fi operation and startup

The sketch talks to Linux through the UNO Q's internal Bridge, not a USB connection to the laptop. Linux uses the existing `urllib.request` HTTP client over its network connection; the dashboard talks to FastAPI independently. No serial networking, additional library, or service is needed.

1. Configure the UNO Q's Wi-Fi using the existing App Lab board setup. Connect the board and backend host to a network that permits communication; guest-network/client isolation can prevent it. Keep the backend host awake, run the existing Uvicorn command on `0.0.0.0`, and allow its configured port through the host firewall.
2. Set `device_config.json` to the backend host's reachable LAN hostname/address and port (or deployed HTTPS domain). `localhost` on the board means the board itself, not the laptop. Configure the existing device key if used; Wi-Fi credentials belong in the board's setup, not this repo.
3. Deploy the custom App Lab app with both the sketch and Python bridge. Select the board over App Lab Network Mode and press **Run** to start it manually after Linux/Wi-Fi boot. A running MCU sketch alone is insufficient: the Linux Python app must also be running. Check the Python logs and dashboard device activity to confirm HTTP connectivity.
4. Power the UNO Q from its appropriate external supply with no laptop USB data connection. Confirm it continues polling, sends button/motion events, and receives check-in/acknowledgment commands. The backend must stay reachable; standalone power does not make the backend run on the board.

Automatic startup is **not configured by this repository**, but Arduino documents a built-in App Lab option: open the custom app's name dropdown and enable **Run at startup**, then check the DEFAULT badge. The smallest setup change is that existing per-app setting, not a new startup service. Leave it off until you choose to configure it; no board startup setting is changed by this patch. If unavailable on the installed version, manually start the app through App Lab after each boot and verify the board/version before adding any startup mechanism. Power-cycle the externally powered board and test Wi-Fi recovery and app launch before relying on an unattended demo. See the [official UNO Q startup instructions](https://docs.arduino.cc/tutorials/uno-q/user-manual/#running-an-app-at-startup).

### Manual Arduino validation (physical tests still required)

1. Upload the sketch and deploy the matching bridge. Keep motor output disabled until the driver/power checks above are complete. Start the local server without API keys, select replay 1×, and monitor the caregiver dashboard.
2. Press once: no Help before the gesture window; then one Help event, red on, green off. Hold/release and introduce ordinary button bounce: no duplicate Help. Double press within 600 ms: one OK, no Help, green for approximately five seconds unless Help is already active.
3. Trigger PIR: one motion event and five seconds of green. Hold its output HIGH: no stream of events. Check that motion changes last activity/motion but not the manual OK timestamp. Repeat within/after the two-second rate limit.
4. Request a wellness check: verify Pending, device receipt after polling, question-mark prompt, and (only with verified motor output enabled) short-short-long vibration. Double press: Confirmed with response timestamp. Repeat without responding: Unanswered after five application minutes, unchanged activity timestamps, no new automatic Help caused by the manual timeout. A duplicate pending request must keep the same deadline.
5. Initiate Help. Acknowledge it from the dashboard or existing responder phone: two short motor pulses when enabled, heart on the matrix, red still on. Confirm a manual wellness check while Help is active: Help remains open/red. Mark Assistance Resolved: red off.
6. Disconnect the server/network, initiate Help, and verify red stays on with no acknowledgment. Reconnect: the bridge retries; only a caregiver acceptance produces acknowledgment, and only backend resolution clears red. Request a check while the device is offline: no receipt is reported until the client reconnects and acknowledges. Do not infer delivery from an HTTP request being queued.

Automated tests compile the actual sketch against simulated GPIO/Bridge headers with motor output both enabled and disabled, and exercise the Python bridge and backend. This host compilation is not an Arduino board/toolchain build or a physical electrical test. A C++ compiler is needed for those pytest cases; they report skipped if unavailable. Existing rule tests are unchanged.

## Deploy

On a Vultr Ubuntu instance with Docker: point the domain's A record at the instance, put a filled `.env` in the repo root, then run

```bash
docker compose -f deploy/docker-compose.yml --env-file .env up -d --build
```

Caddy serves the app over HTTPS on the domain.

## Demo people

The residents and volunteers in `data/demo_people.json` are made up. Margaret is driven by the real box or the on-screen box; the others are simulated and marked that way. Their map points are the centres of their real Calgary communities, and the map outline and rivers come from OpenStreetMap (© OpenStreetMap contributors, ODbL), in `web/calgary-map.json`.

## Team

Built at Hack the Change 2026 in Calgary by Abdalla Eldoumani, Ibrahim Ahmed, Seyar Hazrat and Abdurahmann Ben Issa.
