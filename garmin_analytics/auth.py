"""
Autenticazione Garmin Connect con session directory e protezione anti-blocco.

Strategia:
  1. Si tenta SEMPRE prima il login con i token salvati su disco
     (session directory). Nessuna credenziale viene inviata a Garmin.
  2. Solo se i token mancano o sono scaduti/revocati si esegue il login
     con email/password (+ MFA se attivo), poi i token vengono salvati.
     garminconnect rinnova da solo il token tramite refresh token, senza SSO.
  3. Dopo un HTTP 429 viene scritto un file di cooldown: per tutta la
     sua durata il login con credenziali e' rifiutato localmente, cosi'
     tentativi ripetuti non peggiorano il blocco lato Garmin.
  4. `throttled()` distanzia le chiamate API e attiva il cooldown sui 429.
"""
from __future__ import annotations

import getpass
import json
import logging
import os
import time
from typing import Any, Callable, Optional

from garminconnect import (
    Garmin,
    GarminConnectAuthenticationError,
    GarminConnectConnectionError,
    GarminConnectTooManyRequestsError,
)

from .config import API_PAUSE_SECONDS, COOLDOWN_SECONDS, IS_CN, TOKEN_DIR

TOKEN_FILE = TOKEN_DIR / "garmin_tokens.json"
COOLDOWN_FILE = TOKEN_DIR / ".rate_limit_cooldown.json"

log = logging.getLogger("garmin_analytics.auth")


class AuthError(RuntimeError):
    """Errore di autenticazione non recuperabile automaticamente."""


# --------------------------------------------------------------------------- #
# Cooldown dopo rate limit
# --------------------------------------------------------------------------- #
def cooldown_remaining() -> int:
    if not COOLDOWN_FILE.exists():
        return 0
    try:
        until = json.loads(COOLDOWN_FILE.read_text())["until"]
    except (ValueError, KeyError):
        COOLDOWN_FILE.unlink(missing_ok=True)
        return 0
    return max(0, int(until - time.time()))


def _start_cooldown() -> None:
    TOKEN_DIR.mkdir(parents=True, exist_ok=True)
    COOLDOWN_FILE.write_text(json.dumps({"until": time.time() + COOLDOWN_SECONDS}))
    log.warning("Rate limit Garmin (429): login con credenziali bloccato per %d min.", COOLDOWN_SECONDS // 60)


# --------------------------------------------------------------------------- #
# Login
# --------------------------------------------------------------------------- #
def login_with_tokens() -> Optional[Garmin]:
    """Riprende la sessione dai token salvati. Ritorna None se non utilizzabili."""
    if not TOKEN_FILE.exists():
        log.info("Nessun token in %s.", TOKEN_DIR)
        return None
    try:
        # Senza credenziali: se i token non sono validi la libreria solleva
        # un errore invece di ripiegare sul login SSO.
        api = Garmin(is_cn=IS_CN)
        api.login(str(TOKEN_DIR))
        # il token puo' essere stato rinnovato: risalviamo per non perderlo
        api.client.dump(str(TOKEN_DIR))
        log.info("Sessione ripristinata dai token (%s).", TOKEN_DIR)
        return api
    except GarminConnectTooManyRequestsError:
        _start_cooldown()
        raise AuthError("Rate limit Garmin anche con i token: riprova piu' tardi.")
    except (GarminConnectAuthenticationError, GarminConnectConnectionError) as exc:
        log.warning("Token non validi o scaduti (%s).", exc)
        return None


def _get_credentials() -> tuple[str, str]:
    # spazi e "a capo" agli estremi arrivano spesso incollando (o premendo Invio nei segreti di GitHub)
    email = (os.getenv("GARMIN_EMAIL") or input("Email Garmin Connect: ")).strip()
    password = (os.getenv("GARMIN_PASSWORD") or getpass.getpass("Password Garmin Connect: ")).strip()
    if not email or not password:
        raise AuthError("Credenziali mancanti.")
    return email, password


def _login_with_credentials(interactive: bool) -> Garmin:
    """Login completo con email/password (+ MFA). Unica funzione che invia credenziali."""
    remaining = cooldown_remaining()
    if remaining:
        raise AuthError(
            f"Cooldown attivo dopo un rate limit: attendi ancora {remaining // 60} min "
            f"(o elimina {COOLDOWN_FILE} se sai cosa stai facendo)."
        )
    if not interactive and not ((os.getenv("GARMIN_EMAIL") or "").strip() and (os.getenv("GARMIN_PASSWORD") or "").strip()):
        raise AuthError("Token non validi e modalita' non interattiva: esegui 'python main.py login'.")

    email, password = _get_credentials()
    # In modalita' non interattiva nessun prompt MFA: la libreria solleva un errore.
    prompt_mfa = (lambda: input("Codice MFA (email/app): ").strip()) if interactive else None
    api = Garmin(email=email, password=password, is_cn=IS_CN, prompt_mfa=prompt_mfa)
    try:
        api.login()
    except GarminConnectTooManyRequestsError:
        _start_cooldown()
        raise AuthError("Garmin ha risposto 429 Too Many Requests.")
    except GarminConnectAuthenticationError as exc:
        if "MFA Required" in str(exc):
            raise AuthError("Account con MFA: esegui 'python main.py login' da terminale.")
        raise AuthError(f"Credenziali o codice MFA errati: {exc}")
    except GarminConnectConnectionError as exc:
        raise AuthError(f"Errore di connessione a Garmin Connect: {exc}")

    api.client.dump(str(TOKEN_DIR))
    COOLDOWN_FILE.unlink(missing_ok=True)
    log.info("Login con credenziali riuscito, token salvati in %s.", TOKEN_DIR)
    return api


def get_client(interactive: bool = False) -> Garmin:
    """
    Restituisce un client Garmin autenticato.

    interactive=False (default per job automatici/schedulati): usa solo i token
    o le credenziali da .env, senza mai fermarsi su un prompt.
    """
    api = login_with_tokens()
    if api is not None:
        return api
    return _login_with_credentials(interactive)


# --------------------------------------------------------------------------- #
# Chiamate API distanziate
# --------------------------------------------------------------------------- #
_last_call = 0.0


def throttled(fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    """Esegue una chiamata API rispettando API_PAUSE_SECONDS; un 429 attiva il cooldown."""
    global _last_call
    wait = API_PAUSE_SECONDS - (time.monotonic() - _last_call)
    if wait > 0:
        time.sleep(wait)
    try:
        return fn(*args, **kwargs)
    except GarminConnectTooManyRequestsError:
        _start_cooldown()
        raise AuthError("Garmin ha risposto 429 Too Many Requests: sincronizzazione interrotta.")
    finally:
        _last_call = time.monotonic()
