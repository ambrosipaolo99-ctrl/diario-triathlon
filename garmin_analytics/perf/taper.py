"""
Dynamic impulse-response taper model (Banister) per la gara obiettivo.

  forma(t)  = sum carico(s) e^-(t-s)/tau1        fatica(t) = sum carico(s) e^-(t-s)/tau2   (s < t: al mattino)
  prestazione(t) = k1 forma(t) - k2 fatica(t),   k1 = 1, k2 = 2
Il modello e' il riferimento classico per lo scarico [CONSOLIDATO come schema]; le previsioni individuali con
pochi dati restano incerte [PRELIMINARE MA RILEVANTE].

Carico = TSS della sola corsa: per una gara podistica conta il lavoro specifico; con il carico di tutti gli sport
il volume estivo in bici gonfierebbe la "forma" e sposterebbe il picco [EMERGENTE].
Valori di riferimento: forma 42 gg, fatica 11 gg (modelli di prestazione di Banister/Busso: 40-50 e 10-15 gg).

Costanti adattate allo storico (ricerca su griglia, poi media con i valori classici in base all'evidenza):
  tau2 (fatica, 3-15 gg)   quella con cui la fatica del giorno prima spiega meglio l'indice di recupero del
                           mattino; i giorni delle settimane di scarico (carico < 70% delle 3 precedenti) pesano
                           il triplo: e' li' che si vede quanto in fretta passa la fatica
  tau1 (forma, 21-63 gg)   quella con cui la forma spiega meglio l'Efficiency Factor delle corse continue
  peso del dato = min(1, R^2 / 0.3): con R^2 basso si resta vicini a 42 e 7 giorni.

Proiezione: carico reale fino a oggi (TSS), poi quello del piano (minuti x IF^2 x 100/60 per tipo di seduta);
il picco e' il mattino di massima prestazione tra oggi e il giorno della gara (dopo la gara il piano non prevede
carico e la curva salirebbe solo per il riposo). Il grafico prosegue 7 giorni oltre la gara.

Righe esportate
  taper       date, tss, projected, fitness, fatigue, perf, perf_idx, is_race, is_peak
  taper_meta  tau1, tau2, r2_fitness, r2_fatigue, tau1_source, tau2_source, deload_weeks, race_date,
              peak_date, gap_days, note
"""
from __future__ import annotations

import math
import sqlite3
from datetime import date, timedelta
from typing import Optional

import numpy as np
import pandas as pd

from ..load import daily_tss

K1, K2 = 1.0, 2.0
TAU1_PRIOR, TAU2_PRIOR = 42.0, 11.0
PLAN_IF = {"facile": 0.72, "lungo": 0.75, "qualità": 0.85, "gara": 0.84}


def _impulse(load: np.ndarray, tau: float) -> np.ndarray:
    out, x, k = np.empty(len(load)), 0.0, math.exp(-1 / tau)
    for i, w in enumerate(load):
        x = x * k + w
        out[i] = x
    return out


def _wr2(x: np.ndarray, y: np.ndarray, w: np.ndarray) -> tuple[float, float]:
    """R^2 pesato e segno della correlazione."""
    m = ~(np.isnan(x) | np.isnan(y))
    if m.sum() < 15:
        return 0.0, 0.0
    x, y, w = x[m], y[m], w[m]
    mx, my = np.average(x, weights=w), np.average(y, weights=w)
    cov = np.average((x - mx) * (y - my), weights=w)
    vx, vy = np.average((x - mx) ** 2, weights=w), np.average((y - my) ** 2, weights=w)
    if vx <= 0 or vy <= 0:
        return 0.0, 0.0
    r = cov / math.sqrt(vx * vy)
    return r * r, math.copysign(1, r)


def _blend(best: float, r2: float, prior: float) -> tuple[float, str]:
    w = min(1.0, r2 / 0.3)
    tau = w * best + (1 - w) * prior
    src = "dallo storico" if w >= 0.66 else "in parte dallo storico" if w >= 0.2 else "valore classico (dati insufficienti)"
    return round(tau, 1), src


def deload_mask(days: pd.DatetimeIndex, tss: np.ndarray) -> tuple[np.ndarray, int]:
    s = pd.Series(tss, index=days)
    weekly = s.resample("W-SUN").sum()
    prev = weekly.shift(1).rolling(3).mean()
    deload_weeks = weekly[(prev > 0) & (weekly < 0.7 * prev)].index
    mask = np.zeros(len(days), dtype=bool)
    for wk in deload_weeks:
        mask |= (days > wk - pd.Timedelta(days=7)) & (days <= wk)
    return mask, len(deload_weeks)


