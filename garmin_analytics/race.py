"""
Stima del tempo gara per un obiettivo di corsa, ricalcolata giorno per giorno.

Quattro metodi, ognuno con la sua stima e un'affidabilita' 0-1:

  Velocita' critica   inviluppo dei migliori sforzi 3-20' delle ultime 16 settimane
                      (outdoor), modello distanza = CS*t + D'; maratona ~85% della CS
                      (Smyth & Muniz-Pumares 2020).                          [EMERGENTE]
  VDOT                Daniels-Gilbert: sforzi >= 30' con FC >= 90% della soglia nelle
                      ultime 16 settimane + VDOT da FC delle corse continue recenti
                      (%FCris ~ %VO2ris, Swain 1997). Le tabelle VDOT sono pratica
                      diffusa; la relazione %FCris-%VO2ris e'                [CONSOLIDATO]
  Riegel adattato     T2 = T1*(D2/D1)^k con k da 1.06 a 1.11 secondo volume e lunghi:
                      gli amatori rallentano piu' del k=1.06 originale
                      (Vickers & Vertosick 2016).                            [EMERGENTE]
  Durability          passo alla FC da maratona dalla relazione passo-FC recente,
                      corretto per deriva cardiaca e cali di passo nei lunghi
                      (Maunder 2021, Jones 2024). Coefficienti = pratica da allenatore.
                                                                             [EMERGENTE]

Le corse dal giorno dopo l'obiettivo precedente pesano di piu': la FC-VDOT e la
relazione passo-FC usano solo quelle (se bastano), gli sforzi massimali e la CS
anche lo storico delle 16 settimane come contesto.
"""
from __future__ import annotations

import json
import math
import sqlite3
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any, Optional

import numpy as np

from . import db
from .goals import RunProfile

LOOKBACK_DAYS = 112                 # 16 settimane
CS_DURATIONS = [3, 5, 8, 12, 20]    # minuti
EFFORT_DURATIONS = [12, 20, 30, 45, 60, 90]
OFF_BIKE_FACTOR = 0.97              # corsa dopo la bici: tempo equivalente a fresco (pratica, evidenze deboli)
BASE_WEIGHTS = {"cs": 0.20, "vdot": 0.25, "riegel": 0.25, "durability": 0.30}


# --------------------------------------------------------------------------- #
# Dati
# --------------------------------------------------------------------------- #
@dataclass
class Athlete:
    lthr: float = 175
    hrmax: float = 190
    rhr: float = 48
    vt1: float = 150                 # tetto Z2 Garmin corsa, usato come soglia aerobica
    lt_speed: Optional[float] = None  # m/s alla soglia secondo Garmin
    floors: list[float] = field(default_factory=list)


@dataclass
class Run:
    id: str
    day: date
    start: str
    name: str
    treadmill: bool
    steady: bool
    hilly: bool
    multisport: bool
    km: float
    moving_s: float
    speed: Optional[float]
    hr: Optional[float]
    dec: Optional[float]
    slow: Optional[float]
    tss: Optional[float]
    stream: list[dict]
    splits: list[dict]
    hr_bins: list[dict]
    ascent_m: Optional[float] = None      # dislivello positivo (Strava se disponibile)
    ascent_source: Optional[str] = None

    def best(self, minutes: int) -> Optional[tuple[float, Optional[float]]]:
        """Velocita' media (m/s) e FC media del miglior tratto di `minutes` minuti."""
        n = minutes * 2
        s = self.stream
        if len(s) <= n:
            return None
        best, hr = None, None
        for i in range(len(s) - n):
            a, b = s[i].get("dist_km"), s[i + n].get("dist_km")
            if a is None or b is None:
                continue
            d = b - a
            if best is None or d > best:
                best = d
                hs = [p["hr"] for p in s[i:i + n] if p.get("hr")]
                hr = float(np.mean(hs)) if len(hs) > n * 0.8 else None
        return (best * 1000 / (minutes * 60), hr) if best else None


