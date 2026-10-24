"""
Modulo 3 - Trend e grafici (plotly, export HTML + PNG + CSV dei dati).

Regola di lettura: niente grafici a doppio asse. Grandezze con scale diverse
(carico, HRV, sonno) stanno in pannelli sovrapposti con l'asse del tempo condiviso,
cosi' l'allineamento temporale e' esatto senza inventare correlazioni di scala.
"""
from __future__ import annotations

import json
import logging
import sqlite3
from datetime import date, timedelta
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from . import db
from .config import REPORT_DIR
from .load import pmc

log = logging.getLogger("garmin_analytics.trends")

# palette di riferimento (ordine fisso, validato per daltonismo) e inchiostri
C1, C2, C3 = "#2a78d6", "#eb6834", "#1baf7a"     # blu, arancio, acqua
INK, INK2, MUTED = "#0b0b0b", "#52514e", "#898781"
SURFACE, GRID, AXIS = "#fcfcfb", "#e1e0d9", "#c3c2b7"
BAND = "rgba(42,120,214,0.10)"
FONT = "system-ui, -apple-system, Segoe UI, sans-serif"


def _style(fig: go.Figure, title: str, height: int) -> go.Figure:
    fig.update_layout(
        title=dict(text=title, x=0, xanchor="left", font=dict(size=18, color=INK)),
        height=height, paper_bgcolor=SURFACE, plot_bgcolor=SURFACE,
        font=dict(family=FONT, size=13, color=INK2),
        margin=dict(l=64, r=24, t=72, b=48),
        hovermode="x unified", hoverlabel=dict(bgcolor="white", font=dict(color=INK)),
        legend=dict(orientation="h", yanchor="bottom", y=1.0, xanchor="right", x=1, font=dict(color=INK2)),
        bargap=0.25,
    )
    fig.update_xaxes(showgrid=False, linecolor=AXIS, tickfont=dict(color=MUTED),
                     showspikes=True, spikemode="across", spikethickness=1, spikecolor=AXIS, spikedash="solid")
    fig.update_yaxes(gridcolor=GRID, zeroline=False, linecolor=AXIS, tickfont=dict(color=MUTED),
                     title_font=dict(color=INK2, size=12))
    return fig


def _export(fig: go.Figure, data: pd.DataFrame, name: str, out_dir: Path, png: bool) -> dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = {"html": out_dir / f"{name}.html", "csv": out_dir / f"{name}.csv"}
    fig.write_html(paths["html"], include_plotlyjs="cdn", full_html=True)
    data.to_csv(paths["csv"], index=True)          # vista tabellare dei dati del grafico
    if png:
        try:
            fig.write_image(out_dir / f"{name}.png", width=1400, height=fig.layout.height or 700, scale=2)
            paths["png"] = out_dir / f"{name}.png"
        except Exception as exc:
            log.warning("PNG non generato per %s (%s). Serve kaleido>=1 e Chrome: "
                        "'pip install -U kaleido' e poi 'plotly_get_chrome'.", name, exc)
    return paths


def _activities(conn: sqlite3.Connection, sport: str, since: str) -> pd.DataFrame:
    df = db.read_df(conn, "SELECT activity_id, start_local, name, score, tss, metrics_json FROM activities "
                          "WHERE sport=? AND is_parent=0 AND duplicate_of IS NULL AND metrics_json IS NOT NULL "
                          "AND start_local >= ? ORDER BY start_local", (sport, since))
    if df.empty:
        return df
    df["date"] = pd.to_datetime(df["start_local"])
    df["m"] = df["metrics_json"].map(lambda s: json.loads(s).get("metrics", {}))
    return df.drop(columns="metrics_json")


# --------------------------------------------------------------------------- #
# FTP / potenza
# --------------------------------------------------------------------------- #
def plot_ftp(conn: sqlite3.Connection, days: int = 365, out_dir: Path = REPORT_DIR, png: bool = True):
    since = (date.today() - timedelta(days=days)).isoformat()
    df = _activities(conn, "bike", since)
    if df.empty:
        log.warning("Nessuna uscita in bici analizzata.")
        return None
    df = df[df["m"].map(lambda m: m.get("has_power"))]
    if df.empty:
        log.warning("Nessuna uscita con potenza.")
        return None
    data = pd.DataFrame({
        "date": df["date"].dt.normalize(),
        "ftp_garmin": df["m"].map(lambda m: m.get("ftp_used")),
        "best_5min": df["m"].map(lambda m: (m.get("power_curve") or {}).get("300")),
        "best_20min": df["m"].map(lambda m: (m.get("power_curve") or {}).get("1200")),
        "best_60min": df["m"].map(lambda m: (m.get("power_curve") or {}).get("3600")),
        "name": df["name"],
    }).set_index("date")
    # FTP stimata: 95% del miglior 20' negli ultimi 90 giorni (Allen/Coggan)
    b20 = data["best_20min"].groupby(level=0).max()
    est = (b20.reindex(pd.date_range(b20.index.min(), date.today())).rolling("90D").max() * 0.95)
    data = data.join(est.rename("ftp_estimated"), how="left")

    fig = go.Figure()
    fig.add_trace(go.Scatter(x=est.index, y=est.round(0), name="FTP stimata (95% best 20' su 90 gg)",
                             mode="lines", line=dict(color=C1, width=2)))
    fig.add_trace(go.Scatter(x=data.index, y=data["ftp_garmin"], name="FTP impostata su Garmin",
                             mode="lines", line=dict(color=C2, width=2, shape="hv")))
    fig.add_trace(go.Scatter(x=data.index, y=data["best_20min"], name="Miglior 20' dell'uscita",
                             mode="markers", marker=dict(color=C3, size=8, line=dict(color=SURFACE, width=2)),
                             customdata=data["name"], hovertemplate="%{y:.0f} W - %{customdata}<extra></extra>"))
    fig.update_yaxes(title_text="Watt")
    _style(fig, "Evoluzione FTP e potenza", 520)
    return _export(fig, data, "ftp_potenza", out_dir, png)


