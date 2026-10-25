"""
Analisi corsa con la griglia di un preparatore: sette sezioni, ciascuna con voto 0-100.

  Controllo intensita'   15  tempo nelle zone FC o nei target del workout
  Efficienza aerobica    20  deriva cardiaca (Pa:HR) + Efficiency Factor vs corse simili
  Gestione del ritmo     15  costanza nei lap e split; nelle ripetute regolarita' e tenuta
  Cadenza                10  livello rispetto alla velocita' e stabilita'
  Contatto al suolo      15  GCT rispetto alla velocita' attesa + simmetria sx/dx
  Rimbalzo verticale     10  rapporto verticale e oscillazione
  Resistenza alla fatica 15  ultimo terzo vs primo: cadenza, GCT, passo, oscillazione, costo cardiaco

Oltre al voto produce le serie per i grafici (ogni 30 s), gli split per km, il passo
per fascia di FC (passo a parita' di cuore) e le dinamiche per fascia di passo.
"""
from __future__ import annotations

from typing import Any, Optional

import numpy as np
import pandas as pd

from ..fitdata import FitSession
from .common import (
    AthleteContext, Component, SessionResult, adherence_component, cv, decoupling, halves,
    hr_tss, is_interval_session, lap_slice, lin, normalized_power, percentile_score, power_tss,
    rnd, time_in_zones, to_1hz, warmup_seconds, within_lap_cv,
)

MOVING_SPEED = 1.0          # m/s, sotto si considera camminata/sosta
MAX_PLAUSIBLE_IF = 1.3      # oltre, la potenza di corsa e' considerata non affidabile
STREAM_STEP_S = 30
HR_BIN = 5                  # bpm
PACE_BIN = 15               # s/km

W = {"intensity": 15, "efficiency": 20, "pacing": 15, "cadence": 10, "contact": 15, "vertical": 10, "fatigue": 15}


def _pace(speed: Optional[float]) -> str:
    if not speed or speed <= 0 or not np.isfinite(speed):
        return "-"
    sec = 1000 / speed
    return f"{int(sec // 60)}:{int(round(sec % 60)):02d}/km"


def _avg(vals: list[Optional[float]]) -> Optional[float]:
    v = [x for x in vals if x is not None]
    return float(np.mean(v)) if v else None


def _has(m: pd.DataFrame, col: str, share: float = 0.5) -> bool:
    return col in m and bool(m[col].notna().mean() > share)


def _thirds(m: pd.DataFrame, skip: int) -> tuple[pd.DataFrame, pd.DataFrame]:
    d = m.iloc[skip:]
    n = len(d) // 3
    return d.iloc[:n], d.iloc[-n:] if n else d.iloc[:0]


def _pct(a: float, b: float) -> Optional[float]:
    return (b / a - 1) * 100 if a and np.isfinite(a) and np.isfinite(b) else None


# --------------------------------------------------------------------------- #
# Sezioni
# --------------------------------------------------------------------------- #
def _efficiency(m, hr, has_hr, intervals, dur, skip, hilly, power_ok, treadmill, history, metrics) -> Component:
    parts, notes = [], []
    ef = (m["speed"].mean() * 60) / hr.mean() if has_hr else None
    metrics["ef_speed"] = rnd(ef, 3)
    if power_ok and has_hr:
        metrics["ef_power"] = rnd(m["power"].mean() / hr.mean(), 3)
    if not intervals and has_hr and dur >= 1800:
        channel = "power" if hilly and power_ok else "speed"
        dec = decoupling(m[channel], hr, skip)
        a, b = halves(hr.to_frame("v"), skip)
        metrics.update({"decoupling_pct": rnd(dec), "decoupling_channel": channel,
                        "hr_drift_bpm": rnd(b["v"].mean() - a["v"].mean())})
        if dec is not None:
            parts.append(lin(dec, [2, 5, 8, 12, 15], [100, 85, 60, 30, 10]))
            notes.append(f"deriva {dec:+.1f}%" + (" (potenza/FC)" if channel == "power" else ""))
    hist = [h.get("ef_speed") for h in history
            if h.get("steady") and h.get("treadmill") == treadmill and (h.get("moving_time_s") or 0) >= 1200]
    if not intervals:
        p = percentile_score(ef, hist)
        if p is not None:
            parts.append(p)
            notes.append(f"EF {ef:.2f} al {int((p - 20) / 0.8)}° percentile su {len(hist)} corse simili")
    if not parts:
        return Component("Efficienza aerobica", None, W["efficiency"], rnd(ef, 2),
                         "non valutabile: ripetute, corsa < 30 min o storico insufficiente")
    return Component("Efficienza aerobica", _avg(parts), W["efficiency"], rnd(ef, 2), "; ".join(notes))


