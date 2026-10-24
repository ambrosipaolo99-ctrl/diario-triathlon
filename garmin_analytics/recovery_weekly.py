"""
Voto di recupero settimanale (lunedi-domenica), 0-100.

Otto aree, ciascuna normalizzata sulla baseline personale dei 60 giorni che
precedono la settimana:

  HRV                   25  media ln(rMSSD) della settimana vs baseline (z) + CV giornaliero (Plews)
  FC a riposo           10  media della settimana vs baseline (z, piu' bassa = meglio)
  Quantita' di sonno    15  ore dormite / fabbisogno Garmin
  Qualita' del sonno    15  Sleep Score + quota profondo+REM
  Regolarita' del sonno  5  deviazione standard dell'orario di addormentamento
  Stress ed energia     10  stress medio diurno + Body Battery ricaricata nella notte
  Equilibrio del carico 15  rapporto acuto:cronico (0,8-1,3 ideale) + forma (TSB)
  Segnali respiratori    5  respiri/min nel sonno e SpO2 vs baseline

Bandiera rossa: HRV z < -1 e FC a riposo z > +1 nella stessa settimana -> voto max 45.
"""
from __future__ import annotations

import sqlite3
from typing import Any, Optional

import numpy as np
import pandas as pd

from . import db
from .load import pmc
from .recovery import label_for

BASELINE_DAYS = 60
MIN_BASELINE = 14
MIN_DAYS = 4                 # giorni con dati richiesti per valutare un'area nella settimana

WEIGHTS = {"hrv": 25, "rhr": 10, "sleep_qty": 15, "sleep_qual": 15, "sleep_reg": 5,
           "stress": 10, "load": 15, "resp": 5}
NAMES = {"hrv": "HRV", "rhr": "FC a riposo", "sleep_qty": "Quantità di sonno", "sleep_qual": "Qualità del sonno",
         "sleep_reg": "Regolarità del sonno", "stress": "Stress ed energia", "load": "Equilibrio del carico",
         "resp": "Segnali respiratori"}


def lin(x: Optional[float], xp: list[float], fp: list[float]) -> Optional[float]:
    if x is None or not np.isfinite(x):
        return None
    return float(np.interp(x, xp, fp))


def _mean(vals) -> Optional[float]:
    v = [x for x in vals if x is not None and np.isfinite(x)]
    return float(np.mean(v)) if v else None


def daily_features(conn: sqlite3.Connection) -> pd.DataFrame:
    """Serie giornaliera con baseline mobili (60 gg precedenti) e metriche derivate."""
    df = db.read_df(conn, "SELECT * FROM wellness_daily ORDER BY date")
    if df.empty:
        return df
    df["date"] = pd.to_datetime(df["date"])
    df = df.set_index("date").asfreq("D")
    ln = np.log(df["hrv_last_night"].where(df["hrv_last_night"] > 0))
    roll = ln.shift(1).rolling(BASELINE_DAYS, min_periods=MIN_BASELINE)
    df["ln_hrv"] = ln
    df["ln_base"], df["ln_sd"] = roll.mean(), roll.std().clip(lower=0.03)
    df["ln_7d"] = ln.rolling(7, min_periods=4).mean()
    df["hrv_cv7"] = ln.rolling(7, min_periods=4).std() / df["ln_7d"] * 100
    # "range normale" della media 7 gg: baseline +- 0,5 SD (smallest worthwhile change)
    df["hrv_norm_lo"] = np.exp(df["ln_base"] - 0.5 * df["ln_sd"])
    df["hrv_norm_hi"] = np.exp(df["ln_base"] + 0.5 * df["ln_sd"])
    df["hrv_7d_ms"] = np.exp(df["ln_7d"])
    for col, out in (("rhr", "rhr"), ("resp_sleep", "resp"), ("spo2_sleep", "spo2")):
        r = df[col].astype(float).shift(1).rolling(BASELINE_DAYS, min_periods=MIN_BASELINE)
        df[f"{out}_base"], df[f"{out}_sd"] = r.mean(), r.std()
    df["sleep_need_h"] = df["sleep_need_minutes"] / 60
    df["sleep_h"] = df["sleep_seconds"] / 3600
    df["sleep_ratio"] = df["sleep_seconds"] / 60 / df["sleep_need_minutes"].fillna(480)
    tot = df["sleep_seconds"].where(df["sleep_seconds"] > 0)
    df["deep_pct"] = df["deep_seconds"] / tot * 100
    df["rem_pct"] = df["rem_seconds"] / tot * 100
    st = pd.to_datetime(df["sleep_start"], errors="coerce")
    # minuti dalle 18:00, cosi' un addormentamento dopo mezzanotte resta continuo
    df["bedtime_min"] = ((st.dt.hour * 60 + st.dt.minute - 18 * 60) % 1440).where(st.notna())
    df["bb_charge"] = df["bb_sleep_charge"].combine_first(df["bb_charged"])
    df["sleep_score_7d"] = df["sleep_score"].rolling(7, min_periods=4).mean()
    df["recovery_7d"] = df["recovery_index"].rolling(7, min_periods=4).mean()
    df["rhr_7d"] = df["rhr"].astype(float).rolling(7, min_periods=4).mean()
    load = pmc(conn)
    if not load.empty:
        df = df.join(load[["tss", "ctl", "atl", "tsb", "acwr"]], how="left")
    return df


