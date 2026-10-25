"""
Tipi del piano "Road to Race" (documentazione dei dizionari usati da coach.py ed esportati alla dashboard).

Flusso a ogni sincronizzazione (07:15, 19:15, pulsante "Aggiorna"): le attivita' nuove entrano nel database,
coach() ricostruisce il piano (giorni passati congelati, futuri ricalcolati), applica lo scarico esponenziale,
abbina le corse ai giorni, applica gli adattamenti (una volta sola ciascuno) e salva lo stato in `plan:<goal_id>`.
"""
from __future__ import annotations

from typing import Literal, Optional, TypedDict

WorkoutType = Literal["facile", "qualità", "lungo", "gara", "riposo"]
Status = Literal["svolto", "svolto (spostato)", "svolto (anticipato)", "svolto (altro tipo)", "sostituito",
                 "corsa extra", "saltato", "riposo", "oggi", "da fare"]


class RaceTarget(TypedDict):
    """Un obiettivo di data/goals.json."""
    id: str
    name: str
    date: str                       # AAAA-MM-GG
    discipline: str                 # corsa / triathlon / ...
    distance: str                   # etichetta: 5 km, 10 km, Mezza maratona, Maratona
    distance_km: float
    priority: Literal["A", "B", "C"]


class TaperBlock(TypedDict):
    """Un blocco dello scarico esponenziale (riga del dataset taper_plan)."""
    block: str                      # Settimana gara / Scarico 2 / Scarico 1
    start: str
    end: str
    target_km: float                # volume obiettivo della curva V(d) = V0/7 e^(-k (T - d))
    planned_km: float               # volume del piano dopo adattamenti
    reduction_pct: int              # rispetto al volume pre-scarico
    pre_taper_week_km: float        # V0
    final_cut_pct: int              # 45 (5k) / 50 (10k) / 55 (mezza) / 60 (maratona)
    taper_days: int                 # 7 / 10 / 14 / 21


class Segment(TypedDict):
    zone: str                       # facile, lungo, gara, soglia, vo2
    reps: int
    dist_km: float
    rec_min: float
    pace_lo: float                  # s/km
    pace_hi: float
    hr_lo: float
    hr_hi: float


class PlannedWorkout(TypedDict, total=False):
    """Un giorno del piano (riga del dataset goal_plan)."""
    date: str
    d: int                          # giorni alla gara
    phase: str                      # Carico / Scarico 1 / Scarico 2 / Settimana gara
    type: WorkoutType
    title: str
    purpose: str                    # obiettivo fisiologico con etichetta di evidenza
    km: Optional[float]
    minutes: Optional[int]
    pace_lo: Optional[float]
    pace_hi: Optional[float]
    hr_lo: Optional[int]
    hr_hi: Optional[int]
    structure: str
    segments: list[Segment]
    notes: str                      # alimentazione, gara
    status: Status
    activity_id: Optional[str]      # corsa abbinata
    grade: Optional[int]
    adapted: Optional[str]          # motivo dell'adattamento
    changed_from: Optional[str]     # com'era prima dell'adattamento
    changed_on: Optional[str]       # quando e' cambiato
    warning: Optional[str]          # avviso non salvato (es. recupero basso)