def _pacing(sess, m, intervals, hilly, skip, metrics) -> Component:
    sp = m["speed"]
    if intervals:
        work = [l for l in sess.laps if (l.get("total_timer_time") or 0) >= 45
                and str(l.get("intensity", "active")) in ("active", "None", "interval")]
        speeds = [lap_slice(sp, l).mean() for l in work]
        speeds = [s for s in speeds if s and np.isfinite(s)]
        if len(speeds) >= 3:
            med = np.median(speeds)
            reps = [s for s in speeds if s >= med]
            c = cv(reps)
            if c is not None:      # servono almeno 3 ripetute veloci
                fade = (reps[0] / reps[-1] - 1) * 100
                metrics.update({"reps": len(reps), "reps_cv_pct": rnd(c * 100), "reps_fade_pct": rnd(fade)})
                sc = _avg([lin(c, [0.02, 0.04, 0.07, 0.12], [100, 85, 55, 20]), lin(fade, [1, 3, 6], [100, 70, 30])])
                return Component("Gestione del ritmo", sc, W["pacing"], metrics["reps_cv_pct"],
                                 f"{len(reps)} ripetute: variabilita' {c * 100:.1f}%, calo ultima vs prima {fade:+.1f}%")
    stab = within_lap_cv(sess, sp, only_work=intervals)
    metrics["pace_cv_pct"] = rnd(stab * 100 if stab is not None else None)
    pts = ([0.05, 0.08, 0.12, 0.18, 0.25], [100, 85, 60, 30, 5]) if hilly else ([0.03, 0.05, 0.08, 0.12, 0.18], [100, 85, 60, 30, 5])
    parts = [lin(stab, *pts)]
    note = f"variabilita' nei lap {stab * 100:.1f}%" if stab is not None else ""
    a, b = halves(sp.to_frame("v"), skip)
    if len(a) > 300 and not intervals:
        slow = (a["v"].mean() / b["v"].mean() - 1) * 100       # + = seconda meta' piu' lenta
        metrics["split_slowdown_pct"] = rnd(slow)
        parts.append(lin(slow, [-1, 1, 3, 6], [100, 95, 65, 25]))
        note += f"; {'split negativo' if slow < -0.5 else 'split pari' if slow <= 1 else 'seconda meta piu lenta'} ({slow:+.1f}%)"
    return Component("Gestione del ritmo", _avg(parts), W["pacing"], metrics["pace_cv_pct"], note.strip("; "))