# --------------------------------------------------------------------------- #
# Efficienza aerobica corsa
# --------------------------------------------------------------------------- #
def plot_running_efficiency(conn: sqlite3.Connection, days: int = 365, out_dir: Path = REPORT_DIR, png: bool = True):
    since = (date.today() - timedelta(days=days)).isoformat()
    df = _activities(conn, "run", since)
    if df.empty:
        log.warning("Nessuna corsa analizzata.")
        return None
    df = df[df["m"].map(lambda m: m.get("steady") and m.get("ef_speed") and (m.get("moving_time_s") or 0) >= 1200)]
    if df.empty:
        log.warning("Nessuna corsa continua >= 20 min con FC.")
        return None
    data = pd.DataFrame({
        "date": df["date"],
        "ambiente": df["m"].map(lambda m: "Tapis roulant" if m.get("treadmill") else "Outdoor"),
        "ef": df["m"].map(lambda m: m.get("ef_speed")),
        "decoupling_pct": df["m"].map(lambda m: m.get("decoupling_pct")),
        "passo": df["m"].map(lambda m: m.get("avg_pace")),
        "fc_media": df["m"].map(lambda m: m.get("avg_hr")),
        "name": df["name"],
    }).set_index("date")

    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.08, row_heights=[0.65, 0.35],
                        subplot_titles=("Efficiency Factor (m/min per battito) - piu' alto = meglio",
                                        "Deriva cardiaca Pa:HR (%) - sotto 5% = buona base aerobica"))
    for env, color in (("Outdoor", C1), ("Tapis roulant", C2)):
        d = data[data["ambiente"] == env]
        if d.empty:
            continue
        fig.add_trace(go.Scatter(x=d.index, y=d["ef"], name=env, mode="markers", legendgroup=env,
                                 marker=dict(color=color, size=8, opacity=0.55, line=dict(color=SURFACE, width=2)),
                                 customdata=np.stack([d["passo"], d["fc_media"], d["name"]], axis=1),
                                 hovertemplate="EF %{y:.2f} - %{customdata[0]} @ %{customdata[1]} bpm"
                                               "<br>%{customdata[2]}<extra></extra>"), row=1, col=1)
        trend = d["ef"].rolling("28D", min_periods=2).mean()
        fig.add_trace(go.Scatter(x=d.index, y=trend, name=f"{env} media 28 gg", mode="lines", legendgroup=env,
                                 line=dict(color=color, width=2), hoverinfo="skip"), row=1, col=1)
        dc = d.dropna(subset=["decoupling_pct"])
        fig.add_trace(go.Scatter(x=dc.index, y=dc["decoupling_pct"], name=f"{env} deriva", mode="markers",
                                 legendgroup=env, showlegend=False,
                                 marker=dict(color=color, size=8, line=dict(color=SURFACE, width=2)),
                                 hovertemplate="deriva %{y:.1f}%<extra></extra>"), row=2, col=1)
    fig.add_hline(y=5, line=dict(color=AXIS, width=1), row=2, col=1)
    _style(fig, "Efficienza aerobica nella corsa", 680)
    fig.update_annotations(font=dict(size=13, color=INK2), x=0, xanchor="left")
    return _export(fig, data, "efficienza_corsa", out_dir, png)


