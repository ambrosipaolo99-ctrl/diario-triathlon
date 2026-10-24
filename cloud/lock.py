"""
Genera cloud/requirements.txt con versioni esatte e hash SHA-256 di ogni file pubblicato su PyPI.

  python -m cloud.lock <cartella con i wheel scaricati per linux/py3.12>

Le versioni vengono dai wheel scaricati (risoluzione delle dipendenze fatta da pip); gli hash dall'API
JSON ufficiale di PyPI, per tutte le varianti di piattaforma. fitparse e' solo sorgente: si usa il wheel
costruito in cloud/wheels/, con il suo hash.
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main() -> None:
    wheels = Path(sys.argv[1])
    pins = {}
    for w in sorted(wheels.glob("*.whl")):
        name, ver = w.name.split("-")[:2]
        pins[re.sub(r"[-_.]+", "-", name).lower()] = ver
    lines = ["# Generato da cloud/lock.py: versioni esatte e hash (pip install --require-hashes)."]
    for name, ver in sorted(pins.items()):
        with urllib.request.urlopen(f"https://pypi.org/pypi/{name}/{ver}/json", timeout=30) as r:
            files = json.load(r)["urls"]
        hashes = sorted({f["digests"]["sha256"] for f in files})
        if not hashes:
            raise SystemExit(f"nessun file per {name}=={ver}")
        lines.append(f"{name}=={ver} \\")
        lines += [f"    --hash=sha256:{h}" + (" \\" if i < len(hashes) - 1 else "") for i, h in enumerate(hashes)]
    for w in sorted((ROOT / "cloud" / "wheels").glob("*.whl")):
        digest = hashlib.sha256(w.read_bytes()).hexdigest()
        lines.append(f"./cloud/wheels/{w.name} --hash=sha256:{digest}")
    (ROOT / "cloud" / "requirements.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"{len(pins) + 1} pacchetti con hash")


if __name__ == "__main__":
    main()