def athlete(conn: sqlite3.Connection) -> Athlete:
    a = Athlete()
    zones = db.get_setting(conn, "hr_zones") or []
    z = next((x for x in zones if x.get("sport") == "RUNNING"), None) or next(
        (x for x in zones if x.get("sport") == "DEFAULT"), None)
    if z:
        a.lthr = z.get("lactateThresholdHeartRateUsed") or a.lthr
        a.hrmax = z.get("maxHeartRateUsed") or a.hrmax
        a.rhr = z.get("restingHeartRateUsed") or a.rhr
        a.floors = [z[f"zone{i}Floor"] for i in range(1, 6)]
        a.vt1 = z.get("zone3Floor") or a.vt1
    lt = (db.get_setting(conn, "lactate_threshold") or {}).get("speed_and_heart_rate") or {}
    if lt.get("speed"):
        a.lt_speed = float(lt["speed"]) * 10      # Garmin la salva in decimi di m/s
    r = conn.execute("SELECT AVG(rhr) v FROM (SELECT rhr FROM wellness_daily WHERE rhr IS NOT NULL "
                     "ORDER BY date DESC LIMIT 30)").fetchone()
    if r and r["v"]:
        a.rhr = float(r["v"])
    return a


def load_runs(conn: sqlite3.Connection) -> list[Run]:
    q = ("SELECT activity_id, parent_id, start_local, name, tss, metrics_json FROM activities "
         "WHERE sport='run' AND is_parent=0 AND duplicate_of IS NULL AND metrics_json IS NOT NULL "
         "ORDER BY start_local")
    out = []
    for r in conn.execute(q):
        res = json.loads(r["metrics_json"])
        m = res.get("metrics", {})
        if not m.get("avg_speed_ms"):
            continue
        out.append(Run(
            id=str(r["activity_id"]), day=date.fromisoformat(r["start_local"][:10]), start=r["start_local"],
            name=r["name"] or "", treadmill=bool(m.get("treadmill")), steady=bool(m.get("steady")),
            hilly=bool(m.get("hilly")), multisport=r["parent_id"] is not None,
            km=m.get("distance_km") or 0, moving_s=m.get("moving_time_s") or 0, speed=m.get("avg_speed_ms"),
            hr=m.get("avg_hr"), dec=m.get("decoupling_pct"), slow=m.get("split_slowdown_pct"), tss=r["tss"],
            stream=res.get("stream", []), splits=res.get("splits", []), hr_bins=res.get("hr_bins", []),
            ascent_m=m.get("ascent_m"), ascent_source=m.get("ascent_source"),
        ))
    return out


# --------------------------------------------------------------------------- #
# Formule
# --------------------------------------------------------------------------- #
def vo2_cost(v_mpm: float) -> float:
    """Costo in ml/kg/min alla velocita' v (m/min), Daniels-Gilbert."""
    return -4.60 + 0.182258 * v_mpm + 0.000104 * v_mpm ** 2


def pct_max(t_min: float) -> float:
    """Frazione di VO2max sostenibile per t minuti, Daniels-Gilbert."""
    return 0.8 + 0.1894393 * math.exp(-0.012778 * t_min) + 0.2989558 * math.exp(-0.1932605 * t_min)


def vdot(dist_m: float, t_s: float) -> float:
    t = t_s / 60
    return vo2_cost(dist_m / t) / pct_max(t)


def time_for_vdot(vd: float, dist_m: float) -> float:
    lo, hi = dist_m / 7.0, dist_m / 1.5
    for _ in range(60):
        mid = (lo + hi) / 2
        if vdot(dist_m, mid) > vd:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def speed_at_vo2(vo2: float) -> float:
    """Velocita' (m/s) il cui costo e' vo2 ml/kg/min."""
    a, b, c = 0.000104, 0.182258, -(4.60 + vo2)
    return (-b + math.sqrt(b * b - 4 * a * c)) / (2 * a) / 60


