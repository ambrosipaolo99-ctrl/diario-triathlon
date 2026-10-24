"""
Modulo 1 - Recupero e fisiologia (dati non-attivita').

Acquisizione:
  * storico: endpoint a intervallo (riepiloghi giornalieri, sonno, HRV) a blocchi
    di 28 giorni -> ~3 chiamate ogni 4 settimane;
  * ultimi giorni: endpoint giornalieri di dettaglio, che aggiungono stress nel
    sonno, Body Battery al risveglio e Training Readiness.

Indice di recupero (0-100): media pesata di cinque componenti, ciascuna
normalizzata rispetto alla baseline personale (60 giorni precedenti, esclusa la
giornata in esame) con z-score; HRV su scala logaritmica (ln rMSSD) come da
letteratura (Plews et al., Buchheit). Senza baseline sufficiente si usano le
fasce calcolate da Garmin.
"""
from __future__ import annotations

import json
import logging
import sqlite3
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

import numpy as np
import pandas as pd

from . import db
from .auth import throttled
from .config import DATA_START

log = logging.getLogger("garmin_analytics.recovery")

RANGE_CHUNK_DAYS = 28
DETAIL_DAYS = 3            # giorni recenti scaricati anche con gli endpoint di dettaglio
BASELINE_DAYS = 60
MIN_BASELINE_DAYS = 14

WEIGHTS = {"hrv": 0.30, "sleep": 0.25, "rhr": 0.15, "body_battery": 0.15, "stress": 0.15}

LABELS = [(80, "Ottimo"), (65, "Buono"), (50, "Moderato"), (35, "Basso"), (0, "Molto basso")]


# --------------------------------------------------------------------------- #
# Parsing risposte API
# --------------------------------------------------------------------------- #
def _g(d: Any, *path: str) -> Any:
    for p in path:
        if not isinstance(d, dict):
            return None
        d = d.get(p)
    return d


def _stress(v: Any) -> Optional[int]:
    # Garmin usa valori negativi per "dati insufficienti"
    return v if isinstance(v, (int, float)) and v >= 0 else None


def _local_ms(ms: Any) -> Optional[str]:
    # i timestamp "Local" Garmin sono l'ora locale codificata come se fosse UTC
    if not ms:
        return None
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).replace(tzinfo=None).isoformat(timespec="minutes")


def _parse_summary(s: dict) -> dict:
    bb = s.get("bodyBattery") or {}
    st = s.get("stress") or {}
    high_ms = st.get("highStressDurationInMillis")
    return {
        "date": s["calendarDate"],
        "rhr": _g(s, "heartRate", "restingValue"),
        "bb_high": bb.get("maxValue"),
        "bb_low": bb.get("minValue"),
        "bb_charged": bb.get("chargedValue"),
        "bb_drained": bb.get("drainedValue"),
        "stress_avg": _stress(st.get("avgLevel")),
        "stress_max": _stress(st.get("maxLevel")),
        "stress_high_seconds": int(high_ms / 1000) if high_ms is not None else None,
    }


def _parse_sleep_range(s: dict) -> dict:
    v = s.get("values") or {}
    return {
        "date": s["calendarDate"],
        "sleep_seconds": v.get("totalSleepTimeInSeconds"),
        "deep_seconds": v.get("deepTime"),
        "light_seconds": v.get("lightTime"),
        "rem_seconds": v.get("remTime"),
        "awake_seconds": v.get("awakeTime"),
        "sleep_score": v.get("sleepScore"),
        "sleep_need_minutes": v.get("sleepNeed"),
        "sleep_start": _local_ms(v.get("localSleepStartTimeInMillis")),
        "sleep_end": _local_ms(v.get("localSleepEndTimeInMillis")),
        "resp_sleep": v.get("respiration"),
        "spo2_sleep": v.get("spO2"),
        "bb_sleep_charge": v.get("bodyBatteryChange"),
    }


def _parse_hrv_summary(h: dict) -> dict:
    return {
        "date": h["calendarDate"],
        "hrv_last_night": h.get("lastNightAvg"),
        "hrv_weekly_avg": h.get("weeklyAvg"),
        "hrv_5min_high": h.get("lastNight5MinHigh"),
        "hrv_status": h.get("status"),
        "hrv_baseline_low": _g(h, "baseline", "balancedLow"),
        "hrv_baseline_high": _g(h, "baseline", "balancedUpper"),
    }