def _cadence(m, steady_mask, metrics, dyn) -> Component:
    if not _has(m, "cadence"):
        return Component("Cadenza", None, W["cadence"], note="cadenza non registrata")
    frac = m["fractional_cadence"].fillna(0) if "fractional_cadence" in m else 0
    spm = 2 * (m["cadence"] + frac)          # nel FIT: passi di un piede al minuto
    cad, speed = float(spm.mean()), float(m["speed"].mean())
    ref = 150 + 8 * min(max(speed, 2.5), 6.0)  # cadenza attesa: cresce con la velocita'
    c = cv(spm[steady_mask].rolling(30, min_periods=15).mean())
    dyn.update({"cadence_spm": rnd(cad, 0), "cadence_ref_spm": rnd(ref, 0), "cadence_cv_pct": rnd(c * 100 if c else None)})
    level = lin(cad - ref, [-15, -8, -3, 0], [20, 55, 85, 100])
    stab = lin(c, [0.02, 0.04, 0.07], [100, 75, 40])
    return Component("Cadenza", _avg([0.7 * level + 0.3 * stab]) if stab is not None else level, W["cadence"], rnd(cad, 0),
                     f"{cad:.0f} passi/min, attesa ~{ref:.0f} a {_pace(speed)}" + (f"; variabilita' {c * 100:.1f}%" if c else ""))


def _contact(m, dyn) -> Component:
    if not _has(m, "stance_time"):
        return Component("Contatto al suolo", None, W["contact"], note="serve la fascia HRM-Pro/Run o il Running Dynamics Pod")
    gct, speed = float(m["stance_time"].mean()), float(m["speed"].mean())
    exp = 355 - 33 * min(max(speed, 2.5), 6.0)      # ~256 ms a 3 m/s, ~190 ms a 5 m/s
    ratio = gct / exp
    dyn.update({"gct_ms": rnd(gct, 0), "gct_expected_ms": rnd(exp, 0)})
    parts = [lin(ratio, [0.92, 1.0, 1.08, 1.16], [100, 85, 55, 25])]
    note = f"{gct:.0f} ms (atteso ~{exp:.0f} a questa velocita')"
    if _has(m, "stance_time_balance"):
        bal = float(m["stance_time_balance"].mean())
        dyn["gct_balance_left_pct"] = rnd(bal)
        parts = [0.7 * parts[0] + 0.3 * lin(abs(bal - 50), [0.5, 1.5, 3, 5], [100, 80, 40, 0])]
        note += f"; bilanciamento {bal:.1f}% sx / {100 - bal:.1f}% dx"
    if _has(m, "stance_time_percent"):
        dyn["stance_time_pct"] = rnd(m["stance_time_percent"].mean())
    return Component("Contatto al suolo", parts[0], W["contact"], rnd(gct, 0), note)


def _vertical(m, dyn) -> Component:
    vr = float(m["vertical_ratio"].mean()) if _has(m, "vertical_ratio") else None
    vo = float(m["vertical_oscillation"].mean()) / 10 if _has(m, "vertical_oscillation") else None
    if _has(m, "step_length"):
        dyn["step_length_m"] = rnd(m["step_length"].mean() / 1000, 2)
    if vr is None and vo is None:
        return Component("Rimbalzo verticale", None, W["vertical"], note="dinamiche non registrate")
    dyn.update({"vertical_ratio_pct": rnd(vr), "vertical_oscillation_cm": rnd(vo)})
    s_vr = lin(vr, [6, 7.5, 9, 10.5, 12], [100, 85, 60, 35, 15])
    s_vo = lin(vo, [6.5, 8, 9.5, 11], [100, 80, 50, 20])
    sc = 0.6 * s_vr + 0.4 * s_vo if s_vr is not None and s_vo is not None else (s_vr if s_vr is not None else s_vo)
    return Component("Rimbalzo verticale", sc, W["vertical"], rnd(vr),
                     " · ".join(x for x in (f"rapporto verticale {vr:.1f}%" if vr else "",
                                            f"oscillazione {vo:.1f} cm" if vo else "") if x))


