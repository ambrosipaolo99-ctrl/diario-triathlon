"""Analisi ciclismo: potenza media/normalizzata, curva di potenza, bilanciamento Dx/Sx, TSS."""
from __future__ import annotations

from typing import Any, Optional

import numpy as np
import pandas as pd

from ..fitdata import FitSession
from .common import (
    AthleteContext, Component, SessionResult, adherence_component, decoupling, halves, hr_tss,
    is_interval_session, lin, mean_max, normalized_power, percentile_score, power_tss, rnd,
    time_in_zones, to_1hz, warmup_seconds,
)

CURVE_DURATIONS = [1, 5, 10, 30, 60, 120, 300, 600, 1200, 1800, 3600, 5400, 7200]
# zone Coggan in % FTP (floor Z1..Z7), usate se Garmin non fornisce le zone di potenza
COGGAN_FLOORS = [0, 0.55, 0.75, 0.90, 1.05, 1.20, 1.50]

WEIGHTS = {"adherence": 25, "decoupling": 20, "variability": 20, "balance": 15, "efficiency": 20}


def decode_lr_record(v: Any) -> Optional[float]:
    """left_right_balance dei record (uint8): bit 7 = valore riferito al pedale destro, bit 0-6 = %."""
    if v is None or pd.isna(v):
        return None
    v = int(v)
    if v == 0xFF:
        return None
    pct = v & 0x7F
    return float(100 - pct if v & 0x80 else pct)       # restituisce sempre la % SINISTRA


def decode_lr_session(v: Any) -> Optional[float]:
    """left_right_balance di sessione (uint16): bit 15 = destro, bit 0-13 = % * 100."""
    if v is None or pd.isna(v):
        return None
    v = int(v)
    if v == 0xFFFF:
        return None
    pct = (v & 0x3FFF) / 100
    return 100 - pct if v & 0x8000 else pct


def _balance(m: pd.DataFrame, ftp: Optional[float], skip: int) -> tuple[dict[str, Any], Optional[float]]:
    if "left_right_balance" not in m:
        return {}, None
    left = m["left_right_balance"].map(decode_lr_record)
    pw = m["power"].fillna(0)
    ok = left.notna() & (pw > 0)
    if ok.mean() < 0.3:
        return {}, None
    # media pesata per potenza: i tratti a bassa spinta contano meno
    w_left = float(np.average(left[ok], weights=pw[ok]))
    out: dict[str, Any] = {"left_pct": rnd(w_left), "right_pct": rnd(100 - w_left)}
    if ftp:
        lo, hi = ok & (pw < 0.75 * ftp), ok & (pw >= 0.75 * ftp)
        if lo.sum() > 120:
            out["left_pct_below_75ftp"] = rnd(np.average(left[lo], weights=pw[lo]))
        if hi.sum() > 120:
            out["left_pct_above_75ftp"] = rnd(np.average(left[hi], weights=pw[hi]))
    frame = pd.DataFrame({"l": left, "p": pw})[ok]
    a, b = halves(frame, skip)
    if len(a) > 300 and len(b) > 300:
        out["left_drift_pct"] = rnd(np.average(b["l"], weights=b["p"]) - np.average(a["l"], weights=a["p"]))
    return out, w_left


