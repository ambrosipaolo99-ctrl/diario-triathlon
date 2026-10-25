"""
Zone, piano e voto degli allenamenti per l'obiettivo di corsa attivo.

Zone      dal VDOT equivalente alla stima centrale (paces di Daniels) e dalle zone FC
          Garmin: facile sotto la soglia aerobica (tetto Z2 = VT1), gara alla FC attesa.
Piano     un giorno per riga dal lunedi' della prima generazione alla gara. Scarico
          progressivo (maratona: -15%, -30%, -55% del volume delle 4 settimane prima
          dello scarico, intensita' mantenuta: Bosquet 2007 [CONSOLIDATO]). I giorni
          passati restano come erano stati proposti (salvati nel database); i futuri si
          ricalcolano e si adattano a quanto svolto.
Voto      ogni corsa del blocco viene abbinata al giorno del piano (o, senza piano, al
          tipo dedotto) e valutata 0-100 sui parametri ottimali del suo tipo.
"""
from __future__ import annotations

import json
import math
import re
import sqlite3
from datetime import date, timedelta
from typing import Any, Optional

import numpy as np

from . import db
from .goals import RunProfile
from .race import Athlete, Run, fast_block, fmt_pace, race_hr, speed_at_vo2, vdot

STORE_KEY = "plan:{}"
TOL = 8                 # s/km di tolleranza sul passo target


def lin(x: Optional[float], xp: list[float], fp: list[float]) -> Optional[float]:
    if x is None or not np.isfinite(x):
        return None
    return float(np.interp(x, xp, fp))


# --------------------------------------------------------------------------- #
# Zone
# --------------------------------------------------------------------------- #
def zones(ath: Athlete, prof: RunProfile, central_s: float) -> dict[str, dict]:
    goal_m = prof.distance_km * 1000
    vd = vdot(goal_m, central_s)
    p = lambda pct: 1000 / speed_at_vo2(pct * vd)  # noqa: E731  passo (s/km) a una % del VDOT
    gp = central_s / prof.distance_km
    rh = race_hr(ath, prof)
    z2_lo = ath.floors[1] if len(ath.floors) > 1 else ath.vt1 - 17
    return {
        "facile": {"name": "Facile", "pace_lo": p(0.70), "pace_hi": p(0.62), "hr_lo": z2_lo, "hr_hi": ath.vt1 - 3,
                   "use": "corsa facile e recupero, sotto la soglia aerobica (VT1 ≈ tetto Z2)"},
        "lungo": {"name": "Lungo", "pace_lo": p(0.74), "pace_hi": p(0.65), "hr_lo": z2_lo, "hr_hi": ath.vt1,
                  "use": "parte facile dei lunghi"},
        "gara": {"name": prof.race_pace_name.capitalize(), "pace_lo": gp - 4, "pace_hi": gp + 4,
                 "hr_lo": rh - 4, "hr_hi": rh + 4, "use": "ritmo obiettivo dalla stima centrale"},
        "soglia": {"name": "Soglia", "pace_lo": p(0.89), "pace_hi": p(0.86), "hr_lo": 0.94 * ath.lthr,
                   "hr_hi": ath.lthr, "use": "ripetute lunghe alla soglia del lattato"},
        "vo2": {"name": "VO2max", "pace_lo": p(1.0), "pace_hi": p(0.97), "hr_lo": 0.98 * ath.lthr,
                "hr_hi": ath.hrmax, "use": "ripetute brevi, non usate nello scarico"},
        "_meta": {"vdot": vd, "race_hr": rh, "vt1": ath.vt1},
    }


def zone_rows(Z: dict) -> list[dict]:
    return [{"key": k, "name": z["name"], "pace_lo": z["pace_lo"], "pace_hi": z["pace_hi"],
             "hr_lo": round(z["hr_lo"]), "hr_hi": round(z["hr_hi"]), "use": z["use"],
             "vdot": round(Z["_meta"]["vdot"], 1)} for k, z in Z.items() if not k.startswith("_")]


# --------------------------------------------------------------------------- #
# Testi di supporto (evidenze etichettate)
# --------------------------------------------------------------------------- #
PURPOSE = {
    "facile": "Mantenere volume e capillarizzazione senza aggiungere fatica: la maggior parte del volume a bassa "
              "intensita' e' la base di ogni piano di endurance [CONSOLIDATO]; la quota esatta (80/20) e' [EMERGENTE].",
    "soglia": "Conservare la velocita' alla soglia del lattato: nello scarico si taglia il volume ma si mantiene "
              "l'intensita' (Bosquet 2007, meta-analisi) [CONSOLIDATO].",
    "passo_gara": "Automatizzare il ritmo gara e la percezione dello sforzo, verificando FC e sensazioni al passo "
                  "obiettivo (pratica da allenatore, nessuno studio specifico).",
    "vo2": "Alzare il massimo consumo di ossigeno: per 5 e 10 km e' lo stimolo che pesa di piu' sulla prestazione "
           "[CONSOLIDATO]; ripetute di 2-5 minuti con recuperi brevi.",
    "tempo": "Spostare in alto la soglia aerobica-anaerobica: il tempo run continuo e' il lavoro tipico della mezza "
             "[CONSOLIDATO come pratica, evidenza sperimentale limitata].",
    "lungo": "Stimolo di durata specifico: tenere il passo in affaticamento (durability, Jones 2024) [EMERGENTE] "
             "e provare l'alimentazione di gara.",
    "allunghi": "Attivazione neuromuscolare senza fatica: gli allunghi brevi prima della gara sono pratica "
                "diffusa; l'effetto 'priming' ha evidenze minime [PRELIMINARE MA RILEVANTE].",
    "gara": "Gara obiettivo.",
    "riposo": "Recupero: la supercompensazione dello scarico arriva riducendo la fatica accumulata [CONSOLIDATO].",
}


def _fuel_long(weight: float) -> str:
    return ("Prova la strategia di gara: 60-90 g/h di carboidrati (gel + bevanda), mix glucosio:fruttosio oltre "
            "60 g/h [CONSOLIDATO]; allenare l'intestino migliora tolleranza e assorbimento [EMERGENTE]. Dopo: "
            f"~{round(weight, -1):.0f} g di carboidrati e 20-25 g di proteine entro 1-2 h [CONSOLIDATO].")


def _race_notes(d: int, weight: float, prof: RunProfile) -> str:
    g = lambda k: f"{round(weight * k, -1):.0f}"  # noqa: E731  grammi/mg arrotondati alla decina
    if d == 0:
        return (f"Colazione 2-3 h prima con {g(1.5)}-{g(3)} g di carboidrati (1,5-3 g/kg; range studiato 1-4 g/kg "
                f"1-4 h prima) [CONSOLIDATO]; caffeina ~{g(3)} mg (3 mg/kg) 45-60' prima [CONSOLIDATO]. In gara "
                "60-90 g/h di carboidrati dai primi 20-25' [CONSOLIDATO]; liquidi a sete, 400-800 ml/h secondo il "
                "meteo, sodio 300-600 mg/h se sudi molto [EMERGENTE]. Primi 5 km 3-5 s/km piu' lenti del ritmo "
                "obiettivo, poi regolare: lo split pari o leggermente negativo e' la strategia piu' efficiente "
                "(Diaz 2018, dati osservazionali) [EMERGENTE].")
    if d <= 2 and prof.is_marathon:
        return (f"Carico di carboidrati: 8-12 g/kg/giorno nelle 36-48 h prima (~{g(8)}-{g(10)} g "
                "al giorno), senza fase di deplezione [CONSOLIDATO]. Riduci fibre e grassi; l'aumento di peso "
                "di 1-2 kg e' acqua legata al glicogeno.")
    if d <= 6:
        return ("Dormi 8 ore o piu' in questa settimana: l'estensione del sonno migliora la prestazione in "
                "piccoli studi [PRELIMINARE MA RILEVANTE]. Nitrati (succo di barbabietola ~6-8 mmol 2-3 h prima "
                "o carico di 3-6 giorni): effetto piccolo, piu' probabile negli amatori [EMERGENTE]. Nessuna "
                "novita' su scarpe, gel o colazione rispetto a quanto gia' provato.")
    return ""


# --------------------------------------------------------------------------- #
# Costruzione dei giorni
# --------------------------------------------------------------------------- #
def _work(day: date, d: int, phase: str, kind: str, title: str, Z: dict, km: float, zone: str,
          structure: str = "", segments: Optional[list] = None, purpose: Optional[str] = None,
          notes: str = "") -> dict:
    z = Z[zone] if zone in Z else None
    mid = (z["pace_lo"] + z["pace_hi"]) / 2 if z else None
    easy = Z["facile"]
    # durata: segmenti al loro passo, il resto a passo facile
    seg_km = sum(s["reps"] * s.get("dist_km", 0) for s in segments or [])
    seg_min = sum(s["reps"] * s.get("dist_km", 0) * (s["pace_lo"] + s["pace_hi"]) / 2 / 60 for s in segments or [])
    rest_pace = mid if not segments else (easy["pace_lo"] + easy["pace_hi"]) / 2
    minutes = seg_min + (km - seg_km) * (rest_pace or 0) / 60 if km else 0
    tgt = segments[0] if segments else z
    return {"date": day.isoformat(), "d": d, "phase": phase, "type": kind, "title": title,
            "purpose": purpose or PURPOSE.get(("passo_gara" if zone == "gara" else zone) if kind == "qualità" else kind, ""),
            "km": round(km, 1) if km else None, "minutes": round(minutes) if km else None, "zone": zone,
            "pace_lo": tgt["pace_lo"] if tgt else None, "pace_hi": tgt["pace_hi"] if tgt else None,
            "hr_lo": round(tgt["hr_lo"]) if tgt else None, "hr_hi": round(tgt["hr_hi"]) if tgt else None,
            "structure": structure, "segments": segments or [], "notes": notes}


