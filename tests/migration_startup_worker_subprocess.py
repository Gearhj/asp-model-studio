"""Fresh-process migration worker using files instead of Windows named pipes."""

from __future__ import annotations

from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3
import sys
import time


def main() -> int:
    if len(sys.argv) != 4:
        return 2
    database_path = Path(sys.argv[1]).resolve()
    gate = Path(sys.argv[2]).resolve()
    result_path = Path(sys.argv[3]).resolve()
    deadline = time.monotonic() + 30.0
    while not gate.is_file():
        if time.monotonic() >= deadline:
            raise TimeoutError("Concurrent migration start gate was not released.")
        time.sleep(0.01)

    # Bind the isolated fixture only after sitecustomize has validated the
    # launcher's original authority envelope and before importing persistence.
    os.environ["ATLAS_SQLITE_PATH"] = str(database_path)
    from server.persistence import db as spawned_persistence_db

    spawned_persistence_db._database = None
    health = spawned_persistence_db.initialize_persistence()
    with closing(sqlite3.connect(database_path)) as connection:
        versions = [
            row[0]
            for row in connection.execute(
                "SELECT version FROM schema_migrations ORDER BY version"
            ).fetchall()
        ]
        total, distinct = connection.execute(
            "SELECT COUNT(*), COUNT(DISTINCT version) FROM schema_migrations"
        ).fetchone()
    result_path.write_text(
        json.dumps(
            {
                "ok": bool(health["ok"]),
                "versions": versions,
                "total": int(total),
                "distinct": int(distinct),
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
