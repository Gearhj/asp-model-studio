from __future__ import annotations

import json
import logging
import os
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterator


LOGGER = logging.getLogger("atlas.persistence")
PERSISTENCE_ROOT = Path(__file__).resolve().parent
DEFAULT_DATABASE_PATH = PERSISTENCE_ROOT.parent / "data" / "atlas_local.db"
SCHEMA_PATH = PERSISTENCE_ROOT / "schema.sql"
MIGRATIONS_PATH = PERSISTENCE_ROOT / "migrations"


class PersistenceUnavailableError(RuntimeError):
    pass


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json_default(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    if hasattr(value, "item"):
        try:
            return value.item()
        except Exception:
            pass
    if isinstance(value, set):
        return sorted(value)
    return str(value)


def json_dumps(value: Any, fallback: Any = None) -> str:
    safe_value = fallback if value is None else value
    try:
        return json.dumps(safe_value, default=_json_default, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
    except (TypeError, ValueError):
        return json.dumps(fallback if fallback is not None else {}, ensure_ascii=True, separators=(",", ":"), sort_keys=True)


def json_loads(value: Any, fallback: Any = None) -> Any:
    if value in (None, ""):
        return fallback if fallback is not None else {}
    if not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return fallback if fallback is not None else {}


def decode_row(row: sqlite3.Row | None) -> Dict[str, Any] | None:
    if row is None:
        return None
    record = dict(row)
    for key, value in list(record.items()):
        if key.endswith("_json"):
            record[key] = json_loads(value, [] if key == "completed_steps_json" else {})
    return record


class Database:
    def __init__(self, path: str | Path | None = None) -> None:
        configured = path or os.getenv("ATLAS_SQLITE_PATH") or DEFAULT_DATABASE_PATH
        self.path = Path(configured).expanduser().resolve()

    def connect(self) -> sqlite3.Connection:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            connection = sqlite3.connect(self.path, timeout=10.0)
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute("PRAGMA busy_timeout = 10000")
            connection.execute("PRAGMA journal_mode = WAL")
            return connection
        except (OSError, sqlite3.Error) as exc:
            raise PersistenceUnavailableError(f"ATLAS persistence database is unavailable: {exc}") from exc

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        connection = self.connect()
        try:
            yield connection
        finally:
            connection.close()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        connection = self.connect()
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def initialize(self) -> Dict[str, Any]:
        try:
            with self.transaction() as connection:
                connection.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
                applied = {
                    row["version"]
                    for row in connection.execute("SELECT version FROM schema_migrations ORDER BY version").fetchall()
                }
                for migration in sorted(MIGRATIONS_PATH.glob("*.sql")):
                    if migration.name in applied:
                        continue
                    connection.executescript(migration.read_text(encoding="utf-8"))
                    connection.execute(
                        "INSERT INTO schema_migrations (version, applied_at) VALUES (?, ?)",
                        (migration.name, now_iso()),
                    )
            if os.getenv("ATLAS_ENV", "development").lower() in {"development", "dev", "local"}:
                LOGGER.info("ATLAS SQLite persistence initialized at %s", self.path)
            return self.health()
        except (OSError, sqlite3.Error, PersistenceUnavailableError) as exc:
            raise PersistenceUnavailableError(f"ATLAS persistence initialization failed: {exc}") from exc

    def health(self) -> Dict[str, Any]:
        try:
            with self.connection() as connection:
                connection.execute("SELECT 1").fetchone()
                tables = [
                    row["name"]
                    for row in connection.execute(
                        "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
                    ).fetchall()
                ]
            return {
                "ok": True,
                "status": "available",
                "databasePath": str(self.path),
                "databaseExists": self.path.exists(),
                "tables": tables,
            }
        except (OSError, sqlite3.Error, PersistenceUnavailableError) as exc:
            return {
                "ok": False,
                "status": "unavailable",
                "databasePath": str(self.path),
                "databaseExists": self.path.exists(),
                "error": str(exc),
                "tables": [],
            }


_database: Database | None = None


def get_database() -> Database:
    global _database
    configured = Path(os.getenv("ATLAS_SQLITE_PATH") or DEFAULT_DATABASE_PATH).expanduser().resolve()
    if _database is None or _database.path != configured:
        _database = Database(configured)
    return _database


def initialize_persistence() -> Dict[str, Any]:
    return get_database().initialize()
