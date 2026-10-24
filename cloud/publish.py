"""
Pubblica il repository pubblico della web app in un unico commit (API Git di GitHub via gh, senza git).

  python -m cloud.publish --repo utente/diario-triathlon [--dry-run]

Il repository rispecchia esattamente l'elenco qui sotto: cio' che non c'e' viene rimosso. Prima di
pubblicare ogni file viene controllato: se contiene token, chiavi, immagini incorporate o una parola
dell'elenco personale (cloud/.publish_blocklist, un termine per riga, mai pubblicato) la pubblicazione
si ferma.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GH = os.environ.get("GH_PATH", r"C:\Program Files\GitHub CLI\gh.exe")

INCLUDE = ["garmin_analytics/**/*.py", "cloud/*.py", "cloud/requirements.in", "cloud/requirements.txt",
           "cloud/wheels/*.whl", "web/**/*", "web/.nojekyll", "web_src/**/*", ".github/workflows/sync.yml"]
RENAME = {"cloud/README.repo.md": "README.md", "cloud/repo.gitignore": ".gitignore"}
BINARY = {".whl", ".png"}
SECRETS = [re.compile(p) for p in (
    r"gh[pousr]_[A-Za-z0-9]{20,}", r"github_pat_[A-Za-z0-9_]{20,}", r"-----BEGIN [A-Z ]*PRIVATE KEY",
    "data" + r":image/", r"di_refresh_token\"\s*:\s*\"[A-Za-z0-9]", r"[A-Za-z0-9._%+-]+@(gmail|yahoo|hotmail|outlook|icloud)\.",
    r"AKIA[0-9A-Z]{16}",
)]


def files() -> dict[str, Path]:
    out: dict[str, Path] = {}
    for pattern in INCLUDE:
        for p in ROOT.glob(pattern):
            if p.is_file() and "__pycache__" not in p.parts:
                out[p.relative_to(ROOT).as_posix()] = p
    for src, dst in RENAME.items():
        out[dst] = ROOT / src
    return dict(sorted(out.items()))


def check(items: dict[str, Path]) -> None:
    block_file = ROOT / "cloud" / ".publish_blocklist"
    words = [w.strip() for w in block_file.read_text(encoding="utf-8").splitlines() if w.strip()] if block_file.exists() else []
    if not words:
        raise SystemExit("cloud/.publish_blocklist mancante o vuoto: serve l'elenco delle parole personali")
    problems = []
    for rel, p in items.items():
        if p.suffix in BINARY:
            continue
        text = p.read_text(encoding="utf-8", errors="replace")
        problems += [f"{rel}: segreto/immagine ({rx.pattern[:24]})" for rx in SECRETS if rx.search(text)]
        problems += [f"{rel}: parola personale" for w in words if re.search(re.escape(w), text, re.I)]
    if problems:
        raise SystemExit("Pubblicazione fermata:\n  " + "\n  ".join(problems))


def gh_api(path: str, method: str = "GET", body: dict | None = None) -> dict:
    args = [GH, "api", "-X", method, path]
    if body is not None:
        args += ["--input", "-"]
    res = subprocess.run(args, input=json.dumps(body).encode() if body is not None else None, capture_output=True)
    if res.returncode:
        raise SystemExit(f"gh api {method} {path}: {res.stderr.decode(errors='replace')[:300]}")
    return json.loads(res.stdout or b"{}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    ap.add_argument("--message", default="Aggiorna la web app")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    items = files()
    check(items)
    print(f"{len(items)} file controllati: nessun segreto ne' parola personale.")
    if a.dry_run:
        for rel in items:
            print(" ", rel)
        return
    r = f"repos/{a.repo}"
    head = gh_api(f"{r}/git/ref/heads/main")["object"]["sha"]
    tree = []
    for rel, p in items.items():
        blob = gh_api(f"{r}/git/blobs", "POST", {"content": base64.b64encode(p.read_bytes()).decode(), "encoding": "base64"})
        tree.append({"path": rel, "mode": "100644", "type": "blob", "sha": blob["sha"]})
    t = gh_api(f"{r}/git/trees", "POST", {"tree": tree})
    c = gh_api(f"{r}/git/commits", "POST", {"message": a.message, "tree": t["sha"], "parents": [head]})
    gh_api(f"{r}/git/refs/heads/main", "PATCH", {"sha": c["sha"]})
    print(f"Pubblicato: commit {c['sha'][:10]} ({len(items)} file)")


if __name__ == "__main__":
    main()