def _parse_sleep_detail(day: str, sleep: dict) -> dict:
    dto = (sleep or {}).get("dailySleepDTO") or {}
    if not dto.get("sleepTimeSeconds"):
        return {"date": day}
    return {
        "date": day,
        "sleep_seconds": dto.get("sleepTimeSeconds"),
        "deep_seconds": dto.get("deepSleepSeconds"),
        "light_seconds": dto.get("lightSleepSeconds"),
        "rem_seconds": dto.get("remSleepSeconds"),
        "awake_seconds": dto.get("awakeSleepSeconds"),
        "sleep_score": _g(dto, "sleepScores", "overall", "value"),
        "sleep_need_minutes": _g(dto, "sleepNeed", "actual"),
        "sleep_start": _local_ms(dto.get("sleepStartTimestampLocal")),
        "sleep_end": _local_ms(dto.get("sleepEndTimestampLocal")),
        "avg_sleep_stress": _stress(dto.get("avgSleepStress")),
        "resp_sleep": dto.get("averageRespirationValue"),
        "spo2_sleep": dto.get("averageSpO2Value"),
        "bb_sleep_charge": (sleep or {}).get("bodyBatteryChange"),
    }


def _parse_stats_detail(day: str, st: dict) -> dict:
    st = st or {}
    return {
        "date": day,
        "rhr": st.get("restingHeartRate"),
        "bb_at_wake": st.get("bodyBatteryAtWakeTime"),
        "bb_high": st.get("bodyBatteryHighestValue"),
        "bb_low": st.get("bodyBatteryLowestValue"),
        "bb_charged": st.get("bodyBatteryChargedValue"),
        "bb_drained": st.get("bodyBatteryDrainedValue"),
        "stress_avg": _stress(st.get("averageStressLevel")),
        "stress_max": _stress(st.get("maxStressLevel")),
        "stress_high_seconds": st.get("highStressDuration"),
    }


# --------------------------------------------------------------------------- #
# Sincronizzazione
# --------------------------------------------------------------------------- #
def _merge(rows: dict[str, dict], new: dict) -> None:
    cur = rows.setdefault(new["date"], {"date": new["date"]})
    cur.update({k: v for k, v in new.items() if v is not None})


def _fetch_range(api, start: date, end: date) -> dict[str, dict]:
    rows: dict[str, dict] = {}
    s, e = start.isoformat(), end.isoformat()
    for item in (throttled(api.get_daily_summaries, s, e) or {}).get("data", []):
        _merge(rows, _parse_summary(item))
    for item in throttled(api.get_sleep_daily, s, e) or []:
        _merge(rows, _parse_sleep_range(item))
    for item in (throttled(api.get_hrv_data_range, s, e) or {}).get("hrvSummaries", []):
        _merge(rows, _parse_hrv_summary(item))
    return rows


def _fetch_detail(api, day: date) -> dict:
    d = day.isoformat()
    row: dict = {"date": d}
    row.update({k: v for k, v in _parse_sleep_detail(d, throttled(api.get_sleep_data, d)).items() if v is not None})
    row.update({k: v for k, v in _parse_stats_detail(d, throttled(api.get_stats, d)).items() if v is not None})
    hrv = throttled(api.get_hrv_data, d)
    if hrv and hrv.get("hrvSummary"):
        row.update({k: v for k, v in _parse_hrv_summary(hrv["hrvSummary"]).items() if v is not None})
    try:
        tr = throttled(api.get_morning_training_readiness, d)
        if tr and tr.get("score") is not None:
            row["training_readiness"] = tr["score"]
    except Exception as exc:  # endpoint non critico
        log.debug("Training readiness non disponibile per %s: %s", d, exc)
    return row


