"""Esporta il database in file JSON (righe piatte) per la dashboard su claude.ai."""
from __future__ import annotations

import json
import re
import sqlite3
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from . import db
from .config import DATA_DIR, DATA_START
from .load import pmc
from .recovery_weekly import daily_features, weekly_recovery
from .today import today_rows

EXPORT_DIR = DATA_DIR / "export"
SPORT_IT = {"run": "Corsa", "bike": "Bici", "swim": "Nuoto", "other": "Altro", "multi": "Multisport"}
LIMITER_IT = {"hrv": "HRV", "sleep": "sonno", "rhr": "FC a riposo", "body_battery": "Body Battery", "stress": "stress"}


def _clean(v):
    if v is None:
        return None
    if isinstance(v, (float, np.floating)):
        return None if not np.isfinite(v) else round(float(v), 3)
    if isinstance(v, np.integer):
        return int(v)
    if isinstance(v, np.bool_):
        return bool(v)
    return v


def _write(name: str, rows: list[dict], out_dir: Path) -> Path:
    path = out_dir / f"{name}.json"
    path.write_text(json.dumps([{k: _clean(v) for k, v in r.items()} for r in rows], ensure_ascii=False),
                    encoding="utf-8")
    return path


def _wellness(conn: sqlite3.Connection, since: str) -> list[dict]:
    feats = daily_features(conn)
    rows = []
    for r in conn.execute("SELECT * FROM wellness_daily WHERE date >= ? ORDER BY date", (since,)):
        d = json.loads(r["recovery_json"] or "{}")
        c = d.get("components", {})
        f = feats.loc[pd.Timestamp(r["date"])] if pd.Timestamp(r["date"]) in feats.index else {}
        g = lambda k: f.get(k) if hasattr(f, "get") else None  # noqa: E731
        rows.append({
            "hrv_7d_ms": g("hrv_7d_ms"), "hrv_norm_lo": g("hrv_norm_lo"), "hrv_norm_hi": g("hrv_norm_hi"),
            "hrv_cv7": g("hrv_cv7"), "rhr_base": g("rhr_base"), "resp": r["resp_sleep"], "resp_base": g("resp_base"),
            "spo2": r["spo2_sleep"], "bb_charge": g("bb_charge"), "sleep_need_h": g("sleep_need_h"),
            "deep_pct": g("deep_pct"), "rem_pct": g("rem_pct"), "bedtime_min": g("bedtime_min"),
            "sleep_stress": r["avg_sleep_stress"], "acwr": g("acwr"), "tsb": g("tsb"),
            "sleep_score_7d": g("sleep_score_7d"), "recovery_7d": g("recovery_7d"), "rhr_7d": g("rhr_7d"),
            "date": r["date"], "recovery": r["recovery_index"], "recovery_label": d.get("label"),
            "limiter": d.get("limiter"), "limiter_label": LIMITER_IT.get(d.get("limiter")),
            "red_flag": d.get("red_flag"),
            "c_hrv": c.get("hrv"), "c_sleep": c.get("sleep"), "c_rhr": c.get("rhr"),
            "c_body_battery": c.get("body_battery"), "c_stress": c.get("stress"),
            "hrv": r["hrv_last_night"], "hrv_7d": r["hrv_weekly_avg"],
            "hrv_low": r["hrv_baseline_low"], "hrv_high": r["hrv_baseline_high"], "hrv_status": r["hrv_status"],
            "rhr": r["rhr"], "sleep_score": r["sleep_score"],
            "sleep_h": r["sleep_seconds"] / 3600 if r["sleep_seconds"] else None,
            "deep_h": r["deep_seconds"] / 3600 if r["deep_seconds"] else None,
            "rem_h": r["rem_seconds"] / 3600 if r["rem_seconds"] else None,
            "body_battery": r["bb_at_wake"] or r["bb_high"], "stress": r["stress_avg"],
            "readiness": r["training_readiness"],
        })
    return rows


