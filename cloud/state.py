"""Stato persistente tra un'esecuzione e l'altra: database, obiettivi, token Garmin, sale dei dati, immagini."""
from __future__ import annotations

import io
import tarfile
from pathlib import Path

from .crypto import open_state, seal_state

# solo questi file entrano ed escono dallo stato (percorsi relativi alla cartella di stato)
FILES = ("data/garmin.db", "data/goals.json", "tokens/garmin_tokens.json", "tokens/.rate_limit_cooldown.json",
         "tokens/strava_tokens.json", "data_salt.bin", "carica_img.json")


def pack(root: Path, key: bytes) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for rel in FILES:
            p = root / rel
            if p.is_file():
                tar.add(p, arcname=rel, recursive=False)
    return seal_state(buf.getvalue(), key)


def unpack(blob: bytes, root: Path, key: bytes) -> list[str]:
    raw = open_state(blob, key)
    root.mkdir(parents=True, exist_ok=True)
    names = []
    with tarfile.open(fileobj=io.BytesIO(raw), mode="r:gz") as tar:
        for m in tar.getmembers():
            # solo file regolari con nomi attesi: niente percorsi assoluti, "..", link o dispositivi
            if not m.isfile() or m.name not in FILES:
                raise ValueError(f"voce inattesa nello stato: {m.name!r}")
        tar.extractall(root, filter="data")
        names = [m.name for m in tar.getmembers()]
    return names