def sync_wellness(api, days: int = 7, conn: Optional[sqlite3.Connection] = None) -> int:
    """Scarica gli ultimi `days` giorni (storico via range + dettaglio recente) e ricalcola l'indice."""
    conn = conn or db.connect()
    today = date.today()
    start = max(today - timedelta(days=days - 1), date.fromisoformat(DATA_START))

    rows: dict[str, dict] = {}
    chunk_start = start
    while chunk_start <= today:
        chunk_end = min(chunk_start + timedelta(days=RANGE_CHUNK_DAYS - 1), today)
        log.info("Wellness %s -> %s", chunk_start, chunk_end)
        for r in _fetch_range(api, chunk_start, chunk_end).values():
            _merge(rows, r)
        chunk_start = chunk_end + timedelta(days=1)

    for i in range(min(DETAIL_DAYS, days)):
        day = today - timedelta(days=i)
        log.info("Dettaglio wellness %s", day)
        _merge(rows, _fetch_detail(api, day))

    stamp = db.now_iso()
    for r in rows.values():
        r["fetched_at"] = stamp
        db.upsert(conn, "wellness_daily", "date", r)
    conn.commit()
    update_recovery_index(conn)
    return len(rows)


# --------------------------------------------------------------------------- #
# Indice di recupero
# --------------------------------------------------------------------------- #
def _interp(x: float, xp: list[float], fp: list[float]) -> float:
    return float(np.interp(x, xp, fp))


def _baseline(s: pd.Series) -> tuple[pd.Series, pd.Series]:
    """Media e deviazione standard dei BASELINE_DAYS precedenti (giorno corrente escluso)."""
    prev = s.shift(1)
    roll = prev.rolling(BASELINE_DAYS, min_periods=MIN_BASELINE_DAYS)
    return roll.mean(), roll.std()