def _load(conn: sqlite3.Connection, since: str) -> list[dict]:
    p = pmc(conn)
    p = p[p.index >= pd.Timestamp(since)]
    return [{"date": i.strftime("%Y-%m-%d"), "tss": r.tss, "ctl": r.ctl, "atl": r.atl, "tsb": r.tsb,
             "acwr": r.acwr} for i, r in p.iterrows()]


def _activities(conn: sqlite3.Connection, since: str) -> tuple[list[dict], list[dict]]:
    acts, comps = [], []
    q = ("SELECT * FROM activities WHERE start_local >= ? AND metrics_json IS NOT NULL "
         "AND is_parent = 0 ORDER BY start_local DESC")
    for r in conn.execute(q, (since,)):
        res = json.loads(r["metrics_json"])
        m = res.get("metrics", {})
        dyn = m.get("dynamics") or {}
        lr = m.get("lr_balance") or {}
        acts.append({
            "id": str(r["activity_id"]), "date": r["start_local"][:10], "start": r["start_local"],
            "sport": r["sport"], "sport_label": SPORT_IT.get(r["sport"], r["sport"]),
            "type": r["type_key"], "name": r["name"],
            "multisport": bool(r["parent_id"]), "duplicate": bool(r["duplicate_of"]),
            "duration_min": (r["duration_s"] or 0) / 60,
            "distance_km": (r["distance_m"] or 0) / 1000,
            "score": r["score"], "confidence": res.get("confidence"),
            "tss": r["tss"], "tss_method": r["tss_method"], "avg_hr": m.get("avg_hr"),
            "steady": m.get("steady"), "indoor": m.get("indoor") or m.get("treadmill"),
            "pace": m.get("avg_pace"), "ef_speed": m.get("ef_speed"), "ef_power": m.get("ef_power"),
            "decoupling_pct": m.get("decoupling_pct"), "pace_cv_pct": m.get("pace_cv_pct"),
            "cadence_spm": dyn.get("cadence_spm"), "gct_ms": dyn.get("gct_ms"),
            "gct_balance_left": dyn.get("gct_balance_left_pct"), "vertical_ratio": dyn.get("vertical_ratio_pct"),
            "avg_power": m.get("avg_power"), "np": m.get("normalized_power"),
            "if": m.get("intensity_factor"), "vi": m.get("variability_index"), "ftp": m.get("ftp_used"),
            "lr_left": lr.get("left_pct"),
            "best_5min": (m.get("power_curve") or {}).get("300"),
            "best_20min": (m.get("power_curve") or {}).get("1200"),
            "best_60min": (m.get("power_curve") or {}).get("3600"),
            "swolf": m.get("avg_swolf"), "swolf_cv_pct": m.get("swolf_cv_pct"),
            "stroke_rate": m.get("avg_stroke_rate_spm"), "pace_100m_s": m.get("avg_pace_100m_s"),
            "open_water": m.get("open_water"),
            "ascent_m": m.get("ascent_m"), "ascent_source": m.get("ascent_source"),
        })
        for i, c in enumerate(res.get("components", [])):
            comps.append({"key": f"{r['activity_id']}-{i}", "activity_id": str(r["activity_id"]),
                          "component": c["name"], "score": c["score"], "weight": c["weight"],
                          "value": None if c["value"] is None else str(c["value"]), "note": c["note"]})
    return acts, comps


