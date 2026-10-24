"""Carico di allenamento: TSS giornaliero, CTL (cronico 42 gg), ATL (acuto 7 gg), TSB e ACWR."""
from __future__ import annotations

import sqlite3
from datetime import date
from typing import Optional

import pandas as pd

from . import db

CTL_DAYS = 42
ATL_DAYS = 7


def daily_tss(conn: sqlite3.Connection) -> pd.DataFrame:
    """TSS per giorno e per sport: frazioni dei multisport incluse, genitori e duplicati esclusi."""
    df = db.read_df(conn, "SELECT start_local, sport, tss FROM activities "
                          "WHERE is_parent=0 AND duplicate_of IS NULL AND tss IS NOT NULL AND start_local IS NOT NULL")
    if df.empty:
        return pd.DataFrame(columns=["total"])
    df["date"] = pd.to_datetime(df["start_local"]).dt.normalize()
    wide = df.pivot_table(index="date", columns="sport", values="tss", aggfunc="sum", fill_value=0)
    wide["total"] = wide.sum(axis=1)
    return wide


def pmc(conn: sqlite3.Connection, until: Optional[date] = None) -> pd.DataFrame:
    """
    Performance Management Chart (modello di Banister/Coggan):
      CTL_t = CTL_t-1 + (TSS_t - CTL_t-1) / 42      (fitness)
      ATL_t = ATL_t-1 + (TSS_t - ATL_t-1) / 7       (fatica)
      TSB_t = CTL_t-1 - ATL_t-1                     (forma del mattino)
      ACWR  = ATL / CTL                             (rapporto acuto:cronico; 0.8-1.3 zona "sicura")
    Le prime ~6 settimane sono sottostimate: conviene sincronizzare almeno 120 giorni.
    """
    d = daily_tss(conn)
    if d.empty:
        return pd.DataFrame(columns=["tss", "ctl", "atl", "tsb", "acwr"])
    end = pd.Timestamp(until or date.today())
    idx = pd.date_range(d.index.min(), max(end, d.index.max()), freq="D")
    tss = d["total"].reindex(idx, fill_value=0.0)
    out = pd.DataFrame({"tss": tss})
    out["ctl"] = tss.ewm(alpha=1 / CTL_DAYS, adjust=False).mean()
    out["atl"] = tss.ewm(alpha=1 / ATL_DAYS, adjust=False).mean()
    out["tsb"] = out["ctl"].shift(1) - out["atl"].shift(1)
    out["acwr"] = (out["atl"] / out["ctl"]).where(out["ctl"] > 1)
    return out
