# Porchlight

A check-in box for people who live alone in Calgary. It has two buttons: **I'm OK** and **Help**. Every morning the person presses I'm OK. If they don't, a volunteer neighbour gets asked to call or knock.

When it's very cold and Alberta's electricity grid is under strain, every box asks again ("Please press I'm OK") and anyone who doesn't answer within 30 minutes gets a neighbour at the door. Volunteers reply from their phone, and the box buzzes and shows a heart when someone is on the way.

Porchlight doesn't replace 911. It gets a neighbour there sooner.

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
- **The box.** An Arduino UNO Q. The microcontroller reads the buttons and a motion sensor and drives a vibration motor and the 8x13 LED matrix. The Linux side of the board sends presses to the server over Wi-Fi and polls for what to show. A press shows on the box straight away, even if the network is down, and is resent until the server gets it. The browser box simulator (`/box.html`) uses the same API, so the demo works without the hardware.
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
python -m uvicorn server.app:app --host 0.0.0.0 --port 8000
```

Open http://localhost:8000. The demo screen replays January 13, 2024 from 3:15 pm at 30 times real speed, with Margaret's box on the left, a map of Calgary in the middle and a volunteer's phone on the right. The bar under the clock says what is happening and what to try next; **Skip ahead** jumps to the next thing that happens. When anyone presses Help, the replay drops to real time so the call plays out live.

**Pitch** is a six-slide deck (arrow keys to move, F for full screen) that hands off to the demo. **How it works** explains the idea in plain words, with the Calgary numbers and their sources. Every page has a bigger-text and a high-contrast button in the top bar, remembered in that browser, and the logo always leads back to the demo.

To switch services on, open **Keys** in the top bar, paste a key, press Test, then Save. Everything there is optional. Keys typed there are kept in memory, or in the computer's own password store (Windows Credential Manager) if "Remember on this computer" is ticked; nothing is written into the project. From another device the Keys page asks for the setup code printed in the server window. Environment variables (see `.env.example`) still work and are the way to configure a server you deploy.

Tests: `python -m pytest -q`

## The box

Wiring (all 3.3 V logic): I'm OK button between D2 and GND, Help button between D4 and GND, vibration module IN on D5 (VCC to 5V, GND to GND), PIR OUT on D7 (VCC to 5V, GND to GND).

In Arduino App Lab, create a new app, paste `device/porchlight-box/sketch/sketch.ino` into the sketch and `device/porchlight-box/python/main.py` into the Python part, and put a `device_config.json` beside `main.py` (see the example file). The `key` must match the Box key on the Keys page. On Windows, allow Python through the firewall on public networks too, or the board can't reach a laptop on a phone hotspot.

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
