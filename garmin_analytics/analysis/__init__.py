"""
Modulo 2 - Analisi allenamenti e punteggio 1-100.

`analyze_activity(activity_id)` riconosce lo sport, scarica (una sola volta) il
FIT originale, analizza ogni sessione e salva risultato e metriche su SQLite.
I multisport vengono divisi in frazioni (nuoto/bici/corsa), valutate
singolarmente; il voto del multisport e' la media pesata per durata.
"""
from __future__ import annotations

import json
import logging
import sqlite3
from dataclasses import asdict, replace
from datetime import date, datetime, timedelta
from typing import Any, Optional

import numpy as np
import pandas as pd

from .. import db, strava
from ..auth import get_client, throttled
from ..config import CSS_SEC_PER_100M, DATA_START
from ..fitdata import FitSession, load_activity_fit
from .common import AthleteContext, SessionResult, hr_tss, rnd
from .cycling import analyze_bike
from .running import analyze_run
from .swimming import analyze_swim

log = logging.getLogger("garmin_analytics.analysis")

ANALYZER_VERSION = 4
HISTORY_DAYS = {"run": 120, "bike": 180, "swim": 240}
SETTINGS_MAX_AGE_DAYS = 7

FIT_SPORT = {"running": "run", "cycling": "bike", "swimming": "swim"}
ANALYZERS = {"run": analyze_run, "bike": analyze_bike, "swim": analyze_swim}
SPORT_LABEL = {"run": "Corsa", "bike": "Bici", "swim": "Nuoto", "multi": "Multisport", "other": "Altro"}


def sport_family(type_key: str) -> str:
    t = (type_key or "").lower()
    if t == "multi_sport":
        return "multi"
    if "run" in t:
        return "run"
    if "cycl" in t or "biking" in t or "ride" in t:
        return "bike"
    if "swim" in t:
        return "swim"
    return "other"


def _iso(ts: Any) -> Optional[str]:
    if not ts:
        return None
    return pd.Timestamp(ts).strftime("%Y-%m-%dT%H:%M:%S")


# --------------------------------------------------------------------------- #
# Riepiloghi attivita' (elenco e dettaglio hanno forme diverse)
# --------------------------------------------------------------------------- #
def summary_from_list(x: dict) -> dict:
    tk = x["activityType"]["typeKey"]
    return {
        "activity_id": x["activityId"],
        "start_local": _iso(x.get("startTimeLocal")),
        "start_gmt": _iso(x.get("startTimeGMT")),
        "type_key": tk, "sport": sport_family(tk), "name": x.get("activityName"),
        "duration_s": x.get("duration"), "distance_m": x.get("distance"),
        "avg_hr": x.get("averageHR"), "avg_power": x.get("avgPower"), "norm_power": x.get("normPower"),
        "garmin_load": x.get("activityTrainingLoad"), "device_id": x.get("deviceId"),
        "is_parent": int(bool(x.get("isParent")) or tk == "multi_sport"),
        "raw_json": json.dumps(x),
    }


def summary_from_detail(d: dict) -> dict:
    s = d.get("summaryDTO") or {}
    tk = d["activityTypeDTO"]["typeKey"]
    return {
        "activity_id": d["activityId"],
        "start_local": _iso(s.get("startTimeLocal")),
        "start_gmt": _iso(s.get("startTimeGMT")),
        "type_key": tk, "sport": sport_family(tk), "name": d.get("activityName"),
        "duration_s": s.get("duration"), "distance_m": s.get("distance"),
        "avg_hr": s.get("averageHR"), "avg_power": s.get("averagePower"), "norm_power": s.get("normalizedPower"),
        "garmin_load": s.get("activityTrainingLoad"),
        "device_id": int((d.get("metadataDTO") or {}).get("deviceMetaDataDTO", {}).get("deviceId") or 0) or None,
        "is_parent": int(bool(d.get("isMultiSportParent"))),
        "raw_json": json.dumps(d),
    }


# --------------------------------------------------------------------------- #
# Soglie e zone dell'atleta
# --------------------------------------------------------------------------- #
def refresh_settings(api, conn: sqlite3.Connection, force: bool = False) -> None:
    """Zone FC/potenza, FTP e soglia lattato da Garmin (al massimo una volta a settimana)."""
    age = db.setting_age_days(conn, "hr_zones")
    if not force and age is not None and age < SETTINGS_MAX_AGE_DAYS:
        return
    for key, fn in (("hr_zones", api.get_heart_rate_zones), ("power_zones", api.get_power_zones),
                    ("cycling_ftp", api.get_cycling_ftp), ("lactate_threshold", api.get_lactate_threshold)):
        try:
            db.set_setting(conn, key, throttled(fn))
        except Exception as exc:
            log.warning("Impostazione %s non disponibile: %s", key, exc)
    conn.commit()


