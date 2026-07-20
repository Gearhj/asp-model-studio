"""Back up and reset the local ATLAS SQLite database from the repository root."""

from __future__ import annotations

import argparse
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATABASE = ROOT / "server" / "data" / "atlas_local.db"
sys.path.insert(0, str(ROOT))

from server.persistence.db import Database  # noqa: E402
from server.persistence.service import PersistenceService  # noqa: E402
from server.security.security_store import init_security_store, list_users  # noqa: E402


def reset(database_path: Path, *, confirmed: bool, backup: bool) -> int:
    path = database_path.expanduser().resolve()
    if not confirmed:
        print("REFUSED: pass --yes to reset the local ATLAS database.")
        return 2
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and backup:
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        backup_path = path.with_name(f"{path.stem}.{timestamp}.bak{path.suffix}")
        shutil.copy2(path, backup_path)
        print(f"Backup created: {backup_path}")
    for suffix in ("", "-wal", "-shm"):
        candidate = Path(f"{path}{suffix}")
        if candidate.exists():
            candidate.unlink()
    database = Database(path)
    health = database.initialize()
    init_security_store()
    service = PersistenceService(database)
    for user in list_users():
        service.sync_user(user)
    print(f"ATLAS SQLite reset complete: {path}")
    print(f"Schema version: {health.get('schemaVersion', 'unknown')}; users seeded: {len(list_users())}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--db",
        type=Path,
        default=Path(os.getenv("ATLAS_SQLITE_PATH", DEFAULT_DATABASE)),
        help="SQLite path (defaults to server/data/atlas_local.db or ATLAS_SQLITE_PATH).",
    )
    parser.add_argument("--yes", action="store_true", help="Confirm the destructive reset operation.")
    parser.add_argument("--no-backup", action="store_true", help="Skip the timestamped database backup.")
    args = parser.parse_args()
    return reset(args.db, confirmed=args.yes, backup=not args.no_backup)


if __name__ == "__main__":
    raise SystemExit(main())