def riegel(t1: float, d1: float, d2: float, k: float) -> float:
    return t1 * (d2 / d1) ** k


def cs_fraction(hours: float) -> float:
    """Frazione della CS sostenibile per la durata (maratona ~0.85, Smyth & Muniz-Pumares 2020)."""
    return float(np.interp(hours, [0.25, 0.67, 1.5, 3.0, 4.0], [1.02, 0.97, 0.92, 0.85, 0.82]))


def fmt_time(s: Optional[float]) -> str:
    if s is None:
        return "-"
    s = int(round(s))
    return f"{s // 3600}:{s % 3600 // 60:02d}:{s % 60:02d}"


def fmt_pace(s: Optional[float]) -> str:
    if s is None:
        return "-"
    s = int(round(s))
    return f"{s // 60}:{s % 60:02d}"


# --------------------------------------------------------------------------- #
# Metodi
# --------------------------------------------------------------------------- #
def _efforts(runs: list[Run], ath: Athlete, min_minutes: int) -> list[dict]:
    """Prestazioni 'da gara': corse intere o tratti >= min_minutes con FC >= 90% della soglia."""
    out = []
    for r in runs:
        if r.treadmill:
            continue
        k = OFF_BIKE_FACTOR if r.multisport else 1.0
        if r.steady and r.hr and r.hr >= 0.9 * ath.lthr and r.moving_s >= min_minutes * 60 and r.km >= 3:
            out.append({"run": r, "dist": r.km * 1000, "t": r.moving_s * k, "what": "corsa intera"})
        for m in EFFORT_DURATIONS:
            if m < min_minutes or m * 60 > r.moving_s * 0.95:
                continue
            b = r.best(m)
            if b and b[1] and b[1] >= 0.9 * ath.lthr:
                out.append({"run": r, "dist": b[0] * m * 60, "t": m * 60 * k, "what": f"miglior {m}'"})
    return out


def _method_cs(season: list[Run], goal_m: float, as_of: date) -> Optional[dict]:
    pts = []
    for m in CS_DURATIONS:
        cands = [(r.best(m), r) for r in season if not r.treadmill]
        cands = [(b[0], r) for b, r in cands if b]
        if cands:
            v, r = max(cands, key=lambda x: x[0])
            pts.append((m * 60, v * m * 60, r))
    if len(pts) < 3:
        return None
    t = np.array([p[0] for p in pts], float)
    d = np.array([p[1] for p in pts], float)
    cs, dprime = np.polyfit(t, d, 1)
    if not (2.5 < cs < 7.0) or dprime < 0:
        return None
    pred = d - (cs * t + dprime)
    r2 = 1 - (pred ** 2).sum() / ((d - d.mean()) ** 2).sum()
    tt = goal_m / (cs * 0.85)
    for _ in range(5):
        tt = goal_m / (cs * cs_fraction(tt / 3600))
    sessions = {p[2].id for p in pts}
    recent_hard = any((as_of - p[2].day).days <= 42 for p in pts)
    conf = min(1.0, len(pts) / 5) * (1.0 if len(sessions) >= 2 else 0.7) * (1.0 if recent_hard else 0.7)
    conf *= 1.0 if r2 >= 0.98 else 0.8
    return {"key": "cs", "name": "Velocita' critica", "evidence": "EMERGENTE", "time_s": tt, "conf": conf,
            "detail": f"CS {fmt_pace(1000 / cs)}/km, D' {dprime:.0f} m da {len(pts)} migliori sforzi 3-20' "
                      f"(16 settimane, outdoor, R² {r2:.3f}); gara a {cs_fraction(tt / 3600) * 100:.0f}% della CS"}