def _seg(Z: dict, zone: str, reps: int, dist_km: float, rec_min: float) -> dict:
    z = Z[zone]
    return {"zone": zone, "reps": reps, "dist_km": dist_km, "rec_min": rec_min, "pace_lo": z["pace_lo"],
            "pace_hi": z["pace_hi"], "hr_lo": z["hr_lo"], "hr_hi": z["hr_hi"]}


def _rest(day: date, d: int, phase: str, note: str = "") -> dict:
    return {"date": day.isoformat(), "d": d, "phase": phase, "type": "riposo", "title": "Riposo",
            "purpose": PURPOSE["riposo"], "km": None, "minutes": None, "zone": None, "pace_lo": None,
            "pace_hi": None, "hr_lo": None, "hr_hi": None, "structure": note, "segments": [], "notes": ""}


TAPER_FINAL_CUT = ((7, 0.45), (15, 0.50), (30, 0.55))      # distanza < km -> riduzione finale; oltre 0.60


def taper_params(prof: RunProfile, v0: float, race_day: date) -> dict:
    """
    Scarico esponenziale (Mujika & Padilla; Bosquet 2007: riduzione del volume del 41-60%, intensita' e frequenza
    mantenute) [CONSOLIDATO]: volume giornaliero di riferimento V(d) = V0/7 * e^(-k (T - d)), con T = giorni di
    scarico e k scelto per arrivare alla riduzione finale della distanza il giorno prima della gara.
    Blocchi: settimana gara (d 1-6, la gara esclusa), scarico 2 (7-13), scarico 1 (14-T).
    """
    T = prof.taper_days
    cut = next((c for lim, c in TAPER_FINAL_CUT if prof.distance_km < lim), 0.60)
    k = -math.log(1 - cut) / max(T - 1, 1)
    per_day = lambda d: v0 / 7 * math.exp(-k * (T - d))  # noqa: E731
    blocks = []
    for name, lo, hi in (("Settimana gara", 1, 6), ("Scarico 2", 7, 13), ("Scarico 1", 14, T)):
        ds = [d for d in range(lo, min(hi, T) + 1)]
        if not ds:
            continue
        target = sum(per_day(d) for d in ds)
        blocks.append({"block": name, "from": (race_day - timedelta(days=max(ds))).isoformat(),
                       "to": (race_day - timedelta(days=min(ds))).isoformat(), "days": ds,
                       "target_km": round(target, 1), "reduction_pct": round(100 * (1 - target / (v0 / 7 * len(ds))))
                       if v0 else None})
    return {"T": T, "final_cut": cut, "k": k, "v0": v0, "blocks": blocks}


def retitle(title: str, old_km: float, new_km: float) -> str:
    """Aggiorna nel titolo solo i km TOTALI (es. "Lungo 24 km"), mai quelli di un blocco ("con 5 km a passo gara")."""
    return re.sub(rf"\b{round(old_km):d} km\b(?! a )", f"{round(new_km):d} km", title, count=1)


def apply_taper(plan: dict[str, dict], tp: dict, today: date, frozen: set[str], race_day: date) -> None:
    """Riscala facili e lunghi ancora da fare di ogni blocco per centrare il volume esponenziale (qualita' intatta)."""
    for b in tp["blocks"]:
        keys = [(race_day - timedelta(days=d)).isoformat() for d in b["days"]]
        keys = [k for k in keys if k in plan]
        movable = [k for k in keys if k >= today.isoformat() and k not in frozen and plan[k]["type"] in ("facile", "lungo")
                   and plan[k]["d"] > 1 and plan[k].get("km")]
        fixed = sum(plan[k].get("km") or 0 for k in keys if k not in movable and plan[k]["type"] != "riposo")
        free = sum(plan[k]["km"] for k in movable)
        if free > 0:
            f = float(np.clip((b["target_km"] - fixed) / free, 0.6, 1.3))
            for k in movable:
                w = plan[k]
                new = max(3, round(w["km"] * f))
                if w.get("minutes"):
                    w["minutes"] = round(w["minutes"] * new / w["km"])
                w["title"] = retitle(w["title"], w["km"], new)
                w["km"] = new
        b["planned_km"] = round(sum(plan[k].get("km") or 0 for k in keys if plan[k]["type"] != "riposo"), 1)


def taper_day(day: date, d: int, Z: dict, prof: RunProfile, s: float, weight: float) -> dict:
    """Scarico. Il modello e' la maratona (21 gg); per distanze piu' corte si usano gli ultimi giorni."""
    rp = "passo gara"
    phase = "Settimana gara" if d <= 6 else "Scarico 2" if d <= 13 else "Scarico 1"
    E = lambda km: round(km * s)  # noqa: E731
    if d == 0:
        return {**_work(day, 0, phase, "gara", f"Gara: {prof.distance_km:g} km", Z, prof.distance_km, "gara",
                        "Partenza 3-5 s/km piu' lenta del ritmo obiettivo per 5 km, poi regolare."),
                "notes": _race_notes(0, weight, prof)}
    if d == 1:
        return _work(day, d, phase, "facile", "Sgambata pre-gara", Z, 4, "facile",
                     "20' molto facili + 3 allunghi da 15\"", purpose=PURPOSE["allunghi"], notes=_race_notes(1, weight, prof))
    if d == 3:
        return _work(day, d, phase, "facile", "Facile + allunghi", Z, E(5), "facile", "facile + 4 allunghi da 20\"",
                     notes=_race_notes(3, weight, prof))
    if d == 4:
        return _work(day, d, phase, "facile", "Facile", Z, E(6), "facile", notes=_race_notes(4, weight, prof))
    if d == 5:
        # richiamo a passo gara: tensione neuromuscolare senza fatica; il volume a ritmo gara cresce con la distanza
        reps, dist, rec = sharpener(prof)
        seg = [_seg(Z, "gara", reps, dist, rec)]
        label = f"{reps}×{_dist(dist)}"
        return _work(day, d, phase, "qualità", f"{label} a {rp}", Z, round(4 + reps * dist + (reps - 1) * rec / 5, 1),
                     "gara", f"2 km facili + {label} a {rp} (rec {rec:g}' facile) + 2 km facili", seg,
                     purpose="Mantenere l'intensita' riducendo il volume: richiami brevi a ritmo gara conservano la "
                             "tensione neuromuscolare senza aggiungere fatica (Bosquet 2007, Mujika) [CONSOLIDATO].",
                     notes=_race_notes(5, weight, prof))
    if d in (2, 6, 9, 13, 15, 20):
        return _rest(day, d, phase, "Riposo o 20-30' di mobilita'" + (": forza leggera ok fino a 10 giorni dalla gara "
                     "[EMERGENTE]" if d >= 10 else ""))
    if d == 7 and prof.distance_km >= 20:
        seg = [_seg(Z, "gara", 1, 5 if prof.is_marathon else 4, 0)]
        return _work(day, d, phase, "lungo", f"Medio-lungo con {seg[0]['dist_km']} km a {rp}", Z, E(14), "lungo",
                     f"facile, con {seg[0]['dist_km']} km continui a {rp} nella seconda meta'", seg,
                     notes="Ultima prova completa di scarpe, abbigliamento e gel di gara.")
    if d in (7, 8, 10, 12, 16, 18, 19):
        km = {7: 7, 8: 6, 10: 7, 12: 7, 16: 6, 18: 6, 19: 8}[d]
        extra = " + 6 allunghi" if d in (8, 16) else ""
        return _work(day, d, phase, "facile", "Facile" + (" + allunghi" if extra else ""), Z, E(km), "facile",
                     "corsa facile" + extra)
    if d == 11:
        seg = [_seg(Z, "soglia", 5, 1, 1.5)]
        return _work(day, d, phase, "qualità", "5×1 km a soglia", Z, 2 + 5 + 1.5 + 2, "soglia",
                     "2 km facili + 5×1 km a soglia (rec 90\" facile) + 2 km facili", seg)
    if d == 14:
        if prof.is_marathon:
            seg = [_seg(Z, "gara", 3, 4, 5)]
            return _work(day, d, phase, "lungo", f"Lungo {E(22)} km con 3×4 km a {rp}", Z, E(22), "lungo",
                         f"6 km facili, poi 3×4 km a {rp} con 1 km facile tra i blocchi, chiusura facile", seg,
                         notes=_fuel_long(weight))
        return _work(day, d, phase, "lungo", "Lungo", Z, E(16), "lungo", notes=_fuel_long(weight))
    if d == 17:
        seg = [_seg(Z, "soglia", 4, 1.6, 2)]
        return _work(day, d, phase, "qualità", "4×1600 m a soglia", Z, 2 + 6.4 + 2 + 1.5, "soglia",
                     "2 km facili + 4×1600 m a soglia (rec 2' facile) + 1-2 km facili", seg)
    # d == 21: ultimo lungo pieno
    return _work(day, d, phase, "lungo", f"Ultimo lungo {prof.long_peak_km:.0f} km", Z, E(prof.long_peak_km), "lungo",
                 f"facile, ultimi 8-10 km a {rp} se le sensazioni sono buone", notes=_fuel_long(weight))


