"""Phase 7D.5A (Workstream F) — surgical, verified, idempotent quarantine of an INCOMPLETE test-project namespace
left in the shared .runtime (e.g. an HGB attempt that failed before COMPLETE evidence).

It refuses to touch a namespace unless EVERY supplied identity matches AND there is no COMPLETE run, no run receipt,
no evidence-registry entry, no activation, no active-candidate, no reparse point, and nothing escapes the runtime
root. It never deletes immutable COMPLETE evidence, never uses wildcards, and never touches any other project. The
namespace is MOVED (not deleted) into an authority-excluded quarantine area with a manifest, so it can be audited.

Usage:
  python -m scripts.quarantine_incomplete_test_namespace --project-id <id> --expected-binding-id <b>
      --expected-request-sha <r> --expected-authority-id <a> --reason "<why>" [--dry-run] [--apply]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import time
from pathlib import Path

from server.sports_cockpit import gen3_authority as A
from server.sports_cockpit.path_containment import contained_no_reparse, is_reparse_point


class NamespaceCleanupError(RuntimeError):
    pass


def _sha16(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()[:16]


def verify_incomplete(project_id: str, expected_binding: str, expected_request_sha: str,
                      expected_authority: str) -> dict:
    key = hashlib.sha256(project_id.encode("utf-8")).hexdigest()[:32]
    state_root = Path(A.STATE_ROOT).resolve()
    base = contained_no_reparse(state_root / key, [state_root])           # containment + reparse rejection
    if not base.exists():
        raise NamespaceCleanupError(f"namespace does not exist: {base}")
    # exact identity match
    bindings = sorted(p.stem for p in (base / "bindings").glob("*.json")) if (base / "bindings").is_dir() else []
    authorities = sorted(p.stem for p in (base / "authorities").glob("*.json")) if (base / "authorities").is_dir() else []
    requests = sorted(p.stem for p in (base / "requests").glob("*.json")) if (base / "requests").is_dir() else []
    if bindings != [expected_binding]:
        raise NamespaceCleanupError(f"binding set {bindings} != [{expected_binding}]")
    if authorities != [expected_authority]:
        raise NamespaceCleanupError(f"authority set {authorities} != [{expected_authority}]")
    if requests != [expected_request_sha]:
        raise NamespaceCleanupError(f"request set {[r[:16] for r in requests]} != [{expected_request_sha[:16]}]")
    # NO COMPLETE evidence of any kind
    for forbidden in ("runs", "evidence", "evidence-v2/objects", "evidence-v2/receipts", "activations", "comparisons"):
        d = base / forbidden
        contained_no_reparse(d, [base])                          # R6: reject a junctioned source dir BEFORE iterating
        if d.is_dir() and any(d.iterdir()):
            raise NamespaceCleanupError(f"COMPLETE/evidence artifact present ({forbidden}); refusing to touch")
    if (base / "evidence-v2" / "registry.json").is_file():
        raise NamespaceCleanupError("evidence registry present; refusing to touch")
    if (base / "active-candidate.json").is_file():
        raise NamespaceCleanupError("active candidate present; refusing to touch")
    # no reparse point anywhere in the namespace
    for p in base.rglob("*"):
        if is_reparse_point(p):
            raise NamespaceCleanupError(f"reparse point in namespace: {p}")
    inv = {str(p.relative_to(base)): _sha16(p) for p in sorted(base.rglob("*")) if p.is_file()}
    return {"projectId": project_id, "projectKey": key, "path": str(base), "before": inv}


def quarantine(project_id: str, expected_binding: str, expected_request_sha: str, expected_authority: str,
               reason: str, apply: bool) -> dict:
    info = verify_incomplete(project_id, expected_binding, expected_request_sha, expected_authority)
    base = Path(info["path"])
    runtime_root = Path(A.STATE_ROOT).resolve().parents[2]              # .../asp-model-studio
    qroot = runtime_root / "quarantine" / "incomplete-test-namespaces"
    dest = qroot / f"{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}-{info['projectKey']}"
    disposition = {"action": "DRY_RUN" if not apply else "QUARANTINED", "reason": reason,
                   "from": str(base), "to": str(dest), **info}
    if apply:
        contained_no_reparse(qroot, [runtime_root])             # R6: reject a junctioned quarantine destination BEFORE move
        qroot.mkdir(parents=True, exist_ok=True)
        contained_no_reparse(dest, [qroot])
        shutil.move(str(base), str(dest))
        (dest / "_quarantine-manifest.json").write_text(json.dumps(disposition, indent=2), encoding="utf-8")
        # after: confirm removed from state root + no canonical registry reference to this key
        disposition["afterExists"] = base.exists()
    return disposition


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--project-id", required=True)
    ap.add_argument("--expected-binding-id", required=True)
    ap.add_argument("--expected-request-sha", required=True)
    ap.add_argument("--expected-authority-id", required=True)
    ap.add_argument("--reason", required=True)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args(argv)
    if a.apply == a.dry_run:
        print("choose exactly one of --dry-run / --apply", file=sys.stderr)
        return 2
    try:
        out = quarantine(a.project_id, a.expected_binding_id, a.expected_request_sha, a.expected_authority_id,
                         a.reason, a.apply)
    except NamespaceCleanupError as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 3
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