def _runs(conn: sqlite3.Connection, since: str) -> dict[str, list[dict]]:
    """Dati di dettaglio della corsa: riepilogo, serie 30 s, split, passo per FC, dinamiche per passo."""
    out: dict[str, list[dict]] = {"runs": [], "run_stream": [], "run_splits": [], "run_hr_pace": [], "run_pace_dyn": []}
    q = ("SELECT activity_id, start_local, name, score, raw_json, metrics_json FROM activities "
         "WHERE sport='run' AND is_parent=0 AND duplicate_of IS NULL AND metrics_json IS NOT NULL "
         "AND start_local >= ? ORDER BY start_local")
    for r in conn.execute(q, (since,)):
        res = json.loads(r["metrics_json"])
        m, dyn = res.get("metrics", {}), res.get("metrics", {}).get("dynamics") or {}
        raw = json.loads(r["raw_json"] or "{}")
        aid, day = str(r["activity_id"]), r["start_local"][:10]
        sec = {c["name"]: c["score"] for c in res.get("components", [])}
        zones = m.get("hr_zone_pct") or [None] * 5
        fat = dyn.get("fatigue_change_pct") or {}
        out["runs"].append({
            "id": aid, "date": day, "start": r["start_local"], "name": r["name"], "score": r["score"],
            "env": "in" if m.get("treadmill") else "out", "steady": m.get("steady"), "hilly": m.get("hilly"),
            "altitude_reliable": m.get("altitude_reliable"),
            "ascent_m": m.get("ascent_m"), "ascent_source": m.get("ascent_source"),
            "distance_km": m.get("distance_km"), "moving_min": (m.get("moving_time_s") or 0) / 60,
            "pace": m.get("avg_pace"), "pace_s": 1000 / m["avg_speed_ms"] if m.get("avg_speed_ms") else None,
            "avg_hr": m.get("avg_hr"), "max_hr": m.get("max_hr"), "ef": m.get("ef_speed"),
            "decoupling_pct": m.get("decoupling_pct"), "hr_drift_bpm": m.get("hr_drift_bpm"),
            "pace_cv_pct": m.get("pace_cv_pct"), "split_slowdown_pct": m.get("split_slowdown_pct"),
            "cadence": dyn.get("cadence_spm"), "cadence_ref": dyn.get("cadence_ref_spm"),
            "gct": dyn.get("gct_ms"), "gct_expected": dyn.get("gct_expected_ms"),
            "gct_balance_left": dyn.get("gct_balance_left_pct"), "vo_cm": dyn.get("vertical_oscillation_cm"),
            "vr": dyn.get("vertical_ratio_pct"), "step_m": dyn.get("step_length_m"),
            "fatigue_cad_pct": fat.get("cadence"), "fatigue_gct_pct": fat.get("gct"),
            "fatigue_step_pct": fat.get("step_length"), "fatigue_vo_pct": fat.get("vertical_oscillation"),
            "fatigue_eff_pct": fat.get("speed_per_beat"),
            "vo2max": raw.get("vO2MaxValue"),
            "z1": zones[0], "z2": zones[1], "z3": zones[2], "z4": zones[3], "z5": zones[4],
            "s_intensity": sec.get("Controllo intensita'"), "s_efficiency": sec.get("Efficienza aerobica"),
            "s_pacing": sec.get("Gestione del ritmo"), "s_cadence": sec.get("Cadenza"),
            "s_contact": sec.get("Contatto al suolo"), "s_vertical": sec.get("Rimbalzo verticale"),
            "s_fatigue": sec.get("Resistenza alla fatica"),
        })
        for i, p in enumerate(res.get("stream", [])):
            out["run_stream"].append({"key": f"{aid}-{i}", "activity_id": aid, **p})
        for p in res.get("splits", []):
            out["run_splits"].append({"key": f"{aid}-{p['km']}", "activity_id": aid, **p})
        for p in res.get("hr_bins", []):
            out["run_hr_pace"].append({"key": f"{aid}-{p['hr_bin']}", "activity_id": aid, "date": day,
                                       "env": "in" if m.get("treadmill") else "out", **p})
        for p in res.get("pace_bins", []):
            out["run_pace_dyn"].append({"key": f"{aid}-{p['pace_bin']}", "activity_id": aid, "date": day,
                                        "env": "in" if m.get("treadmill") else "out", **p})
    return out


_ACUTE = ("perche", "finche", "poiche", "affinche", "benche")


