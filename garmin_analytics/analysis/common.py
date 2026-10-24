"""Funzioni di calcolo condivise tra gli sport."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional, Sequence

import numpy as np
import pandas as pd

from ..fitdata import FitSession

MAX_GAP_FILL_S = 10         # smart recording registra ogni 1-8 s; buchi piu' lunghi = pausa, esclusi


# --------------------------------------------------------------------------- #
# Contesto atleta e risultato
# --------------------------------------------------------------------------- #
@dataclass
class AthleteContext:
    ftp_bike: Optional[float] = None
    ftp_run: Optional[float] = None
    lthr_run: Optional[float] = None
    lthr_bike: Optional[float] = None
    max_hr: Optional[float] = None
    rhr: Optional[float] = None
    css_sec_100m: Optional[float] = None
    hr_zones: dict[str, list[float]] = field(default_factory=dict)      # sport -> floor Z1..Z5
    power_zones: dict[str, list[float]] = field(default_factory=dict)   # sport -> floor Z1..Z7

    def hr_floors(self, sport: str) -> Optional[list[float]]:
        return self.hr_zones.get(sport) or self.hr_zones.get("DEFAULT")


@dataclass
class Component:
    """Una voce del punteggio: valore misurato, punteggio 0-100 e peso."""
    name: str
    score: Optional[float]
    weight: float
    value: Any = None
    note: str = ""


@dataclass
class SessionResult:
    sport: str
    metrics: dict[str, Any]
    components: list[Component]
    tss: Optional[float]
    tss_method: str
    duration_s: float
    extra: dict[str, Any] = field(default_factory=dict)   # serie per i grafici, non usate nello storico

    @property
    def score(self) -> Optional[int]:
        return weighted_score(self.components)

    @property
    def confidence(self) -> float:
        """Quota del peso totale coperta da componenti calcolabili (1 = voto completo)."""
        total = sum(c.weight for c in self.components)
        return round(sum(c.weight for c in self.components if c.score is not None) / total, 2) if total else 0.0


# --------------------------------------------------------------------------- #
# Serie temporali
# --------------------------------------------------------------------------- #
def to_1hz(sess: FitSession, cols: Sequence[str]) -> pd.DataFrame:
    """
    Serie a 1 Hz dei canali richiesti, senza le pause.

    Buchi <= MAX_GAP_FILL_S secondi vengono riempiti (smart recording / perdita
    di segnale); buchi piu' lunghi sono pause e vengono rimossi.
    """
    rec = sess.records
    cols = [c for c in cols if c in rec]
    if rec.empty or not cols:
        return pd.DataFrame(columns=cols)
    s = rec.set_index("timestamp")[cols].apply(pd.to_numeric, errors="coerce")
    s = s.resample("1s").mean()
    present = s.notna().any(axis=1)
    run_len = present.groupby((present != present.shift()).cumsum()).transform("size")
    short_gap = ~present & (run_len <= MAX_GAP_FILL_S)
    s = s.ffill(limit=MAX_GAP_FILL_S)
    return s[present | short_gap]


def halves(df: pd.DataFrame, skip_s: int = 0) -> tuple[pd.DataFrame, pd.DataFrame]:
    d = df.iloc[skip_s:]
    mid = len(d) // 2
    return d.iloc[:mid], d.iloc[mid:]


def warmup_seconds(duration_s: float) -> int:
    """Riscaldamento escluso da deriva/decoupling: 15% della durata, max 10 min."""
    return int(min(600, 0.15 * duration_s)) if duration_s >= 1200 else 0


def decoupling(output: pd.Series, hr: pd.Series, skip_s: int) -> Optional[float]:
    """
    Aerobic decoupling (Friel): variazione % del rapporto output/FC tra prima e
    seconda meta'. Positivo = la FC sale a parita' di output (deriva cardiaca).
    """
    df = pd.DataFrame({"o": output, "h": hr}).dropna()
    df = df[(df["h"] > 40) & (df["o"] > 0)]
    if len(df) < 1200:
        return None
    a, b = halves(df, skip_s)
    ef1, ef2 = a["o"].mean() / a["h"].mean(), b["o"].mean() / b["h"].mean()
    return float((ef1 - ef2) / ef1 * 100)


def normalized_power(power: pd.Series) -> Optional[float]:
    p = power.fillna(0)
    if len(p) < 60:
        return None
    rolled = p.rolling(30, min_periods=30).mean().dropna()
    return float((rolled ** 4).mean() ** 0.25)


def mean_max(series: pd.Series, durations: Sequence[int]) -> dict[int, float]:
    s = series.fillna(0)
    return {d: float(s.rolling(d).mean().max()) for d in durations if len(s) >= d}


def time_in_zones(values: pd.Series, floors: Sequence[float]) -> list[float]:
    """Frazione di tempo per zona dati i limiti inferiori (Z1 floor ... Zn floor)."""
    v = values.dropna()
    if v.empty:
        return [0.0] * len(floors)
    idx = np.clip(np.searchsorted(np.asarray(floors[1:], dtype=float), v.to_numpy(), side="right"), 0, len(floors) - 1)
    counts = np.bincount(idx, minlength=len(floors))
    return (counts / counts.sum()).tolist()


def cv(x: pd.Series | Sequence[float]) -> Optional[float]:
    a = pd.Series(x, dtype=float).dropna()
    if len(a) < 3 or a.mean() == 0:
        return None
    return float(a.std() / a.mean())


# --------------------------------------------------------------------------- #
# Aderenza alle zone
# --------------------------------------------------------------------------- #
def _decode_target(step: dict, kind: str, ctx: AthleteContext, sport: str) -> Optional[tuple[float, float]]:
    """Converte il target di uno step di workout FIT in (min, max) nell'unita' del canale."""
    lo = next((step[k] for k in (f"custom_target_{kind}_low", "custom_target_value_low") if step.get(k)), None)
    hi = next((step[k] for k in (f"custom_target_{kind}_high", "custom_target_value_high") if step.get(k)), None)
    if lo is None or hi is None:
        return None
    lo, hi = float(lo), float(hi)
    if kind == "heart_rate":
        # FIT: >100 = bpm + 100, <=100 = % FC max
        conv = (lambda v: v - 100) if lo > 100 else (lambda v: v / 100 * (ctx.max_hr or 190))
        return conv(lo), conv(hi)
    if kind == "power":
        ftp = ctx.ftp_bike if sport == "bike" else ctx.ftp_run
        conv = (lambda v: v - 1000) if lo > 1000 else (lambda v: v / 100 * (ftp or 250))
        return conv(lo), conv(hi)
    if kind == "speed":
        scale = 1000 if lo > 50 else 1     # valore grezzo in mm/s se non gia' scalato
        return lo / scale, hi / scale
    return None


def workout_adherence(sess: FitSession, df: pd.DataFrame, ctx: AthleteContext, sport: str) -> Optional[float]:
    """% di tempo dentro il target, per ogni lap associato a uno step di workout con target."""
    if not sess.workout_steps:
        return None
    steps = {s.get("message_index", i): s for i, s in enumerate(sess.workout_steps)}
    channel = {"heart_rate": "heart_rate", "power": "power", "speed": "speed"}
    inside = total = 0
    for lap in sess.laps:
        step = steps.get(lap.get("wkt_step_index"))
        if not step:
            continue
        kind = str(step.get("target_type", ""))
        col = channel.get(kind)
        rng = _decode_target(step, kind, ctx, sport) if col else None
        if not rng or col not in df:
            continue
        seg = lap_slice(df[col], lap).dropna()
        if col != "heart_rate":
            seg = seg.rolling(10, min_periods=1).mean()   # potenza/passo: media 10 s come sul device
        inside += int(((seg >= rng[0]) & (seg <= rng[1])).sum())
        total += len(seg)
    return inside / total if total >= 300 else None


def inferred_adherence(values: pd.Series, floors: Sequence[float], skip_s: int) -> Optional[tuple[float, int]]:
    """
    Senza workout strutturato l'intensita' voluta non e' nota: si misura quanto
    e' stata tenuta, come quota di tempo nelle due zone contigue piu' usate
    (robusto quando la FC media cade sul confine tra due zone).
    Ritorna (quota, zona inferiore della coppia 1-based).
    """
    v = values.iloc[skip_s:].dropna()
    if len(v) < 300 or not floors:
        return None
    tiz = time_in_zones(v, floors)
    pairs = [tiz[i] + tiz[i + 1] for i in range(len(tiz) - 1)]
    best = int(np.argmax(pairs))
    return pairs[best], best + 1


def adherence_component(sess: FitSession, df: pd.DataFrame, ctx: AthleteContext, sport: str,
                        col: str, floors: Optional[Sequence[float]], skip_s: int, weight: float) -> Component:
    pts = ([0.4, 0.6, 0.8, 0.92], [10, 45, 85, 100])
    share = workout_adherence(sess, df, ctx, sport)
    if share is not None:
        return Component("Aderenza target workout", lin(share, *pts), weight, round(share * 100, 1),
                         "% di tempo nel target degli step")
    if floors and col in df:
        res = inferred_adherence(df[col], floors, skip_s)
        if res:
            share, z = res
            return Component("Aderenza zone", lin(share, *pts), weight, round(share * 100, 1),
                             f"% tempo in Z{z}-Z{z + 1} (coppia di zone piu' usata)")
    return Component("Aderenza zone", None, weight, note="zone non disponibili")


# --------------------------------------------------------------------------- #
# Lap e intervalli
# --------------------------------------------------------------------------- #
def is_interval_session(sess: FitSession, value_key: str = "avg_speed", max_lap_cv: float = 0.15) -> bool:
    """Workout strutturato, lap di recupero o forte variabilita' tra lap = sessione a intervalli."""
    if sess.workout_steps and len(sess.workout_steps) > 2:
        return True
    if any(str(l.get("intensity")) in ("rest", "recovery") for l in sess.laps):
        return True
    vals = [l.get(value_key) or l.get(f"enhanced_{value_key}") for l in sess.laps
            if (l.get("total_timer_time") or 0) >= 60]
    vals = [v for v in vals if v]
    return len(vals) >= 4 and (cv(vals) or 0) > max_lap_cv


