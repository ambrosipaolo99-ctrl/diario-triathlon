"""
Dual-vector load: carico cardiovascolare e carico strutturale (meccanico) della corsa.

Vettore A, cardiovascolare
  TRIMP di Edwards: minuti in ogni zona FC Garmin x peso della zona (1-5) [CONSOLIDATO]. Non dipende dal
  sesso (il TRIMP di Banister si'), quindi non serve un dato che non abbiamo.

Vettore B, strutturale (unita': migliaia di picchi di carico in pesi corporei, kBW)
  per ogni tratto di 30 s:  passi x forza di picco stimata / peso  x  fattore discesa
  - forza di picco dal modello molla-massa: F/BW = pi/2 x (tf/tc + 1), con tc = contatto al suolo e
    tf = tempo di volo (60/cadenza - tc) (Morin 2005, validato su pedana) [CONSOLIDATO]; senza dinamiche
    una stima dalla velocita' [PRELIMINARE MA RILEVANTE]
  - discesa: +3,4% di forza d'impatto per ogni 1% di pendenza negativa (Gottschall & Kram 2005: +54% a -9 gradi)
    [EMERGENTE]; con la quota dell'orologio inaffidabile si stima dal dislivello Strava (percorso ad anello)
  - asimmetria: il lato che sta piu' a terra porta la quota maggiore (fattore = quota del lato / 50)
  L'indice nel suo insieme e' una costruzione di questo progetto [PRELIMINARE MA RILEVANTE]: va letto come
  confronto con il proprio storico, non come valore assoluto.

Indici 0-100: percentile rispetto al proprio storico (corse dei 120 giorni precedenti per la singola corsa,
somme mobili di 7 giorni per il giorno).

Regola di protezione: se lo stress strutturale e' alto e quello cardiaco basso (corsa collinare, discese
veloci) niente lavori ad alto impatto per 48 h: ripetute veloci, discese, lunghi collinari.

Righe esportate
  run_load      id, date, km, trimp, mech_kbw, f_peak_bw, steps, descent_m, descent_method, downhill_factor,
                asym_factor, mech_method, cardio_si, struct_si, impact_block, note
  load_vectors  date, cardio_load, mech_load, cardio_7d, mech_7d, cardio_idx, struct_idx, impact_block, reason
"""
from __future__ import annotations

import math
import sqlite3
from datetime import date, timedelta
from typing import Optional

import numpy as np

from ..race import Athlete
from .common import STEP_S, RunDetail, percentile_of

HISTORY_DAYS = 120
DOWNHILL_PER_PCT = 0.034        # aumento della forza d'impatto per 1% di pendenza negativa
BLOCK_STRUCT = 80               # percentile strutturale oltre cui scatta la protezione...
BLOCK_GAP = 25                  # ...se supera quello cardiaco di almeno tanti punti
BLOCK_HOURS = 48


def _zone_weight(hr: Optional[float], floors: list[float]) -> int:
    if hr is None or not floors:
        return 0
    return sum(1 for f in floors if hr >= f)


def trimp(r: RunDetail, ath: Athlete) -> Optional[float]:
    pts = [p for p in r.stream if p.get("hr")]
    if len(pts) >= 10 and ath.floors:
        return round(sum(_zone_weight(p["hr"], ath.floors) for p in pts) * STEP_S / 60, 1)
    if r.hr and ath.floors:
        return round(_zone_weight(r.hr, ath.floors) * r.moving_s / 60, 1)
    return None


def _f_peak(p: dict) -> tuple[Optional[float], str]:
    cad, gct = p.get("cad"), p.get("gct")
    if cad and gct and cad > 100 and 120 < gct < 450:
        tc = gct / 1000
        tf = max(60 / cad - tc, 0.01)
        return float(np.clip(math.pi / 2 * (tf / tc + 1), 1.3, 4.5)), "molla-massa"
    if p.get("pace_s"):
        v = 1000 / p["pace_s"]
        return float(np.clip(2.0 + 0.25 * (v - 2.5), 1.6, 3.5)), "velocita'"
    return None, ""