def _it(v):
    """Accenti finali scritti con l'apostrofo nel codice (piu', meta', e') -> lettere accentate."""
    if not isinstance(v, str):
        return v

    def fix(m: re.Match) -> str:
        word, vowel = m.group(1), m.group(2)
        acc = "é" if vowel == "e" and word.lower() in _ACUTE else {"a": "à", "e": "è", "i": "ì", "o": "ò", "u": "ù"}[vowel]
        return word[:-1] + acc
    return re.sub(r"\b(\w*([aeiou]))'(?=[\s.,;:)\]]|$)", fix, v)


def _goal(conn: sqlite3.Connection, impact: dict | None = None) -> dict[str, list[dict]]:
    out = _goal_rows(conn, impact)
    return {k: [{c: _it(x) for c, x in r.items()} for r in rows] for k, rows in out.items()}


def _perf_base(conn: sqlite3.Connection) -> dict:
    """Corse con serie, atleta e carico a due vettori: servono prima del piano (protezione strutturale)."""
    from .perf import common, load_vectors
    from .race import athlete
    ath = athlete(conn)
    runs = common.load_runs(conn, DATA_START)
    run_load = load_vectors.run_rows(runs, ath)
    today = date.today()
    start = date.fromisoformat(run_load[0]["date"]) if run_load else today
    daily = load_vectors.daily_rows(run_load, start, today)
    return {"ath": ath, "runs": runs, "weight": common.athlete_weight(conn), "run_load": run_load, "daily": daily,
            "impact": load_vectors.impact_until(daily, today)}


def _perf(conn: sqlite3.Connection, since: str, base: dict, goal: dict[str, list[dict]]) -> dict[str, list[dict]]:
    from .perf import biomech, fuel, readiness, taper
    active = next((g for g in goal["goals"] if g.get("status") == "attivo" and g.get("discipline") == "corsa"), None)
    runs = base["runs"]
    taper_rows, taper_meta = taper.model(conn, active, goal["goal_plan"],
                                         [(r.day.isoformat(), r.ef) for r in runs
                                          if r.ef and r.steady and not r.treadmill and r.moving_s >= 1200])
    out = {
        "run_load": [r for r in base["run_load"] if r["date"] >= since],
        "load_vectors": [r for r in base["daily"] if r["date"] >= since],
        "readiness": readiness.rows(conn, since, base["daily"]),
        "fuel": [r for r in fuel.rows(runs, base["ath"], base["weight"], goal["goal_plan"]) if r["date"] >= since],
        "biomech": [r for r in biomech.rows(runs) if r["date"] >= since],
        "taper": taper_rows, "taper_meta": taper_meta,
    }
    return {k: [{c: _it(x) for c, x in r.items()} for r in rows] for k, rows in out.items()}


