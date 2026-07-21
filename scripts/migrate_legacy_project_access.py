"""FND-002: migrate rows from the legacy project_access ACL table (in the
security database) into SharingService's resource_permissions table (in the
persistence database), which is now the single authoritative store for
project access.

This is additive and idempotent:
  - It never deletes or modifies the legacy project_access table.
  - resource_permissions has a UNIQUE(resource_type, resource_id, principal_type,
    principal_id) constraint with an upsert, so re-running this script is safe.
  - project_collaborators rows are written on a best-effort basis and skipped
    (reported, not fatal) when the referenced project or user does not yet
    exist in the persistence database, since project_id/user_id are FK columns
    there; resource_permissions has no such FK and remains the authoritative
    record either way.

Defaults to a dry run; pass --apply to write.
"""

from __future__ import annotations

import argparse
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SECURITY_DB = ROOT / "server" / "artifacts" / "security" / "atlas_security.db"
DEFAULT_PERSISTENCE_DB = ROOT / "server" / "data" / "atlas_local.db"

# Mirrors server/security/security_store.py's LEGACY_TO_SHARING_PERMISSION.
# Kept as an independent literal (rather than importing the server package)
# so this one-off migration script has no runtime import dependency on it.
LEGACY_TO_SHARING_PERMISSION = {
    "owner": "admin",
    "editor": "edit",
    "approver": "approve",
    "viewer": "view",
    "auditor": "view",
}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def migrate(security_db: Path, persistence_db: Path, apply: bool) -> int:
    if not security_db.is_file():
        print(f"ERROR: security database not found at {security_db}")
        return 1
    if not persistence_db.is_file():
        print(f"ERROR: persistence database not found at {persistence_db}")
        return 1

    sec = sqlite3.connect(f"file:{security_db}?mode=ro", uri=True)
    sec.row_factory = sqlite3.Row
    try:
        legacy_rows = sec.execute(
            "SELECT project_id, user_id, permission, granted_by_user_id, granted_at FROM project_access ORDER BY granted_at"
        ).fetchall()
    finally:
        sec.close()

    print(f"Legacy project_access rows found: {len(legacy_rows)}")
    if not legacy_rows:
        print("Nothing to migrate.")
        return 0

    per = sqlite3.connect(persistence_db)
    per.row_factory = sqlite3.Row
    per.execute("PRAGMA foreign_keys = ON")

    migrated: List[Dict[str, Any]] = []
    unmapped: List[Dict[str, Any]] = []
    collaborator_skipped: List[Dict[str, Any]] = []

    try:
        project_ids = {row["project_id"] for row in per.execute("SELECT project_id FROM projects")}
        user_ids = {row["user_id"] for row in per.execute("SELECT user_id FROM users")}

        for row in legacy_rows:
            legacy_permission = row["permission"]
            mapped = LEGACY_TO_SHARING_PERMISSION.get(legacy_permission)
            if mapped is None:
                unmapped.append(dict(row))
                continue

            plan = {
                "project_id": row["project_id"],
                "user_id": row["user_id"],
                "legacy_permission": legacy_permission,
                "mapped_permission": mapped,
                "granted_by_user_id": row["granted_by_user_id"],
                "granted_at": row["granted_at"] or now_iso(),
            }
            migrated.append(plan)

            if not apply:
                continue

            per.execute(
                """
                INSERT INTO resource_permissions (
                  permission_id, resource_type, resource_id, principal_type, principal_id,
                  permission_level, granted_by_user_id, granted_at, expires_at, status, metadata_json
                ) VALUES (?, 'project', ?, 'user', ?, ?, ?, ?, NULL, 'active', ?)
                ON CONFLICT(resource_type, resource_id, principal_type, principal_id) DO UPDATE SET
                  permission_level = excluded.permission_level,
                  granted_by_user_id = excluded.granted_by_user_id,
                  status = 'active'
                """,
                (
                    f"perm_{uuid.uuid4().hex}",
                    plan["project_id"],
                    plan["user_id"],
                    mapped,
                    plan["granted_by_user_id"],
                    plan["granted_at"],
                    '{"source": "fnd002_legacy_project_access_migration"}',
                ),
            )

            if plan["project_id"] in project_ids and plan["user_id"] in user_ids:
                per.execute(
                    """
                    INSERT INTO project_collaborators (
                      collaborator_id, project_id, user_id, project_role, added_by_user_id,
                      added_at, status, metadata_json
                    ) VALUES (?, ?, ?, ?, ?, ?, 'active', ?)
                    ON CONFLICT(project_id, user_id) DO UPDATE SET
                      project_role = excluded.project_role,
                      status = 'active'
                    """,
                    (
                        f"collab_{uuid.uuid4().hex}",
                        plan["project_id"],
                        plan["user_id"],
                        mapped,
                        plan["granted_by_user_id"],
                        plan["granted_at"],
                        '{"source": "fnd002_legacy_project_access_migration"}',
                    ),
                )
            else:
                collaborator_skipped.append(plan)

        if apply:
            per.commit()
    finally:
        per.close()

    print(f"\n{'Applied' if apply else 'Would migrate'}: {len(migrated)} row(s) into resource_permissions")
    for plan in migrated:
        print(f"  project={plan['project_id']} user={plan['user_id']} {plan['legacy_permission']} -> {plan['mapped_permission']}")

    if collaborator_skipped:
        print(f"\nproject_collaborators sync skipped for {len(collaborator_skipped)} row(s) "
              "(project and/or user not present in the persistence database yet -- "
              "resource_permissions is still the authoritative record for these):")
        for plan in collaborator_skipped:
            print(f"  project={plan['project_id']} user={plan['user_id']}")

    if unmapped:
        print(f"\nWARNING: {len(unmapped)} legacy row(s) had a permission value with no mapping and were NOT migrated:")
        for row in unmapped:
            print(f"  {row}")

    print("\nThe legacy project_access table was not modified or deleted.")
    if not apply:
        print("This was a dry run. Re-run with --apply to write.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--security-db", type=Path, default=DEFAULT_SECURITY_DB)
    parser.add_argument("--persistence-db", type=Path, default=DEFAULT_PERSISTENCE_DB)
    parser.add_argument("--apply", action="store_true", help="Write changes. Without this flag, only a plan is printed.")
    args = parser.parse_args()
    return migrate(args.security_db, args.persistence_db, args.apply)


if __name__ == "__main__":
    raise SystemExit(main())
