"""Database SQLite locale."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from typing import Any, Iterable, Optional

import pandas as pd

from .config import DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS wellness_daily (
    date                TEXT PRIMARY KEY,   -- giorno del risveglio (YYYY-MM-DD)
    sleep_seconds       INTEGER,
    deep_seconds        INTEGER,
    light_seconds       INTEGER,
    rem_seconds         INTEGER,
    awake_seconds       INTEGER,
    sleep_score         INTEGER,
    sleep_need_minutes  INTEGER,
    sleep_start         TEXT,
    sleep_end           TEXT,
    avg_sleep_stress    REAL,
    hrv_last_night      REAL,
    hrv_weekly_avg      REAL,
    hrv_5min_high       REAL,
    hrv_status          TEXT,
    hrv_baseline_low    REAL,
    hrv_baseline_high   REAL,
    rhr                 INTEGER,
    bb_at_wake          INTEGER,
    bb_high             INTEGER,
    bb_low              INTEGER,
    bb_charged          INTEGER,
    bb_drained          INTEGER,
    stress_avg          INTEGER,
    stress_max          INTEGER,
    stress_high_seconds INTEGER,
    training_readiness  INTEGER,
    recovery_index      REAL,
    recovery_json       TEXT,
    fetched_at          TEXT
);

CREATE TABLE IF NOT EXISTS activities (
    activity_id      INTEGER PRIMARY KEY,
    parent_id        INTEGER,               -- valorizzato per le frazioni di un multisport
    is_parent        INTEGER DEFAULT 0,
    duplicate_of     INTEGER,               -- stessa sessione registrata da un altro device
    start_local      TEXT,
    start_gmt        TEXT,
    type_key         TEXT,
    sport            TEXT,                  -- run / bike / swim / multi / other
    name             TEXT,
    duration_s       REAL,
    distance_m       REAL,
    avg_hr           REAL,
    avg_power        REAL,
    norm_power       REAL,
    garmin_load      REAL,
    device_id        INTEGER,
    tss              REAL,
    tss_method       TEXT,
    score            INTEGER,
    metrics_json     TEXT,
    analyzer_version INTEGER,
    analyzed_at      TEXT,
    raw_json         TEXT
);
CREATE INDEX IF NOT EXISTS idx_act_start ON activities(start_gmt);

-- attivita' Strava, usate per il dislivello: l'orologio lo misura male, Strava no
CREATE TABLE IF NOT EXISTS strava_activities (
    strava_id        INTEGER PRIMARY KEY,
    start_local      TEXT,
    sport_type       TEXT,
    name             TEXT,
    distance_m       REAL,
    moving_s         REAL,
    elevation_gain_m REAL,
    fetched_at       TEXT
);
CREATE INDEX IF NOT EXISTS idx_strava_start ON strava_activities(start_local);

CREATE TABLE IF NOT EXISTS settings (
    key        TEXT PRIMARY KEY,
    value      TEXT,
    updated_at TEXT
);
"""


# colonne aggiunte dopo la prima versione dello schema: (tabella, colonna, tipo)
MIGRATIONS = [
    ("wellness_daily", "resp_sleep", "REAL"),          # respiri/min medi nel sonno
    ("wellness_daily", "spo2_sleep", "REAL"),          # SpO2 media nel sonno
    ("wellness_daily", "bb_sleep_charge", "INTEGER"),  # Body Battery recuperata nella notte
]


def connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    for table, col, typ in MIGRATIONS:
        cols = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
        if col not in cols:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {typ}")
    return conn


def upsert(conn: sqlite3.Connection, table: str, key: str, row: dict[str, Any], keep_existing: bool = True) -> None:
    """INSERT o UPDATE. Con keep_existing un valore None non sovrascrive un dato gia' presente."""
    cols = list(row)
    placeholders = ", ".join("?" for _ in cols)
    if keep_existing:
        updates = ", ".join(f"{c}=COALESCE(excluded.{c}, {c})" for c in cols if c != key)
    else:
        updates = ", ".join(f"{c}=excluded.{c}" for c in cols if c != key)
    sql = (f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({placeholders}) "
           f"ON CONFLICT({key}) DO UPDATE SET {updates}")
    conn.execute(sql, [row[c] for c in cols])


def read_df(conn: sqlite3.Connection, sql: str, params: Iterable[Any] = ()) -> pd.DataFrame:
    return pd.read_sql_query(sql, conn, params=list(params))


def get_setting(conn: sqlite3.Connection, key: str) -> Optional[Any]:
    row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return json.loads(row["value"]) if row else None


def setting_age_days(conn: sqlite3.Connection, key: str) -> Optional[float]:
    row = conn.execute("SELECT updated_at FROM settings WHERE key=?", (key,)).fetchone()
    if not row:
        return None
    return (datetime.now() - datetime.fromisoformat(row["updated_at"])).total_seconds() / 86400


def set_setting(conn: sqlite3.Connection, key: str, value: Any) -> None:
    upsert(conn, "settings", "key",
           {"key": key, "value": json.dumps(value, default=str), "updated_at": now_iso()},
           keep_existing=False)


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")