def _goal_rows(conn: sqlite3.Connection, impact: dict | None = None) -> dict[str, list[dict]]:
    """Obiettivi, stima gara giorno per giorno, zone, piano e voti dell'obiettivo attivo."""
    from .coach import coach
    from .goals import active_goal, goal_rows, goal_window_start, load_goals, run_profile
    from .race import athlete, daily_estimates, fmt_pace, fmt_time, load_runs

    rng = lambda lo, hi: f"{fmt_pace(lo)}–{fmt_pace(hi)}" if lo and hi else None  # noqa: E731

    today = date.today()
    goals = load_goals()
    out: dict[str, list[dict]] = {k: [] for k in ("goals", "race_estimate", "race_methods", "race_factors",
                                                  "goal_zones", "goal_plan", "goal_grades", "goal_grade_parts",
                                                  "taper_plan")}
    out["goals"] = [{**g, "result_fmt": fmt_time(g.get("result_s")) if g.get("result_s") else None}
                    for g in goal_rows(conn, goals, today)]
    goal = active_goal(goals, today)
    if not goal or goal.get("discipline") != "corsa" or not goal.get("distance_km"):
        return out          # stima, piano e voti per ora solo per gli obiettivi di corsa
    prof = run_profile(goal["distance_km"])
    race_day = date.fromisoformat(goal["date"])
    start = goal_window_start(goals, goal)
    ath, runs = athlete(conn), load_runs(conn)
    est = daily_estimates(runs, ath, prof, start, min(today, race_day - timedelta(days=1)), start)
    if not est:
        return out
    for e in est:
        row = {"date": e["as_of"], "goal_id": goal["id"], **{k: e[k] for k in (
            "central_s", "low_s", "high_s", "pace_s", "confidence", "confidence_label", "spread_pct", "vdot")}}
        row.update({f"{m['key']}_s": m["time_s"] for m in e["methods"]})
        row.update({"central_fmt": fmt_time(e["central_s"]), "low_fmt": fmt_time(e["low_s"]),
                    "high_fmt": fmt_time(e["high_s"]), "pace_fmt": fmt_pace(e["pace_s"])})
        out["race_estimate"].append(row)
    last = est[-1]
    out["race_methods"] = [{"key": m["key"], "name": m["name"], "evidence": m["evidence"],
                            "time_s": m["time_s"], "pace_s": m["time_s"] / prof.distance_km,
                            "time_fmt": fmt_time(m["time_s"]), "pace_fmt": fmt_pace(m["time_s"] / prof.distance_km),
                            "weight_pct": m["weight"] * 100, "reliability_pct": m["conf"] * 100,
                            "outlier": m["outlier"], "detail": m["detail"], "as_of": last["as_of"]}
                           for m in last["methods"]]
    out["race_factors"] = [{"key": i, "text": f["text"], "impact": f["impact"], "as_of": last["as_of"]}
                           for i, f in enumerate(last["factors"])]
    res = coach(conn, goal, prof, runs, ath, {e["as_of"]: e for e in est}, start, today, impact=impact)
    out["goal_zones"] = [{**z, "pace_fmt": rng(z["pace_lo"], z["pace_hi"]), "hr_fmt": f"{z['hr_lo']}–{z['hr_hi']}"}
                         for z in res["zones"]]
    out["goal_plan"] = [{**p, "goal_id": goal["id"], "pace_fmt": rng(p["pace_lo"], p["pace_hi"]),
                         "hr_fmt": f"{p['hr_lo']}–{p['hr_hi']}" if p["hr_lo"] else None,
                         "done_pace_fmt": fmt_pace(p["done_pace_s"]) if p.get("done_pace_s") else None}
                        for p in res["plan"]]
    out["goal_grades"] = [{**g, "pace_fmt": fmt_pace(g["pace_s"])} for g in res["grades"]]
    out["goal_grade_parts"] = res["grade_parts"]
    out["taper_plan"] = res.get("taper_plan", [])
    return out


def export_dashboard(conn: sqlite3.Connection | None = None, days: int = 365, out_dir: Path = EXPORT_DIR) -> dict:
    conn = conn or db.connect()
    out_dir.mkdir(parents=True, exist_ok=True)
    since = max((date.today() - timedelta(days=days)).isoformat(), DATA_START)
    acts, comps = _activities(conn, since)
    paths = {
        "wellness": _write("wellness", _wellness(conn, since), out_dir),
        "load": _write("load", _load(conn, since), out_dir),
        "activities": _write("activities", acts, out_dir),
        "components": _write("components", comps, out_dir),
    }
    for name, rows in _runs(conn, since).items():
        paths[name] = _write(name, rows, out_dir)
    weeks = [w for w in weekly_recovery(conn) if w["week_end"] >= since]
    paths["recovery_weekly"] = _write("recovery_weekly", weeks, out_dir)
    base = _perf_base(conn)
    goal = _goal(conn, base["impact"])
    for name, rows in goal.items():
        paths[name] = _write(name, rows, out_dir)
    for name, rows in _perf(conn, since, base, goal).items():
        paths[name] = _write(name, rows, out_dir)
    today, today_parts = today_rows(conn, goal["goal_grades"], goal["goal_grade_parts"])
    paths["today"] = _write("today", [{c: _it(x) for c, x in r.items()} for r in today], out_dir)
    paths["today_parts"] = _write("today_parts", [{c: _it(x) for c, x in r.items()} for r in today_parts], out_dir)
    return paths