def build_context(conn: sqlite3.Connection) -> AthleteContext:
    ctx = AthleteContext(css_sec_100m=CSS_SEC_PER_100M)
    for z in db.get_setting(conn, "hr_zones") or []:
        floors = [z.get(f"zone{i}Floor") for i in range(1, 6)]
        if all(f is not None for f in floors):
            ctx.hr_zones[z.get("sport", "DEFAULT")] = [float(f) for f in floors]
        if z.get("sport") == "DEFAULT":
            ctx.max_hr = z.get("maxHeartRateUsed")
    for z in db.get_setting(conn, "power_zones") or []:
        if z.get("sport") == "CYCLING":
            ctx.power_zones["CYCLING"] = [float(z.get(f"zone{i}Floor") or 0) for i in range(1, 8)]
    ftp = db.get_setting(conn, "cycling_ftp") or {}
    if isinstance(ftp, list):
        ftp = ftp[0] if ftp else {}
    ctx.ftp_bike = ftp.get("functionalThresholdPower")
    lt = db.get_setting(conn, "lactate_threshold") or {}
    ctx.lthr_run = (lt.get("speed_and_heart_rate") or {}).get("heartRate")
    ctx.lthr_bike = (lt.get("speed_and_heart_rate") or {}).get("heartRateCycling")
    ctx.ftp_run = (lt.get("power") or {}).get("functionalThresholdPower")
    row = conn.execute("SELECT AVG(rhr) AS r FROM (SELECT rhr FROM wellness_daily WHERE rhr IS NOT NULL "
                       "ORDER BY date DESC LIMIT 14)").fetchone()
    ctx.rhr = row["r"] if row and row["r"] else None
    return ctx


def _session_context(ctx: AthleteContext, sess: FitSession, sport: str) -> AthleteContext:
    """Le soglie salvate nel FIT sono quelle valide il giorno dell'attivita': hanno la precedenza."""
    z = sess.zones_target or {}
    upd: dict[str, Any] = {}
    if z.get("max_heart_rate"):
        upd["max_hr"] = z["max_heart_rate"]
    if sport == "run":
        if z.get("threshold_heart_rate"):
            upd["lthr_run"] = z["threshold_heart_rate"]
        if z.get("functional_threshold_power"):
            upd["ftp_run"] = z["functional_threshold_power"]
    elif sport == "bike":
        if z.get("threshold_heart_rate"):
            upd["lthr_bike"] = z["threshold_heart_rate"]
        ftp = sess.summary.get("threshold_power") or z.get("functional_threshold_power")
        if ftp:
            upd["ftp_bike"] = ftp
    return replace(ctx, **upd)


def load_history(conn: sqlite3.Connection, sport: str, before_gmt: str) -> list[dict]:
    """Metriche delle sessioni precedenti dello stesso sport (escluse le duplicate)."""
    since = (pd.Timestamp(before_gmt) - timedelta(days=HISTORY_DAYS.get(sport, 120))).strftime("%Y-%m-%dT%H:%M:%S")
    rows = conn.execute(
        "SELECT metrics_json FROM activities WHERE sport=? AND is_parent=0 AND duplicate_of IS NULL "
        "AND metrics_json IS NOT NULL AND start_gmt < ? AND start_gmt >= ?",
        (sport, before_gmt, since)).fetchall()
    return [json.loads(r["metrics_json"]).get("metrics", {}) for r in rows]


# --------------------------------------------------------------------------- #
# Analisi
# --------------------------------------------------------------------------- #
def _result_dict(summary: dict, res: SessionResult) -> dict:
    return {
        "activity_id": summary["activity_id"], "name": summary.get("name"), "sport": res.sport,
        "start_local": summary.get("start_local"), "score": res.score, "confidence": res.confidence,
        "tss": res.tss, "tss_method": res.tss_method, "duration_s": res.duration_s,
        "components": [asdict(c) for c in res.components],
        "metrics": res.metrics,
        **res.extra,
    }


def _save(conn: sqlite3.Connection, summary: dict, result: dict) -> None:
    row = dict(summary)
    row.update({
        "score": result.get("score"), "tss": result.get("tss"), "tss_method": result.get("tss_method"),
        "metrics_json": json.dumps(result, default=str), "analyzer_version": ANALYZER_VERSION,
        "analyzed_at": db.now_iso(),
    })
    db.upsert(conn, "activities", "activity_id", row)


def _analyze_session(conn, ctx, sess: FitSession, sport: str, start_gmt: str) -> SessionResult:
    sctx = _session_context(ctx, sess, sport)
    return ANALYZERS[sport](sess, sctx, load_history(conn, sport, start_gmt))


