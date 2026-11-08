-- Runs on Tiger Data (TimescaleDB) and on plain Postgres. On Tiger Data the
-- two time-series tables become hypertables.
DO $$ BEGIN
  IF EXISTS (SELECT 1 FROM pg_available_extensions WHERE name = 'timescaledb') THEN
    CREATE EXTENSION IF NOT EXISTS timescaledb;
  END IF;
END $$;

CREATE TABLE IF NOT EXISTS grid_readings (
  time        timestamptz NOT NULL,
  source      text        NOT NULL,   -- aeso_ets_2024 (replay) or aeso_api (live)
  ail_mw      double precision,
  price       double precision,
  cushion_mw  double precision,
  temp_c      double precision,
  level       text,
  UNIQUE (time, source)
);

CREATE TABLE IF NOT EXISTS device_events (
  time         timestamptz NOT NULL,
  resident_id  text        NOT NULL,
  kind         text        NOT NULL,  -- ok | help | motion
  simulated    boolean     NOT NULL DEFAULT false
);

CREATE TABLE IF NOT EXISTS alert_log (
  time         timestamptz NOT NULL,
  alert_id     integer     NOT NULL,
  resident_id  text        NOT NULL,
  action       text        NOT NULL,
  detail       text
);

CREATE TABLE IF NOT EXISTS access_log (
  time   timestamptz NOT NULL DEFAULT now(),
  who    text        NOT NULL,
  what   text        NOT NULL
);

DO $$ BEGIN
  IF EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'timescaledb') THEN
    PERFORM create_hypertable('grid_readings', by_range('time'), if_not_exists => TRUE);
    PERFORM create_hypertable('device_events', by_range('time'), if_not_exists => TRUE);
  END IF;
END $$;

CREATE INDEX IF NOT EXISTS device_events_resident ON device_events (resident_id, time DESC);
