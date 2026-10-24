"""
Allenamenti di oggi per la prima pagina della dashboard.

Si esportano gli ultimi giorni e la pagina mostra quelli con la data di oggi (di chi guarda).
Corsa, voto del preparatore in due blocchi:
  Esecuzione dell'allenamento  70%  voto del piano (coach.py): la seduta giusta, fatta come previsto
  Tecnica e tenuta             30%  cadenza, contatto al suolo, rimbalzo, resistenza alla fatica
Intensita', efficienza e ritmo dell'analisi tecnica restano fuori: il voto del piano li valuta gia'
sui target del tipo di seduta (FC, passo, deriva). Senza obiettivo attivo l'esecuzione usa quelle tre
sezioni. Bici e nuoto: voto e sezioni dell'analisi; le altre attivita' non hanno voto.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import date, timedelta
from typing import Optional

W_EXEC, W_TECH = 70, 30
TECH = ("Cadenza", "Contatto al suolo", "Rimbalzo verticale", "Resistenza alla fatica")
EXEC_FALLBACK = ("Controllo intensita'", "Efficienza aerobica", "Gestione del ritmo")
SPORT_IT = {"run": "Corsa", "bike": "Bici", "swim": "Nuoto", "other": "Altro"}
TYPE_IT = {"facile": "Facile", "qualità": "Qualità", "lungo": "Lungo", "gara": "Gara"}


def _avg(comps: list[dict]) -> Optional[float]:
    rated = [c for c in comps if c.get("score") is not None]
    tot = sum(c["weight"] for c in rated)
    return sum(c["score"] * c["weight"] for c in rated) / tot if tot else None


def _part(aid: str, group: str, i: int, c: dict, tot: float) -> dict:
    return {"key": f"{aid}-{group[0]}{i}", "activity_id": aid, "group": group, "component": c["name"],
            "weight": round(c["weight"] / tot * 100) if c.get("score") is not None and tot else 0,
            "score": None if c.get("score") is None else round(c["score"]),
            "value": None if c.get("value") is None else str(c["value"]), "note": c.get("note")}


def _group(aid: str, group: str, comps: list[dict]) -> tuple[Optional[float], list[dict]]:
    tot = sum(c["weight"] for c in comps if c.get("score") is not None)
    return _avg(comps), [_part(aid, group, i, c, tot) for i, c in enumerate(comps)]


def today_rows(conn: sqlite3.Connection, grades: list[dict], grade_parts: list[dict],
               days: int = 7, today: Optional[date] = None) -> tuple[list[dict], list[dict]]:
    today = today or date.today()
    since = (today - timedelta(days=days - 1)).isoformat()
    by_id = {g["id"]: g for g in grades}
    rows, parts = [], []
    q = ("SELECT * FROM activities WHERE start_local >= ? AND is_parent=0 AND duplicate_of IS NULL "
         "ORDER BY start_local")
    for r in conn.execute(q, (since,)):
        aid = str(r["activity_id"])
        res = json.loads(r["metrics_json"] or "{}")
        m = res.get("metrics", {})
        comps = res.get("components", [])
        row = {"id": aid, "date": r["start_local"][:10], "start": r["start_local"], "sport": r["sport"],
               "sport_label": SPORT_IT.get(r["sport"], r["sport"]), "name": r["name"],
               "duration_min": (r["duration_s"] or 0) / 60, "distance_km": (r["distance_m"] or 0) / 1000,
               "avg_hr": m.get("avg_hr") or r["avg_hr"], "tss": r["tss"], "pace": m.get("avg_pace"),
               "treadmill": m.get("treadmill"), "ascent_m": m.get("ascent_m"), "ascent_source": m.get("ascent_source"),
               "hilly": m.get("hilly"), "score": None, "exec_score": None, "tech_score": None,
               "exec_weight": None, "tech_weight": None, "kind": None, "plan_title": None, "comment": None}
        if r["sport"] == "run":
            g = by_id.get(aid)
            if g:
                ex = [{"name": p["component"], "weight": p["weight"], "score": p["score"], "value": p["value"],
                       "note": p["note"]} for p in grade_parts if p["activity_id"] == aid]
                row.update({"kind": TYPE_IT.get(g["type"], g["type"]), "plan_title": g["plan_title"] if g["type_source"] == "piano" else None,
                            "comment": g["comment"]})
            else:
                ex = [c for c in comps if c["name"] in EXEC_FALLBACK]
            exec_s, p1 = _group(aid, "Esecuzione dell'allenamento", ex)
            tech_s, p2 = _group(aid, "Tecnica e tenuta", [c for c in comps if c["name"] in TECH])
            if g and g.get("score") is not None:
                exec_s = g["score"]
            ws = [(s, w) for s, w in ((exec_s, W_EXEC), (tech_s, W_TECH)) if s is not None]
            tw = sum(w for _, w in ws)
            row.update({"exec_score": None if exec_s is None else round(exec_s),
                        "tech_score": None if tech_s is None else round(tech_s),
                        "exec_weight": round(W_EXEC / tw * 100) if exec_s is not None and tw else 0,
                        "tech_weight": round(W_TECH / tw * 100) if tech_s is not None and tw else 0,
                        "score": round(sum(s * w for s, w in ws) / tw) if tw else None})
            weak = min((p for p in p2 if p["score"] is not None), key=lambda p: p["score"], default=None)
            if weak and weak["score"] < 60:
                row["comment"] = ((row["comment"] or "") + f" Tecnica: da curare {weak['component'].lower()} "
                                  f"({weak['note']}).").strip()
            parts += p1 + p2
        elif comps:
            sc, p = _group(aid, "Valutazione", comps)
            row["score"] = r["score"] if r["score"] is not None else (None if sc is None else round(sc))
            parts += p
        rows.append(row)
    return rows, parts
