"""
Glycogen depletion & fuel engine: carboidrati e grassi bruciati in corsa e target di ripristino.

Energia      costo netto della corsa ~1 kcal per kg per km, quasi indipendente dal passo [CONSOLIDATO]
Substrati    quota di carboidrati per tratto di 30 s secondo la FC rispetto alle soglie [EMERGENTE]:
               <= 80% di LT1 40% · LT1 55% · LTHR 85% · LTHR + 8 bpm 98%  (interpolazione lineare)
             il crossover (piu' carboidrati al crescere dell'intensita') e' [CONSOLIDATO]; i valori esatti
             variano molto tra persone e con l'allenamento.
Conversione  4 kcal per g di carboidrati, 9 kcal per g di grassi
Glicogeno    scorta stimata ~7 g/kg (muscolo + fegato, ampia variabilita' 350-700 g) [EMERGENTE]; gel e
             bevande presi in corsa non sono noti, quindi il consumo e' un massimo.
Ripristino   se la corsa ha consumato >= 1,5 g/kg o domani c'e' un allenamento duro: 1,0-1,2 g/kg/h nelle
             prime 4 h; altrimenti un pasto con ~1 g/kg entro 2 h; con 0,3 g/kg di proteine [CONSOLIDATO].

Righe esportate (fuel)
  id, date, kcal, cho_g, fat_g, cho_pct, cho_easy_g, cho_steady_g, cho_hard_g, glycogen_store_g,
  glycogen_used_pct, target_2h_g, protein_g, urgent, target_text
"""
from __future__ import annotations

from datetime import timedelta
from typing import Optional

import numpy as np

from ..race import Athlete
from .common import RunDetail

KCAL_PER_KG_KM = 1.0
GLYCOGEN_G_PER_KG = 7.0
HARD = ("qualità", "lungo", "gara")


def cho_fraction(hr: Optional[float], ath: Athlete) -> float:
    if not hr:
        return 0.65
    lt1, lt2 = ath.vt1, ath.lthr
    return float(np.interp(hr, [0.8 * lt1, lt1, lt2, lt2 + 8], [0.40, 0.55, 0.85, 0.98]))


def run_fuel(r: RunDetail, ath: Athlete, weight: float, next_hard: bool) -> Optional[dict]:
    pts = [p for p in r.stream if p.get("dist_km") is not None]
    if len(pts) < 4:
        return None
    kcal = cho = fat = 0.0
    dom = {"easy": 0.0, "steady": 0.0, "hard": 0.0}
    prev = 0.0
    for p in pts:
        km = max(0.0, p["dist_km"] - prev)
        prev = p["dist_km"]
        e = weight * km * KCAL_PER_KG_KM
        f = cho_fraction(p.get("hr"), ath)
        kcal += e
        cho += e * f / 4
        fat += e * (1 - f) / 9
        hr = p.get("hr") or 0
        dom["hard" if hr >= ath.lthr else "steady" if hr >= ath.vt1 else "easy"] += e * f / 4
    store = GLYCOGEN_G_PER_KG * weight
    urgent = cho >= 1.5 * weight or next_hard
    target = round(max(1.0 * weight, min(cho, 2.0 * weight))) if urgent else round(1.0 * weight)
    protein = round(0.3 * weight)
    why = ", domani c'è un allenamento duro" if next_hard else ""
    text = (f"Integrazione minima consigliata: {target} g di carboidrati nelle prime 2 ore "
            f"(1,0-1,2 g/kg/h fino a 4 h{why}) "
            f"+ {protein} g di proteine [CONSOLIDATO]." if urgent else
            f"Pasto normale entro 2 ore con circa {target} g di carboidrati e {protein} g di proteine: "
            "il glicogeno si ricostituisce con l'alimentazione della giornata [CONSOLIDATO].")
    return {"id": r.id, "date": r.day.isoformat(), "kcal": round(kcal), "cho_g": round(cho), "fat_g": round(fat),
            "cho_pct": round(100 * cho * 4 / kcal) if kcal else None,
            "cho_easy_g": round(dom["easy"]), "cho_steady_g": round(dom["steady"]), "cho_hard_g": round(dom["hard"]),
            "glycogen_store_g": round(store), "glycogen_used_pct": round(100 * cho / store),
            "target_2h_g": target, "protein_g": protein, "urgent": bool(urgent), "target_text": text}


def rows(runs: list[RunDetail], ath: Athlete, weight: float, plan: list[dict]) -> list[dict]:
    hard_days = {p["date"] for p in plan if p.get("type") in HARD}
    out = []
    for r in runs:
        nxt = (r.day + timedelta(days=1)).isoformat()
        row = run_fuel(r, ath, weight, nxt in hard_days)
        if row:
            out.append(row)
    return out