def analyze_bike(sess: FitSession, ctx: AthleteContext, history: list[dict]) -> SessionResult:
    s = sess.summary
    indoor = sess.sub_sport in ("indoor_cycling", "virtual_activity", "spin")
    df = to_1hz(sess, ["power", "heart_rate", "cadence", "speed", "left_right_balance",
                       "left_torque_effectiveness", "right_torque_effectiveness",
                       "left_pedal_smoothness", "right_pedal_smoothness"])
    if df.empty:
        return SessionResult("bike", {"error": "nessun record"}, [], None, "-", 0)

    ftp = float(s.get("threshold_power") or 0) or ctx.ftp_bike
    has_power = bool("power" in df and df["power"].fillna(0).gt(0).mean() > 0.5)
    hr = df["heart_rate"] if "heart_rate" in df else pd.Series(dtype=float)
    has_hr = bool(len(hr) > 0 and hr.notna().mean() > 0.8)
    dur = len(df)
    skip = warmup_seconds(dur)
    # su strada i lap automatici variano molto per salite/discese: soglia piu' alta che nella corsa
    intervals = is_interval_session(sess, "avg_power" if has_power else "avg_speed", max_lap_cv=0.30)

    metrics: dict[str, Any] = {
        "indoor": indoor, "steady": not intervals, "moving_time_s": dur, "has_power": has_power,
        "distance_km": rnd(float(s.get("total_distance") or 0) / 1000, 2),
        "avg_hr": rnd(hr.mean(), 0) if has_hr else None, "ftp_used": rnd(ftp, 0),
        "elevation_gain_m": s.get("total_ascent"),
    }
    comps: list[Component] = []

    if not has_power:
        # niente potenza (es. bici indoor senza sensore): valutazione solo cardio
        comps.append(adherence_component(sess, df, ctx, "bike", "heart_rate", ctx.hr_floors("CYCLING"),
                                         skip, WEIGHTS["adherence"]))
        tss = hr_tss(dur, hr.mean() if has_hr else None, ctx, ctx.lthr_bike)
        metrics["note"] = "nessun dato di potenza: punteggio basato solo sulla FC"
        return SessionResult("bike", metrics, comps, rnd(tss), "hrTSS", dur)

    p = df["power"].fillna(0)
    np_w = normalized_power(p)
    ap = float(p.mean())
    vi = np_w / ap if np_w and ap else None
    intensity = np_w / ftp if np_w and ftp else None
    curve = mean_max(p, CURVE_DURATIONS)
    metrics.update({
        "avg_power": rnd(ap, 0), "normalized_power": rnd(np_w, 0), "max_power": rnd(p.max(), 0),
        "intensity_factor": rnd(intensity, 3), "variability_index": rnd(vi, 3),
        "work_kj": rnd(p.sum() / 1000, 0),
        "power_curve": {str(k): rnd(v, 0) for k, v in curve.items()},
        "garmin_tss": s.get("training_stress_score"),
        "avg_cadence": rnd(df["cadence"][df["cadence"] > 0].mean(), 0) if "cadence" in df else None,
    })
    if ftp:
        tiz = time_in_zones(p, [f * ftp for f in COGGAN_FLOORS])
        metrics["time_in_power_zones_pct"] = [rnd(z * 100) for z in tiz]
    for side in ("left", "right"):
        for k in ("torque_effectiveness", "pedal_smoothness"):
            v = s.get(f"avg_{side}_{k}")
            if v is not None:
                metrics[f"{side}_{k}_pct"] = v

    # aderenza: potenza con zone Garmin del ciclismo, altrimenti Coggan
    floors = ctx.power_zones.get("CYCLING") or ([f * ftp for f in COGGAN_FLOORS] if ftp else None)
    comps.append(adherence_component(sess, df.assign(power=p.rolling(10, min_periods=1).mean()), ctx, "bike",
                                     "power", floors, skip, WEIGHTS["adherence"]))

    # deriva Pw:HR
    if intervals:
        comps.append(Component("Decoupling Pw:HR", None, WEIGHTS["decoupling"], note="non applicabile a intervalli"))
    elif has_hr and dur >= 1800:
        dec = decoupling(p.rolling(30, min_periods=1).mean(), hr, skip)
        metrics["decoupling_pct"] = rnd(dec)
        comps.append(Component("Decoupling Pw:HR", lin(dec, [2, 5, 8, 12, 15], [100, 85, 60, 30, 10]),
                               WEIGHTS["decoupling"], rnd(dec), "variazione % potenza/FC tra le due meta'"))
    else:
        comps.append(Component("Decoupling Pw:HR", None, WEIGHTS["decoupling"], note="serve >= 30 min con FC"))

    # regolarita' della spinta (VI): conta solo nelle uscite continue
    comps.append(Component(
        "Regolarita' potenza (VI)",
        lin(vi, [1.02, 1.05, 1.10, 1.20, 1.30], [100, 90, 65, 30, 10]) if not intervals else None,
        WEIGHTS["variability"], rnd(vi, 3), "NP / potenza media" if not intervals else "non applicabile a intervalli"))

    bal, left = _balance(df.assign(power=p), ftp, skip)
    if left is None:
        left = decode_lr_session(s.get("left_right_balance"))
        if left is not None:
            bal = {"left_pct": rnd(left), "right_pct": rnd(100 - left)}
    metrics["lr_balance"] = bal
    comps.append(Component("Bilanciamento Dx/Sx",
                           lin(abs(left - 50), [1, 2, 4, 6], [100, 90, 50, 10]) if left is not None else None,
                           WEIGHTS["balance"], bal.get("left_pct"), "% sinistra pesata per potenza"))

    ef = np_w / hr.mean() if has_hr and np_w else None
    metrics["ef_power"] = rnd(ef, 3)
    hist = [h.get("ef_power") for h in history
            if h.get("has_power") and h.get("intensity_factor") and intensity
            and abs(h["intensity_factor"] - intensity) <= 0.10 and (h.get("moving_time_s") or 0) >= 1800]
    eff = percentile_score(ef, hist)
    comps.append(Component("Efficienza vs storico", eff, WEIGHTS["efficiency"], metrics["ef_power"],
                           f"percentile NP/FC su {len(hist)} uscite a IF simile" if eff is not None
                           else "storico insufficiente"))

    # record della curva di potenza rispetto alle uscite memorizzate
    best = {}
    for h in history:
        for k, v in (h.get("power_curve") or {}).items():
            if v:
                best[k] = max(best.get(k, 0), v)
    metrics["power_curve_records"] = [k for k, v in metrics["power_curve"].items()
                                      if v and best and v > best.get(k, 0) and int(k) >= 5]

    tss = power_tss(dur, np_w, ftp)
    return SessionResult("bike", metrics, comps, rnd(tss), "TSS potenza", dur)