def _week_scores(w: pd.DataFrame, base: pd.Series) -> dict[str, Any]:
    """Calcola le aree per una settimana. `base` = riga del lunedi' (baseline ai 60 gg precedenti)."""
    comp: dict[str, Optional[float]] = {}
    val: dict[str, Any] = {}
    note: dict[str, str] = {}

    # HRV
    ln = w["ln_hrv"].dropna()
    z_hrv = None
    if len(ln) >= MIN_DAYS:
        mean_ms = float(np.exp(ln.mean()))
        cv_ = float(ln.std() / ln.mean() * 100) if len(ln) >= 3 else None
        val.update({"hrv_ms": mean_ms, "hrv_cv": cv_})
        if pd.notna(base["ln_base"]):
            z_hrv = float((ln.mean() - base["ln_base"]) / base["ln_sd"])
            level = lin(z_hrv, [-2, -1, -0.5, 0, 0.5], [10, 40, 65, 85, 100])
            note["hrv"] = f"media {mean_ms:.0f} ms, {z_hrv:+.1f} SD dalla baseline ({np.exp(base['ln_base']):.0f} ms)"
        else:
            lo, hi = w["hrv_baseline_low"].mean(), w["hrv_baseline_high"].mean()
            z_hrv = float((mean_ms - (lo + hi) / 2) / max(1, (hi - lo) / 2)) if pd.notna(lo) else None
            level = lin(z_hrv, [-2, -1, 0, 1], [10, 45, 80, 100])
            note["hrv"] = f"media {mean_ms:.0f} ms rispetto alla fascia Garmin"
        stab = lin(cv_, [3, 6, 9, 12], [100, 80, 50, 20])
        comp["hrv"] = 0.7 * level + 0.3 * stab if level is not None and stab is not None else level
        if cv_ is not None:
            note["hrv"] += f"; variabilità giornaliera (CV) {cv_:.1f}%"
        val["hrv_z"] = z_hrv

    # FC a riposo
    rhr = w["rhr"].dropna()
    z_rhr = None
    if len(rhr) >= MIN_DAYS and pd.notna(base["rhr_base"]):
        sd = max(1.0, base["rhr_sd"]) if pd.notna(base["rhr_sd"]) else 2.0
        z_rhr = float((rhr.mean() - base["rhr_base"]) / sd)
        comp["rhr"] = lin(z_rhr, [-0.5, 0, 0.5, 1, 2], [100, 90, 70, 45, 10])
        val.update({"rhr": float(rhr.mean()), "rhr_z": z_rhr})
        note["rhr"] = f"media {rhr.mean():.1f} bpm vs baseline {base['rhr_base']:.1f} ({z_rhr:+.1f} SD)"

    # sonno: quantita'
    ratio = w["sleep_ratio"].dropna()
    if len(ratio) >= MIN_DAYS:
        comp["sleep_qty"] = lin(float(ratio.mean()), [0.75, 0.85, 0.95, 1.0], [20, 55, 85, 100])
        val.update({"sleep_h": float(w["sleep_h"].mean()), "sleep_need_h": _mean(w["sleep_need_h"])})
        note["sleep_qty"] = (f"{w['sleep_h'].mean():.1f} h a notte, fabbisogno {val['sleep_need_h'] or 8:.1f} h "
                             f"({ratio.mean() * 100:.0f}%)")

    # sonno: qualita'
    ss = w["sleep_score"].dropna()
    if len(ss) >= MIN_DAYS:
        stages = (w["deep_pct"] + w["rem_pct"]).dropna()
        st_score = lin(float(stages.mean()), [30, 40, 50], [40, 80, 100]) if len(stages) else None
        comp["sleep_qual"] = 0.7 * float(ss.mean()) + 0.3 * st_score if st_score is not None else float(ss.mean())
        val.update({"sleep_score": float(ss.mean()), "deep_rem_pct": float(stages.mean()) if len(stages) else None})
        note["sleep_qual"] = f"Sleep Score medio {ss.mean():.0f}" + (f"; profondo+REM {stages.mean():.0f}%" if len(stages) else "")

    # sonno: regolarita'
    bt = w["bedtime_min"].dropna()
    if len(bt) >= MIN_DAYS:
        sd = float(bt.std())
        comp["sleep_reg"] = lin(sd, [20, 40, 60, 90], [100, 80, 55, 20])
        mean_bt = (bt.mean() + 18 * 60) % 1440
        val["bedtime_sd_min"] = sd
        note["sleep_reg"] = f"addormentamento medio {int(mean_bt // 60):02d}:{int(mean_bt % 60):02d}, ±{sd:.0f} min"

    # stress ed energia
    parts = []
    stv = w["stress_avg"].dropna()
    if len(stv) >= MIN_DAYS:
        parts.append(lin(float(stv.mean()), [20, 30, 40, 55], [100, 80, 55, 20]))
        val["stress"] = float(stv.mean())
    bb = w["bb_charge"].dropna()
    if len(bb) >= MIN_DAYS:
        parts.append(lin(float(bb.mean()), [30, 45, 60, 75], [30, 60, 85, 100]))
        val["bb_charge"] = float(bb.mean())
    if parts:
        comp["stress"] = _mean(parts)
        note["stress"] = ", ".join(x for x in (
            f"stress medio {val['stress']:.0f}" if "stress" in val else "",
            f"Body Battery ricaricata {val['bb_charge']:.0f} a notte" if "bb_charge" in val else "") if x)

    # equilibrio del carico
    if "acwr" in w and w["ctl"].notna().any() and float(w["ctl"].max() or 0) > 5:
        acwr, tsb = _mean(w["acwr"]), _mean(w["tsb"])
        if acwr is not None:
            a = lin(acwr, [0.5, 0.8], [70, 100]) if acwr < 0.8 else 100.0 if acwr <= 1.3 else lin(acwr, [1.3, 1.5, 1.8], [100, 60, 20])
            t = lin(tsb, [-40, -25, -10], [20, 60, 100])
            comp["load"] = _mean([a, t])
            val.update({"acwr": acwr, "tsb": tsb, "tss_week": float(w["tss"].sum())})
            note["load"] = f"TSS settimana {w['tss'].sum():.0f}, acuto:cronico {acwr:.2f}" + \
                (f", forma (TSB) {tsb:+.0f}" if tsb is not None else "")

    # segnali respiratori
    parts, txt = [], []
    rs = w["resp_sleep"].dropna()
    if len(rs) >= MIN_DAYS and pd.notna(base["resp_base"]):
        d = float(rs.mean() - base["resp_base"])
        parts.append(lin(d, [0.3, 0.7, 1.2], [100, 60, 20]))
        val["resp_delta"] = d
        txt.append(f"respiro {rs.mean():.1f}/min ({d:+.1f} vs baseline)")
    sp = w["spo2_sleep"].dropna()
    if len(sp) >= MIN_DAYS and pd.notna(base["spo2_base"]):
        d = float(base["spo2_base"] - sp.mean())
        parts.append(lin(d, [0.5, 1, 2], [100, 60, 20]))
        val["spo2_drop"] = d
        txt.append(f"SpO2 {sp.mean():.1f}% ({-d:+.1f})")
    if parts:
        comp["resp"] = _mean(parts)
        note["resp"] = ", ".join(txt)

    avail = {k: v for k, v in comp.items() if v is not None}
    score = None
    red = bool(z_hrv is not None and z_rhr is not None and z_hrv < -1 and z_rhr > 1)
    if len(avail) >= 3 and ("hrv" in avail or "rhr" in avail):
        score = sum(WEIGHTS[k] * v for k, v in avail.items()) / sum(WEIGHTS[k] for k in avail)
        if red:
            score = min(score, 45.0)
    return {"components": comp, "values": val, "notes": note, "score": score, "red_flag": red}