def _dist(km: float) -> str:
    return f"{km * 1000:.0f} m" if km < 1 or km % 1 else f"{km:g} km"


def sharpener(prof: RunProfile) -> tuple[int, float, float]:
    """Richiamo a passo gara della settimana di gara: ripetute, distanza (km), recupero (min)."""
    if prof.distance_km < 7:
        return 5, 0.6, 2
    if prof.distance_km < 15:
        return 4, 1.0, 2
    return 3, 2.0, 2


def _sessions(prof: RunProfile, Z: dict) -> tuple[dict, dict]:
    """Le due sedute di qualita' della settimana di carico, diverse per distanza: (martedi', giovedi')."""
    rp = prof.race_pace_name
    if prof.distance_km < 15:
        # 5 e 10 km: VO2max e soglia anaerobica, recuperi brevi
        reps, dist, rec = (6, 0.8, 2) if prof.distance_km < 7 else (5, 1.0, 2.5)
        q1 = {"zone": "vo2", "seg": [_seg(Z, "vo2", reps, dist, rec)], "km": round(4 + reps * dist + (reps - 1) * rec / 5, 1),
              "title": f"{reps}×{_dist(dist)} a VO2max", "structure": f"2 km facili + {reps}×{_dist(dist)} a VO2max "
              f"(rec {rec:g}' facile) + 2 km facili"}
        if prof.distance_km < 7:
            q2 = {"zone": "gara", "seg": [_seg(Z, "gara", 5, 1.0, 1.5)], "km": 10.0, "title": f"5×1 km a {rp}",
                  "structure": f"2 km facili + 5×1 km a {rp} (rec 90\" facile) + 2 km facili"}
        else:
            q2 = {"zone": "soglia", "seg": [_seg(Z, "soglia", 3, 2.0, 1.5)], "km": 11.0, "title": "3×2 km a soglia",
                  "structure": "2 km facili + 3×2 km a soglia (rec 90\" facile) + 2 km facili"}
        return q1, q2
    q1 = {"zone": "soglia", "seg": [_seg(Z, "soglia", 5, 1.6, 2)], "km": 14.5, "title": "5×1600 m a soglia",
          "structure": "2 km facili + 5×1600 m a soglia (rec 2' facile) + 2 km facili"}
    n = 10 if prof.is_marathon else 8          # maratona: ritmo gara lungo; mezza: tempo run continuo
    q2 = {"zone": "gara", "seg": [_seg(Z, "gara", 1, n, 0)], "km": n + 5.0, "title": f"{n} km a {rp}",
          "structure": f"3 km facili + {n} km a {rp} + 2 km facili",
          "purpose": None if prof.is_marathon else PURPOSE["tempo"]}
    return q1, q2


def build_day(day: date, d: int, Z: dict, prof: RunProfile, week_km: float, long_km: float, weight: float) -> dict:
    """
    Settimana di carico tipo, diversa per distanza (qualita' il martedi' e il giovedi', lungo la domenica):
      5-10 km   VO2max + soglia (o ritmo 5 km), recuperi brevi, lungo facile
      mezza     soglia + tempo run, lungo con finale a passo mezza
      maratona  soglia + ritmo maratona, lungo con blocco a passo maratona una settimana si' e una no
    """
    wd = day.weekday()
    phase = "Carico"
    q1, q2 = _sessions(prof, Z)
    n_easy = 3 if week_km > 50 else 2          # oltre 50 km/settimana il venerdi' diventa un facile rigenerante
    if wd == 0 or (wd == 4 and n_easy == 2):
        return _rest(day, d, phase, "Riposo o forza (1-2 sedute/settimana: migliorano l'economia di corsa "
                                    "[CONSOLIDATO])")
    if wd in (1, 3):
        q = q1 if wd == 1 else q2
        return _work(day, d, phase, "qualità", q["title"], Z, q["km"], q["zone"], q["structure"], q["seg"],
                     purpose=q.get("purpose"))
    if wd == 6:
        rp = prof.race_pace_name
        if prof.is_marathon and day.isocalendar()[1] % 2 == 0:
            mp = min(12, round(long_km * 0.35))
            seg = [_seg(Z, "gara", 1, mp, 0)]
            return _work(day, d, phase, "lungo", f"Lungo {long_km:.0f} km con {mp} km a {rp}", Z, long_km, "lungo",
                         f"facile, poi gli ultimi {mp} km a {rp}: ritmo gara con il glicogeno gia' in calo", seg,
                         purpose="Specificita' maratona: tenere il ritmo gara a scorte ridotte (durability, Jones 2024) "
                                 "[EMERGENTE] e provare gel e bevande di gara.", notes=_fuel_long(weight))
        if prof.distance_km >= 20 and not prof.is_marathon:
            seg = [_seg(Z, "gara", 1, 5, 0)]
            return _work(day, d, phase, "lungo", f"Lungo {long_km:.0f} km, ultimi 5 a {rp}", Z, long_km, "lungo",
                         f"facile, ultimi 5 km a {rp}", seg, notes=_fuel_long(weight))
        return _work(day, d, phase, "lungo", f"Lungo {long_km:.0f} km", Z, long_km, "lungo",
                     "facile, ultimi 20' in progressione", notes=_fuel_long(weight))
    # il volume restante si divide sui facili; nessun facile supera l'80% del lungo
    rest = min(max(5.0, (week_km - q1["km"] - q2["km"] - long_km) / n_easy), 0.8 * long_km)
    if wd == 4:
        return _work(day, d, phase, "facile", "Facile rigenerante", Z, round(min(rest, 8)), "facile",
                     "corsa molto facile, FC bassa: serve a recuperare per la qualita' del giorno dopo")
    return _work(day, d, phase, "facile", "Facile" + (" + allunghi" if wd == 5 else ""), Z, round(rest), "facile",
                 "corsa facile" + (" + 6 allunghi da 20\"" if wd == 5 else ""))


# --------------------------------------------------------------------------- #
# Analisi della corsa svolta
# --------------------------------------------------------------------------- #
def _pts(r: Run) -> list[dict]:
    return [p for p in r.stream if p.get("dist_km") is not None]