def model(conn: sqlite3.Connection, goal: Optional[dict], plan: list[dict], ef_points: list[tuple[str, float]],
          today: Optional[date] = None) -> tuple[list[dict], list[dict]]:
    today = today or date.today()
    d = daily_tss(conn)
    if d.empty or "run" not in d or not goal:
        return [], []
    race = date.fromisoformat(goal["date"])
    hist_days = pd.date_range(d.index.min(), pd.Timestamp(today), freq="D")
    run_tss = d["run"].reindex(hist_days, fill_value=0.0)
    tss_hist = run_tss.to_numpy(dtype=float)

    # --- adattamento delle costanti
    rec = pd.Series({pd.Timestamp(r["date"]): r["recovery_index"] for r in conn.execute(
        "SELECT date, recovery_index FROM wellness_daily WHERE recovery_index IS NOT NULL")}, dtype=float)
    rec = rec.reindex(hist_days).to_numpy()
    deload, n_deload = deload_mask(hist_days, tss_hist)
    weights = np.where(deload, 3.0, 1.0)
    best2 = (TAU2_PRIOR, 0.0)
    for tau in np.arange(3, 15.5, 0.5):
        fat = np.concatenate([[np.nan], _impulse(tss_hist, tau)[:-1]])     # fatica fino a ieri vs recupero di oggi
        r2, sign = _wr2(fat, rec, weights)
        if sign < 0 and r2 > best2[1]:
            best2 = (float(tau), r2)
    ef = pd.Series({pd.Timestamp(d): v for d, v in ef_points}, dtype=float).groupby(level=0).mean()
    ef = ef.reindex(hist_days).to_numpy()
    best1 = (TAU1_PRIOR, 0.0)
    for tau in range(21, 64, 3):
        r2, sign = _wr2(_impulse(tss_hist, tau), ef, np.ones(len(ef)))
        if sign > 0 and r2 > best1[1]:
            best1 = (float(tau), r2)
    tau1, src1 = _blend(*best1, TAU1_PRIOR)
    tau2, src2 = _blend(*best2, TAU2_PRIOR)

    # --- carico: reale fino a oggi, poi quello del piano
    planned = {}
    for d in plan:
        if d.get("type") in PLAN_IF:
            mins = d.get("minutes") or (d.get("km") or 0) * 6
            planned[d["date"]] = mins * PLAN_IF[d["type"]] ** 2 * 100 / 60
    end = max(race + timedelta(days=7), today)
    days = pd.date_range(hist_days.min(), pd.Timestamp(end), freq="D")
    load, projected = [], []
    for day in days:
        k = day.date().isoformat()
        real = float(run_tss.get(day, 0.0))
        future = day.date() > today or (day.date() == today and real == 0)
        load.append(planned.get(k, 0.0) if future else real)
        projected.append(bool(future))
    load = np.array(load)
    morning = np.concatenate([[0.0], load[:-1]])            # prestazione al mattino: carico fino a ieri
    fit, fat = _impulse(morning, tau1), _impulse(morning, tau2)
    perf = K1 * fit - K2 * fat
    window = [i for i, day in enumerate(days) if today <= day.date() <= race]
    peak_i = max(window, key=lambda i: perf[i]) if window else None
    shown = [i for i, d in enumerate(days) if d.date() >= today - timedelta(days=60)]
    lo, hi = min(perf[i] for i in shown), max(perf[i] for i in shown)

    rows = [{"date": days[i].date().isoformat(), "tss": round(load[i], 1), "projected": projected[i],
             "fitness": round(fit[i], 1), "fatigue": round(fat[i], 1), "perf": round(perf[i], 1),
             "perf_idx": round(100 * (perf[i] - lo) / (hi - lo), 1) if hi > lo else None,
             "is_race": days[i].date() == race, "is_peak": i == peak_i} for i in shown]
    peak = days[peak_i].date() if peak_i is not None else None
    gap = (peak - race).days if peak else None
    ri = window[-1] if window and days[window[-1]].date() == race else None
    rising = ri is not None and perf[ri - 1] > 0 and (perf[ri] / perf[ri - 1] - 1) > 0.01
    if gap is None:
        note = "Picco non calcolabile."
    elif gap == 0 and rising:
        note = ("Il picco di forma cade il giorno della gara, con la curva ancora in crescita: arrivi in salita di "
                "forma. Non aggiungere volume nei giorni finali; mantieni l'intensita' dei richiami brevi "
                "(Bosquet 2007) [CONSOLIDATO].")
    elif gap == 0:
        note = "Il picco di forma previsto cade il giorno della gara: lo scarico e' calibrato."
    else:
        note = (f"Picco previsto {-gap} giorn{'o' if gap == -1 else 'i'} prima della gara: con queste costanti lo "
                "scarico e' leggermente lungo o troppo profondo; un richiamo breve a ritmo gara nei giorni finali aiuta.")
    meta = [{"tau1": tau1, "tau2": tau2, "r2_fitness": round(best1[1], 2), "r2_fatigue": round(best2[1], 2),
             "tau1_source": src1, "tau2_source": src2, "deload_weeks": n_deload, "race_date": race.isoformat(),
             "peak_date": peak.isoformat() if peak else None, "gap_days": gap, "k1": K1, "k2": K2,
             "note": note + " Modello di Banister: schema consolidato, previsione individuale [PRELIMINARE MA RILEVANTE]."}]
    return rows, meta