def weekly_recovery(conn: sqlite3.Connection) -> list[dict]:
    df = daily_features(conn)
    if df.empty:
        return []
    out = []
    weeks = df.groupby(df.index.to_period("W-SUN"))
    today = pd.Timestamp.today().normalize()
    for period, w in weeks:
        start = period.start_time.normalize()
        base = df.loc[start] if start in df.index else w.iloc[0]
        res = _week_scores(w, base)
        days = int(w["hrv_last_night"].notna().sum())
        comps = res["components"]
        lim = min((k for k in comps if comps[k] is not None), key=lambda k: comps[k], default=None)
        row = {
            "week": start.strftime("%Y-%m-%d"), "week_end": (start + pd.Timedelta(days=6)).strftime("%Y-%m-%d"),
            "complete": bool(start + pd.Timedelta(days=6) < today), "days": days,
            "score": round(res["score"], 1) if res["score"] is not None else None,
            "label": label_for(res["score"]) if res["score"] is not None else None,
            "red_flag": res["red_flag"], "limiter": NAMES.get(lim) if lim else None,
        }
        for k in WEIGHTS:
            v = comps.get(k)
            row[f"c_{k}"] = round(v, 1) if v is not None else None
            row[f"n_{k}"] = res["notes"].get(k)
        row.update({k: (round(v, 2) if isinstance(v, float) else v) for k, v in res["values"].items()})
        out.append(row)
    return out