def _hr_vdot(recent: list[Run], ath: Athlete) -> list[tuple[date, float]]:
    out = []
    for r in recent:
        if r.treadmill or r.hilly or not r.steady or not (25 * 60 <= r.moving_s <= 100 * 60):
            continue
        s = r.stream[10:]          # salta i primi 5 minuti
        hs = [p["hr"] for p in s if p.get("hr")]
        if len(s) < 30 or len(hs) < 0.8 * len(s) or s[-1].get("dist_km") is None or s[0].get("dist_km") is None:
            continue
        v = (s[-1]["dist_km"] - s[0]["dist_km"]) * 1000 / (len(s) * 30) * 60     # m/min
        hrr = (np.mean(hs) - ath.rhr) / (ath.hrmax - ath.rhr)
        if 0.55 <= hrr <= 0.92:
            out.append((r.day, 3.5 + (vo2_cost(v) - 3.5) / hrr))
    return out


def _method_vdot(season: list[Run], recent: list[Run], ath: Athlete, prof: RunProfile, goal_m: float) -> Optional[dict]:
    effs = _efforts(season, ath, prof.min_effort_min)
    race = max(effs, key=lambda e: vdot(e["dist"], e["t"]), default=None)
    race_v = vdot(race["dist"], race["t"]) if race else None
    hr_list = _hr_vdot(recent, ath)[-8:]
    hr_v = float(np.median([v for _, v in hr_list])) if len(hr_list) >= 3 else None
    if race_v is None and hr_v is None:
        return None
    if race_v is not None and hr_v is not None:
        v, conf = 0.4 * race_v + 0.6 * hr_v, 1.0
    else:
        v, conf = (race_v or hr_v), 0.65
    parts = []
    if race_v is not None:
        r = race["run"]
        parts.append(f"da prestazione {race_v:.1f} ({race['what']} del {r.day:%d/%m}, "
                     f"{race['dist'] / 1000:.1f} km a {fmt_pace(race['t'] / race['dist'] * 1000)}/km"
                     f"{', corretta per la bici' if r.multisport else ''})")
    if hr_v is not None:
        parts.append(f"da FC {hr_v:.1f} (mediana di {len(hr_list)} corse continue recenti)")
    return {"key": "vdot", "name": "VDOT (Daniels)", "evidence": "CONSOLIDATO", "time_s": time_for_vdot(v, goal_m),
            "conf": conf, "vdot": v, "detail": f"VDOT {v:.1f}: " + "; ".join(parts)}


def _long_runs(runs: list[Run], as_of: date, days: int = 56) -> list[Run]:
    return [r for r in runs if (as_of - r.day).days < days and (r.km >= 24 or r.moving_s >= 110 * 60)]


def _volume(runs: list[Run], as_of: date, weeks: int = 8) -> float:
    return sum(r.km for r in runs if 0 <= (as_of - r.day).days < weeks * 7) / weeks


def _method_riegel(season: list[Run], runs: list[Run], ath: Athlete, prof: RunProfile, goal_m: float,
                   as_of: date) -> Optional[dict]:
    effs = [e for e in _efforts(season, ath, 40) if e["dist"] >= min(15000, goal_m * 0.35)]
    if not effs:
        effs = [e for e in _efforts(season, ath, 30) if e["dist"] >= min(10000, goal_m * 0.25)]
    if not effs:
        return None
    k, why = 1.08, []
    longs = _long_runs(runs, as_of)
    good_longs = [r for r in longs if r.km >= 0.7 * prof.long_peak_km and (r.dec is None or r.dec < 5)]
    vol = _volume(runs, as_of)
    if prof.is_marathon:
        if len(good_longs) >= 2:
            k -= 0.01; why.append(f"{len(good_longs)} lunghi >= {0.7 * prof.long_peak_km:.0f} km con deriva < 5%")
        elif not longs:
            k += 0.015; why.append("nessun lungo >= 24 km in 8 settimane")
        if vol >= 60:
            k -= 0.005; why.append(f"volume {vol:.0f} km/sett")
        elif vol < 40:
            k += 0.01; why.append(f"volume solo {vol:.0f} km/sett")
    k = float(np.clip(k, 1.06, 1.11))
    best = min(effs, key=lambda e: riegel(e["t"], e["dist"], goal_m, k))
    t = riegel(best["t"], best["dist"], goal_m, k)
    r = best["run"]
    age = (as_of - r.day).days
    conf = (1.0 if best["dist"] >= 20000 else 0.8 if best["dist"] >= 15000 else 0.6) * (1.0 if age <= 56 else 0.75)
    return {"key": "riegel", "name": "Riegel adattato", "evidence": "EMERGENTE", "time_s": t, "conf": conf,
            "detail": f"da {best['dist'] / 1000:.1f} km in {fmt_time(best['t'])} ({best['what']} del {r.day:%d/%m}"
                      f"{', corretta per la bici' if r.multisport else ''}), esponente {k:.3f}"
                      + (f" ({'; '.join(why)})" if why else "")}


