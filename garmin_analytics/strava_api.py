"""
API ufficiale di Strava (OAuth): solo lettura delle proprie attivita', per il dislivello delle corse.

  - token di accesso di 6 ore, rinnovato con il refresh token a ogni esecuzione; Strava puo' restituire un refresh
    token nuovo: va sempre salvato l'ultimo (nello stato cifrato, mai nei log)
  - primo accesso: il codice di autorizzazione (scope activity:read_all) si scambia una volta sola
Le attivita' tornano nel formato di strava.import_activities (lo stesso del connettore della sessione Claude).
"""
from __future__ import annotations

import json
import re
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import requests

API = "https://www.strava.com/api/v3"
TOKEN_URL = "https://www.strava.com/oauth/token"
TIMEOUT = 30


class StravaError(RuntimeError):
    pass


def _token(data: dict) -> dict:
    r = requests.post(TOKEN_URL, data=data, timeout=TIMEOUT)
    if r.status_code != 200:
        # solo i nomi dei campi rifiutati (es. code/invalid, client_id/invalid): nessun dato dell'account
        try:
            errs = ", ".join(f"{e.get('resource', '')}.{e.get('field', '')}={e.get('code', '')}" for e in r.json().get("errors", []))
        except ValueError:
            errs = ""
        raise StravaError(f"token Strava rifiutato (HTTP {r.status_code}{': ' + errs if errs else ''})")
    j = r.json()
    return {"refresh_token": j["refresh_token"], "access_token": j["access_token"], "expires_at": j["expires_at"]}


def clean_code(raw: str) -> str:
    """Accetta il codice puro o l'indirizzo intero di ritorno (http://localhost/...?code=...&scope=...)."""
    m = re.search(r"code=([0-9a-fA-F]+)", raw)
    return m.group(1) if m else raw.strip()


def exchange_code(client_id: str, client_secret: str, code: str) -> dict:
    return _token({"client_id": client_id, "client_secret": client_secret, "code": clean_code(code),
                   "grant_type": "authorization_code"})


def refresh(client_id: str, client_secret: str, refresh_token: str) -> dict:
    return _token({"client_id": client_id, "client_secret": client_secret, "refresh_token": refresh_token,
                   "grant_type": "refresh_token"})


def load_tokens(path: Path) -> Optional[dict]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def save_tokens(path: Path, tok: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"refresh_token": tok["refresh_token"]}), encoding="utf-8")


def activities(access_token: str, days: int) -> list[dict]:
    """Attivita' degli ultimi `days` giorni nel formato del connettore (id, sport_type, start_local, summary)."""
    after = int((datetime.now() - timedelta(days=days)).timestamp())
    out, page = [], 1
    while True:
        r = requests.get(f"{API}/athlete/activities", params={"after": after, "per_page": 100, "page": page},
                         headers={"Authorization": f"Bearer {access_token}"}, timeout=TIMEOUT)
        if r.status_code == 429:
            raise StravaError("limite di richieste Strava raggiunto: riprova piu' tardi")
        if r.status_code != 200:
            raise StravaError(f"elenco attivita' Strava non disponibile (HTTP {r.status_code})")
        items = r.json()
        for a in items:
            out.append({"id": str(a["id"]), "name": a.get("name"), "sport_type": a.get("sport_type") or a.get("type"),
                        "start_local": (a.get("start_date_local") or "")[:19],
                        "summary": {"distance": a.get("distance"), "moving_time": a.get("moving_time"),
                                    "elevation_gain": a.get("total_elevation_gain")}})
        if len(items) < 100:
            return out
        page += 1
        time.sleep(1)
