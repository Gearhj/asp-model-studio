from __future__ import annotations

import json
import logging
import os
import sqlite3
import time
from contextlib import contextmanager
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator


LOGGER = logging.getLogger("atlas.persistence")
PERSISTENCE_ROOT = Path(__file__).resolve().parent
DEFAULT_DATABASE_PATH = PERSISTENCE_ROOT.parent / "data" / "atlas_local.db"
SCHEMA_PATH = PERSISTENCE_ROOT / "schema.sql"
MIGRATIONS_PATH = PERSISTENCE_ROOT / "migrations"


class PersistenceUnavailableError(RuntimeError):
    pass


_TRANSACTION_BREAKING_SQL = {
    "ATTACH",
    "BEGIN",
    "COMMIT",
    "DETACH",
    "END",
    "PRAGMA",
    "RELEASE",
    "ROLLBACK",
    "SAVEPOINT",
    "VACUUM",
}


def _sql_statements(script: str) -> Iterator[str]:
    """Yield complete SQLite statements without using ``executescript``.

    ``sqlite3.Connection.executescript`` commits a pending transaction before it
    runs the supplied script.  That behavior makes it unsuitable for migrations:
    a later failing statement can leave earlier schema and data changes durable.
    ``sqlite3.complete_statement`` understands trigger bodies, quoted semicolons,
    and comments, so each yielded statement remains safe to execute inside the
    transaction owned by the migration runner.
    """

    buffer: list[str] = []
    for character in script.lstrip("\ufeff"):
        buffer.append(character)
        if character == ";" and sqlite3.complete_statement("".join(buffer)):
            statement = "".join(buffer).strip()
            if statement:
                yield statement
            buffer.clear()
    trailing = "".join(buffer).strip()
    if trailing:
        # Let SQLite report an incomplete or malformed trailing statement while
        # the migration transaction is still active and therefore rollbackable.
        yield trailing


def _leading_sql_keyword(statement: str) -> str:
    """Return the first executable SQL keyword, ignoring leading comments."""

    remaining = statement.lstrip("\ufeff \t\r\n")
    while remaining:
        if remaining.startswith("--"):
            newline = remaining.find("\n")
            if newline < 0:
                return ""
            remaining = remaining[newline + 1 :].lstrip()
            continue
        if remaining.startswith("/*"):
            end = remaining.find("*/", 2)
            if end < 0:
                return ""
            remaining = remaining[end + 2 :].lstrip()
            continue
        break
    return remaining.split(None, 1)[0].rstrip(";").upper() if remaining else ""


def _validate_transactional_statement(statement: str, *, source: str) -> None:
    keyword = _leading_sql_keyword(statement)
    if keyword in _TRANSACTION_BREAKING_SQL:
        raise PersistenceUnavailableError(
            f"{source} contains transaction-breaking top-level SQL ({keyword}); "
            "transaction control belongs to the ATLAS migration runner"
        )


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
        connection: sqlite3.Connection | None = None
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            connection = sqlite3.connect(self.path, timeout=10.0)
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute("PRAGMA busy_timeout = 10000")
            deadline = time.monotonic() + 10.0
            while True:
                try:
                    current_mode = connection.execute("PRAGMA journal_mode").fetchone()[0]
                    if str(current_mode).lower() != "wal":
                        connection.execute("PRAGMA journal_mode = WAL").fetchone()
                    break
                except sqlite3.OperationalError as exc:
                    if "locked" not in str(exc).lower() or time.monotonic() >= deadline:
                        raise
                    # journal_mode changes do not consistently honor SQLite's
                    # busy timeout.  Retry only this connection bootstrap race;
                    # migration writes remain serialized by BEGIN IMMEDIATE.
                    time.sleep(0.025)
            return connection
        except (OSError, sqlite3.Error) as exc:
            if connection is not None:
                connection.close()
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

    def _execute_script_atomically(self, script: str, *, source: str) -> None:
        connection = self.connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            for statement in _sql_statements(script):
                _validate_transactional_statement(statement, source=source)
                connection.execute(statement)
            connection.commit()
        except BaseException:
            if connection.in_transaction:
                connection.rollback()
            raise
        finally:
            connection.close()

    def _apply_migration(self, migration: Path, script: str) -> bool:
        """Apply one migration and its history row in one serialized transaction."""

        connection = self.connect()
        try:
            # BEGIN IMMEDIATE serializes writers.  The migration history is
            # deliberately rechecked only after this lock is acquired so two
            # concurrent startup processes cannot both apply the same file.
            connection.execute("BEGIN IMMEDIATE")
            already_applied = connection.execute(
                "SELECT 1 FROM schema_migrations WHERE version = ?",
                (migration.name,),
            ).fetchone()
            if already_applied is not None:
                connection.commit()
                return False
            for statement in _sql_statements(script):
                _validate_transactional_statement(statement, source=migration.name)
                connection.execute(statement)
            connection.execute(
                "INSERT INTO schema_migrations (version, applied_at) VALUES (?, ?)",
                (migration.name, now_iso()),
            )
            connection.commit()
            return True
        except BaseException:
            if connection.in_transaction:
                connection.rollback()
            raise
        finally:
            connection.close()

    def apply_migrations(self, migrations: Iterable[str | Path] | None = None) -> list[str]:
        """Apply migration files independently and return newly applied versions."""

        migration_paths = (
            sorted(MIGRATIONS_PATH.glob("*.sql"))
            if migrations is None
            else sorted((Path(migration) for migration in migrations), key=lambda path: path.name)
        )
        applied: list[str] = []
        for migration in migration_paths:
            try:
                script = migration.read_text(encoding="utf-8")
                if self._apply_migration(migration, script):
                    applied.append(migration.name)
            except (OSError, sqlite3.Error, PersistenceUnavailableError) as exc:
                raise PersistenceUnavailableError(
                    f"ATLAS migration {migration.name} failed atomically: {exc}"
                ) from exc
        return applied

    def initialize(self) -> Dict[str, Any]:
        try:
            self._execute_script_atomically(
                SCHEMA_PATH.read_text(encoding="utf-8"),
                source=SCHEMA_PATH.name,
            )
            self.apply_migrations()
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
