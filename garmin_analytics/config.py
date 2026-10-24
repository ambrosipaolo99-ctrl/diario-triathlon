"""Percorsi e parametri globali (sovrascrivibili da .env)."""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.getenv("GARMIN_DATA_DIR", ROOT / "data")).expanduser()
DB_PATH = DATA_DIR / "garmin.db"
FIT_DIR = DATA_DIR / "fit"
REPORT_DIR = Path(os.getenv("GARMIN_REPORT_DIR", ROOT / "reports")).expanduser()

TOKEN_DIR = Path(os.getenv("GARMIN_TOKEN_DIR", Path.home() / ".garminconnect")).expanduser()
COOLDOWN_SECONDS = int(os.getenv("GARMIN_COOLDOWN_SECONDS", 3600))
IS_CN = os.getenv("GARMIN_IS_CN", "false").lower() == "true"

# inizio dello storico: nulla prima di questa data viene scaricato, analizzato o esportato
DATA_START = os.getenv("GARMIN_DATA_START", "2026-01-01")

# pausa minima tra due chiamate API consecutive (anti rate-limit)
API_PAUSE_SECONDS = float(os.getenv("GARMIN_API_PAUSE", 1.0))

# CSS (Critical Swim Speed) in secondi per 100 m, opzionale: abilita il confronto passo/soglia nel nuoto
CSS_SEC_PER_100M = float(os.getenv("GARMIN_CSS_SEC_100M", 0)) or None
