# Porchlight

Porchlight helps nurses, home-care workers, family caregivers and volunteer neighbours keep an eye on people who live alone, and get someone to the door when they need help. It's for older people living on their own, people with disabilities, and anyone who sometimes needs a hand.

Each person has a small box by the door with **I'm OK** and **Help**. Every morning they press I'm OK. If they don't, if they press Help, or if a caregiver asks for a check-in and gets no answer, the first person on their list is asked to go and check, then the next, then the coordinator. When it's very cold and Alberta's grid is under strain, every box asks at once.

Porchlight doesn't diagnose anything, doesn't detect falls, and doesn't replace 911. Motion only shows someone was moving; it never counts as an I'm OK.

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
- **The box.** An Arduino UNO Q. The microcontroller reads the button and a motion sensor and drives a green and a red light, the 8x13 LED matrix and a vibration motor. The Linux side of the board sends presses to the server over Wi-Fi and polls for what to show. A Help press lights red straight away, even with no network, and is resent until the server has it. The browser box simulator (`/box.html`) has separate I'm OK and Help buttons and uses the same API, so the demo works without the hardware.
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

### Asking for a check-in

On the coordinator page (`/dashboard.html`), **Ask for a check-in** on someone's card makes their box show a question mark and buzz. They have 5 minutes to answer with I'm OK; the card shows Pending with a countdown, then Confirmed or Unanswered. An unanswered check-in doesn't start a Help call on its own: **Send someone** on the card does that if the coordinator decides it's needed. The card also shows when the person last pressed I'm OK, when the box last saw movement, and who is assigned to them. To try it without hardware, open `/box.html` next to the dashboard and press I'm OK there.

The time limit is `PORCHLIGHT_CHECKIN_TIMEOUT_SECONDS` (default 300). It runs on the replay clock, so at 30x speed 5 minutes passes in about 10 seconds; use 1x when testing the real box.

## The box

Our prototype's wiring:

| Part | Pin |
|---|---|
| Motion sensor (Adafruit PIR) | D2 |
| Button, to GND | D3 |
| Vibration motor driver | D5 |
| Green LED, with resistor | D8 |
| Red LED, with resistor | D9 |

The prototype reads one button: two quick presses (within 600 ms) mean I'm OK, one press means Help. Holding it down doesn't repeat. Green stays on for 5 seconds after an I'm OK or movement. Red stays on from a Help press until a coordinator marks it resolved, even if someone has already said they're going.

The motor is off by default (`PORCHLIGHT_MOTOR_ENABLED 0` in the sketch). Turn it on only once the motor is driven through a driver module, never straight from the pin. A check-in buzzes short, short, long; "someone is coming" buzzes twice.

In Arduino App Lab, create a new app, paste `device/porchlight-box/sketch/sketch.ino` into the sketch and `device/porchlight-box/python/main.py` into the Python part, and put a `device_config.json` beside `main.py` (see the example file). Set `server` to the laptop's address on the network (not `localhost`, which on the board means the board itself), `resident` to the person's ID, and `key` to the Box key on the Keys page. Put the board and the laptop on the same Wi-Fi, one without client isolation, and on Windows allow Python through the firewall on public networks too. Then press **Run** in App Lab; both the sketch and the Python part have to be running. To start it on power-up, turn on **Run at startup** for the app in App Lab ([Arduino's instructions](https://docs.arduino.cc/tutorials/uno-q/user-manual/#running-an-app-at-startup)).

`tests/test_device.py` compiles the real sketch against fake pins with the motor on and off and checks the button timing, the lights and the Python bridge. It needs a C++ compiler and skips itself without one. It doesn't replace trying it on the board.

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