def _fatigue(m, hr, has_hr, intervals, dur, skip, dyn) -> Component:
    if dur < 1500:
        return Component("Resistenza alla fatica", None, W["fatigue"], note="corsa sotto i 25 minuti")
    d = m
    if intervals:      # nelle ripetute si confrontano solo i tratti veloci
        d = m[m["speed"] >= m["speed"].quantile(0.6)]
    a, b = _thirds(d, 0 if intervals else skip)
    if len(a) < 120:
        return Component("Resistenza alla fatica", None, W["fatigue"], note="dati insufficienti")
    parts, notes, ch = [], [], {}
    if _has(d, "cadence"):
        x = _pct(a["cadence"].mean(), b["cadence"].mean())
        ch["cadence"] = x
        parts.append(lin(-x, [1, 3, 6], [100, 70, 30])); notes.append(f"cadenza {x:+.1f}%")
    if _has(d, "stance_time"):
        x = _pct(a["stance_time"].mean(), b["stance_time"].mean())
        ch["gct"] = x
        parts.append(lin(x, [1, 3, 6], [100, 70, 30])); notes.append(f"contatto {x:+.1f}%")
    if _has(d, "step_length"):
        x = _pct(a["step_length"].mean(), b["step_length"].mean())
        ch["step_length"] = x
        parts.append(lin(-x, [1, 3, 6], [100, 70, 30])); notes.append(f"passo {x:+.1f}%")
    if _has(d, "vertical_oscillation"):
        x = _pct(a["vertical_oscillation"].mean(), b["vertical_oscillation"].mean())
        ch["vertical_oscillation"] = x
        parts.append(lin(x, [2, 5, 10], [100, 70, 30])); notes.append(f"oscillazione {x:+.1f}%")
    if has_hr:
        ea = a["speed"].mean() / a["heart_rate"].mean()
        eb = b["speed"].mean() / b["heart_rate"].mean()
        x = _pct(ea, eb)
        ch["speed_per_beat"] = x
        parts.append(lin(-x, [2, 5, 10], [100, 70, 30])); notes.append(f"metri per battito {x:+.1f}%")
    dyn["fatigue_change_pct"] = {k: rnd(v) for k, v in ch.items()}
    parts = [p for p in parts if p is not None]
    return Component("Resistenza alla fatica", _avg(parts), W["fatigue"], None,
                     "ultimo terzo vs primo: " + ", ".join(notes))


# --------------------------------------------------------------------------- #
# Serie per i grafici
# --------------------------------------------------------------------------- #
def _derived(m: pd.DataFrame) -> pd.DataFrame:
    out = pd.DataFrame(index=m.index)
    out["t"] = np.arange(len(m))
    out["speed"] = m["speed"]
    if "distance" in m and m["distance"].notna().any():
        dist = m["distance"].ffill().bfill()
        out["dist_km"] = (dist - dist.iloc[0]) / 1000
    else:
        out["dist_km"] = m["speed"].cumsum() / 1000
    for src, dst, k in (("heart_rate", "hr", 1), ("stance_time", "gct", 1), ("vertical_ratio", "vr", 1),
                        ("vertical_oscillation", "vo", 0.1), ("step_length", "step", 0.001),
                        ("power", "power", 1), ("altitude", "alt", 1), ("stance_time_balance", "gct_bal", 1)):
        if src in m:
            out[dst] = m[src] * k
    if "cadence" in m:
        out["cad"] = 2 * (m["cadence"] + (m["fractional_cadence"].fillna(0) if "fractional_cadence" in m else 0))
    return out


