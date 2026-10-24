"""Download, cache e parsing dei file .FIT originali."""
from __future__ import annotations

import io
import logging
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional

import pandas as pd
from fitparse import FitFile

from .auth import throttled
from .config import FIT_DIR

log = logging.getLogger("garmin_analytics.fit")

RECORD_FIELDS = [
    "timestamp", "heart_rate", "power", "cadence", "fractional_cadence", "enhanced_speed", "speed",
    "distance", "enhanced_altitude", "altitude", "left_right_balance", "stance_time",
    "stance_time_balance", "vertical_oscillation", "vertical_ratio", "step_length",
    "left_torque_effectiveness", "right_torque_effectiveness",
    "left_pedal_smoothness", "right_pedal_smoothness", "temperature", "total_cycles",
]


@dataclass
class FitSession:
    """Una sessione del file (le attivita' multisport ne contengono una per frazione)."""
    index: int
    sport: str
    sub_sport: str
    start: datetime                      # UTC
    end: datetime
    summary: dict[str, Any]
    records: pd.DataFrame
    laps: list[dict[str, Any]]
    lengths: list[dict[str, Any]]
    workout_steps: list[dict[str, Any]]
    zones_target: dict[str, Any]


@dataclass
class FitActivity:
    path: Path
    sessions: list[FitSession] = field(default_factory=list)


def fit_path(activity_id: int) -> Path:
    return FIT_DIR / f"{activity_id}.fit"


def download_fit(api, activity_id: int, force: bool = False) -> Path:
    """Scarica il file originale (zip) una sola volta e ne estrae il .fit."""
    path = fit_path(activity_id)
    if path.exists() and not force:
        return path
    FIT_DIR.mkdir(parents=True, exist_ok=True)
    data = throttled(api.download_activity, activity_id, dl_fmt=api.ActivityDownloadFormat.ORIGINAL)
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        fits = [n for n in zf.namelist() if n.lower().endswith(".fit")]
        if not fits:
            raise ValueError(f"Nessun file .fit nell'archivio dell'attivita' {activity_id}")
        # se ci sono piu' file (raro) si tiene il piu' grande, che contiene i record
        name = max(fits, key=lambda n: zf.getinfo(n).file_size)
        path.write_bytes(zf.read(name))
    log.info("FIT salvato: %s", path)
    return path


def _clean(values: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in values.items() if v is not None and not k.startswith("unknown_")}


def parse_fit(path: Path) -> FitActivity:
    ff = FitFile(str(path))
    records, laps, lengths, sessions, steps = [], [], [], [], []
    zones: dict[str, Any] = {}
    for msg in ff.get_messages(["record", "lap", "length", "session", "workout_step", "zones_target"]):
        vals = msg.get_values()
        if msg.name == "record":
            records.append({k: vals.get(k) for k in RECORD_FIELDS if vals.get(k) is not None})
        elif msg.name == "lap":
            laps.append(_clean(vals))
        elif msg.name == "length":
            lengths.append(_clean(vals))
        elif msg.name == "session":
            sessions.append(_clean(vals))
        elif msg.name == "workout_step":
            steps.append(_clean(vals))
        elif msg.name == "zones_target":
            zones.update(_clean(vals))

    rec = pd.DataFrame(records)
    if not rec.empty:
        rec["timestamp"] = pd.to_datetime(rec["timestamp"])
        if "enhanced_speed" in rec:
            rec["speed"] = rec["enhanced_speed"].combine_first(rec.get("speed", pd.Series(dtype=float)))
        if "enhanced_altitude" in rec:
            rec["altitude"] = rec["enhanced_altitude"].combine_first(rec.get("altitude", pd.Series(dtype=float)))
        rec = rec.drop(columns=[c for c in ("enhanced_speed", "enhanced_altitude") if c in rec])
        rec = rec.sort_values("timestamp").drop_duplicates("timestamp", keep="last").reset_index(drop=True)

    act = FitActivity(path=path)
    for i, s in enumerate(sorted(sessions, key=lambda s: s["start_time"])):
        start = s["start_time"]
        end = start + timedelta(seconds=float(s.get("total_elapsed_time") or 0))

        def in_window(t: Optional[datetime]) -> bool:
            return t is not None and start <= t <= end

        sess_rec = rec[(rec["timestamp"] >= start) & (rec["timestamp"] <= end)].reset_index(drop=True) \
            if not rec.empty else rec
        act.sessions.append(FitSession(
            index=i,
            sport=str(s.get("sport", "generic")),
            sub_sport=str(s.get("sub_sport", "generic")),
            start=start,
            end=end,
            summary=s,
            records=sess_rec,
            laps=[l for l in laps if in_window(l.get("start_time"))],
            lengths=[l for l in lengths if in_window(l.get("start_time"))],
            workout_steps=steps,
            zones_target=zones,
        ))
    return act


def load_activity_fit(api, activity_id: int, force_download: bool = False) -> FitActivity:
    return parse_fit(download_fit(api, activity_id, force=force_download))
