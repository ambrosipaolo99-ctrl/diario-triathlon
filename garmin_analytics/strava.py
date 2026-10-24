"""
Dislivello da Strava.

Il barometro dell'orologio puo' registrare dislivelli impossibili anche in piano (migliaia di metri
su un lungo in pianura, dove Strava ne conta meno di 100): per le corse il riferimento e' Strava.
Le attivita' arrivano dal connettore Strava della sessione Claude come JSON (formato di
`list_activities`) e si importano con `python main.py strava-import <file>`; le corse il cui
dislivello cambia vengono rianalizzate dai FIT gia' scaricati, senza chiamate a Garmin.
"""
from __future__ import annotations

import json
import logging
import sqlite3
from datetime import timedelta
from pathlib import Path
from typing import Optional

import pandas as pd

from . import db

log = logging.getLogger("garmin_analytics.strava")

MATCH_S = 300           # scarto massimo tra le partenze Garmin e Strava
RUN_TYPES = ("Run", "TrailRun", "VirtualRun")


def _items(payload) -> list[dict]:
    """Accetta la risposta di list_activities, un elenco di risposte o un elenco di attivita'."""
    if isinstance(payload, dict):
        return payload.get("activities", [])
    out = []
    for x in payload:
        out.extend(_items(x) if isinstance(x, dict) and "activities" in x else [x])
    return out


def import_activities(conn: sqlite3.Connection, payload) -> int:
    n = 0
    for a in _items(payload):
        s = a.get("summary") or {}
        if not a.get("id") or not a.get("start_local"):
            continue
        db.upsert(conn, "strava_activities", "strava_id", {
            "strava_id": int(a["id"]), "start_local": a["start_local"][:19], "sport_type": a.get("sport_type"),
            "name": a.get("name"), "distance_m": s.get("distance"), "moving_s": s.get("moving_time"),
            "elevation_gain_m": s.get("elevation_gain"), "fetched_at": db.now_iso(),
        }, keep_existing=False)
        n += 1
    conn.commit()
    return n


def import_file(conn: sqlite3.Connection, path: Path) -> int:
    return import_activities(conn, json.loads(Path(path).read_text(encoding="utf-8")))


def match(conn: sqlite3.Connection, start_local: Optional[str], distance_m: Optional[float] = None) -> Optional[dict]:
    """La corsa Strava con la partenza piu' vicina (entro 5'); a parita', la distanza piu' simile."""
    if not start_local:
        return None
    t = pd.Timestamp(start_local)
    lo, hi = ((t + timedelta(seconds=s)).strftime("%Y-%m-%dT%H:%M:%S") for s in (-MATCH_S, MATCH_S))
    rows = conn.execute(
        f"SELECT * FROM strava_activities WHERE start_local BETWEEN ? AND ? "
        f"AND sport_type IN ({','.join('?' * len(RUN_TYPES))})", (lo, hi, *RUN_TYPES)).fetchall()
    if not rows:
        return None
    key = lambda r: (abs((pd.Timestamp(r["start_local"]) - t).total_seconds()),  # noqa: E731
                     abs((r["distance_m"] or 0) - (distance_m or 0)))
    return dict(min(rows, key=key))


def stale_runs(conn: sqlite3.Connection) -> list[int]:
    """Corse analizzate con un dislivello diverso da quello Strava ora disponibile (per le frazioni, il multisport)."""
    out = []
    q = ("SELECT activity_id, parent_id, start_local, distance_m, metrics_json FROM activities "
         "WHERE sport='run' AND is_parent=0 AND metrics_json IS NOT NULL")
    for r in conn.execute(q):
        sv = match(conn, r["start_local"], r["distance_m"])
        if not sv or sv["elevation_gain_m"] is None:
            continue
        m = json.loads(r["metrics_json"]).get("metrics", {})
        if m.get("treadmill"):
            continue
        if m.get("ascent_source") != "strava" or m.get("ascent_m") != round(sv["elevation_gain_m"]):
            out.append(r["parent_id"] or r["activity_id"])
    return sorted(set(out))


def reanalyze(conn: sqlite3.Connection, ids: list[int]) -> int:
    """
    Rianalisi dai FIT in cache, dalla corsa piu' vecchia: lo storico dei confronti resta coerente.
    Solo i multisport chiedono a Garmin il dettaglio con le frazioni (login con i token salvati).
    """
    from .analysis import analyze_summary, mark_duplicates
    from .auth import get_client
    cols = ("activity_id", "start_local", "start_gmt", "type_key", "sport", "name", "duration_s", "distance_m",
            "avg_hr", "avg_power", "norm_power", "garmin_load", "device_id", "is_parent")
    rows = conn.execute(f"SELECT * FROM activities WHERE activity_id IN ({','.join('?' * len(ids))}) "
                        "ORDER BY start_gmt", ids).fetchall() if ids else []
    done, api = 0, None
    for r in rows:
        try:
            if r["sport"] == "multi" and api is None:
                api = get_client()
            analyze_summary(api, conn, {k: r[k] for k in cols}, json.loads(r["raw_json"] or "{}"))
            done += 1
        except Exception as exc:
            log.error("Rianalisi fallita per %s (%s): %s", r["activity_id"], r["name"], exc)
    if done:
        mark_duplicates(conn)
    return done