def _analyze_other(summary: dict, ctx: AthleteContext) -> dict:
    """Sport non valutati (forza, camminata, ...): solo carico da FC per il calcolo acuto/cronico."""
    tss = hr_tss(summary.get("duration_s") or 0, summary.get("avg_hr"), ctx, ctx.lthr_run)
    return {"activity_id": summary["activity_id"], "name": summary.get("name"), "sport": "other",
            "start_local": summary.get("start_local"), "score": None, "tss": rnd(tss),
            "tss_method": "hrTSS", "duration_s": summary.get("duration_s"),
            "components": [], "metrics": {"type_key": summary.get("type_key")}}


def _analyze_multisport(api, conn, ctx, summary: dict, detail: dict, fit) -> dict:
    meta = detail.get("metadataDTO") or {}
    child_ids = meta.get("childIds") or []
    child_types = meta.get("childActivityTypes") or []
    sessions = fit.sessions
    aligned = len(child_ids) == len(sessions)
    t0 = sessions[0].start if sessions else None
    legs, transitions = [], []
    for i, sess in enumerate(sessions):
        sport = FIT_SPORT.get(sess.sport)
        if sport is None:
            transitions.append(round((sess.end - sess.start).total_seconds()))
            continue
        start_gmt = _iso(sess.start)
        start_local = None
        if summary.get("start_local") and t0:
            start_local = _iso(pd.Timestamp(summary["start_local"]) + (sess.start - t0))
        if sport == "run":
            sv = strava.match(conn, start_local, sess.summary.get("total_distance"))
            if sv and sv["elevation_gain_m"] is not None:
                sess.summary["strava_ascent_m"] = sv["elevation_gain_m"]
        res = _analyze_session(conn, ctx, sess, sport, start_gmt)
        child_id = child_ids[i] if aligned else None
        child = {
            "activity_id": child_id, "parent_id": summary["activity_id"], "is_parent": 0,
            "start_local": start_local, "start_gmt": start_gmt,
            "type_key": child_types[i] if aligned and i < len(child_types) else sess.sport,
            "sport": sport, "name": f"{summary.get('name')} - {SPORT_LABEL[sport]}",
            "duration_s": res.duration_s, "distance_m": sess.summary.get("total_distance"),
            "avg_hr": sess.summary.get("avg_heart_rate"), "avg_power": sess.summary.get("avg_power"),
            "norm_power": sess.summary.get("normalized_power"), "device_id": summary.get("device_id"),
        }
        result = _result_dict(child, res)
        if child_id:
            _save(conn, child, result)
        legs.append(result)

    scored = [l for l in legs if l["score"] is not None]
    weights = [l["duration_s"] or 0 for l in scored]
    score = int(round(np.average([l["score"] for l in scored], weights=weights))) if scored and sum(weights) else None
    tss = sum(l["tss"] or 0 for l in legs)
    return {
        "activity_id": summary["activity_id"], "name": summary.get("name"), "sport": "multi",
        "start_local": summary.get("start_local"), "score": score, "tss": rnd(tss),
        "tss_method": "somma frazioni", "duration_s": summary.get("duration_s"),
        "components": [], "metrics": {"transitions_s": transitions}, "legs": legs,
    }


def _pick_session(fit, sport: str, start_gmt: Optional[str]) -> Optional[FitSession]:
    cands = [s for s in fit.sessions if FIT_SPORT.get(s.sport) == sport] or fit.sessions
    if not cands:
        return None
    if start_gmt:
        t = pd.Timestamp(start_gmt)
        return min(cands, key=lambda s: abs((pd.Timestamp(s.start) - t).total_seconds()))
    return cands[0]


def analyze_summary(api, conn: sqlite3.Connection, summary: dict, detail: Optional[dict] = None,
                    force_download: bool = False, save: bool = True) -> dict:
    ctx = build_context(conn)
    sport = summary["sport"]
    if sport == "other":
        result = _analyze_other(summary, ctx)
    else:
        fit = load_activity_fit(api, summary["activity_id"], force_download=force_download)
        if sport == "multi":
            if detail is None or "metadataDTO" not in detail:
                detail = throttled(api.get_activity, summary["activity_id"])
            result = _analyze_multisport(api, conn, ctx, summary, detail, fit)
        else:
            sess = _pick_session(fit, sport, summary.get("start_gmt"))
            if sess is None:
                raise ValueError(f"Il FIT dell'attivita' {summary['activity_id']} non contiene sessioni")
            fit_sport = FIT_SPORT.get(sess.sport, sport)
            if fit_sport == "run":
                sv = strava.match(conn, summary.get("start_local"), summary.get("distance_m"))
                if sv and sv["elevation_gain_m"] is not None:
                    sess.summary["strava_ascent_m"] = sv["elevation_gain_m"]
            res = _analyze_session(conn, ctx, sess, fit_sport, summary.get("start_gmt") or _iso(sess.start))
            result = _result_dict(summary, res)
    if save:
        _save(conn, summary, result)
        conn.commit()
    return result


