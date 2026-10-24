"""Analisi nuoto: SWOLF, passo /100 m, costanza della frequenza di bracciata (piscina e acque libere)."""
from __future__ import annotations

from typing import Any, Optional

import numpy as np
import pandas as pd

from ..fitdata import FitSession
from .common import (
    AthleteContext, Component, SessionResult, cv, hr_tss, lin, percentile_score, rnd, to_1hz,
)

WEIGHTS = {"pace": 25, "swolf": 20, "stroke_rate": 20, "pace_stability": 20, "fatigue": 15}
OW_SEGMENT_M = 100
DEFAULT_IF = 0.75           # intensita' assunta se mancano CSS e FC


def _fmt100(sec: Optional[float]) -> str:
    if not sec:
        return "-"
    return f"{int(sec // 60)}:{int(round(sec % 60)):02d}/100m"


def _pool_table(sess: FitSession) -> tuple[pd.DataFrame, float]:
    pool = float(sess.summary.get("pool_length") or 25)
    rows = []
    for l in sess.lengths:
        if str(l.get("length_type")) != "active":
            continue
        t = float(l.get("total_timer_time") or l.get("total_elapsed_time") or 0)
        strokes = l.get("total_strokes")
        if t <= 0:
            continue
        rows.append({"start": l.get("start_time"), "time": t, "strokes": strokes,
                     "stroke": str(l.get("swim_stroke", "freestyle")),
                     "rate": l.get("avg_swimming_cadence")})
    df = pd.DataFrame(rows)
    if df.empty:
        return df, pool
    df = df[df["stroke"] != "drill"]
    free = df[df["stroke"] == "freestyle"]
    if len(free) >= 0.5 * len(df):          # metriche di costanza sullo stile prevalente
        df = free
    df["swolf"] = df["time"] + df["strokes"].astype(float)
    df["pace100"] = df["time"] / pool * 100
    return df.reset_index(drop=True), pool


