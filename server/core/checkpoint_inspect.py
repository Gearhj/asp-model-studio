"""Checkpoint inspection utility (Stage 6.1 size-control tooling).

Reports what is actually inside a workflow checkpoint file: total size,
scope counts, the largest scopes, the largest fields aggregated across
scopes, empty scopes, and (best-effort) scopes whose project or owner no
longer exists in the persistence/security databases.

Usage (from the repository root):

    .venv/Scripts/python.exe -m server.core.checkpoint_inspect            # default path
    .venv/Scripts/python.exe -m server.core.checkpoint_inspect PATH.json  # explicit file

Read-only: never modifies the checkpoint or any database.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple


def _field_sizes(fields: Dict[str, Any]) -> Dict[str, int]:
    return {key: len(json.dumps(value)) for key, value in fields.items()}


def _is_encoded_empty(fields: Dict[str, Any]) -> bool:
    return all(value in (None, {}, [], "") for value in fields.values())


def inspect_checkpoint(path: Path, top: int = 10) -> Dict[str, Any]:
    """Return the structured inspection report for `path`."""
    raw = path.read_text(encoding="utf-8")
    payload = json.loads(raw)

    live_projects: Optional[Set[str]] = None
    live_users: Optional[Set[str]] = None
    try:
        from .session_checkpoint import _live_identity_sets

        live_projects, live_users = _live_identity_sets()
    except Exception:
        pass

    scopes: List[Dict[str, Any]] = []
    field_totals: Dict[str, int] = {}
    empty_count = 0
    orphan_count = 0
    for kind, payload_key in (("datastore", "dataset"), ("results", "results")):
        for entry in payload.get(f"{kind}_scopes", []) or []:
            fields = entry.get(payload_key)
            if not isinstance(fields, dict):
                continue
            sizes = _field_sizes(fields)
            user_id = str(entry.get("owner_user_id"))
            project_id = str(entry.get("project_id"))
            empty = _is_encoded_empty(fields)
            orphaned = False
            if project_id != "unscoped":
                if live_projects is not None and project_id not in live_projects:
                    orphaned = True
                elif live_users is not None and user_id not in live_users and user_id != "anonymous":
                    orphaned = True
            empty_count += int(empty)
            orphan_count += int(orphaned)
            scopes.append({
                "kind": kind,
                "owner_user_id": user_id,
                "project_id": project_id,
                "bytes": sum(sizes.values()),
                "fields": sizes,
                "empty": empty,
                "orphaned": orphaned,
            })
            for key, size in sizes.items():
                field_totals[f"{kind}.{key}"] = field_totals.get(f"{kind}.{key}", 0) + size

    scopes.sort(key=lambda s: s["bytes"], reverse=True)
    return {
        "path": str(path),
        "file_bytes": len(raw.encode("utf-8")),
        "schema_version": payload.get("schema_version"),
        "saved_at": payload.get("saved_at"),
        "scope_count": len(scopes),
        "empty_scope_count": empty_count,
        "orphaned_scope_count": orphan_count,
        "largest_scopes": scopes[:top],
        "field_totals": dict(sorted(field_totals.items(), key=lambda kv: kv[1], reverse=True)),
    }


def main(argv: List[str]) -> int:
    default_path = Path(__file__).resolve().parents[2] / ".runtime" / "workflow_checkpoint.json"
    path = Path(argv[1]) if len(argv) > 1 else default_path
    if not path.exists():
        print(f"Checkpoint file not found: {path}")
        return 1
    report = inspect_checkpoint(path)
    print(f"Checkpoint: {report['path']}")
    print(f"  file size: {report['file_bytes']:,} bytes | schema {report['schema_version']} | saved_at {report['saved_at']}")
    print(f"  scopes: {report['scope_count']} total, {report['empty_scope_count']} empty, "
          f"{report['orphaned_scope_count']} orphaned (project/owner no longer exists)")
    print("  largest scopes:")
    for scope in report["largest_scopes"]:
        flags = "".join([" [EMPTY]" if scope["empty"] else "", " [ORPHANED]" if scope["orphaned"] else ""])
        print(f"    {scope['bytes']:>12,} B  {scope['kind']:<9} {scope['owner_user_id']} / {scope['project_id']}{flags}")
    print("  bytes by field (all scopes):")
    for field, size in report["field_totals"].items():
        print(f"    {size:>12,} B  {field}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