def race_hr(ath: Athlete, prof: RunProfile) -> float:
    """FC media attesa in gara (pratica da allenatore, in % della FC di soglia)."""
    return ath.lthr * (0.93 if prof.is_marathon else 0.97 if prof.distance_km > 20 else 1.0)


def _method_durability(recent: list[Run], runs: list[Run], ath: Athlete, prof: RunProfile, goal_m: float,
                       as_of: date) -> Optional[dict]:
    # relazione passo-FC "a fresco": corse sotto i 100', la fatica dei lunghi entra nella penalita'
    bins = [(b["hr_bin"], 1000 / b["pace_s"], b["seconds"]) for r in recent
            if not r.treadmill and not r.hilly and not r.multisport and r.moving_s <= 100 * 60
            for b in r.hr_bins if b.get("pace_s")]
    if len(bins) < 8 or len({b[0] for b in bins}) < 3:
        return None
    hr = np.array([b[0] for b in bins], float)
    sp = np.array([b[1] for b in bins], float)
    w = np.array([b[2] for b in bins], float)
    target = race_hr(ath, prof)
    if ath.lt_speed:
        # il rumore della FC appiattisce la regressione: retta tra il baricentro recente e la soglia Garmin
        hc, vc = np.average(hr, weights=w), np.average(sp, weights=w)
        slope = (ath.lt_speed - vc) / (ath.lthr - hc)
        icpt = vc - slope * hc
        how = f"retta tra {len(bins)} fasce passo-FC recenti e la soglia Garmin {fmt_pace(1000 / ath.lt_speed)}/km @ {ath.lthr:.0f}"
    else:
        slope, icpt = np.polyfit(hr, sp, 1, w=np.sqrt(w))
        how = f"retta passo-FC su {len(bins)} fasce recenti"
    if slope <= 0:
        return None
    v = icpt + slope * target
    extrap = 0 if ath.lt_speed else target - hr.max()
    longs = _long_runs(runs, as_of)
    decs = [r.dec for r in longs if r.dec is not None]
    fades = [r.slow for r in longs if r.slow is not None]
    dec = float(np.mean(decs)) if decs else None
    fade = float(np.mean(fades)) if fades else None
    pen, why = (1.0, ["1% di base per la seconda meta'"]) if prof.is_marathon else (0.3, [])
    if dec is not None and dec > 0:
        pen += 0.4 * dec; why.append(f"deriva media nei lunghi {dec:+.1f}%")
    if fade is not None and fade > 0:
        pen += 0.3 * fade; why.append(f"calo di passo nei lunghi {fade:+.1f}%")
    # tratti veloci dentro i lunghi: FC rispetto a quella attesa a fresco allo stesso passo
    excess = []
    for r in longs:
        blk = fast_block(r)
        if blk:
            v_b, hr_b, n_km = blk
            exp_hr = (v_b - icpt) / slope
            excess.append((hr_b - exp_hr) * slope / v_b * 100)
    if excess:
        x = float(np.mean(excess[-3:]))
        # a meta' peso: in gara si arriva scaricati, ma la fatica dei primi 25 km sara' a ritmo gara
        pen += float(np.clip(0.5 * x, -1.0, 4.0))
        why.append(f"FC nei tratti veloci dei lunghi {'sopra' if x > 0 else 'sotto'} l'attesa a fresco "
                   f"({x:+.1f}% di velocita' equivalente)")
    longest = max((r.km for r in longs), default=0)
    if prof.is_marathon and longest < 28:
        pen += 1.5; why.append(f"lungo piu' lungo {longest:.0f} km")
    elif prof.is_marathon and len([r for r in longs if r.km >= 28]) < 2:
        pen += 0.5; why.append("un solo lungo >= 28 km")
    v *= 1 - pen / 100
    conf = (1.0 if len(bins) >= 20 else 0.75) * (1.0 if len(longs) >= 2 else 0.7) * (0.8 if extrap > 8 else 1.0)
    return {"key": "durability", "name": "Durability (FC gara + lunghi)", "evidence": "EMERGENTE",
            "time_s": goal_m / v, "conf": conf, "pen_pct": pen,
            "detail": f"passo a FC gara {target:.0f} bpm {fmt_pace(1000 / (icpt + slope * target))}/km "
                      f"({how}), penalita' {pen:.1f}%: " + ", ".join(why)}