def _open_water_table(sess: FitSession) -> pd.DataFrame:
    """Segmenti da 100 m ricavati dai record: tempo, bracciate, SWOLF equivalente su 25 m."""
    r = to_1hz(sess, ["distance", "speed", "cadence"])
    if r.empty or "distance" not in r:
        return pd.DataFrame()
    r = r[r["speed"].fillna(0) > 0.3] if "speed" in r else r
    r = r.assign(seg=(r["distance"] // OW_SEGMENT_M).astype(int))
    rows = []
    for seg, g in r.groupby("seg"):
        if len(g) < 20 or g["distance"].iloc[-1] - g["distance"].iloc[0] < OW_SEGMENT_M * 0.8:
            continue
        meters = g["distance"].iloc[-1] - g["distance"].iloc[0]
        time = len(g) * OW_SEGMENT_M / meters
        # bracciate dalla cadenza (colpi/min): il contatore cumulativo nei record e' irregolare
        strokes = g["cadence"].mean() * time / 60 if "cadence" in g and g["cadence"].notna().any() else None
        rows.append({"time": time, "strokes": strokes, "rate": g["cadence"].mean() if "cadence" in g else None})
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df["pace100"] = df["time"]
    # SWOLF acque libere come Garmin: riferito a 25 m (tempo + bracciate ogni 25 m)
    df["swolf"] = (df["time"] + df["strokes"].astype(float)) / 4
    return df


def analyze_swim(sess: FitSession, ctx: AthleteContext, history: list[dict]) -> SessionResult:
    s = sess.summary
    open_water = sess.sub_sport == "open_water"
    table, pool = (_open_water_table(sess), None) if open_water else _pool_table(sess)
    dist = float(s.get("total_distance") or 0)
    timer = float(s.get("total_timer_time") or 0)
    hr_vals = sess.records["heart_rate"].dropna() if "heart_rate" in sess.records else pd.Series(dtype=float)

    metrics: dict[str, Any] = {"open_water": open_water, "distance_m": rnd(dist, 0), "pool_length_m": pool,
                               "moving_time_s": timer, "avg_hr": rnd(hr_vals.mean(), 0) if len(hr_vals) else None}
    if table.empty:
        metrics["error"] = "nessuna vasca/segmento utilizzabile"
        return SessionResult("swim", metrics, [], None, "-", timer)

    swim_time = float(table["time"].sum()) if not open_water else timer
    pace100 = (swim_time / (len(table) * pool) * 100) if not open_water else timer / max(dist, 1) * 100
    metrics.update({
        "avg_pace_100m_s": rnd(pace100), "avg_pace": _fmt100(pace100),
        "avg_swolf": rnd(table["swolf"].mean()),
        "avg_stroke_rate_spm": rnd(table["rate"].astype(float).mean(), 0),
        "distance_per_stroke_m": rnd(s.get("avg_stroke_distance")
                                     or (pool / table["strokes"].astype(float).mean() if pool else None), 2),
        "lengths_or_segments": len(table),
    })

    comps: list[Component] = []
    css = ctx.css_sec_100m
    if css:
        ratio = pace100 / css          # < 1 = piu' veloce della soglia
        metrics["pace_vs_css_pct"] = rnd((ratio - 1) * 100)
        comps.append(Component("Passo vs CSS", lin(ratio, [1.0, 1.05, 1.12, 1.20, 1.30], [100, 90, 70, 45, 20]),
                               WEIGHTS["pace"], metrics["pace_vs_css_pct"], "% piu' lento della CSS"))
    else:
        hist = [-h["avg_pace_100m_s"] for h in history
                if h.get("open_water") == open_water and h.get("avg_pace_100m_s")]
        sc = percentile_score(-pace100, hist)
        comps.append(Component("Passo vs storico", sc, WEIGHTS["pace"], metrics["avg_pace"],
                               f"percentile su {len(hist)} nuotate {'in acque libere' if open_water else 'in piscina'}"
                               if sc is not None else "storico insufficiente (imposta GARMIN_CSS_SEC_100M)"))

    sw_cv = cv(table["swolf"])
    metrics["swolf_cv_pct"] = rnd(sw_cv * 100 if sw_cv is not None else None)
    comps.append(Component("Costanza SWOLF", lin(sw_cv, [0.03, 0.06, 0.10, 0.15], [100, 75, 40, 10]),
                           WEIGHTS["swolf"], metrics["swolf_cv_pct"], "CV % dello SWOLF"))

    sr_cv = cv(table["rate"].astype(float))
    metrics["stroke_rate_cv_pct"] = rnd(sr_cv * 100 if sr_cv is not None else None)
    comps.append(Component("Costanza frequenza bracciata", lin(sr_cv, [0.04, 0.08, 0.12, 0.20], [100, 70, 40, 10]),
                           WEIGHTS["stroke_rate"], metrics["stroke_rate_cv_pct"], "CV % colpi/min"))

    p_cv = cv(table["pace100"])
    metrics["pace_cv_pct"] = rnd(p_cv * 100 if p_cv is not None else None)
    pts = ([0.04, 0.08, 0.12, 0.20], [100, 70, 40, 10]) if open_water else ([0.03, 0.06, 0.10, 0.15], [100, 75, 40, 10])
    comps.append(Component("Stabilita' passo", lin(p_cv, *pts), WEIGHTS["pace_stability"],
                           metrics["pace_cv_pct"], "CV % del passo per " + ("100 m" if open_water else "vasca")))

    if len(table) >= 8:
        mid = len(table) // 2
        fade = (table["swolf"].iloc[mid:].mean() / table["swolf"].iloc[:mid].mean() - 1) * 100
        metrics["swolf_fade_pct"] = rnd(fade)
        comps.append(Component("Tenuta (SWOLF 2a meta')", lin(fade, [0, 3, 6, 10], [100, 85, 55, 20]),
                               WEIGHTS["fatigue"], rnd(fade), "aumento % SWOLF nella seconda meta'"))

    # sTSS: IF = velocita' / velocita' CSS (al cubo, per la resistenza idrodinamica)
    if css:
        intensity, method = css / pace100, "sTSS (CSS)"
        tss = timer / 3600 * intensity ** 3 * 100
    elif len(hr_vals) > 0.8 * timer:
        # in acqua la FC di soglia e' ~10 bpm piu' bassa che nella corsa
        lthr_swim = ctx.lthr_run - 10 if ctx.lthr_run else None
        tss, method = hr_tss(timer, hr_vals.mean(), ctx, lthr_swim), "hrTSS"
    else:
        tss, method = timer / 3600 * DEFAULT_IF ** 2 * 100, "stima per durata"
    return SessionResult("swim", metrics, comps, rnd(tss), method, timer)