def compute_recovery(df: pd.DataFrame) -> pd.DataFrame:
    """
    Calcola l'indice di recupero per ogni riga di wellness_daily.

    Componenti (0-100):
      hrv          z-score di ln(HRV notte) e ln(HRV media 7gg) vs baseline personale
      rhr          z-score inverso della FC a riposo (piu' bassa = meglio)
      sleep        70% Sleep Score + 30% durata rispetto al fabbisogno di sonno Garmin
      body_battery Body Battery al risveglio (o massimo giornaliero)
      stress       stress medio del giorno precedente + stress medio nel sonno
    Pesi in WEIGHTS, rinormalizzati sulle componenti disponibili.
    Bandiera rossa: HRV z < -1.5 e RHR z > +1.5 insieme -> indice limitato a 40
    (pattern tipico di sovraccarico, malattia incipiente o alcol).
    """
    if df.empty:
        return df.assign(recovery_index=np.nan, recovery_json=None)

    df = df.copy()
    df["date"] = pd.to_datetime(df["date"])
    df = df.set_index("date").asfreq("D")   # giorni mancanti -> NaN, cosi' shift/rolling sono in giorni reali

    ln_hrv = np.log(df["hrv_last_night"].where(df["hrv_last_night"] > 0))
    ln_week = np.log(df["hrv_weekly_avg"].where(df["hrv_weekly_avg"] > 0))
    hrv_mu, hrv_sd = _baseline(ln_hrv)
    hrv_sd = hrv_sd.clip(lower=0.05)
    z_night = (ln_hrv - hrv_mu) / hrv_sd
    z_week = (ln_week - hrv_mu) / hrv_sd
    # fallback: posizione nella fascia "bilanciata" di Garmin (bordi = +-1)
    mid = (df["hrv_baseline_low"] + df["hrv_baseline_high"]) / 2
    half = ((df["hrv_baseline_high"] - df["hrv_baseline_low"]) / 2).clip(lower=1)
    z_night = z_night.fillna((df["hrv_last_night"] - mid) / half)
    z_week = z_week.fillna((df["hrv_weekly_avg"] - mid) / half)
    z_hrv = (0.6 * z_night + 0.4 * z_week.fillna(z_night)).where(z_night.notna())

    rhr_mu, rhr_sd = _baseline(df["rhr"].astype(float))
    rhr_mu = rhr_mu.fillna(df["rhr"].shift(1).rolling(7, min_periods=3).mean())
    z_rhr = (df["rhr"] - rhr_mu) / rhr_sd.fillna(2.0).clip(lower=1.0)

    prev_stress = df["stress_avg"].shift(1)
    bb = df["bb_at_wake"].fillna(df["bb_high"]) if "bb_at_wake" in df else df["bb_high"]

    indices, details = [], []
    for ts, row in df.iterrows():
        comp: dict[str, Optional[float]] = {}
        zh, zr = z_hrv.get(ts), z_rhr.get(ts)
        comp["hrv"] = float(np.clip(50 + 25 * min(zh, 2.0), 0, 100)) if pd.notna(zh) else None
        comp["rhr"] = float(np.clip(50 - 25 * zr, 0, 100)) if pd.notna(zr) else None

        if pd.notna(row["sleep_score"]) or pd.notna(row["sleep_seconds"]):
            need = row["sleep_need_minutes"] if pd.notna(row["sleep_need_minutes"]) else 480
            dur = min(1.0, (row["sleep_seconds"] or 0) / 60 / need) * 100 if pd.notna(row["sleep_seconds"]) else None
            if pd.notna(row["sleep_score"]) and dur is not None:
                comp["sleep"] = 0.7 * row["sleep_score"] + 0.3 * dur
            else:
                comp["sleep"] = float(row["sleep_score"]) if pd.notna(row["sleep_score"]) else dur
        else:
            comp["sleep"] = None

        comp["body_battery"] = float(bb.get(ts)) if pd.notna(bb.get(ts)) else None

        parts = []
        if pd.notna(prev_stress.get(ts)):
            parts.append(_interp(prev_stress[ts], [15, 75], [100, 0]))
        if pd.notna(row.get("avg_sleep_stress")):
            parts.append(_interp(row["avg_sleep_stress"], [10, 45], [100, 0]))
        comp["stress"] = float(np.mean(parts)) if parts else None

        avail = {k: v for k, v in comp.items() if v is not None}
        # serve almeno un marker autonomico (HRV o RHR) piu' un'altra componente
        if len(avail) < 2 or (comp["hrv"] is None and comp["rhr"] is None):
            indices.append(np.nan)
            details.append(None)
            continue
        wsum = sum(WEIGHTS[k] for k in avail)
        index = sum(WEIGHTS[k] * v for k, v in avail.items()) / wsum
        red_flag = pd.notna(zh) and pd.notna(zr) and zh < -1.5 and zr > 1.5
        if red_flag:
            index = min(index, 40.0)
        limiter = min(avail, key=avail.get)
        details.append(json.dumps({
            "components": {k: (round(v, 1) if v is not None else None) for k, v in comp.items()},
            "z_hrv": round(float(zh), 2) if pd.notna(zh) else None,
            "z_rhr": round(float(zr), 2) if pd.notna(zr) else None,
            "red_flag": bool(red_flag),
            "limiter": limiter,
            "label": label_for(index),
        }))
        indices.append(round(index, 1))

    df["recovery_index"] = indices
    df["recovery_json"] = details
    out = df.reset_index()
    out["date"] = out["date"].dt.strftime("%Y-%m-%d")
    return out


def label_for(index: float) -> str:
    return next(lbl for thr, lbl in LABELS if index >= thr)


def update_recovery_index(conn: sqlite3.Connection) -> None:
    df = db.read_df(conn, "SELECT * FROM wellness_daily ORDER BY date")
    if df.empty:
        return
    res = compute_recovery(df).dropna(subset=["recovery_index"])
    conn.executemany(
        "UPDATE wellness_daily SET recovery_index=?, recovery_json=? WHERE date=?",
        [(float(r.recovery_index), r.recovery_json, r.date) for r in res.itertuples()],
    )
    conn.commit()


def get_recovery(conn: sqlite3.Connection, day: Optional[str] = None) -> Optional[dict]:
    """Indice e dettaglio per un giorno (default: il piu' recente disponibile)."""
    sql = "SELECT * FROM wellness_daily WHERE recovery_index IS NOT NULL"
    params: list = []
    if day:
        sql += " AND date=?"
        params.append(day)
    row = conn.execute(sql + " ORDER BY date DESC LIMIT 1", params).fetchone()
    if not row:
        return None
    out = dict(row)
    out["detail"] = json.loads(out.pop("recovery_json") or "{}")
    return out
