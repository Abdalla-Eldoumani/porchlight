"""Where events and readings are kept: Postgres (Tiger Data) when a database
URL is set, otherwise in memory, so the demo runs with nothing configured."""
import asyncio
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = Path(__file__).with_name("schema.sql").read_text()


class MemoryStore:
    kind = "memory"

    def __init__(self):
        self.grid, self.events, self.alerts, self.access = {}, [], [], []

    async def init(self):
        pass

    async def add_grid(self, t, source, row):
        self.grid[(t, source)] = dict(row, time=t, source=source)

    async def add_event(self, t, rid, kind, simulated):
        self.events.append({"time": t, "resident_id": rid, "kind": kind, "simulated": simulated})

    async def add_alert_log(self, t, alert_id, rid, action, detail):
        self.alerts.append({"time": t, "alert_id": alert_id, "resident_id": rid, "action": action, "detail": detail})

    async def add_access(self, who, what):
        self.access.append({"time": datetime.now(timezone.utc), "who": who, "what": what})

    async def recent_events(self, rid, limit):
        rows = [e for e in self.events if e["resident_id"] == rid]
        return rows[-limit:][::-1]

    async def recent_access(self, limit):
        return self.access[-limit:][::-1]

    async def grid_hourly(self, start, end, source):
        rows = [r for (t, s), r in self.grid.items() if s == source and start <= t < end]
        return sorted(rows, key=lambda r: r["time"])


class PgStore:
    kind = "postgres"

    def __init__(self, url):
        self.url, self.conn, self.lock = url, None, asyncio.Lock()
        self.timescale = False

    async def init(self):
        import psycopg
        self.conn = await psycopg.AsyncConnection.connect(self.url, autocommit=True)
        await self.conn.execute(SCHEMA)
        cur = await self.conn.execute("SELECT 1 FROM pg_extension WHERE extname = 'timescaledb'")
        self.timescale = await cur.fetchone() is not None
        self.kind = "tiger data (timescaledb)" if self.timescale else "postgres"

    async def _run(self, sql, args=()):
        async with self.lock:
            return await self.conn.execute(sql, args)

    async def add_grid(self, t, source, row):
        await self._run(
            "INSERT INTO grid_readings (time, source, ail_mw, price, cushion_mw, temp_c, level) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s) ON CONFLICT (time, source) DO NOTHING",
            (t, source, row.get("ail_mw"), row.get("price"), row.get("cushion_mw"), row.get("temp_c"), row.get("level")))

    async def add_event(self, t, rid, kind, simulated):
        await self._run("INSERT INTO device_events VALUES (%s, %s, %s, %s)", (t, rid, kind, simulated))

    async def add_alert_log(self, t, alert_id, rid, action, detail):
        await self._run("INSERT INTO alert_log VALUES (%s, %s, %s, %s, %s)", (t, alert_id, rid, action, detail))

    async def add_access(self, who, what):
        await self._run("INSERT INTO access_log (who, what) VALUES (%s, %s)", (who, what))

    async def _rows(self, sql, args):
        async with self.lock:
            cur = await self.conn.execute(sql, args)
            cols = [d.name for d in cur.description]
            return [dict(zip(cols, r)) for r in await cur.fetchall()]

    async def recent_events(self, rid, limit):
        return await self._rows("SELECT time, kind, simulated FROM device_events WHERE resident_id = %s "
                                "ORDER BY time DESC LIMIT %s", (rid, limit))

    async def recent_access(self, limit):
        return await self._rows("SELECT time, who, what FROM access_log ORDER BY time DESC LIMIT %s", (limit,))

    async def grid_hourly(self, start, end, source):
        bucket = "time_bucket('1 hour', time)" if self.timescale else "date_trunc('hour', time)"
        return await self._rows(
            f"SELECT {bucket} AS time, avg(ail_mw) AS ail_mw, avg(price) AS price, avg(temp_c) AS temp_c "
            f"FROM grid_readings WHERE source = %s AND time >= %s AND time < %s GROUP BY 1 ORDER BY 1",
            (source, start, end))

