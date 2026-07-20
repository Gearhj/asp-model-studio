"""Inspect the local ATLAS SQLite persistence database from the repository root."""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
from pathlib import Path
from typing import Iterable


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATABASE = ROOT / "server" / "data" / "atlas_local.db"

SECTIONS = (
    ("Users", "users", "updated_at", ("user_id", "display_name", "email", "role", "status", "last_active_at", "updated_at")),
    ("Latest projects", "projects", "updated_at", ("project_id", "project_name", "project_type", "workflow_type", "template_id", "status", "created_by", "updated_by", "updated_at")),
    ("Latest workflow states", "workflow_state", "updated_at", ("project_id", "current_step_id", "completed_steps_json", "completed_by", "updated_at")),
    ("Latest evidence artifacts", "evidence_artifacts", "created_at", ("evidence_id", "project_id", "step_id", "artifact_type", "status", "title", "created_by", "created_at")),
    ("Latest run records", "run_records", "completed_at", ("run_id", "project_id", "run_type", "status", "created_by", "metrics_json", "completed_at")),
    ("Latest documentation packages", "documentation_packages", "updated_at", ("package_id", "project_id", "package_type", "status", "readiness_score", "section_count", "completed_section_count", "created_by", "updated_at")),
    ("Latest export artifacts", "export_artifacts", "created_at", ("export_id", "project_id", "export_type", "file_name", "storage_mode", "file_path", "created_by", "created_at")),
    ("Latest decision journal entries", "decision_journal", "updated_at", ("decision_id", "project_id", "decision_type", "title", "status", "owner", "updated_at")),
    ("Latest audit events", "audit_log", "created_at", ("audit_id", "user_id", "project_id", "action_type", "entity_type", "entity_id", "summary", "created_at")),
    ("Latest demo feedback", "demo_feedback", "created_at", ("feedback_id", "user_id", "project_id", "workflow_type", "step_id", "issue_type", "severity", "created_at")),
)


def compact(value: object, width: int = 180) -> str:
    if value is None:
        return "-"
    text = str(value).replace("\r", " ").replace("\n", " ")
    if text.startswith(("{", "[")):
        try:
            text = json.dumps(json.loads(text), ensure_ascii=True, separators=(",", ":"))
        except (TypeError, ValueError):
            pass
    return text if len(text) <= width else f"{text[: width - 3]}..."


def print_rows(rows: Iterable[sqlite3.Row], columns: tuple[str, ...]) -> None:
    found = False
    for row in rows:
        found = True
        print("  " + " | ".join(f"{column}={compact(row[column])}" for column in columns))
    if not found:
        print("  (none)")


def inspect(database_path: Path, limit: int) -> int:
    path = database_path.expanduser().resolve()
    print(f"ATLAS SQLite database: {path}")
    if not path.is_file():
        print("ERROR: database file does not exist. Start the backend once to initialize it.")
        return 1

    connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        tables = {
            row["name"]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )
        }
        print("\nTable counts")
        for table in sorted(tables):
            count = connection.execute(f'SELECT COUNT(*) AS count FROM "{table}"').fetchone()["count"]
            print(f"  {table}: {count:,}")

        for title, table, order_column, columns in SECTIONS:
            print(f"\n{title}")
            if table not in tables:
                print("  (table not present)")
                continue
            available = {row["name"] for row in connection.execute(f'PRAGMA table_info("{table}")')}
            selected = tuple(column for column in columns if column in available)
            order = order_column if order_column in available else selected[0]
            query = f'SELECT {", ".join(selected)} FROM "{table}" ORDER BY "{order}" DESC LIMIT ?'
            print_rows(connection.execute(query, (limit,)).fetchall(), selected)
    finally:
        connection.close()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--db",
        type=Path,
        default=Path(os.getenv("ATLAS_SQLITE_PATH", DEFAULT_DATABASE)),
        help="SQLite path (defaults to server/data/atlas_local.db or ATLAS_SQLITE_PATH).",
    )
    parser.add_argument("--limit", type=int, default=10, help="Rows shown per detail section.")
    args = parser.parse_args()
    return inspect(args.db, max(1, min(args.limit, 100)))


if __name__ == "__main__":
    raise SystemExit(main())
