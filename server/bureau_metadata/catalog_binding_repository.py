"""Append-only persistence for exact dataset-version catalog bindings.

Binding tables share the existing crosswalk-governance SQLite authority.  Read
operations are deliberately lazy and read-only: constructing this repository
or reading a missing authority never creates a directory, database, or table.
"""

from __future__ import annotations

from pathlib import Path
import sqlite3
from threading import RLock
from typing import Protocol, runtime_checkable

from .catalog_binding import (
    DatasetCatalogBindingRevision,
    calculate_binding_revision_checksum,
    dataset_catalog_binding_scope,
)
from .crosswalk_governance_repository import CROSSWALK_DATABASE_RELATIVE
from .restricted_storage import validate_restricted_metadata_root


MAX_BINDING_REVISION_BYTES = 512 * 1024


class CatalogBindingRepositoryError(RuntimeError):
    """Base error that never discloses catalog or dataset content."""


class CatalogBindingNotFoundError(CatalogBindingRepositoryError):
    """The exact binding identity or revision does not exist."""


class CatalogBindingConflictError(CatalogBindingRepositoryError):
    """The expected binding revision is not current."""

    def __init__(self, *, expected_revision: int, current_revision: int) -> None:
        self.expected_revision = expected_revision
        self.current_revision = current_revision
        super().__init__("Catalog binding revision conflict.")


class CatalogBindingRepositoryStateError(CatalogBindingRepositoryError):
    """Stored or proposed binding history is contradictory."""


@runtime_checkable
class CatalogBindingRepository(Protocol):
    def append(
        self,
        record: DatasetCatalogBindingRevision,
        *,
        expected_revision: int,
    ) -> DatasetCatalogBindingRevision: ...

    def get_current(self, binding_id: str) -> DatasetCatalogBindingRevision: ...

    def get_revision(
        self, binding_id: str, revision: int
    ) -> DatasetCatalogBindingRevision: ...

    def history(
        self, binding_id: str
    ) -> tuple[DatasetCatalogBindingRevision, ...]: ...


def _clean_binding_id(value: object) -> str:
    cleaned = str(value or "").strip()
    if not cleaned or len(cleaned) > 220 or any(
        ord(character) < 32 or ord(character) == 127 for character in cleaned
    ):
        raise CatalogBindingRepositoryStateError(
            "Catalog binding identity is missing or invalid."
        )
    return cleaned


