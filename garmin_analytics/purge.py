"""Cancellazione dei dati precedenti a una data (database + file FIT), con copia di sicurezza."""
from __future__ import annotations

import shutil
import sqlite3
from datetime import datetime

from . import db
from .config import DB_PATH
from .fitdata import fit_path


def purge_before(day: str, dry_run: bool = True, conn: sqlite3.Connection | None = None) -> dict:
    conn = conn or db.connect()
    acts = [r["activity_id"] for r in conn.execute(
        "SELECT activity_id FROM activities WHERE COALESCE(start_local, start_gmt) < ? "
        "OR parent_id IN (SELECT activity_id FROM activities WHERE COALESCE(start_local, start_gmt) < ?)",
        (day, day))]
    n_well = conn.execute("SELECT COUNT(*) FROM wellness_daily WHERE date < ?", (day,)).fetchone()[0]
    fits = [fit_path(a) for a in acts if fit_path(a).exists()]
    out = {"activities": len(acts), "wellness_days": n_well, "fit_files": len(fits), "backup": None}
    if dry_run:
        return out
    backup = DB_PATH.with_name(f"garmin_backup_{datetime.now():%Y%m%d_%H%M%S}.db")
    conn.commit()
    shutil.copy2(DB_PATH, backup)
    out["backup"] = str(backup)
    conn.executemany("DELETE FROM activities WHERE activity_id=?", [(a,) for a in acts])
    conn.execute("DELETE FROM wellness_daily WHERE date < ?", (day,))
    conn.commit()
    for f in fits:
        f.unlink(missing_ok=True)
    return out
