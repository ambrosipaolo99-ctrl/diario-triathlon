"""
Readiness a due sistemi per la corsa: autonomo (ANS) qui, neuromuscolare (CNS) sul telefono.

System 1, ANS
  punteggio 0-100 dalle componenti dell'indice di recupero: HRV notturna 50%, FC a riposo 25%, sonno 25%,
  ognuna gia' confrontata con la baseline personale di 60 giorni. Allenarsi seguendo l'HRV produce adattamenti
  pari o migliori del piano fisso con meno giorni duri [EMERGENTE]. "Alto" se il punteggio e' >= 60 senza la
  bandiera rossa (HRV molto sotto e FC a riposo molto sopra insieme).

System 2, CNS (web app, salvato solo sul dispositivo)
  tapping test di 10 s sul touchscreen [PRELIMINARE MA RILEVANTE] o salto CMJ in cm inserito a mano
  [EMERGENTE nei runner, CONSOLIDATO negli sport di squadra]; "basso" se il valore del giorno e' sotto la media
  personale degli ultimi 28 giorni di piu' di mezza deviazione standard (almeno 5 test per la baseline).

Matrice (la compone la pagina, che conosce entrambi i sistemi)
  ANS alto / CNS alto   verde   qualita', ritmo maratona, ripetute
  ANS alto / CNS basso  giallo  lento Z2 o rigenerante; niente ritmi veloci o lavori reattivi
  ANS basso / CNS alto  giallo  brevi richiami a ritmo gara; niente lunghissimi
  ANS basso / CNS basso rosso   riposo attivo, camminata o scarico totale
  La protezione strutturale (load_vectors) toglie comunque i lavori ad alto impatto.

Righe esportate (readiness)
  date, ans_score, ans_state (alto/basso), c_hrv, c_rhr, c_sleep, red_flag, recovery, impact_block, impact_reason
"""
from __future__ import annotations

import json
import sqlite3
from typing import Optional

ANS_WEIGHTS = {"hrv": 0.5, "rhr": 0.25, "sleep": 0.25}
ANS_HIGH = 60


def ans_score(components: dict) -> Optional[float]:
    avail = {k: components.get(k) for k in ANS_WEIGHTS if components.get(k) is not None}
    if "hrv" not in avail:
        return None                 # senza HRV non si giudica il sistema autonomo
    tot = sum(ANS_WEIGHTS[k] for k in avail)
    return round(sum(ANS_WEIGHTS[k] * v for k, v in avail.items()) / tot, 1)


def rows(conn: sqlite3.Connection, since: str, daily_load: list[dict]) -> list[dict]:
    block = {r["date"]: r for r in daily_load}
    out = []
    for r in conn.execute("SELECT date, recovery_index, recovery_json FROM wellness_daily "
                          "WHERE date >= ? AND recovery_json IS NOT NULL ORDER BY date", (since,)):
        d = json.loads(r["recovery_json"] or "{}")
        comp = d.get("components", {})
        score = ans_score(comp)
        red = bool(d.get("red_flag"))
        b = block.get(r["date"], {})
        out.append({
            "date": r["date"], "ans_score": score,
            "ans_state": None if score is None else "alto" if score >= ANS_HIGH and not red else "basso",
            "c_hrv": comp.get("hrv"), "c_rhr": comp.get("rhr"), "c_sleep": comp.get("sleep"), "red_flag": red,
            "recovery": r["recovery_index"], "impact_block": bool(b.get("impact_block")), "impact_reason": b.get("reason"),
        })
    return out