class SQLiteCatalogBindingRepository:
    """Exact binding history in the crosswalk-governance SQLite authority."""

    def __init__(
        self,
        restricted_root: str | Path,
        *,
        repository_root: str | Path | None = None,
        database_path: str | Path | None = None,
    ) -> None:
        self.root = validate_restricted_metadata_root(
            restricted_root, repository_root=repository_root
        )
        self.database_path = (
            Path(database_path)
            if database_path is not None
            else self.root / CROSSWALK_DATABASE_RELATIVE
        )
        if not self.database_path.is_absolute():
            raise CatalogBindingRepositoryStateError(
                "Catalog binding database path must be absolute."
            )
        parent = self.database_path.parent.resolve(strict=False)
        if parent != self.root and self.root not in parent.parents:
            raise CatalogBindingRepositoryStateError(
                "Catalog binding database must remain under the restricted root."
            )
        self._lock = RLock()

    def _connect_write(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            str(self.database_path),
            timeout=30,
            isolation_level=None,
            check_same_thread=False,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 30000")
        return connection

    def _connect_read(self) -> sqlite3.Connection:
        if not self.database_path.is_file():
            raise CatalogBindingNotFoundError(
                "The exact catalog binding was not found."
            )
        connection = sqlite3.connect(
            f"{self.database_path.resolve(strict=True).as_uri()}?mode=ro",
            uri=True,
            timeout=30,
            isolation_level=None,
            check_same_thread=False,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only = ON")
        connection.execute("PRAGMA busy_timeout = 30000")
        return connection

    def _initialize_for_write(self) -> None:
        statements = (
            """
            CREATE TABLE IF NOT EXISTS bureau_catalog_binding_revisions (
              binding_id TEXT NOT NULL,
              revision INTEGER NOT NULL,
              revision_json TEXT NOT NULL,
              revision_checksum TEXT NOT NULL,
              previous_revision_checksum TEXT,
              tenant_id TEXT,
              project_id TEXT NOT NULL,
              dataset_id TEXT NOT NULL,
              dataset_version_id TEXT NOT NULL,
              catalog_version_id TEXT NOT NULL,
              catalog_checksum TEXT NOT NULL,
              server_recorded_at TEXT NOT NULL,
              PRIMARY KEY(binding_id, revision),
              UNIQUE(binding_id, revision_checksum)
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS bureau_catalog_binding_heads (
              binding_id TEXT PRIMARY KEY,
              current_revision INTEGER NOT NULL,
              current_checksum TEXT NOT NULL,
              FOREIGN KEY(binding_id, current_revision)
                REFERENCES bureau_catalog_binding_revisions(binding_id, revision)
            )
            """,
            """
            CREATE TRIGGER IF NOT EXISTS bureau_catalog_binding_revisions_no_update
            BEFORE UPDATE ON bureau_catalog_binding_revisions
            BEGIN SELECT RAISE(ABORT, 'catalog binding history is append only'); END
            """,
            """
            CREATE TRIGGER IF NOT EXISTS bureau_catalog_binding_revisions_no_delete
            BEFORE DELETE ON bureau_catalog_binding_revisions
            BEGIN SELECT RAISE(ABORT, 'catalog binding history is append only'); END
            """,
        )
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock, self._connect_write() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                for statement in statements:
                    connection.execute(statement)
                connection.commit()
            except Exception:
                connection.rollback()
                raise

    @staticmethod
    def _encode(record: DatasetCatalogBindingRevision) -> str:
        payload = record.model_dump_json()
        if len(payload.encode("utf-8")) > MAX_BINDING_REVISION_BYTES:
            raise CatalogBindingRepositoryStateError(
                "Catalog binding revision exceeds its storage limit."
            )
        return payload

    @staticmethod
    def _decode(payload: str) -> DatasetCatalogBindingRevision:
        try:
            record = DatasetCatalogBindingRevision.model_validate_json(payload)
        except Exception as exc:
            raise CatalogBindingRepositoryStateError(
                "Stored catalog binding violates its governed contract."
            ) from exc
        if calculate_binding_revision_checksum(record) != record.revision_checksum:
            raise CatalogBindingRepositoryStateError(
                "Stored catalog binding checksum verification failed."
            )
        return record

    @staticmethod
    def _validate_transition(
        record: DatasetCatalogBindingRevision,
        current: DatasetCatalogBindingRevision | None,
    ) -> None:
        if calculate_binding_revision_checksum(record) != record.revision_checksum:
            raise CatalogBindingRepositoryStateError(
                "Catalog binding checksum verification failed."
            )
        current_revision = current.revision if current else 0
        if record.revision != current_revision + 1:
            raise CatalogBindingRepositoryStateError(
                "The appended binding revision must be current revision plus one."
            )
        if current is None:
            if record.previous_revision_checksum is not None:
                raise CatalogBindingRepositoryStateError(
                    "The first binding revision cannot reference a predecessor."
                )
            return
        if record.previous_revision_checksum != current.revision_checksum:
            raise CatalogBindingRepositoryStateError(
                "The previous binding checksum is not the exact current checksum."
            )
        if (
            dataset_catalog_binding_scope(record.identity)
            != dataset_catalog_binding_scope(current.identity)
            or record.binding_id != current.binding_id
        ):
            raise CatalogBindingRepositoryStateError(
                "Catalog binding dataset scope is immutable across revisions."
            )

    @staticmethod
    def _binding_tables_exist(connection: sqlite3.Connection) -> bool:
        row = connection.execute(
            """
            SELECT COUNT(*) AS table_count FROM sqlite_master
            WHERE type='table' AND name IN (
              'bureau_catalog_binding_revisions',
              'bureau_catalog_binding_heads'
            )
            """
        ).fetchone()
        return bool(row and int(row["table_count"]) == 2)

    def append(
        self,
        record: DatasetCatalogBindingRevision,
        *,
        expected_revision: int,
    ) -> DatasetCatalogBindingRevision:
        binding_id = _clean_binding_id(record.binding_id)
        if expected_revision < 0:
            raise CatalogBindingRepositoryStateError(
                "expected_revision cannot be negative."
            )
        payload = self._encode(record)
        self._initialize_for_write()
        with self._lock, self._connect_write() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                head = connection.execute(
                    "SELECT * FROM bureau_catalog_binding_heads WHERE binding_id=?",
                    (binding_id,),
                ).fetchone()
                current_revision = int(head["current_revision"]) if head else 0
                if expected_revision != current_revision:
                    raise CatalogBindingConflictError(
                        expected_revision=expected_revision,
                        current_revision=current_revision,
                    )
                current = None
                if head is not None:
                    row = connection.execute(
                        """
                        SELECT revision_json FROM bureau_catalog_binding_revisions
                        WHERE binding_id=? AND revision=?
                        """,
                        (binding_id, current_revision),
                    ).fetchone()
                    if row is None:
                        raise CatalogBindingRepositoryStateError(
                            "Catalog binding head references a missing revision."
                        )
                    current = self._decode(row["revision_json"])
                self._validate_transition(record, current)
                identity = record.identity
                connection.execute(
                    """
                    INSERT INTO bureau_catalog_binding_revisions (
                      binding_id, revision, revision_json, revision_checksum,
                      previous_revision_checksum, tenant_id, project_id,
                      dataset_id, dataset_version_id, catalog_version_id,
                      catalog_checksum, server_recorded_at
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        binding_id,
                        record.revision,
                        payload,
                        record.revision_checksum,
                        record.previous_revision_checksum,
                        identity.tenant_id,
                        identity.project_id,
                        identity.dataset_id,
                        identity.dataset_version_id,
                        identity.catalog_version_id,
                        identity.catalog_checksum,
                        record.server_recorded_at,
                    ),
                )
                if head is None:
                    connection.execute(
                        """
                        INSERT INTO bureau_catalog_binding_heads(
                          binding_id, current_revision, current_checksum
                        ) VALUES (?,?,?)
                        """,
                        (binding_id, record.revision, record.revision_checksum),
                    )
                else:
                    changed = connection.execute(
                        """
                        UPDATE bureau_catalog_binding_heads
                        SET current_revision=?, current_checksum=?
                        WHERE binding_id=? AND current_revision=?
                        """,
                        (
                            record.revision,
                            record.revision_checksum,
                            binding_id,
                            expected_revision,
                        ),
                    ).rowcount
                    if changed != 1:
                        raise CatalogBindingConflictError(
                            expected_revision=expected_revision,
                            current_revision=current_revision,
                        )
                connection.commit()
                return record
            except Exception:
                connection.rollback()
                raise

    def get_current(self, binding_id: str) -> DatasetCatalogBindingRevision:
        exact_id = _clean_binding_id(binding_id)
        with self._connect_read() as connection:
            if not self._binding_tables_exist(connection):
                raise CatalogBindingNotFoundError(
                    "The exact catalog binding was not found."
                )
            row = connection.execute(
                """
                SELECT r.revision_json
                FROM bureau_catalog_binding_heads h
                JOIN bureau_catalog_binding_revisions r
                  ON r.binding_id=h.binding_id
                 AND r.revision=h.current_revision
                WHERE h.binding_id=?
                """,
                (exact_id,),
            ).fetchone()
        if row is None:
            raise CatalogBindingNotFoundError(
                "The exact catalog binding was not found."
            )
        return self._decode(row["revision_json"])

    def get_revision(
        self, binding_id: str, revision: int
    ) -> DatasetCatalogBindingRevision:
        exact_id = _clean_binding_id(binding_id)
        if int(revision) < 1:
            raise CatalogBindingNotFoundError(
                "The exact catalog binding revision was not found."
            )
        with self._connect_read() as connection:
            if not self._binding_tables_exist(connection):
                raise CatalogBindingNotFoundError(
                    "The exact catalog binding revision was not found."
                )
            row = connection.execute(
                """
                SELECT revision_json FROM bureau_catalog_binding_revisions
                WHERE binding_id=? AND revision=?
                """,
                (exact_id, int(revision)),
            ).fetchone()
        if row is None:
            raise CatalogBindingNotFoundError(
                "The exact catalog binding revision was not found."
            )
        record = self._decode(row["revision_json"])
        if record.revision != int(revision):
            raise CatalogBindingRepositoryStateError(
                "Stored catalog binding revision is contradictory."
            )
        return record

    def history(
        self, binding_id: str
    ) -> tuple[DatasetCatalogBindingRevision, ...]:
        exact_id = _clean_binding_id(binding_id)
        with self._connect_read() as connection:
            if not self._binding_tables_exist(connection):
                raise CatalogBindingNotFoundError(
                    "The exact catalog binding was not found."
                )
            rows = connection.execute(
                """
                SELECT revision_json FROM bureau_catalog_binding_revisions
                WHERE binding_id=? ORDER BY revision ASC
                """,
                (exact_id,),
            ).fetchall()
        if not rows:
            raise CatalogBindingNotFoundError(
                "The exact catalog binding was not found."
            )
        history = tuple(self._decode(row["revision_json"]) for row in rows)
        for index, record in enumerate(history, start=1):
            if record.revision != index:
                raise CatalogBindingRepositoryStateError(
                    "Stored catalog binding revision sequence is contradictory."
                )
            if index > 1 and (
                record.previous_revision_checksum
                != history[index - 2].revision_checksum
            ):
                raise CatalogBindingRepositoryStateError(
                    "Stored catalog binding checksum chain is contradictory."
                )
        return history


__all__ = [
    "CatalogBindingConflictError",
    "CatalogBindingNotFoundError",
    "CatalogBindingRepository",
    "CatalogBindingRepositoryError",
    "CatalogBindingRepositoryStateError",
    "MAX_BINDING_REVISION_BYTES",
    "SQLiteCatalogBindingRepository",
]
