"""
Obiettivi stagionali: storico e obiettivo attivo.

Gli obiettivi stanno in data/goals.json (modificabile a mano o con `python main.py goal ...`).
Campi: id, name, date, discipline (corsa / triathlon / ...), distance (etichetta),
distance_km (distanza della corsa da stimare), priority (A/B/C), active (opzionale).

L'obiettivo attivo e' quello con active=true; se nessuno lo e', il primo futuro con
priorita' piu' alta. Il profilo della distanza decide fase di scarico, lungo di
riferimento e metodi di stima usati nel resto dell'analisi.
"""
from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Optional

from .config import DATA_DIR

GOALS_PATH = DATA_DIR / "goals.json"

# nessun obiettivo predefinito: sono dati personali e il codice e' pubblico (si aggiungono con `main.py goal add`)
DEFAULT_GOALS: list[dict[str, Any]] = []

# distanze di corsa note: etichetta -> km
RUN_DISTANCES = {"5 km": 5.0, "10 km": 10.0, "mezza maratona": 21.0975, "maratona": 42.195}


@dataclass
class RunProfile:
    """Parametri della distanza di corsa che guidano piano, zone e voti."""
    distance_km: float
    taper_days: int           # giorni di scarico prima della gara
    long_peak_km: float       # lungo di riferimento nel periodo di carico
    race_pace_name: str       # come si chiama il ritmo gara nel piano
    min_effort_min: int       # durata minima degli sforzi usati per VDOT/Riegel

    @property
    def is_marathon(self) -> bool:
        return self.distance_km > 40


def run_profile(distance_km: float) -> RunProfile:
    # scarico: 7-10 gg per 5-10 km, ~2 settimane per la mezza, 3 per la maratona (Bosquet 2007, Mujika)
    if distance_km >= 40:
        return RunProfile(distance_km, 21, 32, "passo maratona", 30)
    if distance_km >= 20:
        return RunProfile(distance_km, 14, 22, "passo mezza", 20)
    if distance_km >= 9:
        return RunProfile(distance_km, 10, 16, "passo 10 km", 12)
    return RunProfile(distance_km, 7, 12, "passo 5 km", 6)


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:48]


def load_goals() -> list[dict[str, Any]]:
    if not GOALS_PATH.exists():
        save_goals(DEFAULT_GOALS)
    return json.loads(GOALS_PATH.read_text(encoding="utf-8"))


def save_goals(goals: list[dict[str, Any]]) -> None:
    GOALS_PATH.parent.mkdir(parents=True, exist_ok=True)
    goals = sorted(goals, key=lambda g: g["date"])
    GOALS_PATH.write_text(json.dumps(goals, ensure_ascii=False, indent=2), encoding="utf-8")


def active_goal(goals: list[dict[str, Any]], today: Optional[date] = None) -> Optional[dict[str, Any]]:
    today = today or date.today()
    flagged = [g for g in goals if g.get("active")]
    if flagged:
        return flagged[0]
    future = [g for g in goals if date.fromisoformat(g["date"]) >= today]
    future.sort(key=lambda g: (g.get("priority", "C"), g["date"]))
    return future[0] if future else None


def goal_window_start(goals: list[dict[str, Any]], goal: dict[str, Any]) -> date:
    """Il blocco dell'obiettivo parte il giorno dopo l'obiettivo precedente (max 16 settimane prima)."""
    d = date.fromisoformat(goal["date"])
    prev = [date.fromisoformat(g["date"]) for g in goals if date.fromisoformat(g["date"]) < d]
    start = max(prev) + timedelta(days=1) if prev else d - timedelta(weeks=16)
    return max(start, d - timedelta(weeks=16))


def add_goal(name: str, day: str, discipline: str, distance: str, priority: str,
             distance_km: Optional[float] = None, activate: bool = False) -> dict[str, Any]:
    goals = load_goals()
    km = distance_km or RUN_DISTANCES.get(distance.lower())
    g = {"id": _slug(f"{name}-{day[:4]}"), "name": name, "date": day, "discipline": discipline.lower(),
         "distance": distance, "distance_km": km, "priority": priority.upper()}
    goals = [x for x in goals if x["id"] != g["id"]] + [g]
    if activate:
        for x in goals:
            x.pop("active", None)
        g["active"] = True
    save_goals(goals)
    return g


def set_active(goal_id: str) -> bool:
    goals = load_goals()
    if not any(g["id"] == goal_id for g in goals):
        return False
    for g in goals:
        g.pop("active", None)
        if g["id"] == goal_id:
            g["active"] = True
    save_goals(goals)
    return True


def _race_result(conn: sqlite3.Connection, goal: dict[str, Any]) -> dict[str, Any]:
    """Tempo finale dall'attivita' del giorno di gara (multisport intero o corsa), +-1 giorno."""
    d = date.fromisoformat(goal["date"])
    lo, hi = (d - timedelta(days=1)).isoformat(), (d + timedelta(days=1)).isoformat() + "T23:59"
    if goal.get("discipline") == "triathlon":
        q = ("SELECT activity_id, start_local, duration_s, distance_m FROM activities WHERE is_parent=1 "
             "AND start_local BETWEEN ? AND ? ORDER BY duration_s DESC LIMIT 1")
    else:
        q = ("SELECT activity_id, start_local, duration_s, distance_m FROM activities WHERE sport='run' "
             "AND is_parent=0 AND duplicate_of IS NULL AND start_local BETWEEN ? AND ? "
             "AND distance_m >= ? ORDER BY distance_m DESC LIMIT 1")
    args = (lo, hi) if goal.get("discipline") == "triathlon" else (lo, hi, 0.9 * (goal.get("distance_km") or 0) * 1000)
    r = conn.execute(q, args).fetchone()
    if not r:
        return {}
    return {"result_activity_id": str(r["activity_id"]), "result_date": r["start_local"][:10],
            "result_s": r["duration_s"]}


def goal_rows(conn: sqlite3.Connection, goals: list[dict[str, Any]], today: Optional[date] = None) -> list[dict]:
    today = today or date.today()
    act = active_goal(goals, today)
    rows = []
    for g in sorted(goals, key=lambda x: x["date"]):
        d = date.fromisoformat(g["date"])
        status = "attivo" if act and g["id"] == act["id"] else "concluso" if d < today else "futuro"
        row = {"id": g["id"], "name": g["name"], "date": g["date"], "discipline": g.get("discipline"),
               "distance": g.get("distance"), "distance_km": g.get("distance_km"),
               "priority": g.get("priority"), "status": status, "days_to": (d - today).days,
               "target_s": g.get("target_s")}
        if d <= today:
            row.update(_race_result(conn, g))
        rows.append(row)
    return rows