def mechanical(r: RunDetail) -> dict:
    pts = r.stream
    loads, forces, steps_tot, methods = 0.0, [], 0.0, set()
    descent, down_weighted, dist_tot = 0.0, 0.0, 0.0
    use_alt = r.altitude_reliable and not r.treadmill and sum(1 for p in pts if p.get("alt") is not None) > len(pts) * 0.8
    alt_s = None
    if use_alt:
        alts = [p.get("alt") for p in pts]
        # media mobile su 3 punti (90 s): toglie il rumore del barometro senza appiattire le salite
        alt_s = [np.nanmean([a for a in alts[max(0, i - 1):i + 2] if a is not None] or [np.nan]) for i in range(len(alts))]
    prev_d = 0.0
    for i, p in enumerate(pts):
        d = p.get("dist_km")
        if d is None:
            continue
        dd = max(0.0, (d - prev_d) * 1000)
        prev_d = d
        f, method = _f_peak(p)
        if f is None or dd < 1:
            continue
        methods.add(method)
        steps = (p.get("cad") or 168) * STEP_S / 60
        down = 1.0
        if alt_s is not None and i > 0 and not np.isnan(alt_s[i]) and not np.isnan(alt_s[i - 1]):
            dz = alt_s[i] - alt_s[i - 1]
            if dz < 0:
                descent += -dz
                grade = -dz / dd
                if grade > 0.02:
                    down = 1 + DOWNHILL_PER_PCT * min(grade * 100, 20)
        loads += steps * f * down
        down_weighted += dd * down
        dist_tot += dd
        forces.append(f)
        steps_tot += steps
    if not forces:
        return {}
    desc_method = "quota" if use_alt else None
    if not use_alt and not r.treadmill and r.ascent_m:
        # quota dell'orologio non affidabile: percorso ad anello, si scende quanto si sale (dislivello Strava)
        descent = float(r.ascent_m)
        desc_method = "stima da D+ " + ("Strava" if r.ascent_source == "strava" else "orologio")
        half = max(dist_tot / 2, 1)
        grade = descent / half
        avg_down = 1 + DOWNHILL_PER_PCT * min(grade * 100, 20) if grade > 0.02 else 1.0
        loads *= (1 + avg_down) / 2              # meta' percorso in discesa
        down_factor = (1 + avg_down) / 2
    else:
        down_factor = down_weighted / dist_tot if dist_tot else 1.0
    asym = max(r.gct_balance, 100 - r.gct_balance) / 50 if r.gct_balance else 1.0
    return {
        "mech_kbw": round(loads * asym / 1000, 2), "f_peak_bw": round(float(np.mean(forces)), 2),
        "steps": int(steps_tot), "descent_m": round(descent) if desc_method else None, "descent_method": desc_method,
        "downhill_factor": round(down_factor, 3), "asym_factor": round(asym, 3),
        "mech_method": " + ".join(sorted(methods)),
    }


def run_rows(runs: list[RunDetail], ath: Athlete) -> list[dict]:
    rows = []
    for r in runs:
        m = mechanical(r)
        rows.append({"id": r.id, "date": r.day.isoformat(), "start": r.start, "km": round(r.km, 2),
                     "trimp": trimp(r, ath), **{k: m.get(k) for k in ("mech_kbw", "f_peak_bw", "steps", "descent_m",
                                                                       "descent_method", "downhill_factor", "asym_factor",
                                                                       "mech_method")}})
    for i, row in enumerate(rows):
        d0 = date.fromisoformat(row["date"])
        hist = [x for x in rows[:i] if (d0 - date.fromisoformat(x["date"])).days <= HISTORY_DAYS]
        row["cardio_si"] = percentile_of(row["trimp"], [x["trimp"] for x in hist])
        row["struct_si"] = percentile_of(row["mech_kbw"], [x["mech_kbw"] for x in hist])
        cs, ss = row["cardio_si"], row["struct_si"]
        row["impact_block"] = bool(ss is not None and cs is not None and ss >= BLOCK_STRUCT and ss - cs >= BLOCK_GAP)
        row["note"] = (f"Stress strutturale alto ({ss:.0f}° percentile) con carico cardiaco basso ({cs:.0f}°): "
                       f"per {BLOCK_HOURS} h niente ripetute veloci, discese o lunghi collinari." if row["impact_block"] else None)
    return rows


def daily_rows(runs: list[dict], start: date, end: date) -> list[dict]:
    by_day: dict[str, list[dict]] = {}
    for r in runs:
        by_day.setdefault(r["date"], []).append(r)
    days, cardio, mech = [], [], []
    d = start
    while d <= end:
        rs = by_day.get(d.isoformat(), [])
        days.append(d)
        cardio.append(sum(r["trimp"] or 0 for r in rs))
        mech.append(sum(r["mech_kbw"] or 0 for r in rs))
        d += timedelta(days=1)
    c7 = [sum(cardio[max(0, i - 6):i + 1]) for i in range(len(days))]
    m7 = [sum(mech[max(0, i - 6):i + 1]) for i in range(len(days))]
    out = []
    for i, d in enumerate(days):
        lo = max(0, i - HISTORY_DAYS)
        ci = percentile_of(c7[i], c7[lo:i]) if i >= 28 else None
        si = percentile_of(m7[i], m7[lo:i]) if i >= 28 else None
        # protezione attiva se una corsa delle ultime 48 h l'ha accesa, o se la settimana e' squilibrata
        recent = [r for r in runs if r["impact_block"] and 0 <= (d - date.fromisoformat(r["date"])).days < BLOCK_HOURS / 24]
        week = si is not None and ci is not None and si >= 85 and si - ci >= 20
        reason = (recent[-1]["note"] if recent else
                  f"Settimana con carico strutturale alto ({si:.0f}°) rispetto a quello cardiaco ({ci:.0f}°)." if week else None)
        out.append({"date": d.isoformat(), "cardio_load": round(cardio[i], 1), "mech_load": round(mech[i], 2),
                    "cardio_7d": round(c7[i], 1), "mech_7d": round(m7[i], 2), "cardio_idx": ci, "struct_idx": si,
                    "impact_block": bool(recent or week), "reason": reason})
    return out


def impact_until(daily: list[dict], today: date) -> Optional[dict]:
    """La protezione vale per oggi e domani se e' attiva oggi (usata dal piano per rimandare il lavoro duro)."""
    row = next((r for r in daily if r["date"] == today.isoformat()), None)
    if row and row["impact_block"]:
        return {"until": (today + timedelta(days=1)).isoformat(), "reason": row["reason"]}
    return None
