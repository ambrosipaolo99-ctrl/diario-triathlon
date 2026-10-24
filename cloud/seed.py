"""
Stato iniziale del repository (da eseguire una volta sul PC).

  python -m cloud.seed --repo utente/diario-triathlon

Genera una STATE_KEY casuale e la salva come segreto del repository (passa a gh da stdin: non viene
stampata ne' scritta su disco), cifra database, obiettivi e immagini della card "La carica" e li
carica come asset "state-...-iniziale.bin" della release "state" (il workflow usa sempre il piu' recente). I token Garmin del PC NON entrano nello stato:
GitHub fa un suo login separato, cosi' i due rinnovi non si invalidano a vicenda.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import re
import shutil
import sqlite3
import subprocess
import tempfile
from pathlib import Path

from garmin_analytics.config import DATA_DIR

from . import state

ROOT = Path(__file__).resolve().parent.parent
GH = os.environ.get("GH_PATH", r"C:\Program Files\GitHub CLI\gh.exe")


def gh(*args: str, stdin: bytes | None = None) -> str:
    res = subprocess.run([GH, *args], input=stdin, capture_output=True, check=False)
    if res.returncode:
        raise SystemExit(f"gh {' '.join(args[:3])} fallito: {res.stderr.decode(errors='replace')[:300]}")
    return res.stdout.decode(errors="replace")


def carica_images() -> dict:
    out = {}
    for p in sorted((ROOT / "dashboard").glob("carica_img_*.js")):
        m = re.search(r"Object\.assign\(window\.CK_IMG \|\| \{\}, (\{.*\})\);", p.read_text(encoding="utf-8"), re.S)
        if m:
            out.update(json.loads(m.group(1)))
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    a = ap.parse_args()

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "state"
        (root / "data").mkdir(parents=True)
        # copia coerente del database anche se e' aperto altrove
        with sqlite3.connect(DATA_DIR / "garmin.db") as src, sqlite3.connect(root / "data" / "garmin.db") as dst:
            src.backup(dst)
        shutil.copy2(DATA_DIR / "goals.json", root / "data" / "goals.json")
        (root / "carica_img.json").write_text(json.dumps(carica_images()), encoding="utf-8")

        key = os.urandom(32)
        blob = state.pack(root, key)
        gh("secret", "set", "STATE_KEY", "-R", a.repo, stdin=base64.b64encode(key))
        del key

        bin_path = Path(tmp) / "state-00000000T000000-iniziale.bin"
        bin_path.write_bytes(blob)
        rel = subprocess.run([GH, "release", "view", "state", "-R", a.repo], capture_output=True)
        if rel.returncode:
            gh("release", "create", "state", "-R", a.repo, "--title", "Stato cifrato",
               "--notes", "Stato della sincronizzazione, cifrato (AES-256-GCM). Non contiene dati leggibili.")
        gh("release", "upload", "state", str(bin_path), "-R", a.repo)
        print(f"Stato iniziale caricato ({len(blob) // 1024} KB cifrati), STATE_KEY salvata nei segreti.")


if __name__ == "__main__":
    main()
