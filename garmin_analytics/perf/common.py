"""Corse con serie a 30 s, dinamiche e quota, condivise dai moduli di analisi."""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from datetime import date
from typing import Optional

from .. import db

STEP_S = 30                     # passo delle serie salvate dall'analisi
DEFAULT_WEIGHT = 66.0


@dataclass
class RunDetail:
    id: str
    day: date
    start: str
    name: str
    km: float
    moving_s: float
    treadmill: bool
    steady: bool
    hr: Optional[float]
    speed: Optional[float]
    stream: list[dict] = field(default_factory=list)
    gct_balance: Optional[float] = None       # % sinistra, media della corsa
    altitude_reliable: bool = False
    ascent_m: Optional[float] = None
    ascent_source: Optional[str] = None
    ef: Optional[float] = None                # Efficiency Factor (m/min per battito)


def load_runs(conn: sqlite3.Connection, since: Optional[str] = None) -> list[RunDetail]:
    q = ("SELECT activity_id, start_local, name, metrics_json FROM activities WHERE sport='run' AND is_parent=0 "
         "AND duplicate_of IS NULL AND metrics_json IS NOT NULL" + (" AND start_local >= ?" if since else "") +
         " ORDER BY start_local")
    out = []
    for r in conn.execute(q, (since,) if since else ()):
        res = json.loads(r["metrics_json"])
        m = res.get("metrics", {})
        if not m.get("avg_speed_ms"):
            continue
        out.append(RunDetail(
            id=str(r["activity_id"]), day=date.fromisoformat(r["start_local"][:10]), start=r["start_local"],
            name=r["name"] or "", km=m.get("distance_km") or 0, moving_s=m.get("moving_time_s") or 0,
            treadmill=bool(m.get("treadmill")), steady=bool(m.get("steady")), hr=m.get("avg_hr"),
            speed=m.get("avg_speed_ms"), stream=res.get("stream", []),
            gct_balance=(m.get("dynamics") or {}).get("gct_balance_left_pct"),
            altitude_reliable=bool(m.get("altitude_reliable")), ascent_m=m.get("ascent_m"),
            ascent_source=m.get("ascent_source"), ef=m.get("ef_speed"),
        ))
    return out


def athlete_weight(conn: sqlite3.Connection) -> float:
    """Peso dal profilo Garmin (stesso dato usato dal piano), altrimenti un valore di riferimento."""
    lt = (db.get_setting(conn, "lactate_threshold") or {}).get("power") or {}
    try:
        return float(lt["weight"]) if lt.get("weight") else DEFAULT_WEIGHT
    except (TypeError, ValueError):
        return DEFAULT_WEIGHT


def percentile_of(value: Optional[float], history: list[float]) -> Optional[float]:
    """Posizione 0-100 del valore rispetto allo storico (meta' dei pari conta come sotto)."""
    h = [x for x in history if x is not None]
    if value is None or len(h) < 5:
        return None
    below = sum(1 for x in h if x < value) + 0.5 * sum(1 for x in h if x == value)
    return round(100 * below / len(h), 1)