def analyze_activity(activity_id: int, api=None, conn: Optional[sqlite3.Connection] = None,
                     force_download: bool = False, save: bool = True) -> dict:
    """Analizza una singola attivita' e restituisce punteggio 1-100, componenti e metriche."""
    conn = conn or db.connect()
    api = api or get_client()
    refresh_settings(api, conn)
    detail = throttled(api.get_activity, activity_id)
    summary = summary_from_detail(detail)
    result = analyze_summary(api, conn, summary, detail, force_download=force_download, save=save)
    if save:
        mark_duplicates(conn)
    return result


# --------------------------------------------------------------------------- #
# Sincronizzazione attivita' e duplicati
# --------------------------------------------------------------------------- #
def sync_activities(api, days: int = 30, conn: Optional[sqlite3.Connection] = None,
                    reanalyze: bool = False) -> tuple[int, int]:
    """Scarica l'elenco attivita' degli ultimi `days` giorni e analizza quelle nuove (dalla piu' vecchia)."""
    conn = conn or db.connect()
    refresh_settings(api, conn)
    start = max((date.today() - timedelta(days=days - 1)).isoformat(), DATA_START)
    items = throttled(api.get_activities_by_date, start, date.today().isoformat()) or []
    for x in items:
        db.upsert(conn, "activities", "activity_id", summary_from_list(x))
    conn.commit()

    ids = {x["activityId"] for x in items}
    rows = conn.execute(
        "SELECT * FROM activities WHERE parent_id IS NULL AND start_gmt >= ? ORDER BY start_gmt", (start,)
    ).fetchall()
    todo = [dict(r) for r in rows if r["activity_id"] in ids
            and (reanalyze or (r["analyzer_version"] or 0) < ANALYZER_VERSION)]
    done = 0
    for r in todo:
        summary = {k: r[k] for k in ("activity_id", "start_local", "start_gmt", "type_key", "sport", "name",
                                     "duration_s", "distance_m", "avg_hr", "avg_power", "norm_power",
                                     "garmin_load", "device_id", "is_parent")}
        try:
            res = analyze_summary(api, conn, summary, json.loads(r["raw_json"] or "{}"))
            done += 1
            log.info("%s  %-28s voto=%s TSS=%s", r["start_local"], (r["name"] or "")[:28], res["score"], res["tss"])
        except Exception as exc:
            if exc.__class__.__name__ == "AuthError":
                raise
            log.error("Analisi fallita per %s (%s): %s", r["activity_id"], r["name"], exc)
    mark_duplicates(conn)
    return len(items), done


def mark_duplicates(conn: sqlite3.Connection) -> int:
    """
    Stessa sessione registrata da due device (es. Edge 840 + frazione bici del multisport
    sul Forerunner): si tiene la registrazione con potenza, poi quella autonoma, poi la piu' lunga.
    """
    df = db.read_df(conn, "SELECT activity_id, parent_id, sport, start_gmt, duration_s, avg_power, tss "
                          "FROM activities WHERE is_parent=0 AND start_gmt IS NOT NULL AND sport != 'other'")
    conn.execute("UPDATE activities SET duplicate_of=NULL")
    if df.empty:
        conn.commit()
        return 0
    df["start"] = pd.to_datetime(df["start_gmt"])
    df["end"] = df["start"] + pd.to_timedelta(df["duration_s"].fillna(0), unit="s")
    df["prio"] = list(zip(df["avg_power"].fillna(0) > 0, df["parent_id"].isna(), df["duration_s"].fillna(0)))
    marked = 0
    for _, g in df.sort_values("start").groupby("sport"):
        recs = g.to_dict("records")
        for i, a in enumerate(recs):
            for b in recs[i + 1:]:
                if b["start"] >= a["end"]:
                    break
                overlap = (min(a["end"], b["end"]) - max(a["start"], b["start"])).total_seconds()
                shorter = min(a["duration_s"] or 0, b["duration_s"] or 0)
                if shorter > 0 and overlap / shorter > 0.5:
                    keep, drop = (a, b) if a["prio"] >= b["prio"] else (b, a)
                    conn.execute("UPDATE activities SET duplicate_of=? WHERE activity_id=?",
                                 (int(keep["activity_id"]), int(drop["activity_id"])))
                    marked += 1
    conn.commit()
    return marked
