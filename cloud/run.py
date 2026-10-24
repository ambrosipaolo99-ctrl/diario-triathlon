"""
Esecuzione notturna su GitHub Actions.

  python -m cloud.run --state-in state.bin --state-out state.new --data-out site/data.bin --status status.txt

1. apre lo stato cifrato (database, obiettivi, token Garmin)
2. accede a Garmin con i token; solo se non valgono usa GARMIN_EMAIL / GARMIN_PASSWORD
3. sincronizza gli ultimi giorni, ricalcola recupero, voti, stima e piano
4. cifra i dati della dashboard con la chiave della frase segreta
5. richiude lo stato (anche se un passo e' fallito: i token rinnovati non vanno persi)

Le variabili GARMIN_DATA_DIR e GARMIN_TOKEN_DIR devono puntare dentro la cartella di stato prima di
importare garmin_analytics. Su stdout/stderr non esce nulla: i log di un repository pubblico li legge
chiunque. Il file di stato riporta solo "OK"/"ERRORE" per fase; i dettagli vanno nel pacchetto cifrato.
"""
from __future__ import annotations

import argparse
import contextlib
import gzip
import io
import json
import logging
import os
import sys
import traceback
from datetime import datetime
from pathlib import Path

from . import crypto, state

SYNC_DAYS = 3
LOG_LINES = 400


class Run:
    def __init__(self, status_path: Path, log: io.StringIO):
        self.status_path = status_path
        self.log = log
        self.steps: list[dict] = []
        self.ok = True

    def step(self, name: str, fn, *args, **kwargs):
        """Esegue una fase: su GitHub solo l'esito, il dettaglio dell'errore nel log cifrato."""
        try:
            out = fn(*args, **kwargs)
            self.steps.append({"step": name, "ok": True, "note": None})
            return out
        except Exception as exc:  # noqa: BLE001
            self.ok = False
            self.steps.append({"step": name, "ok": False, "note": type(exc).__name__})
            logging.getLogger("cloud").error("fase %s fallita:\n%s", name, traceback.format_exc())
            return None
        finally:
            self.write_status()

    def note(self, name: str, text: str) -> None:
        self.steps.append({"step": name, "ok": True, "note": text})
        self.write_status()

    def write_status(self) -> None:
        lines = [f"{'OK' if s['ok'] else 'ERRORE':7} {s['step']}" + (f" ({s['note']})" if s["note"] else "")
                 for s in self.steps]
        self.status_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--state-in", type=Path, required=True)
    ap.add_argument("--state-out", type=Path, required=True)
    ap.add_argument("--data-out", type=Path, required=True)
    ap.add_argument("--status", type=Path, required=True)
    a = ap.parse_args()

    log = io.StringIO()
    logging.basicConfig(level=logging.INFO, stream=log, format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
                        force=True)
    for noisy in ("urllib3", "garminconnect", "curl_cffi"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    run = Run(a.status, log)
    with contextlib.redirect_stdout(log), contextlib.redirect_stderr(log):
        _main(a, run, log)
    return 0 if run.ok else 1


def _main(a: argparse.Namespace, run: Run, log: io.StringIO) -> None:
    root = Path(os.environ["GARMIN_DATA_DIR"]).parent
    key = run.step("chiave di stato", crypto.state_key, os.environ.get("STATE_KEY"))
    if key is None:
        return
    if run.step("apertura stato", state.unpack, a.state_in.read_bytes(), root, key) is None:
        return            # stato mancante o alterato: non si scrive nulla al suo posto

    try:
        salt_path = root / "data_salt.bin"
        if not salt_path.exists():
            salt_path.write_bytes(os.urandom(16))
        salt = salt_path.read_bytes()
        dkey = run.step("frase segreta", crypto.data_key, os.environ.get("DATA_PASSPHRASE"), salt)

        # import solo ora: config legge le cartelle dalle variabili d'ambiente
        from garmin_analytics import db
        from garmin_analytics.analysis import sync_activities
        from garmin_analytics.auth import _login_with_credentials, login_with_tokens
        from garmin_analytics.export import export_dashboard
        from garmin_analytics.recovery import sync_wellness

        conn = db.connect()

        def login():
            api = login_with_tokens()
            if api is None:
                api = _login_with_credentials(interactive=False)
                run.note("login con password", "fatto: ora cancella il segreto GARMIN_PASSWORD")
            return api

        api = run.step("accesso Garmin", login)
        if api is not None:
            run.step("sincronizzazione wellness", sync_wellness, api, days=SYNC_DAYS, conn=conn)
            run.step("sincronizzazione attivita'", sync_activities, api, days=SYNC_DAYS, conn=conn)
            with contextlib.suppress(Exception):
                api.client.dump(str(Path(os.environ["GARMIN_TOKEN_DIR"])))   # token rinnovati nello stato

        out = Path(os.environ.get("RUNNER_TEMP", root)) / "export"
        paths = run.step("calcolo dashboard", export_dashboard, conn, out_dir=out)
        conn.close()
        if dkey is not None and paths:
            run.step("cifratura dati", write_data, paths, root, dkey, salt, run, log, a.data_out)
    finally:
        # lo stato si richiude sempre: i token rinnovati da Garmin non devono andare persi
        blob = run.step("salvataggio stato", state.pack, root, key)
        if blob:
            a.state_out.write_bytes(blob)


def write_data(paths: dict, root: Path, dkey: bytes, salt: bytes, run: Run, log: io.StringIO, out: Path) -> None:
    bundle = {name: json.loads(Path(p).read_text(encoding="utf-8")) for name, p in paths.items()}
    img = root / "carica_img.json"
    bundle["_carica_img"] = json.loads(img.read_text(encoding="utf-8")) if img.exists() else {}
    bundle["_meta"] = [{"generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
                        "ok": run.ok, "steps": run.steps}]
    bundle["_sync_log"] = log.getvalue().splitlines()[-LOG_LINES:]
    raw = gzip.compress(json.dumps(bundle, ensure_ascii=False, separators=(",", ":")).encode("utf-8"), 9)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(crypto.seal_data(raw, dkey, salt))


if __name__ == "__main__":
    sys.exit(main())