def stream_decoupling(r: Run) -> Optional[float]:
    p = _pts(r)[10:]
    p = [x for x in p if x.get("hr")]
    if len(p) < 40:
        return None
    a, b = p[:len(p) // 2], p[len(p) // 2:]
    ef = lambda q: (q[-1]["dist_km"] - q[0]["dist_km"]) / len(q) / np.mean([x["hr"] for x in q])  # noqa: E731
    e1, e2 = ef(a), ef(b)
    return (e1 - e2) / e1 * 100 if e1 > 0 else None


def segments(r: Run, pace_max: float, min_pts: int = 2) -> list[dict]:
    """Tratti continui (>= 1') con passo <= pace_max: durata, passo, FC, recupero precedente."""
    p = _pts(r)
    out, cur, last_end = [], [], None

    def close():
        nonlocal last_end
        if len(cur) >= min_pts:
            i0, i1 = cur[0], cur[-1]
            dist = p[i1]["dist_km"] - (p[i0 - 1]["dist_km"] if i0 > 0 else 0)
            hrs = [p[i]["hr"] for i in cur[1:] if p[i].get("hr")]
            out.append({"start": i0, "min": len(cur) / 2, "km": dist, "pace": len(cur) * 30 / dist if dist > 0 else None,
                        "hr": float(np.mean(hrs)) if hrs else None,
                        "rec_min": (i0 - last_end - 1) / 2 if last_end is not None else None,
                        "paces": [p[i]["pace_s"] for i in cur]})
            last_end = i1

    for i, x in enumerate(p):
        if x.get("pace_s") and x["pace_s"] <= pace_max:
            cur.append(i)
        else:
            close()
            cur = []
    close()
    return [s for s in out if s["pace"]]


def infer_type(r: Run, Z: dict, prof: RunProfile) -> str:
    if r.km >= max(18, 0.55 * prof.long_peak_km) or r.moving_s >= 100 * 60:
        return "lungo"
    work = sum(s["min"] for s in segments(r, Z["gara"]["pace_hi"] + TOL))
    if work >= 8 or (not r.steady and work >= 4):
        return "qualità"
    return "facile"


def _comp(name: str, weight: float, score: Optional[float], value: str, note: str, tip: str) -> dict:
    """Una voce del voto; `tip` e' il consiglio mostrato se e' la voce peggiore."""
    return {"name": name, "weight": weight, "score": score, "value": value, "note": note, "tip": tip}


def terrain(r: Run) -> str:
    """Nota sul percorso: in salita il passo non misura lo sforzo, conta la FC."""
    if not r.hilly or not r.ascent_m:
        return ""
    return (f"Percorso collinare: {r.ascent_m:.0f} m D+ ({r.ascent_m / max(r.km, 0.1):.0f} m/km, Strava); "
            "passo e regolarita' pesano meno, conta la FC. ")


def grade_easy(r: Run, w: Optional[dict], Z: dict, ath: Athlete) -> list[dict]:
    z = Z["facile"]
    p = _pts(r)[10:]
    hrs = [x["hr"] for x in p if x.get("hr")]
    share = np.mean([h <= ath.vt1 for h in hrs]) if len(hrs) >= 10 else None
    pace = 1000 / r.speed if r.speed else None
    fast = (z["pace_lo"] - pace) if pace else None
    slow = (pace - z["pace_hi"]) if pace else None
    sp = (lin(fast, [0, 8, 20, 40], [100, 85, 45, 10]) if fast and fast > 0
          else lin(slow, [0, 30, 60], [100, 90, 70]) if slow and slow > 0 else 100 if pace else None)
    dec = stream_decoupling(r) if r.moving_s >= 20 * 60 else None
    tm = " Sul tapis roulant la velocita' puo' essere tarata male: guida con la FC." if r.treadmill else ""
    hill = r.hilly and not r.treadmill
    out = [
        _comp("FC sotto la soglia aerobica", 45 if hill else 35, lin(share, [0.5, 0.75, 0.9, 0.97], [10, 50, 85, 100]),
              f"{share * 100:.0f}% del tempo" if share is not None else "-",
              f"tempo con FC <= {ath.vt1:.0f} bpm (VT1 ≈ tetto Z2) dopo i primi 5'",
              f"Troppo tempo sopra la soglia aerobica ({share * 100 if share is not None else 0:.0f}% sotto): rallenta "
              f"finche' la FC resta sotto {ath.vt1:.0f} bpm, anche in salita." + tm),
        _comp("Passo nel range facile", 8 if hill else 25, sp, f"{fmt_pace(pace)}/km" if pace else "-",
              f"range {fmt_pace(z['pace_lo'])}-{fmt_pace(z['pace_hi'])}/km; penalizzato soprattutto se piu' veloce"
              + ("; peso ridotto: in salita il passo non misura lo sforzo" if hill else ""),
              f"Troppo veloce per un facile ({fmt_pace(pace)}/km): stai sotto {fmt_pace(z['pace_lo'])}/km, il "
              "facile serve a recuperare per la qualita'." if fast and fast > 0 else
              f"Piu' lento del range ({fmt_pace(pace)}/km): va bene se la FC era alta per caldo o stanchezza."),
        _comp("Deriva cardiaca", 20, lin(dec, [3, 5, 8, 12], [100, 85, 50, 20]),
              f"{dec:+.1f}%" if dec is not None else "-", "metri per battito, seconda meta' vs prima",
              f"Deriva cardiaca alta ({dec if dec is not None else 0:+.1f}%): parti piu' piano, idratati prima, evita "
              "le ore calde; se succede spesso nei facili e' un segnale di fatica."),
    ]
    if w and w.get("km"):
        dev = abs(r.km / w["km"] - 1)
        out.append(_comp("Durata rispettata", 20, lin(dev, [0.1, 0.2, 0.35, 0.6], [100, 85, 50, 15]),
                         f"{r.km:.1f} di {w['km']:.0f} km", "distanza svolta vs prevista",
                         f"Volume diverso dal previsto ({r.km:.1f} di {w['km']:.0f} km): nello scarico non si "
                         "aggiunge volume e quello perso non si recupera."))
    return out


def grade_quality(r: Run, w: Optional[dict], Z: dict, ath: Athlete) -> list[dict]:
    if w and w.get("segments"):
        spec = w["segments"][0]
        lo, hi, hlo, hhi = spec["pace_lo"], spec["pace_hi"], spec["hr_lo"], spec["hr_hi"]
    else:
        spec = None
        segs0 = segments(r, Z["gara"]["pace_hi"] + TOL)
        med = np.median([s["pace"] for s in segs0]) if segs0 else Z["gara"]["pace_lo"]
        key = min(("gara", "soglia", "vo2"), key=lambda k: abs((Z[k]["pace_lo"] + Z[k]["pace_hi"]) / 2 - med))
        lo, hi, hlo, hhi = Z[key]["pace_lo"], Z[key]["pace_hi"], Z[key]["hr_lo"], Z[key]["hr_hi"]
    segs = [s for s in segments(r, hi + TOL + 4) if s["min"] >= 1]
    if spec and spec["reps"] > 1:
        # le ripetute sono i tratti piu' lunghi; il resto (allunghi, accelerazioni) si scarta
        segs = sorted(sorted(segs, key=lambda s: -s["min"])[:spec["reps"] + 1], key=lambda s: s["start"])
    if not segs:
        return [_comp("Passo delle ripetute", 30, 10, "-", f"nessun tratto a {fmt_pace(lo)}-{fmt_pace(hi)}/km rilevato",
                      f"Nessun tratto al passo target ({fmt_pace(lo)}-{fmt_pace(hi)}/km): se eri stanco, meglio "
                      "trasformarla in un facile e dirlo al piano che forzare.")]
    out = []
    hill = r.hilly and not r.treadmill
    tot = sum(s["min"] for s in segs)
    dev = sum(s["min"] * (max(0, lo - s["pace"]) + max(0, s["pace"] - hi)) for s in segs) / tot
    too_fast = np.mean([s["pace"] for s in segs]) < lo
    too_slow = np.mean([s["pace"] for s in segs]) > hi
    out.append(_comp("Passo delle ripetute", 15 if hill else 30, lin(dev, [0, 4, 8, 15], [100, 85, 55, 20]),
                     " · ".join(fmt_pace(s["pace"]) for s in segs[:8]),
                     f"target {fmt_pace(lo)}-{fmt_pace(hi)}/km; scarto medio fuori range {dev:.0f} s/km"
                     + ("; peso ridotto su percorso collinare" if hill else ""),
                     f"Ripetute {'piu veloci' if too_fast else 'piu lente'} del target di {dev:.0f} s/km: "
                     + ("andare oltre il passo non aggiunge stimolo ma fatica." if too_fast else
                        "parti dal passo giusto e accorcia la ripetuta se non lo tieni.")))
    if len(segs) >= 2:
        cvp = float(np.std([s["pace"] for s in segs]) / np.mean([s["pace"] for s in segs]) * 100)
        note = f"variabilita' tra {len(segs)} ripetute"
    else:
        ps = [x for x in segs[0]["paces"] if x]
        cvp = float(np.std(ps) / np.mean(ps) * 100) if len(ps) >= 3 else None
        note = "variabilita' del passo nel blocco continuo"
    out.append(_comp("Regolarita' tra le ripetute", 20, lin(cvp, [1.5, 3, 5, 8], [100, 85, 55, 20]),
                     f"{cvp:.1f}%" if cvp is not None else "-", note,
                     f"Ripetute irregolari ({cvp if cvp else 0:.1f}%): la prima al passo dell'ultima, lap automatici "
                     "sul km per controllarle."))
    hr = np.mean([s["hr"] for s in segs if s["hr"]]) if any(s["hr"] for s in segs) else None
    # FC bassa al passo giusto = forma migliore del previsto, non un errore
    off = (max(0, hr - hhi) + (max(0, hlo - hr) if too_slow else 0)) if hr else None
    out.append(_comp("FC coerente con lo sforzo", 30 if hill else 15, lin(off, [0, 3, 6, 10], [100, 80, 50, 20]),
                     f"{hr:.0f} bpm" if hr else "-", f"atteso {hlo:.0f}-{hhi:.0f} bpm nei tratti di lavoro",
                     (f"FC sotto l'atteso ({hr:.0f} vs {hlo:.0f}-{hhi:.0f}): passo sotto il target, ripetute troppo "
                      "brevi perche' la FC salga, o tapis roulant che sovrastima la velocita'." if hr and hr < hlo else
                      f"FC sopra l'atteso ({hr if hr else 0:.0f} vs {hlo:.0f}-{hhi:.0f}): lo sforzo era piu' alto del "
                      "previsto; controlla caldo, sonno e recupero.")))
    if spec and spec["reps"] > 1 and spec["rec_min"]:
        recs = [s["rec_min"] for s in segs[1:] if s["rec_min"] is not None]
        if recs:
            ratio = float(np.mean(recs)) / spec["rec_min"]
            out.append(_comp("Recuperi rispettati", 15, lin(abs(ratio - 1), [0.15, 0.35, 0.7], [100, 70, 30]),
                             f"{np.mean(recs):.1f}' di {spec['rec_min']:g}'", "durata media dei recuperi tra le ripetute",
                             f"Recuperi di {np.mean(recs):.1f}' invece di {spec['rec_min']:g}': la durata del "
                             "recupero fa parte dello stimolo, rispettala."))
    if spec:
        planned = spec["reps"] * spec["dist_km"]
        done = sum(s["km"] for s in segs if s["pace"] <= hi + TOL)
        ratio = done / planned
        out.append(_comp("Volume di qualita' completato", 20,
                         85 if ratio > 1.3 else lin(ratio, [0.5, 0.75, 0.9, 1.0], [15, 55, 90, 100]),
                         f"{done:.1f} di {planned:g} km", f"km a passo target (±{TOL} s)",
                         f"Volume di qualita' incompleto ({done:.1f} di {planned:g} km al passo): meglio una "
                         "ripetuta in meno al passo giusto che tutte troppo lente."))
    return out


def grade_long(r: Run, w: Optional[dict], Z: dict, ath: Athlete, prof: RunProfile) -> list[dict]:
    out = []
    if w and w.get("km"):
        dev = abs(r.km / w["km"] - 1)
        out.append(_comp("Durata/distanza", 25, lin(dev, [0.08, 0.15, 0.3, 0.5], [100, 85, 50, 15]),
                         f"{r.km:.1f} di {w['km']:.0f} km", "distanza svolta vs prevista",
                         f"Lungo diverso dal previsto ({r.km:.1f} di {w['km']:.0f} km): nello scarico la durata "
                         "conta quanto il passo."))
    else:
        pk = prof.long_peak_km
        out.append(_comp("Durata/distanza", 25, lin(r.km, [0.5 * pk, 0.7 * pk, 0.85 * pk, pk], [40, 70, 90, 100]),
                         f"{r.km:.1f} km", f"rispetto al lungo di riferimento di {pk:.0f} km",
                         f"Lungo corto rispetto ai {pk:.0f} km di riferimento: aumenta di 2-3 km a settimana."))
    dec = stream_decoupling(r)
    out.append(_comp("Deriva cardiaca (seconda meta')", 25, lin(dec, [2, 4, 6, 9, 12], [100, 90, 70, 40, 15]),
                     f"{dec:+.1f}%" if dec is not None else "-", "metri per battito, seconda meta' vs prima",
                     f"Deriva alta nella seconda meta' ({dec if dec is not None else 0:+.1f}%): carboidrati dai primi "
                     "30-40', liquidi regolari, prima meta' piu' lenta."))
    zg = Z["gara"]
    seg_spec = next((s for s in (w or {}).get("segments", []) if s["zone"] == "gara"), None)
    gp = [s for s in segments(r, zg["pace_hi"] + TOL) if s["min"] >= 3]
    mp_tip = (f"Tratti a passo gara da sistemare: il ritmo obiettivo e' {fmt_pace(zg['pace_lo'])}-"
              f"{fmt_pace(zg['pace_hi'])}/km con FC <= {zg['hr_hi']:.0f}; trovalo nei primi 500 m e poi tienilo.")
    if seg_spec:
        planned = seg_spec["reps"] * seg_spec["dist_km"]
        done = sum(s["km"] for s in gp if zg["pace_lo"] - TOL <= s["pace"])
        hr = np.mean([s["hr"] for s in gp if s["hr"]]) if gp else None
        sc = lin(done / planned, [0.4, 0.7, 0.9, 1.0], [15, 55, 90, 100])
        if hr and hr > zg["hr_hi"] + 3:
            sc = sc * 0.85
        out.append(_comp("Tratti a passo gara", 20, sc, f"{done:.1f} di {planned:g} km",
                         f"a {fmt_pace(zg['pace_lo'])}-{fmt_pace(zg['pace_hi'])}/km" + (f", FC {hr:.0f}" if hr else ""),
                         mp_tip))
    else:
        blk = fast_block(r, 4)
        if blk:
            v, hr, n = blk
            pace = 1000 / v
            off = max(0, zg["pace_lo"] - pace) + max(0, pace - zg["pace_hi"])
            sc = lin(off, [0, 5, 12, 20], [100, 85, 55, 30])
            if hr > zg["hr_hi"] + 3:
                sc *= 0.85
            out.append(_comp("Tratti a passo gara", 20, sc, f"{n} km a {fmt_pace(pace)}",
                             f"blocco veloce nel lungo, FC {hr:.0f}; ritmo gara {fmt_pace(zg['pace_lo'])}-"
                             f"{fmt_pace(zg['pace_hi'])}", mp_tip))
    p = _pts(r)
    if len(p) >= 40:
        # finale vs prima meta' dopo il riscaldamento: un blocco a ritmo gara a meta' lungo non falsa il confronto
        n = len(p)
        first = p[int(n * 0.1):int(n * 0.5)]
        end = p[int(n * 0.8):]
        pf = len(first) * 30 / ((first[-1]["dist_km"] - first[0]["dist_km"]) * 1000) * 1000
        pe = len(end) * 30 / ((end[-1]["dist_km"] - end[0]["dist_km"]) * 1000) * 1000
        slow = (pe / pf - 1) * 100
        hill = r.hilly and not r.treadmill
        if prof.is_marathon:
            # maratona: la simmetria d'appoggio sotto fatica e' una delle priorita' del blocco specifico
            bal = [x["gct_bal"] for x in p[10:] if x.get("gct_bal")]
            if len(bal) >= 60:
                k3 = len(bal) // 3
                bf, bl = float(np.mean(bal[:k3])), float(np.mean(bal[-k3:]))
                sc = lin(abs(bl - 50), [1, 2, 3, 4], [100, 70, 40, 15])
                if abs(bl - 50) > abs(bf - 50) and abs(bl - bf) >= 1.5:
                    sc *= 0.8                     # asimmetria comparsa con la fatica
                out.append(_comp("Simmetria sotto fatica", 10, sc, f"{bl:.1f}% sx",
                                 f"appoggio sinistro nell'ultimo terzo (all'inizio {bf:.1f}%)",
                                 f"Nel finale l'appoggio si sbilancia ({bl:.1f}% sx / {100 - bl:.1f}% dx): in maratona la "
                                 "simmetria sotto fatica conta; forza di anca e caviglia e lunghi con finale controllato "
                                 "[PRELIMINARE MA RILEVANTE]."))
        out.append(_comp("Tenuta del passo nel finale", 12 if hill else 30, lin(slow, [0, 2, 4, 7, 10], [100, 90, 65, 30, 10]),
                         f"{slow:+.1f}%", f"ultimo 20% ({fmt_pace(pe)}/km) vs prima meta' ({fmt_pace(pf)}/km)"
                         + ("; peso ridotto: il profilo altimetrico falsa il confronto" if hill else ""),
                         f"Calo nel finale ({slow:+.1f}%): parti piu' piano e anticipa i carboidrati (60-90 g/h "
                         "dal primo terzo)."))
    return out


def grade_race(r: Run, est: Optional[dict], ath: Athlete) -> list[dict]:
    sp = [s["pace_s"] for s in r.splits if not s.get("partial") and s.get("pace_s")]
    out = []
    if len(sp) >= 5:
        h = len(sp) // 2
        neg = (np.mean(sp[h:]) / np.mean(sp[:h]) - 1) * 100
        out.append(_comp("Gestione del ritmo", 35, lin(neg, [-1, 1, 3, 6], [100, 95, 60, 20]),
                         f"{neg:+.1f}%", "seconda meta' vs prima (negativo = split negativo)",
                         f"Seconda meta' piu' lenta del {neg:.1f}%: la prossima volta primi 10 km 5 s/km piu' lenti."))
        cvp = float(np.std(sp) / np.mean(sp) * 100)
        out.append(_comp("Regolarita'", 20, lin(cvp, [1.5, 3, 5], [100, 75, 35]), f"{cvp:.1f}%",
                         "variabilita' degli split", f"Split irregolari ({cvp:.1f}%): ritmo piu' costante ai rifornimenti."))
    dec = stream_decoupling(r)
    out.append(_comp("Deriva cardiaca", 15, lin(dec, [3, 6, 10], [100, 70, 30]), f"{dec:+.1f}%" if dec is not None else "-",
                     "metri per battito, seconda meta' vs prima",
                     "Deriva alta: rivedi idratazione e carboidrati in gara."))
    if est:
        diff = (r.moving_s / est["central_s"] - 1) * 100
        out.append(_comp("Risultato vs stima", 30, lin(diff, [-2, 0, 2, 5, 8], [100, 95, 75, 40, 15]),
                         f"{diff:+.1f}%", "tempo in movimento vs stima centrale della vigilia",
                         f"Tempo {diff:+.1f}% rispetto alla stima: guarda passo e FC dei km in cui hai perso."))
    return out


def comment(comps: list[dict], kind: str) -> str:
    rated = [c for c in comps if c["score"] is not None]
    if not rated:
        return "Dati insufficienti per un commento."
    worst = min(rated, key=lambda c: c["score"])
    if worst["score"] >= 85:
        best = max(rated, key=lambda c: c["score"])
        return f"Eseguito bene per un {kind}. Punto di forza: {best['name']} ({best['value']})."
    return worst["tip"]


def weighted(comps: list[dict]) -> Optional[int]:
    rated = [c for c in comps if c["score"] is not None]
    if not rated:
        return None
    tot = sum(c["weight"] for c in rated)
    for c in comps:
        c["eff_weight"] = round(c["weight"] / tot * 100) if c["score"] is not None else 0
    return int(round(sum(c["score"] * c["weight"] for c in rated) / tot))


# --------------------------------------------------------------------------- #
# Piano + abbinamento + voti
# --------------------------------------------------------------------------- #
def _monday(d: date) -> date:
    return d - timedelta(days=d.weekday())


def _week_km(runs: list[Run], start: date, end: date) -> float:
    return sum(r.km for r in runs if start <= r.day <= end)


def coach(conn: sqlite3.Connection, goal: dict, prof: RunProfile, runs: list[Run], ath: Athlete,
          est_by_day: dict[str, dict], window_start: date, today: Optional[date] = None,
          impact: Optional[dict] = None) -> dict[str, list[dict]]:
    """`impact`: protezione strutturale attiva ({until, reason}, da perf.load_vectors) o None."""
    today = today or date.today()
    race_day = date.fromisoformat(goal["date"])
    # days: giorni passati come proposti; pinned: giorni futuri gia' adattati; applied: adattamenti gia' fatti
    store = db.get_setting(conn, STORE_KEY.format(goal["id"])) or {"start": None, "days": {}}
    store.setdefault("pinned", {})
    applied: set[str] = set(store.get("applied", []))
    touched: set[str] = set()
    start =date.fromisoformat(store["start"]) if store.get("start") else _monday(min(today, race_day))
    weight = 66.0
    lt = (db.get_setting(conn, "lactate_threshold") or {}).get("power") or {}
    if lt.get("weight"):
        weight = float(lt["weight"])
    taper_start = race_day - timedelta(days=prof.taper_days)
    # volume di riferimento: media delle 3 settimane piu' cariche tra le 4 prima dello scarico
    blocks = sorted(_week_km(runs, taper_start - timedelta(days=7 * i + 6), taper_start - timedelta(days=7 * i))
                    for i in range(4))
    v0 = float(np.mean(blocks[1:]))
    if v0 < 1:
        # scarico ancora lontano: le settimane prima dello scarico sono nel futuro, il riferimento e' il volume reale
        # delle ultime 3 settimane
        recent = [_week_km(runs, today - timedelta(days=7 * i + 7), today - timedelta(days=7 * i + 1)) for i in range(3)]
        v0 = float(np.mean(recent))
    s = float(np.clip(v0 / 60, 0.6, 1.3)) if v0 else 1.0

    def est_for(day: date) -> dict:
        keys = [k for k in est_by_day if k < day.isoformat()]
        return est_by_day[max(keys)] if keys else est_by_day[min(est_by_day)]

    # 1) giorni del piano: passati congelati, futuri ricalcolati
    plan: dict[str, dict] = {}
    day = start
    while day <= race_day:
        k = day.isoformat()
        if day < today and k not in store["days"] and k in store["pinned"]:
            # giorno adattato e poi passato: resta com'era stato proposto dopo l'adattamento
            plan[k] = {x: v for x, v in store["pinned"][k].items() if x not in ("status", "activity_id", "grade", "warning")
                       and not x.startswith("done_")}
        elif day < today and k in store["days"]:
            # il contenuto resta quello proposto; stato e abbinamento si ricalcolano (sync tardivi)
            plan[k] = {x: v for x, v in store["days"][k].items()
                       if x not in ("status", "activity_id", "grade", "done_km", "done_pace_s", "done_hr", "done_note", "warning")}
        else:
            # i giorni passati mai salvati si generano con i dati fino al lunedi' della loro settimana
            ref = _monday(day) if day < today else today
            Z = zones(ath, prof, est_for(ref)["central_s"])
            d = (race_day - day).days
            if d <= prof.taper_days:
                w = taper_day(day, d, Z, prof, s, weight)
            else:
                last = _week_km(runs, ref - timedelta(days=7), ref - timedelta(days=1))
                wk = min(max(last * 1.08, v0 * 0.8), max(v0 * 1.1, 40))
                lg = min(prof.long_peak_km, max(14, 0.3 * wk))
                w = build_day(day, d, Z, prof, wk, lg, weight)
            w["generated_on"] = (ref - timedelta(days=1)).isoformat() if day < today else today.isoformat()
            plan[k] = w
            if day >= today and k in store["pinned"]:
                # giorno gia' adattato in un calcolo precedente: resta adattato
                plan[k] = {x: v for x, v in store["pinned"][k].items() if x not in ("status", "activity_id", "grade", "warning")
                           and not x.startswith("done_")}
        day += timedelta(days=1)

    # 1b) scarico esponenziale: volume dei giorni ancora da fare riportato sulla curva (gli adattati restano)
    taper = taper_params(prof, v0, race_day)
    apply_taper(plan, taper, today, set(store["pinned"]), race_day)

    # 2) abbinamento delle corse e voti
    Zt = zones(ath, prof, est_for(today + timedelta(days=1))["central_s"])
    by_day: dict[str, list[Run]] = {}
    for r in runs:
        if window_start <= r.day <= today:
            by_day.setdefault(r.day.isoformat(), []).append(r)
    grades, parts = [], []
    used_plan: set[str] = set()
    for k in sorted(by_day):
        day_runs = sorted(by_day[k], key=lambda r: -r.km)
        for i, r in enumerate(day_runs):
            Z = zones(ath, prof, est_for(r.day)["central_s"])
            inferred = infer_type(r, Z, prof)
            today_w = plan.get(k) if i == 0 and plan.get(k, {}).get("type") not in (None, "riposo") else None

            def fits(pw: dict) -> bool:
                """La corsa e' davvero quel tipo di allenamento (un lungo accorciato resta un lungo)."""
                return (pw["type"] == inferred or pw["type"] == "gara"
                        or (pw["type"] == "lungo" and pw.get("km") and r.km >= 0.75 * pw["km"]))

            w, k_plan = None, None
            if today_w and fits(today_w):
                w, k_plan = today_w, k
            elif i == 0:
                # allenamento slittato: stesso tipo previsto entro 2 giorni nella stessa settimana (prima o dopo)
                wk0, wk1 = _monday(r.day), _monday(r.day) + timedelta(days=6)
                cands = []
                for off in (-1, 1, -2, 2):
                    c = r.day + timedelta(days=off)
                    ck = c.isoformat()
                    pw = plan.get(ck)
                    if (pw and wk0 <= c <= wk1 and pw["type"] not in ("riposo", "gara") and ck not in used_plan
                            and fits(pw) and not (c < r.day and ck in by_day)):
                        cands.append(ck)
                if cands:
                    k_plan = cands[0]
                    w = plan[k_plan]
                elif today_w:
                    w, k_plan = today_w, k       # stesso giorno ma tipo diverso dal previsto
            # voto con i criteri del tipo svolto davvero; il target del piano solo se il tipo coincide
            kind = w["type"] if w and fits(w) else inferred
            spec = w if w and fits(w) else None
            if kind == "gara":
                comps = grade_race(r, est_for(r.day), ath)
            elif kind == "lungo":
                comps = grade_long(r, spec, Z, ath, prof)
            elif kind == "qualità":
                comps = grade_quality(r, spec, Z, ath)
            else:
                comps = grade_easy(r, spec, Z, ath)
            score = weighted(comps)
            done = {"done_km": round(r.km, 1), "done_pace_s": 1000 / r.speed if r.speed else None, "done_hr": r.hr}
            prefix = ""
            if w and not spec:
                prefix = f"Previsto {w['type']} ({w['title']}), svolto {kind}: valutato con i criteri del {kind}. "
            if w and k_plan:
                used_plan.add(k_plan)
                kd = date.fromisoformat(k_plan)
                status = ("svolto" if spec else "svolto (altro tipo)") if k_plan == k else \
                    "svolto (spostato)" if kd < r.day else "svolto (anticipato)"
                w.update({"status": status, "activity_id": r.id, "grade": score, **done,
                          "done_note": None if k_plan == k else f"svolto il {r.day:%d/%m}"})
                if k_plan != k and k in plan:
                    plan[k].update({"status": "sostituito", "activity_id": r.id, **done, "grade": None,
                                    "done_note": f"qui hai fatto {w['title'].lower()} previsto il {kd:%d/%m} (voto {score})"})
            elif i == 0 and k in plan and plan[k].get("type") == "riposo":
                plan[k].update({"status": "corsa extra", "activity_id": r.id, "grade": score, **done,
                                "done_note": "giorno di riposo nel piano: corsa non prevista"})
            grades.append({
                "id": r.id, "date": k, "name": r.name, "km": r.km, "minutes": r.moving_s / 60,
                "pace_s": 1000 / r.speed if r.speed else None, "avg_hr": r.hr, "treadmill": r.treadmill,
                "type": kind, "type_source": "piano" if spec else "dedotto",
                "plan_date": k_plan, "plan_title": w["title"] if w else None, "score": score,
                "ascent_m": r.ascent_m, "ascent_source": r.ascent_source, "hilly": r.hilly,
                "comment": prefix + terrain(r) + comment(comps, kind) + ("" if w or i == 0 else " (corsa extra della giornata)"),
            })
            for j, c in enumerate(comps):
                parts.append({"key": f"{r.id}-{j}", "activity_id": r.id, "component": c["name"], "weight": c["weight"],
                              "eff_weight": c.get("eff_weight", 0), "score": None if c["score"] is None else round(c["score"]),
                              "value": c["value"], "note": c["note"]})

    # 3) stato dei giorni e adattamenti
    rec = conn.execute("SELECT date, recovery_index, recovery_json FROM wellness_daily WHERE recovery_index IS NOT NULL "
                       "ORDER BY date DESC LIMIT 1").fetchone()
    for k, w in plan.items():
        day = date.fromisoformat(k)
        w.setdefault("status", None)
        if w["status"]:
            continue
        if day < today:
            w["status"] = "riposo" if w["type"] == "riposo" else "saltato"
        elif day == today:
            w["status"] = "oggi"
        else:
            w["status"] = "da fare"

    week_start = _monday(today).isoformat()
    week_end = (_monday(today) + timedelta(days=6)).isoformat()
    hard = ("qualità", "lungo", "gara")

    def kind_on(day: date) -> Optional[str]:
        """Tipo effettivo di un giorno: quello svolto se c'e' una corsa, altrimenti quello previsto."""
        k = day.isoformat()
        g = next((x for x in grades if x["date"] == k), None)
        return g["type"] if g else plan.get(k, {}).get("type")

    # fotografia dei giorni futuri prima degli adattamenti: serve a mostrare "prima -> dopo"
    baseline = {k: (w["title"], w.get("km"), w["type"]) for k, w in plan.items() if k >= today.isoformat()}

    # allenamenti rimasti senza giorno (al loro posto ne hai fatto un altro): si ridistribuiscono nella settimana
    displaced = [k for k in sorted(plan) if week_start <= k <= today.isoformat()
                 and plan[k]["status"] == "sostituito" and plan[k]["type"] not in ("riposo", "gara")]
    for dk in displaced:
        if f"displaced:{dk}" in applied:
            continue
        applied.add(f"displaced:{dk}")
        src = plan[dk]
        rests = sum(1 for k in plan if week_start <= k <= week_end and plan[k]["type"] == "riposo"
                    and plan[k]["status"] in ("riposo", "oggi", "da fare"))
        slot = None
        for k in sorted(plan):
            if not (today.isoformat() <= k <= week_end) or plan[k]["type"] != "riposo" or plan[k]["status"] not in ("oggi", "da fare"):
                continue
            day = date.fromisoformat(k)
            prev, nxt = kind_on(day - timedelta(days=1)), kind_on(day + timedelta(days=1))
            if rests <= 1 or plan[k]["d"] < 2:
                break            # resta almeno un giorno di riposo in settimana, e niente spostamenti a ridosso della gara
            if src["type"] in hard and (prev in hard or nxt in hard):
                continue         # mai due giorni duri di fila
            slot = k
            break
        if slot:
            day = date.fromisoformat(slot)
            nxt = kind_on(day + timedelta(days=1))
            moved = {x: v for x, v in src.items() if not x.startswith("done_") and x not in ("activity_id", "grade")}
            moved.update({"date": slot, "d": plan[slot]["d"], "status": plan[slot]["status"], "generated_on": today.isoformat(),
                          "adapted": f"spostato dal {date.fromisoformat(dk):%d/%m}: quel giorno hai fatto un altro allenamento"})
            if src["type"] == "facile" and nxt in hard and moved.get("km"):
                # il giorno prima di un lungo o della qualita': piu' corto e senza allunghi
                moved["km"] = round(moved["km"] * 0.8)
                moved["minutes"] = round(moved["minutes"] * 0.8) if moved.get("minutes") else None
                moved["title"] = "Facile (spostato)"
                moved["structure"] = "corsa facile, senza allunghi: domani c'è " + ("il lungo" if nxt == "lungo" else "un allenamento duro")
            plan[slot] = moved
            touched.add(slot)
            src["adapted"] = f"spostato al {day:%d/%m}"
        else:
            src["adapted"] = "non ripreso: nessun giorno libero adatto in settimana (nello scarico il volume perso non si recupera)"

    # ---- adattamenti: il piano si modula su quanto svolto davvero (solo giorni futuri)
    def note(k: str, text: str) -> None:
        plan[k]["adapted"] = f"{plan[k]['adapted']} · {text}" if plan[k].get("adapted") else text
        touched.add(k)

    def once(key: str) -> bool:
        """Ogni adattamento si applica una volta sola: poi resta salvato nel piano."""
        if key in applied:
            return False
        applied.add(key)
        return True

    def free(k: str) -> bool:
        return plan[k]["status"] in ("oggi", "da fare")

    def easy_neighbours(day: date) -> bool:
        return kind_on(day - timedelta(days=1)) not in hard and kind_on(day + timedelta(days=1)) not in hard

    def drop_rep(k: str, why: str) -> bool:
        w = plan[k]
        seg = (w.get("segments") or [None])[0]
        if not seg or seg["reps"] <= 2:
            return False
        w["segments"] = [{**seg, "reps": seg["reps"] - 1}] + w["segments"][1:]
        old, new = f"{seg['reps']}×", f"{seg['reps'] - 1}×"
        w["title"], w["structure"] = w["title"].replace(old, new), w["structure"].replace(old, new)
        if w.get("km"):
            w["km"] = round(w["km"] - seg.get("dist_km", 0), 1)
        note(k, f"{why}: una ripetuta in meno")
        return True

    def to_easy(k: str, factor: float, why: str) -> None:
        w = plan[k]
        Z = zones(ath, prof, est_for(today)["central_s"])
        km = max(4, min(12, round((w["km"] or 8) * factor)))      # un facile resta un facile
        plan[k] = {**_work(date.fromisoformat(k), w["d"], w["phase"], "facile", "Facile (adattato)", Z, km, "facile"),
                   "status": w["status"], "generated_on": today.isoformat()}
        note(k, f"{why}: {w['title'].lower()} sostituito da un facile")

    def set_km(k: str, km: float) -> None:
        w = plan[k]
        w["title"] = retitle(w["title"], w["km"] or km, km)
        w["km"] = km
        if w.get("minutes") and w.get("pace_lo"):
            w["minutes"] = round(km * (w["pace_lo"] + w["pace_hi"]) / 2 / 60)

    def postpone(k: str, why: str) -> bool:
        """Rimanda di un giorno un allenamento duro, scambiandolo con il giorno dopo se e' facile o riposo."""
        d0 = date.fromisoformat(k)
        nk = (d0 + timedelta(days=1)).isoformat()
        if not (nk in plan and free(nk) and plan[nk]["type"] in ("facile", "riposo") and plan[nk]["d"] >= 2
                and kind_on(d0 + timedelta(days=2)) not in hard):
            return False
        plan[k], plan[nk] = ({**plan[nk], "date": k, "d": plan[k]["d"], "status": plan[k]["status"]},
                             {**plan[k], "date": nk, "d": plan[nk]["d"], "status": plan[nk]["status"]})
        note(nk, f"{why}: rimandato di un giorno")
        note(k, "scambiato con l'allenamento duro, rimandato a domani")
        return True

    future = lambda: [k for k in sorted(plan) if k >= today.isoformat() and free(k)]  # noqa: E731
    last_run_day = max((g["date"] for g in grades), default=None)

    # 1) qualita' saltata questa settimana: nel primo facile utile lontano da lungo e gara
    for mk_ in [k for k in sorted(plan) if week_start <= k < today.isoformat()
                and plan[k]["type"] == "qualità" and plan[k]["status"] == "saltato"]:
        if not once(f"miss-q:{mk_}"):
            continue
        slot = next((k for k in future() if k <= week_end and plan[k]["type"] == "facile" and plan[k]["d"] >= 4
                     and easy_neighbours(date.fromisoformat(k))), None)
        if slot:
            plan[slot] = {**{x: v for x, v in plan[mk_].items() if not x.startswith("done_")}, "date": slot,
                          "d": plan[slot]["d"], "status": plan[slot]["status"], "generated_on": today.isoformat(), "adapted": None}
            note(slot, f"qualità del {date.fromisoformat(mk_):%d/%m} saltata: spostata qui")
            note(mk_, f"spostata al {date.fromisoformat(slot):%d/%m}")
        else:
            note(mk_, "non recuperata: nessun giorno libero lontano da lungo e gara (nello scarico si lascia)")

    # 2) lungo saltato negli ultimi 2 giorni: recuperato piu' corto se la gara e' abbastanza lontana
    for lk in [k for k in sorted(plan) if (today - timedelta(days=2)).isoformat() <= k < today.isoformat()
               and plan[k]["type"] == "lungo" and plan[k]["status"] == "saltato"]:
        if not once(f"miss-l:{lk}"):
            continue
        slot = next((k for k in future() if k <= (today + timedelta(days=3)).isoformat() and plan[k]["type"] == "facile"
                     and plan[k]["d"] >= max(7, prof.taper_days // 3) and easy_neighbours(date.fromisoformat(k))), None)
        if not slot and prof.is_marathon:
            # in maratona il lungo vale piu' di una seduta di soglia: ne prende il posto
            slot = next((k for k in future() if k <= (today + timedelta(days=3)).isoformat() and plan[k]["type"] == "qualità"
                         and plan[k]["d"] >= 10 and easy_neighbours(date.fromisoformat(k))), None)
        if slot:
            src = plan[lk]
            plan[slot] = {**{x: v for x, v in src.items() if not x.startswith("done_")}, "date": slot, "d": plan[slot]["d"],
                          "status": plan[slot]["status"], "generated_on": today.isoformat(), "adapted": None,
                          "title": src["title"] + " (ridotto)"}
            set_km(slot, round((src["km"] or 16) * 0.85))
            note(slot, f"lungo del {date.fromisoformat(lk):%d/%m} saltato: recuperato qui al 85%")
            note(lk, f"recuperato il {date.fromisoformat(slot):%d/%m}")
        elif plan[lk]["d"] > prof.taper_days:
            # fase di carico: il volume perso si spalma sui facili successivi, senza toccare i giorni duri
            lost = plan[lk].get("km") or 0
            # qualche km facile in piu' va bene anche vicino a una qualita', non il giorno prima di un lungo o della gara
            easy = [k for k in future() if k <= (date.fromisoformat(lk) + timedelta(days=7)).isoformat()
                    and plan[k]["type"] == "facile" and plan[k]["d"] > prof.taper_days
                    and kind_on(date.fromisoformat(k) + timedelta(days=1)) not in ("lungo", "gara")][:2]
            add = min(3, round(0.25 * lost))
            if easy and add:
                for k in easy:
                    set_km(k, plan[k]["km"] + add)
                    note(k, f"+{add} km dal lungo saltato il {date.fromisoformat(lk):%d/%m}")
                where = "sul facile successivo" if len(easy) == 1 else f"su ciascuno dei {len(easy)} facili successivi"
                note(lk, f"volume in parte recuperato: +{add} km {where}, senza aggiungere giorni duri")
            else:
                note(lk, "non recuperato: nessun facile adatto nei 7 giorni successivi")
        else:
            note(lk, "non recuperato: troppo vicino alla gara (nello scarico il volume perso non si recupera)")

    # 3) ultima corsa piu' intensa del previsto: il prossimo allenamento duro slitta di un giorno o si alleggerisce
    if last_run_day and last_run_day >= (today - timedelta(days=1)).isoformat():
        lg = [g for g in grades if g["date"] == last_run_day]
        planned_kind = plan.get(last_run_day, {}).get("type")
        hot = None
        for g in lg:
            gp = {p["component"]: p["score"] for p in parts if p["activity_id"] == g["id"]}
            if (g["type"] in ("qualità", "lungo") and planned_kind not in (g["type"], "gara")
                    and g["plan_date"] in (None, last_run_day)):
                hot = f"il {date.fromisoformat(last_run_day):%d/%m} hai fatto un {g['type']} non previsto ({planned_kind or 'nessun piano'})"
            elif g["type"] == "facile" and min(gp.get("FC sotto la soglia aerobica") or 100, gp.get("Passo nel range facile") or 100) < 50:
                hot = f"il facile del {date.fromisoformat(last_run_day):%d/%m} è stato troppo intenso"
        nxt_hard = next((k for k in future() if k <= (date.fromisoformat(last_run_day) + timedelta(days=2)).isoformat()
                         and plan[k]["type"] in ("qualità", "lungo")), None)
        if hot and nxt_hard and once(f"hot:{last_run_day}"):
            if postpone(nxt_hard, hot):
                pass
            elif plan[nxt_hard]["type"] == "qualità":
                if not drop_rep(nxt_hard, hot):
                    to_easy(nxt_hard, 0.8, hot)
            else:
                set_km(nxt_hard, round(plan[nxt_hard]["km"] * 0.85))
                note(nxt_hard, f"{hot}: lungo accorciato del 15%")

    # 4) volume della settimana sopra il previsto: si accorciano i facili rimasti (in scarico conta la fatica)
    cutoff = today.isoformat() if any(g["date"] == today.isoformat() for g in grades) else (today - timedelta(days=1)).isoformat()
    planned_sofar = sum(plan[k]["km"] or 0 for k in plan if week_start <= k <= cutoff and plan[k]["type"] not in ("riposo", "gara"))
    done_sofar = sum(g["km"] for g in grades if week_start <= g["date"] <= cutoff)
    excess = done_sofar - planned_sofar
    easy_left = [k for k in future() if cutoff < k <= week_end and plan[k]["type"] == "facile"]
    # regola di stato, non di evento: si ricalcola ogni volta partendo dai km originali del giorno
    for k in easy_left:
        if plan[k].get("km_plan") is not None:
            plan[k]["km"] = plan[k]["km_plan"]
        if plan[k].get("adapted"):
            plan[k]["adapted"] = " · ".join(x for x in plan[k]["adapted"].split(" · ") if not x.startswith("settimana a")) or None
    if excess > max(5, 0.15 * planned_sofar) and easy_left:
        cut = excess * 0.5 / len(easy_left)
        for k in easy_left:
            plan[k]["km_plan"] = plan[k]["km"]
            plan[k]["km"] = max(4, round(plan[k]["km"] - cut))
            plan[k]["minutes"] = round(plan[k]["km"] * (plan[k]["pace_lo"] + plan[k]["pace_hi"]) / 2 / 60)
            note(k, f"settimana a {done_sofar:.0f} km contro {planned_sofar:.0f} previsti: facile accorciato")
    elif planned_sofar and done_sofar < 0.7 * planned_sofar and easy_left:
        note(easy_left[0], f"settimana a {done_sofar:.0f} km contro {planned_sofar:.0f} previsti: "
                           + ("non si recupera, nello scarico conta arrivare freschi" if plan[easy_left[0]]["d"] <= prof.taper_days
                              else "la prossima settimana riparte dal volume reale (+8% al massimo)"))

    # 5) lungo piu' lungo del previsto: la qualita' successiva perde una ripetuta
    last_long = next((g for g in reversed(grades) if g["type"] == "lungo" and g["plan_date"]), None)
    if last_long:
        lw = plan.get(last_long["plan_date"])
        if lw and lw.get("km") and last_long["km"] > lw["km"] * 1.15:
            nq = next((k for k in future() if plan[k]["type"] == "qualità"), None)
            if nq and once(f"long:{last_long['date']}"):
                drop_rep(nq, f"lungo del {date.fromisoformat(last_long['date']):%d/%m} più lungo del previsto")

    # 6) recupero basso o bandiera rossa: il primo allenamento duro diventa un facile
    if rec and rec["date"] >= (today - timedelta(days=1)).isoformat():
        red = bool(json.loads(rec["recovery_json"] or "{}").get("red_flag"))
        if rec["recovery_index"] < 45 or red:
            k = next((k for k in future() if k <= (today + timedelta(days=1)).isoformat() and plan[k]["type"] in ("qualità", "lungo")), None)
            why = f"recupero {rec['recovery_index']:.0f}/100" + (" con HRV bassa e FC a riposo alta" if red else "")
            tk = today.isoformat()
            if rec["date"] == tk and tk in plan and free(tk) and plan[tk]["type"] == "facile":
                plan[tk]["warning"] = (f"{why}: oggi meglio riposo o 30' molto facili sotto {ath.vt1 - 15:.0f} bpm; "
                                       "con HRV bassa e FC a riposo alta insieme il rischio è accumulare fatica senza beneficio")
            if k and k == rec["date"] == today.isoformat():
                # il dato del mattino vale per l'allenamento di oggi: si rimanda di un giorno, o diventa un facile
                if once(f"rec:{rec['date']}") and not postpone(k, why):
                    to_easy(k, 0.7, why)
            elif k:
                # per domani solo un avviso (non salvato): decide il dato di domattina
                plan[k]["warning"] = (f"{why} il {date.fromisoformat(rec['date']):%d/%m}: se domattina il recupero è "
                                      "ancora sotto 45, rifai l'export e il piano lo rimanda di un giorno")

    # 7) carico strutturale alto con carico cardiaco basso (collina, discese): niente lavoro ad alto impatto per 48 h
    if impact:
        k = next((k for k in future() if k <= impact["until"] and plan[k]["type"] in ("qualità", "lungo")), None)
        if k and once(f"impact:{impact['until']}"):
            why = "carico strutturale alto nelle ultime 48 h (gambe sollecitate, cuore poco)"
            if plan[k]["type"] == "qualità":
                to_easy(k, 0.8, why)
            elif plan[k].get("km"):
                set_km(k, round(plan[k]["km"] * 0.85))
                note(k, f"{why}: lungo accorciato del 15%, su percorso pianeggiante e senza discese veloci")

    # com'era il giorno prima della modifica (resta nei giorni adattati anche nei ricalcoli successivi)
    for k in touched:
        b = baseline.get(k)
        w = plan.get(k)
        if not b or not w or w.get("changed_from") or (w["title"], w.get("km"), w["type"]) == b:
            continue
        w["changed_from"] = b[0] + (f" · {b[1]:g} km" if b[1] and f"{b[1]:g} km" not in b[0] else "")
        w["changed_on"] = today.isoformat()

    # 4) salva i giorni passati come proposti (con stato aggiornato) e prepara le righe
    pinned = {k: plan[k] for k in set(store["pinned"]) | touched if k in plan and k >= today.isoformat()}
    store = {"start": start.isoformat(), "days": {k: w for k, w in plan.items() if date.fromisoformat(k) < today},
             "pinned": pinned, "applied": sorted(applied)}
    db.set_setting(conn, STORE_KEY.format(goal["id"]), store)
    conn.commit()
    rows = []
    for k in sorted(plan):
        w = plan[k]
        rows.append({
            "date": k, "week": _monday(date.fromisoformat(k)).isoformat(), "d": w["d"], "phase": w["phase"],
            "type": w["type"], "title": w["title"], "purpose": w["purpose"], "km": w["km"], "minutes": w["minutes"],
            "pace_lo": w["pace_lo"], "pace_hi": w["pace_hi"], "hr_lo": w["hr_lo"], "hr_hi": w["hr_hi"],
            "structure": w["structure"], "notes": w["notes"], "status": w["status"],
            "activity_id": w.get("activity_id"), "grade": w.get("grade"), "adapted": w.get("adapted"),
            "done_km": w.get("done_km"), "done_pace_s": w.get("done_pace_s"), "done_hr": w.get("done_hr"),
            "done_note": w.get("done_note"), "warning": w.get("warning"),
            "generated_on": w.get("generated_on"), "changed_from": w.get("changed_from"), "changed_on": w.get("changed_on"),
        })
    taper_rows = []
    for b in taper["blocks"]:
        keys = [(race_day - timedelta(days=d)).isoformat() for d in b["days"]]
        planned = sum(plan[k].get("km") or 0 for k in keys if k in plan and plan[k]["type"] != "riposo")
        taper_rows.append({"block": b["block"], "start": b["from"], "end": b["to"], "target_km": b["target_km"],
                           "planned_km": round(planned, 1), "reduction_pct": b["reduction_pct"],
                           "pre_taper_week_km": round(taper["v0"], 1), "final_cut_pct": round(100 * taper["final_cut"]),
                           "taper_days": taper["T"]})
    return {"plan": rows, "grades": grades, "grade_parts": parts, "zones": zone_rows(Zt), "taper_plan": taper_rows}