def _stream(d: pd.DataFrame) -> list[dict]:
    g = d.groupby(d["t"] // STREAM_STEP_S)
    agg = g.mean(numeric_only=True)
    agg["dist_km"] = g["dist_km"].last()
    agg["t_min"] = g["t"].first() / 60
    agg["pace_s"] = 1000 / agg["speed"].where(agg["speed"] > MOVING_SPEED)
    cols = [c for c in ("t_min", "dist_km", "pace_s", "hr", "cad", "gct", "vo", "vr", "step", "power", "alt", "gct_bal")
            if c in agg]
    return [{c: rnd(r[c], 3 if c in ("dist_km", "step") else 2 if c == "gct_bal" else 1) for c in cols}
            for _, r in agg.iterrows()]


def _splits(d: pd.DataFrame, altitude_ok: bool) -> list[dict]:
    rows = []
    km = d["dist_km"].clip(lower=0).astype(float).apply(np.floor).astype(int)
    alt = d["alt"].rolling(15, min_periods=1).mean() if "alt" in d and altitude_ok else None
    for k, g in d.groupby(km):
        meters = (g["dist_km"].iloc[-1] - g["dist_km"].iloc[0]) * 1000
        if meters < 200:
            continue
        r = {"km": int(k) + 1, "partial": bool(meters < 950), "pace_s": rnd(len(g) / meters * 1000, 1)}
        for c in ("hr", "cad", "gct", "vo", "vr", "step", "power"):
            if c in g and g[c].notna().any():
                r[c] = rnd(g[c].mean(), 3 if c == "step" else 1)
        if alt is not None:
            diff = alt.loc[g.index].diff()
            r["elev_gain_m"] = rnd(diff.clip(lower=0).sum(), 0)
        rows.append(r)
    return rows


def _hr_bins(d: pd.DataFrame, skip: int) -> list[dict]:
    """Passo a parita' di FC: velocita' media in ogni fascia di 5 bpm (min 3 minuti)."""
    if "hr" not in d:
        return []
    x = d.iloc[skip:].assign(sp=d["speed"].rolling(30, min_periods=15).mean()).dropna(subset=["hr", "sp"])
    x = x[x["sp"] > MOVING_SPEED]
    out = []
    for b, g in x.groupby((x["hr"] / HR_BIN).round() * HR_BIN):
        if len(g) >= 180:
            out.append({"hr_bin": int(b), "pace_s": rnd(1000 / g["sp"].mean(), 1), "seconds": len(g)})
    return out


def _pace_bins(d: pd.DataFrame) -> list[dict]:
    """Dinamiche a parita' di passo: medie in fasce di 15 s/km (min 2 minuti)."""
    sp = d["speed"].rolling(10, min_periods=5).mean()
    pace = 1000 / sp.where(sp > MOVING_SPEED)
    x = d.assign(pace=pace).dropna(subset=["pace"])
    x = x[(x["pace"] >= 180) & (x["pace"] < 450)]
    out = []
    for b, g in x.groupby((x["pace"] // PACE_BIN) * PACE_BIN):
        if len(g) < 120:
            continue
        r = {"pace_bin": int(b), "seconds": len(g)}
        for c in ("hr", "cad", "gct", "vo", "vr", "step"):
            if c in g and g[c].notna().mean() > 0.5:
                r[c] = rnd(g[c].mean(), 3 if c == "step" else 1)
        out.append(r)
    return out


# --------------------------------------------------------------------------- #
def analyze_run(sess: FitSession, ctx: AthleteContext, history: list[dict]) -> SessionResult:
    treadmill = sess.sub_sport in ("treadmill", "indoor_running", "virtual_activity")
    df = to_1hz(sess, ["heart_rate", "speed", "distance", "power", "cadence", "fractional_cadence", "altitude",
                       "stance_time", "stance_time_balance", "stance_time_percent", "vertical_oscillation",
                       "vertical_ratio", "step_length"])
    if df.empty or "speed" not in df:
        return SessionResult("run", {"error": "nessun dato di velocita'"}, [], None, "-", 0)

    m = df[df["speed"] > MOVING_SPEED]
    dur = len(m)
    s = sess.summary
    dist = float(s.get("total_distance") or 0)
    hr = m["heart_rate"] if "heart_rate" in m else pd.Series(dtype=float)
    has_hr = bool(hr.notna().mean() > 0.8) if len(hr) else False
    intervals = is_interval_session(sess, "avg_speed")
    skip = warmup_seconds(dur)

    # dislivello di riferimento: Strava se disponibile (il barometro dell'orologio sbaglia anche in piano)
    garmin_ascent = float(s.get("total_ascent") or 0)
    strava_ascent = s.get("strava_ascent_m")
    ascent = garmin_ascent if strava_ascent is None else float(strava_ascent)
    ascent_km = 0.0 if treadmill else ascent / max(dist / 1000, 0.1)
    if strava_ascent is None:
        altitude_ok = (not treadmill) and ascent_km < 80      # oltre: barometro inaffidabile
        hilly = altitude_ok and ascent_km > 20
    else:
        # quota dell'orologio (grafico, dislivello per km) solo se il suo totale torna con Strava
        altitude_ok = (not treadmill) and abs(garmin_ascent - ascent) <= max(25.0, 0.3 * ascent)
        hilly = (not treadmill) and ascent_km > 20

    np_w = None
    power_ok = bool("power" in m and m["power"].gt(0).mean() > 0.8)
    if power_ok:
        np_w = normalized_power(m["power"])
        if ctx.ftp_run and np_w and np_w / ctx.ftp_run > MAX_PLAUSIBLE_IF and dur > 1200:
            power_ok = False

    metrics: dict[str, Any] = {
        "treadmill": treadmill, "steady": not intervals, "moving_time_s": dur,
        "distance_km": rnd(dist / 1000, 2), "avg_pace": _pace(m["speed"].mean()),
        "avg_speed_ms": rnd(m["speed"].mean(), 3), "avg_hr": rnd(hr.mean(), 0) if has_hr else None,
        "max_hr": rnd(hr.max(), 0) if has_hr else None,
        "ascent_m_per_km": rnd(ascent_km, 1), "altitude_reliable": altitude_ok, "hilly": hilly,
        "ascent_m": None if treadmill else rnd(ascent, 0), "ascent_garmin_m": None if treadmill else rnd(garmin_ascent, 0),
        "ascent_source": None if treadmill else "strava" if strava_ascent is not None else "garmin",
        "avg_power": rnd(m["power"].mean(), 0) if power_ok else None,
        "normalized_power": rnd(np_w, 0) if power_ok else None,
        "power_reliable": power_ok if "power" in m else None,
    }
    floors = ctx.hr_floors("RUNNING")
    if has_hr and floors:
        metrics["hr_zone_pct"] = [rnd(z * 100) for z in time_in_zones(hr, floors)]
        metrics["hr_zone_floors"] = floors

    dyn: dict[str, Any] = {}
    steady_mask = m["speed"] > 0 if not intervals else m["speed"] >= m["speed"].quantile(0.6)
    comps = [
        adherence_component(sess, m, ctx, "run", "heart_rate", floors, skip, W["intensity"]),
        _efficiency(m, hr, has_hr, intervals, dur, skip, hilly, power_ok, treadmill, history, metrics),
        _pacing(sess, m, intervals, hilly, skip, metrics),
        _cadence(m, steady_mask, metrics, dyn),
        _contact(m, dyn),
        _vertical(m, dyn),
        _fatigue(m, hr, has_hr, intervals, dur, skip, dyn),
    ]
    comps[0].name = "Controllo intensita'"
    metrics["dynamics"] = dyn

    d = _derived(m)
    extra = {
        "stream": _stream(d),
        "splits": _splits(d, altitude_ok),
        "hr_bins": _hr_bins(d, skip) if (not intervals and not hilly) else [],
        "pace_bins": _pace_bins(d),
    }

    # Carico da FC: la potenza di corsa da polso ha picchi (vento, salti di quota) che con la
    # potenza normalizzata gonfiano il TSS; la stima da potenza resta solo informativa.
    tss, method = hr_tss(dur, hr.mean() if has_hr else None, ctx, ctx.lthr_run), "hrTSS"
    if power_ok and ctx.ftp_run:
        metrics["power_tss_info"] = rnd(power_tss(dur, float(m["power"].mean()), ctx.ftp_run))
    if tss is None and power_ok and ctx.ftp_run:
        tss, method = power_tss(dur, float(m["power"].mean()), ctx.ftp_run), "rTSS potenza media"
    return SessionResult("run", metrics, comps, rnd(tss), method, dur, extra)
