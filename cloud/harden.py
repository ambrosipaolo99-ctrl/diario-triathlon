"""
Impostazioni di sicurezza del repository (idempotente).

  python -m cloud.harden --repo utente/diario-triathlon

Azioni: solo quelle di GitHub; token dei workflow in sola lettura di default; approvazione obbligatoria
per i workflow di contributori esterni; scansione dei segreti con blocco al push; avvisi sulle dipendenze;
ramo principale non cancellabile ne' riscrivibile; GitHub Pages pubblicato dal workflow.
"""
from __future__ import annotations

import argparse

from .publish import gh_api


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    r = f"repos/{ap.parse_args().repo}"
    steps = [
        ("azioni consentite", "PUT", f"{r}/actions/permissions", {"enabled": True, "allowed_actions": "selected"}),
        ("solo azioni GitHub", "PUT", f"{r}/actions/permissions/selected-actions",
         {"github_owned_allowed": True, "verified_allowed": False, "patterns_allowed": []}),
        ("token in sola lettura", "PUT", f"{r}/actions/permissions/workflow",
         {"default_workflow_permissions": "read", "can_approve_pull_request_reviews": False}),
        ("approvazione contributori esterni", "PUT", f"{r}/actions/permissions/fork-pr-contributor-approval",
         {"approval_policy": "all_external_contributors"}),
        ("scansione segreti", "PATCH", r, {"has_projects": False, "has_discussions": False, "security_and_analysis": {
            "secret_scanning": {"status": "enabled"}, "secret_scanning_push_protection": {"status": "enabled"}}}),
        ("avvisi dipendenze", "PUT", f"{r}/vulnerability-alerts", None),
        ("protezione main", "POST", f"{r}/rulesets", {
            "name": "Protezione main", "target": "branch", "enforcement": "active",
            "conditions": {"ref_name": {"include": ["~DEFAULT_BRANCH"], "exclude": []}},
            "rules": [{"type": "deletion"}, {"type": "non_fast_forward"}]}),
        ("GitHub Pages dal workflow", "POST", f"{r}/pages", {"build_type": "workflow"}),
    ]
    existing = {x["name"] for x in gh_api(f"{r}/rulesets", "GET") or []}
    for name, method, path, body in steps:
        if name == "protezione main" and "Protezione main" in existing:
            print(f"ok   {name} (gia' presente)")
            continue
        try:
            gh_api(path, method, body)
            print(f"ok   {name}")
        except SystemExit as exc:
            msg = str(exc)
            print(f"{'ok  ' if 'already' in msg or '409' in msg else 'ERRORE'} {name}: {msg[-160:]}")


if __name__ == "__main__":
    main()