# --------------------------------------------------------------------------- #
# Stima combinata
# --------------------------------------------------------------------------- #
def estimate(runs: list[Run], ath: Athlete, prof: RunProfile, as_of: date, window_start: date) -> Optional[dict]:
    goal_m = prof.distance_km * 1000
    hist = [r for r in runs if r.day <= as_of]
    season = [r for r in hist if (as_of - r.day).days < LOOKBACK_DAYS]
    recent = [r for r in hist if r.day >= max(window_start, as_of - timedelta(days=56))]
    if len([r for r in recent if not r.treadmill and r.steady]) < 4:
        recent = [r for r in hist if (as_of - r.day).days < 42]
    methods = [m for m in (
        _method_cs(season, goal_m, as_of),
        _method_vdot(season, recent, ath, prof, goal_m),
        _method_riegel(season, hist, ath, prof, goal_m, as_of),
        _method_durability(recent, hist, ath, prof, goal_m, as_of),
    ) if m]
    if not methods:
        return None
    med = float(np.median([m["time_s"] for m in methods]))
    for m in methods:
        m["weight"] = BASE_WEIGHTS[m["key"]] * m["conf"]
        m["outlier"] = abs(m["time_s"] / med - 1) > 0.05 and len(methods) >= 3
        if m["outlier"]:
            m["weight"] *= 0.5
    tot = sum(m["weight"] for m in methods)
    for m in methods:
        m["weight"] /= tot
    central = sum(m["time_s"] * m["weight"] for m in methods)
    sd = math.sqrt(sum(m["weight"] * (m["time_s"] - central) ** 2 for m in methods))
    core = [m["time_s"] for m in methods if not m["outlier"]] or [m["time_s"] for m in methods]
    spread = (max(core) - min(core)) / central

    # affidabilita' e fattori che la abbassano
    conf, factors = 100.0, []

    def hit(points: float, text: str) -> None:
        nonlocal conf
        conf -= points
        factors.append({"text": text, "impact": -round(points)})

    if len(methods) < 4:
        hit(8 * (4 - len(methods)), f"solo {len(methods)} metodi su 4 calcolabili")
    post = [r for r in hist if r.day >= window_start]
    if not any(r.hr and r.hr >= 0.9 * ath.lthr and not r.treadmill and r.moving_s >= 20 * 60 for r in post):
        hit(10, "nessuno sforzo massimale dopo l'obiettivo precedente: le prestazioni di riferimento vengono da prima")
    longs = _long_runs(hist, as_of)
    target_long = 0.85 * prof.long_peak_km
    n_long = len([r for r in longs if r.km >= target_long])
    if n_long == 0:
        hit(20, f"nessun lungo >= {target_long:.0f} km nelle ultime 8 settimane")
    elif n_long == 1:
        hit(10, f"un solo lungo >= {target_long:.0f} km nelle ultime 8 settimane")
    mp = central / prof.distance_km
    mp_blocks = sum(1 for r in longs if _block_km(r, mp - 10, mp + 10) >= 6)
    if prof.is_marathon and mp_blocks == 0:
        hit(10, "nessun tratto >= 6 km a passo maratona dentro i lunghi")
    weeks = (as_of - window_start).days / 7
    if weeks < 6:
        hit(min(15, (6 - weeks) * 3), f"blocco specifico breve: {weeks:.0f} settimane dall'obiettivo precedente")
    if spread > 0.06:
        hit(15, f"metodi discordanti: {spread * 100:.1f}% tra la stima piu' veloce e la piu' lenta")
    elif spread > 0.03:
        hit(7, f"metodi in parziale disaccordo ({spread * 100:.1f}%)")
    for m in methods:
        if m["outlier"]:
            hit(5, f"{m['name']} lontano dagli altri ({fmt_time(m['time_s'])}): peso dimezzato")
    tm = [r for r in post if r.treadmill]
    if post and len(tm) / len(post) > 0.4:
        hit(5, f"{len(tm)} corse su {len(post)} sul tapis roulant: velocita' meno affidabile")
    hit(5, "meteo e percorso del giorno di gara non noti")
    conf = max(5.0, conf)
    label = "alta" if conf >= 75 else "media" if conf >= 55 else "bassa"
    u = 0.012 + 0.025 * (1 - conf / 100)
    hw = math.sqrt((central * u) ** 2 + sd ** 2)
    return {
        "as_of": as_of.isoformat(), "central_s": central, "low_s": central - hw, "high_s": central + hw,
        "pace_s": central / prof.distance_km, "confidence": round(conf), "confidence_label": label,
        "spread_pct": spread * 100, "methods": methods, "factors": factors,
        "vdot": next((m["vdot"] for m in methods if m["key"] == "vdot"), None),
    }


