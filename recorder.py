#!/usr/bin/env python3
"""Compact daily telemetry and spike recorder for the monitored device."""

from __future__ import annotations

import datetime as dt
import json
import sqlite3
import threading
from pathlib import Path
from typing import Any

from fastapi import FastAPI

DB_PATH = Path(__file__).with_name("monitoring_records.db")
DB_LOCK = threading.Lock()
app = FastAPI(title="IQAC Monitoring Records")


def init_db() -> None:
    with DB_LOCK, sqlite3.connect(DB_PATH) as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS daily_metrics (
                day TEXT PRIMARY KEY,
                reading_count INTEGER NOT NULL,
                temperature_sum REAL NOT NULL,
                temperature_max REAL NOT NULL,
                temperature_min REAL NOT NULL,
                cpu_sum REAL NOT NULL,
                rpm_sum REAL NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS spike_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                recorded_at TEXT NOT NULL,
                agent TEXT NOT NULL,
                temperature_c REAL NOT NULL,
                cpu_usage REAL NOT NULL,
                fan_rpm REAL NOT NULL,
                details TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS recorder_state (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            """
        )


def record_reading(
    temperature_c: float,
    cpu_usage: float = 0.0,
    fan_rpm: float = 0.0,
    agent: str = "monitor",
    recorded_at: str | None = None,
    is_spike: bool = False,
    details: dict[str, Any] | None = None,
) -> None:
    recorded_at = recorded_at or dt.datetime.now(dt.timezone.utc).isoformat()
    timestamp = dt.datetime.fromisoformat(recorded_at.replace("Z", "+00:00"))
    day = timestamp.date().isoformat()
    with DB_LOCK, sqlite3.connect(DB_PATH) as connection:
        connection.execute(
            "INSERT OR IGNORE INTO recorder_state (key, value) VALUES ('first_seen_at', ?)",
            (recorded_at,),
        )
        connection.execute(
            "INSERT INTO recorder_state (key, value) VALUES ('last_seen_at', ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (recorded_at,),
        )
        connection.execute(
            """INSERT INTO daily_metrics
            (day, reading_count, temperature_sum, temperature_max, temperature_min,
             cpu_sum, rpm_sum, updated_at)
            VALUES (?, 1, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(day) DO UPDATE SET
              reading_count = reading_count + 1,
              temperature_sum = temperature_sum + excluded.temperature_sum,
              temperature_max = MAX(temperature_max, excluded.temperature_max),
              temperature_min = MIN(temperature_min, excluded.temperature_min),
              cpu_sum = cpu_sum + excluded.cpu_sum,
              rpm_sum = rpm_sum + excluded.rpm_sum,
              updated_at = excluded.updated_at""",
            (day, temperature_c, temperature_c, temperature_c, cpu_usage, fan_rpm, recorded_at),
        )
        if is_spike:
            connection.execute(
                """INSERT INTO spike_events
                (recorded_at, agent, temperature_c, cpu_usage, fan_rpm, details)
                VALUES (?, ?, ?, ?, ?, ?)""",
                (recorded_at, agent, temperature_c, cpu_usage, fan_rpm, json.dumps(details or {})),
            )


def get_records(since: str | None = None) -> dict[str, Any]:
    with DB_LOCK, sqlite3.connect(DB_PATH) as connection:
        connection.row_factory = sqlite3.Row
        daily_query = "SELECT * FROM daily_metrics"
        params: tuple[Any, ...] = ()
        if since:
            daily_query += " WHERE day >= ?"
            params = (since,)
        daily_query += " ORDER BY day"
        daily = [dict(row) for row in connection.execute(daily_query, params)]
        spikes = [dict(row) for row in connection.execute("SELECT * FROM spike_events ORDER BY id")]
        state = dict(connection.execute("SELECT key, value FROM recorder_state").fetchall())
    for row in daily:
        row["average_temperature_c"] = row.pop("temperature_sum") / row["reading_count"]
        row["average_cpu_usage"] = row.pop("cpu_sum") / row["reading_count"]
        row["average_fan_rpm"] = row.pop("rpm_sum") / row["reading_count"]
        row["spike_count"] = sum(1 for spike in spikes if spike["recorded_at"][:10] == row["day"])
    duration_hours = 0.0
    try:
        duration_hours = max(0.0, (
            dt.datetime.fromisoformat(state["last_seen_at"].replace("Z", "+00:00")).timestamp()
            - dt.datetime.fromisoformat(state["first_seen_at"].replace("Z", "+00:00")).timestamp()
        ) / 3600.0)
    except (KeyError, TypeError, ValueError):
        pass
    return {"daily": daily, "spikes": spikes, "monitoring_duration_hours": duration_hours}


@app.on_event("startup")
def startup() -> None:
    init_db()


@app.get("/")
def health() -> dict[str, str]:
    return {"status": "monitoring", "service": "iqac-recording-agent"}


@app.get("/records")
def records(since: str | None = None) -> dict[str, Any]:
    return get_records(since)


init_db()
