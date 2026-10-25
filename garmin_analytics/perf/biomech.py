"""
Biomechanical drift & asymmetry: come cede il gesto con la fatica.

Confronto ultimo terzo vs primo terzo della corsa, dopo i primi 5 minuti, sui tratti in movimento:
  cadenza (calo), contatto al suolo GCT (aumento), oscillazione verticale (aumento), bilanciamento del
  contatto sx/dx (scostamento da 50/50 e suo spostamento). Nelle ripetute si confrontano solo i tratti veloci.
  Contatto e cadenza dipendono dalla velocita': se il passo cambia piu' del 4% il confronto lo dichiara.

Soglie [PRELIMINARE MA RILEVANTE]: il legame tra asimmetria misurata dal sensore e infortunio non e' dimostrato
in modo solido; un'asimmetria che compare o cresce con la fatica e' pero' un segnale utile da osservare.
Tarate sullo storico: il bilanciamento oscilla di 1-2 punti tra un terzo e l'altro anche senza fatica.
  asimmetria   ultimo terzo oltre 1,5 punti da 50/50, spostato di >= 1,5 punti e lontano dall'equilibrio
  cadenza      calo >= 3%      contatto  aumento >= 4%      oscillazione  aumento >= 5%
               (solo a passo stabile, +-4%: rallentando cadenza e contatto cambiano da soli)
  allerta      asimmetria, oppure almeno due segnali insieme

Righe esportate (biomech)
  id, date, km, has_balance, cad_first, cad_last, cad_chg, gct_first, gct_last, gct_chg, vo_first, vo_last,
  vo_chg, bal_first, bal_last, speed_chg, flags, alert, note
"""
from __future__ import annotations

from typing import Optional

import numpy as np

from .common import RunDetail

MIN_POINTS = 60          # 30 minuti
SKIP = 10                # primi 5 minuti
ASYM_DEV = 1.5           # punti percentuali da 50/50 nel finale
ASYM_SHIFT = 1.5         # spostamento minimo rispetto al primo terzo


def _mean(pts: list[dict], k: str) -> Optional[float]:
    v = [p[k] for p in pts if p.get(k)]
    return float(np.mean(v)) if len(v) >= max(5, len(pts) // 3) else None


def _chg(a: Optional[float], b: Optional[float]) -> Optional[float]:
    return round((b / a - 1) * 100, 1) if a and b else None


def analyse(r: RunDetail) -> Optional[dict]:
    pts = [p for p in r.stream[SKIP:] if p.get("pace_s") and p.get("cad")]
    if len(pts) < MIN_POINTS or not any(p.get("gct") for p in pts):
        return None
    if not r.steady:
        cut = np.quantile([p["pace_s"] for p in pts], 0.4)
        pts = [p for p in pts if p["pace_s"] <= cut]       # solo i tratti veloci delle ripetute
        if len(pts) < 30:
            return None
    n = len(pts) // 3
    a, b = pts[:n], pts[-n:]
    row = {"id": r.id, "date": r.day.isoformat(), "km": round(r.km, 2)}
    for k, name in (("cad", "cad"), ("gct", "gct"), ("vo", "vo")):
        f, l = _mean(a, k), _mean(b, k)
        row.update({f"{name}_first": None if f is None else round(f, 1), f"{name}_last": None if l is None else round(l, 1),
                    f"{name}_chg": _chg(f, l)})
    bf, bl = _mean(a, "gct_bal"), _mean(b, "gct_bal")
    row.update({"has_balance": bf is not None and bl is not None,
                "bal_first": None if bf is None else round(bf, 2), "bal_last": None if bl is None else round(bl, 2)})
    sa, sb = np.mean([1000 / p["pace_s"] for p in a]), np.mean([1000 / p["pace_s"] for p in b])
    row["speed_chg"] = round((sb / sa - 1) * 100, 1)

    flags = []
    if (bf is not None and bl is not None and abs(bl - 50) >= ASYM_DEV and abs(bl - bf) >= ASYM_SHIFT
            and abs(bl - 50) > abs(bf - 50)):
        side = "sinistra" if bl > 50 else "destra"
        flags.append(f"asimmetria nel finale: {bl:.1f}% sx / {100 - bl:.1f}% dx (era {bf:.1f}%), "
                     f"piu' tempo d'appoggio a {side}")
    steady_pace = abs(row["speed_chg"]) <= 4
    if steady_pace and row["cad_chg"] is not None and row["cad_chg"] <= -3:
        flags.append(f"cadenza in calo {row['cad_chg']:+.1f}%")
    if steady_pace and row["gct_chg"] is not None and row["gct_chg"] >= 4:
        flags.append(f"contatto al suolo in aumento {row['gct_chg']:+.1f}%")
    if steady_pace and row["vo_chg"] is not None and row["vo_chg"] >= 5:
        flags.append(f"oscillazione verticale in aumento {row['vo_chg']:+.1f}%")
    asym = bool(flags) and flags[0].startswith("asimmetria")
    alert = asym or len(flags) >= 2
    pace_note = (f" Il passo nel finale e' cambiato del {row['speed_chg']:+.1f}%: cadenza e contatto non si "
                 "confrontano, dipendono dalla velocita'." if not steady_pace else "")
    if alert:
        note = ("Biomechanical Fatigue Alert: " + "; ".join(flags) + ". Con la fatica il gesto si sbilancia: e' un "
                "possibile compenso (catena posteriore, anca o caviglia), non una diagnosi. Se si ripete nei lunghi, "
                "accorcia la parte finale e valuta il gesto con un fisioterapista [PRELIMINARE MA RILEVANTE]." + pace_note)
    elif flags:
        note = "Segnale isolato: " + flags[0] + "." + pace_note
    else:
        note = "Gesto stabile fino alla fine." + pace_note
    if not row["has_balance"]:
        note += " Bilanciamento sx/dx nel tempo non disponibile per questa corsa."
    row.update({"flags": "; ".join(flags) or None, "alert": alert, "note": note})
    return row


def rows(runs: list[RunDetail]) -> list[dict]:
    return [x for x in (analyse(r) for r in runs) if x]