# --------------------------------------------------------------------------- #
# Carico acuto/cronico vs HRV, sonno, recupero
# --------------------------------------------------------------------------- #
def plot_load_vs_recovery(conn: sqlite3.Connection, days: int = 180, out_dir: Path = REPORT_DIR, png: bool = True):
    start = pd.Timestamp(date.today() - timedelta(days=days))
    load = pmc(conn)
    w = db.read_df(conn, "SELECT date, hrv_last_night, hrv_weekly_avg, hrv_baseline_low, hrv_baseline_high, "
                         "sleep_score, recovery_index FROM wellness_daily ORDER BY date")
    if load.empty and w.empty:
        log.warning("Nessun dato di carico o wellness.")
        return None
    w["date"] = pd.to_datetime(w["date"])
    w = w.set_index("date")
    idx = pd.date_range(start, pd.Timestamp(date.today()), freq="D")
    data = load.reindex(idx).join(w.reindex(idx))
    data["sleep_7d"] = data["sleep_score"].rolling(7, min_periods=3).mean()
    data["recovery_7d"] = data["recovery_index"].rolling(7, min_periods=3).mean()

    fig = make_subplots(
        rows=5, cols=1, shared_xaxes=True, vertical_spacing=0.035, row_heights=[0.30, 0.14, 0.20, 0.18, 0.18],
        subplot_titles=("Carico: TSS giornaliero, cronico (CTL 42 gg) e acuto (ATL 7 gg)",
                        "Forma (TSB = CTL - ATL)",
                        "HRV notturna (ms) e fascia bilanciata Garmin",
                        "Sleep Score",
                        "Indice di recupero"))
    fig.add_trace(go.Bar(x=idx, y=data["tss"], name="TSS giornaliero", marker=dict(color=AXIS, line_width=0),
                         hovertemplate="TSS %{y:.0f}<extra></extra>"), row=1, col=1)
    fig.add_trace(go.Scatter(x=idx, y=data["ctl"], name="Cronico (CTL)", line=dict(color=C1, width=2),
                             hovertemplate="CTL %{y:.0f}<extra></extra>"), row=1, col=1)
    fig.add_trace(go.Scatter(x=idx, y=data["atl"], name="Acuto (ATL)", line=dict(color=C2, width=2),
                             customdata=data["acwr"],
                             hovertemplate="ATL %{y:.0f} (ACWR %{customdata:.2f})<extra></extra>"), row=1, col=1)

    fig.add_trace(go.Scatter(x=idx, y=data["tsb"], name="TSB", showlegend=False, line=dict(color=C1, width=2),
                             fill="tozeroy", fillcolor=BAND, hovertemplate="TSB %{y:.0f}<extra></extra>"), row=2, col=1)
    fig.add_hline(y=0, line=dict(color=AXIS, width=1), row=2, col=1)

    fig.add_trace(go.Scatter(x=idx, y=data["hrv_baseline_high"], line=dict(width=0), showlegend=False,
                             hoverinfo="skip"), row=3, col=1)
    fig.add_trace(go.Scatter(x=idx, y=data["hrv_baseline_low"], line=dict(width=0), fill="tonexty",
                             fillcolor=BAND, name="Fascia bilanciata HRV", hoverinfo="skip"), row=3, col=1)
    fig.add_trace(go.Scatter(x=idx, y=data["hrv_last_night"], name="HRV notte", mode="markers",
                             marker=dict(color=C3, size=8, line=dict(color=SURFACE, width=2)),
                             hovertemplate="HRV %{y:.0f} ms<extra></extra>"), row=3, col=1)
    fig.add_trace(go.Scatter(x=idx, y=data["hrv_weekly_avg"], name="HRV media 7 gg", line=dict(color=C3, width=2),
                             hovertemplate="media 7 gg %{y:.0f} ms<extra></extra>"), row=3, col=1)

    fig.add_trace(go.Bar(x=idx, y=data["sleep_score"], name="Sleep Score", showlegend=False,
                         marker=dict(color="#b7d3f6", line_width=0),
                         hovertemplate="Sleep Score %{y:.0f}<extra></extra>"), row=4, col=1)
    fig.add_trace(go.Scatter(x=idx, y=data["sleep_7d"], name="Sonno media 7 gg", showlegend=False,
                             line=dict(color=C1, width=2), hovertemplate="media 7 gg %{y:.0f}<extra></extra>"),
                  row=4, col=1)

    fig.add_trace(go.Scatter(x=idx, y=data["recovery_index"], name="Recupero", showlegend=False, mode="markers",
                             marker=dict(color=C1, size=8, line=dict(color=SURFACE, width=2)),
                             hovertemplate="Recupero %{y:.0f}<extra></extra>"), row=5, col=1)
    fig.add_trace(go.Scatter(x=idx, y=data["recovery_7d"], name="Recupero media 7 gg", showlegend=False,
                             line=dict(color=C1, width=2), hovertemplate="media 7 gg %{y:.0f}<extra></extra>"),
                  row=5, col=1)
    for r in (4, 5):
        fig.update_yaxes(range=[0, 100], row=r, col=1)

    _style(fig, "Carico acuto vs cronico, HRV e sonno", 1100)
    fig.update_annotations(font=dict(size=13, color=INK2), x=0, xanchor="left")
    return _export(fig, data, "carico_recupero", out_dir, png)


def build_report(conn: sqlite3.Connection, days: int = 180, out_dir: Path = REPORT_DIR, png: bool = True) -> dict:
    out = {
        "carico_recupero": plot_load_vs_recovery(conn, days, out_dir, png),
        "ftp_potenza": plot_ftp(conn, max(days, 365), out_dir, png),
        "efficienza_corsa": plot_running_efficiency(conn, max(days, 365), out_dir, png),
    }
    return {k: v for k, v in out.items() if v}
