"""Grid and weather conditions: the real Jan 12-14 2024 data for the replay,
and live AESO + Open-Meteo readings for live mode."""
import csv
import json
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx

TZ = ZoneInfo("America/Edmonton")
DATA = Path(__file__).resolve().parent.parent / "data"
AESO_CSD = "https://apimgw.aeso.ca/public/currentsupplydemand-api/v2/csd/summary/current"
OPEN_METEO = ("https://api.open-meteo.com/v1/forecast?latitude=51.05&longitude=-114.07"
              "&current=temperature_2m,apparent_temperature&timezone=America%2FEdmonton")
HIGH_PRICE = 500.0   # $/MWh; a price this high means supply is tight


class Replay:
    def __init__(self):
        self.hours = {}   # hour start -> {price, ail_mw}
        with open(DATA / "aeso_pool_price_2024-01-12_to_14.csv") as f:
            for row in csv.reader(f):
                if len(row) == 4 and "/" in row[0]:
                    day, he = row[0].split()
                    start = datetime.strptime(day, "%m/%d/%Y").replace(tzinfo=TZ) + timedelta(hours=int(he) - 1)
                    self.hours[start] = {"price": float(row[1]), "ail_mw": float(row[3])}
        self.temps = {}
        with open(DATA / "calgary_weather_2024-01-12_to_14.csv") as f:
            for row in csv.DictReader(f):
                if row["temp_c"]:
                    t = datetime.strptime(row["time_lst"], "%Y-%m-%d %H:%M").replace(tzinfo=TZ)
                    self.temps[t] = float(row["temp_c"])
        timeline = json.loads((DATA / "jan13_2024_timeline.json").read_text())
        self.events = [dict(e, time=datetime.fromisoformat(e["time"])) for e in timeline["events"]]

    def conditions(self, now):
        hour = now.replace(minute=0, second=0, microsecond=0)
        g = self.hours.get(hour, {})
        level = "normal"
        for e in self.events:
            if e["time"] <= now:
                level = e["level"]
        if level == "normal" and g.get("price", 0) >= HIGH_PRICE:
            level = "watch"
        return {"source": "AESO pool price report + Environment Canada, Jan 2024",
                "price": g.get("price"), "ail_mw": g.get("ail_mw"), "cushion_mw": None,
                "temp_c": self.temps.get(hour), "level": level}

    def passed_events(self, before, now):
        return [e for e in self.events if before < e["time"] <= now]

    def series(self, day):
        """Hourly rows for one day, for the dashboard chart and the database seed."""
        out = []
        for start, g in sorted(self.hours.items()):
            if start.date() == day:
                out.append({"time": start.isoformat(), "price": g["price"], "ail_mw": g["ail_mw"],
                            "temp_c": self.temps.get(start)})
        return out


def level_from_cushion(cushion_mw):
    """Live mode has no EEA feed, so we use supply cushion (capability not yet
    generating). Rough thresholds, ours: not AESO's."""
    if cushion_mw is None:
        return "normal"
    if cushion_mw < 500:
        return "alert"
    if cushion_mw < 1000:
        return "watch"
    return "normal"


async def fetch_aeso(client, api_key):
    r = await client.get(AESO_CSD, headers={"API-KEY": api_key, "Cache-Control": "no-cache"}, timeout=10)
    r.raise_for_status()
    ret = r.json()["return"]
    gens = ret.get("generation_data_list", [])
    capability = sum(g.get("aggregated_maximum_capability") or 0 for g in gens)
    generating = sum(g.get("aggregated_net_generation") or 0 for g in gens)
    cushion = capability - generating if gens else None
    return {"ail_mw": ret.get("alberta_internal_load"), "cushion_mw": cushion,
            "level": level_from_cushion(cushion), "aeso_time": ret.get("effective_datetime_utc")}


async def fetch_temp(client):
    r = await client.get(OPEN_METEO, timeout=10)
    r.raise_for_status()
    return r.json()["current"]["temperature_2m"]


class Live:
    def __init__(self):
        self.last = {"source": "live", "price": None, "ail_mw": None, "cushion_mw": None,
                     "temp_c": None, "level": "normal", "error": None}

    def conditions(self, now):
        return dict(self.last, source="AESO Current Supply Demand API + Open-Meteo (live)")

    async def refresh(self, client, api_key):
        errors = []
        if api_key:
            try:
                self.last.update(await fetch_aeso(client, api_key))
            except Exception as e:      # keep the last good reading; show the error
                errors.append(f"AESO: {e}")
        else:
            errors.append("AESO_API_KEY not set")
        try:
            self.last["temp_c"] = await fetch_temp(client)
        except Exception as e:
            errors.append(f"weather: {e}")
        self.last["error"] = "; ".join(errors) or None
        return self.last