def fast_block(r: Run, min_km: int = 5) -> Optional[tuple[float, float, int]]:
    """Blocco piu' lungo di km consecutivi almeno 10 s/km piu' veloci della mediana del lungo,
    dopo i primi 10 km: (velocita' m/s, FC media, km)."""
    sp = [s for s in r.splits if not s.get("partial") and s.get("pace_s") and s.get("hr")]
    if len(sp) < 15:
        return None
    med = float(np.median([s["pace_s"] for s in sp]))
    best, cur = [], []
    for s in sp:
        if s["km"] > 10 and s["pace_s"] <= med - 10:
            cur.append(s)
            best = cur if len(cur) > len(best) else best
        else:
            cur = []
    if len(best) < min_km:
        return None
    return (1000 / float(np.mean([s["pace_s"] for s in best])), float(np.mean([s["hr"] for s in best])), len(best))


def _block_km(r: Run, pace_lo: float, pace_hi: float) -> int:
    """Km consecutivi piu' lunghi con split nel range di passo dato."""
    best = cur = 0
    for s in r.splits:
        if not s.get("partial") and pace_lo <= (s.get("pace_s") or 0) <= pace_hi:
            cur += 1
            best = max(best, cur)
        else:
            cur = 0
    return best


def daily_estimates(runs: list[Run], ath: Athlete, prof: RunProfile, start: date, end: date,
                    window_start: date) -> list[dict]:
    out, d = [], start
    while d <= end:
        e = estimate(runs, ath, prof, d, window_start)
        if e:
            out.append(e)
        d += timedelta(days=1)
    return out