def lap_slice(series: pd.Series | pd.DataFrame, lap: dict) -> pd.Series | pd.DataFrame:
    start = pd.Timestamp(lap["start_time"])
    return series.loc[start:start + pd.Timedelta(seconds=float(lap.get("total_elapsed_time") or 0))]


def within_lap_cv(sess: FitSession, series: pd.Series, only_work: bool, smooth_s: int = 30) -> Optional[float]:
    """CV medio (pesato per durata) della serie lisciata all'interno di ogni lap."""
    sm = series.rolling(smooth_s, min_periods=smooth_s // 2).mean()
    laps = [l for l in sess.laps if (l.get("total_timer_time") or 0) >= 90]
    if only_work:
        laps = [l for l in laps if str(l.get("intensity", "active")) in ("active", "None", "interval")]
        if laps:
            means = [lap_slice(sm, l).mean() for l in laps]
            med = np.nanmedian(means)
            laps = [l for l, m in zip(laps, means) if m >= med]   # solo le ripetute "forti"
    if not laps:
        return cv(sm)
    acc = wsum = 0.0
    for l in laps:
        seg = lap_slice(sm, l)
        seg = seg.iloc[min(len(seg) // 5, 30):]    # esclude l'accelerazione iniziale del lap
        c = cv(seg)
        if c is not None:
            acc += c * len(seg)
            wsum += len(seg)
    return acc / wsum if wsum else cv(sm)


# --------------------------------------------------------------------------- #
# Punteggi
# --------------------------------------------------------------------------- #
def lin(x: Optional[float], xp: Sequence[float], fp: Sequence[float]) -> Optional[float]:
    """Interpolazione lineare a tratti e saturata ai bordi (xp crescente)."""
    if x is None or (isinstance(x, float) and np.isnan(x)):
        return None
    return float(np.interp(x, xp, fp))


def percentile_score(value: Optional[float], history: Sequence[float], min_n: int = 5) -> Optional[float]:
    """Posizione del valore nello storico personale: 0 percentile -> 20, 100 -> 100."""
    h = [v for v in history if v is not None and np.isfinite(v)]
    if value is None or len(h) < min_n:
        return None
    pct = (np.sum(np.asarray(h) < value) + 0.5 * np.sum(np.asarray(h) == value)) / len(h) * 100
    return float(20 + 0.8 * pct)


def weighted_score(components: Sequence[Component]) -> Optional[int]:
    avail = [c for c in components if c.score is not None and c.weight > 0]
    if not avail:
        return None
    total = sum(c.score * c.weight for c in avail) / sum(c.weight for c in avail)
    return int(round(np.clip(total, 1, 100)))


def hr_tss(duration_s: float, avg_hr: Optional[float], ctx: AthleteContext, lthr: Optional[float]) -> Optional[float]:
    """hrTSS approssimato: IF = riserva cardiaca usata / riserva alla soglia."""
    if not avg_hr or not lthr:
        return None
    rhr = ctx.rhr or 50
    intensity = max(0.0, (avg_hr - rhr) / max(1.0, lthr - rhr))
    return duration_s / 3600 * intensity ** 2 * 100


def power_tss(duration_s: float, np_w: Optional[float], ftp: Optional[float]) -> Optional[float]:
    if not np_w or not ftp:
        return None
    intensity = np_w / ftp
    return duration_s * np_w * intensity / (ftp * 3600) * 100


def rnd(x: Optional[float], n: int = 1) -> Optional[float]:
    return None if x is None or (isinstance(x, float) and not np.isfinite(x)) else round(float(x), n)
