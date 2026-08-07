"""Append-only repository contract for governed bureau crosswalk revisions.

The in-memory implementation is a deterministic reference implementation for
isolated tests and composition roots.  Durable adapters must preserve the same
exact-revision and compare-and-append semantics; this module never touches the
application database or migration system.
"""

from __future__ import annotations

from pathlib import Path
import sqlite3
from threading import RLock
from typing import Protocol, runtime_checkable

from .crosswalk_governance import (
    GovernedCrosswalkRevision,
    calculate_revision_checksum,
)
from .restricted_storage import validate_restricted_metadata_root


MAX_CROSSWALK_REVISION_BYTES = 2 * 1024 * 1024
CROSSWALK_DATABASE_RELATIVE = Path("registry") / "crosswalk_governance.sqlite3"


class CrosswalkGovernanceRepositoryError(RuntimeError):
    """Base repository error with no dataset or catalog content."""


class CrosswalkGovernanceNotFoundError(CrosswalkGovernanceRepositoryError):
    """Raised when one exact governance identity or revision does not exist."""


class CrosswalkGovernanceConflictError(CrosswalkGovernanceRepositoryError):
    """Raised when the caller's compare revision is not current."""

    def __init__(self, *, expected_revision: int, current_revision: int) -> None:
        self.expected_revision = expected_revision
        self.current_revision = current_revision
        super().__init__(
            "Crosswalk revision conflict: the expected revision is not current."
        )


class CrosswalkGovernanceStateError(CrosswalkGovernanceRepositoryError):
    """Raised when an append would violate immutable history or lineage."""


@runtime_checkable
class GovernedCrosswalkRepository(Protocol):
    def append(
        self,
        record: GovernedCrosswalkRevision,
        *,
        expected_revision: int,
    ) -> GovernedCrosswalkRevision:
        """Atomically compare the current revision and append exactly one record."""

    def get_current(self, governance_id: str) -> GovernedCrosswalkRevision:
        """Return the exact current record or raise; no first/latest fallback."""

    def get_revision(
        self,
        governance_id: str,
        revision: int,
    ) -> GovernedCrosswalkRevision:
        """Return one exact historical revision or raise."""

    def history(self, governance_id: str) -> tuple[GovernedCrosswalkRevision, ...]:
        """Return immutable append order for one exact governance identity."""


class InMemoryGovernedCrosswalkRepository:
    """Thread-safe append-only reference repository using synthetic memory only."""

    def __init__(self) -> None:
        self._histories: dict[str, tuple[GovernedCrosswalkRevision, ...]] = {}
        self._lock = RLock()

    def append(
        self,
        record: GovernedCrosswalkRevision,
        *,
        expected_revision: int,
    ) -> GovernedCrosswalkRevision:
        if expected_revision < 0:
            raise CrosswalkGovernanceStateError(
                "expected_revision cannot be negative."
            )
        if calculate_revision_checksum(record) != record.revision_checksum:
            raise CrosswalkGovernanceStateError(
                "Crosswalk revision checksum verification failed."
            )

        with self._lock:
            history = self._histories.get(record.governance_id, ())
            current_revision = history[-1].revision if history else 0
            if expected_revision != current_revision:
                raise CrosswalkGovernanceConflictError(
                    expected_revision=expected_revision,
                    current_revision=current_revision,
                )
            if record.revision != current_revision + 1:
                raise CrosswalkGovernanceStateError(
                    "The appended revision must be exactly current revision plus one."
                )

            if not history:
                if record.previous_revision_checksum is not None:
                    raise CrosswalkGovernanceStateError(
                        "The first revision cannot reference a previous record."
                    )
            else:
                current = history[-1]
                if record.previous_revision_checksum != current.revision_checksum:
                    raise CrosswalkGovernanceStateError(
                        "The previous-revision checksum is not the exact current checksum."
                    )
                immutable_identity = (
                    record.lineage,
                    record.source_crosswalk_id,
                    record.source_crosswalk_checksum,
                )
                current_identity = (
                    current.lineage,
                    current.source_crosswalk_id,
                    current.source_crosswalk_checksum,
                )
                if immutable_identity != current_identity:
                    raise CrosswalkGovernanceStateError(
                        "Crosswalk lineage and source identity are immutable across revisions."
                    )

            self._histories[record.governance_id] = (*history, record)
            return record

    def get_current(self, governance_id: str) -> GovernedCrosswalkRevision:
        with self._lock:
            history = self._histories.get(governance_id)
            if not history:
                raise CrosswalkGovernanceNotFoundError(
                    "The exact governed crosswalk was not found."
                )
            return history[-1]

    def get_revision(
        self,
        governance_id: str,
        revision: int,
    ) -> GovernedCrosswalkRevision:
        if revision < 1:
            raise CrosswalkGovernanceNotFoundError(
                "The exact governed crosswalk revision was not found."
            )
        with self._lock:
            history = self._histories.get(governance_id)
            if not history or revision > len(history):
                raise CrosswalkGovernanceNotFoundError(
                    "The exact governed crosswalk revision was not found."
                )
            record = history[revision - 1]
            if record.revision != revision:
                raise CrosswalkGovernanceStateError(
                    "Stored crosswalk revision sequence is contradictory."
                )
            return record

    def history(self, governance_id: str) -> tuple[GovernedCrosswalkRevision, ...]:
        with self._lock:
            history = self._histories.get(governance_id)
            if not history:
                raise CrosswalkGovernanceNotFoundError(
                    "The exact governed crosswalk was not found."
                )
            return history


def _clean_governance_id(value: object) -> str:
    cleaned = str(value or "").strip()
    if not cleaned or len(cleaned) > 220 or any(
        ord(character) < 32 or ord(character) == 127 for character in cleaned
    ):
        raise CrosswalkGovernanceStateError(
            "Crosswalk governance identity is missing or invalid."
        )
    return cleaned


class SQLiteGovernedCrosswalkRepository:
    """Durable append-only repository isolated under restricted metadata root.

    This authority deliberately uses its own self-versioned SQLite file instead
    of the ATLAS application migration runner, so catalog operations never apply
    or depend on live migration 0028.
    """

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
            raise CrosswalkGovernanceStateError(
                "Crosswalk database path must be absolute."
            )
        parent = self.database_path.parent.resolve(strict=False)
        if parent != self.root and self.root not in parent.parents:
            raise CrosswalkGovernanceStateError(
                "Crosswalk database must remain under the restricted root."
            )
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
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

    def _initialize(self) -> None:
        statements = (
            """
            CREATE TABLE IF NOT EXISTS bureau_crosswalk_revisions (
              governance_id TEXT NOT NULL,
              revision INTEGER NOT NULL,
              revision_json TEXT NOT NULL,
              revision_checksum TEXT NOT NULL,
              previous_revision_checksum TEXT,
              project_id TEXT NOT NULL,
              dataset_id TEXT NOT NULL,
              dataset_version_id TEXT NOT NULL,
              catalog_checksum TEXT NOT NULL,
              created_at TEXT NOT NULL,
              PRIMARY KEY(governance_id, revision),
              UNIQUE(governance_id, revision_checksum)
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS bureau_crosswalk_heads (
              governance_id TEXT PRIMARY KEY,
              current_revision INTEGER NOT NULL,
              current_checksum TEXT NOT NULL,
              FOREIGN KEY(governance_id, current_revision)
                REFERENCES bureau_crosswalk_revisions(governance_id, revision)
            )
            """,
            """
            CREATE TRIGGER IF NOT EXISTS bureau_crosswalk_revisions_no_update
            BEFORE UPDATE ON bureau_crosswalk_revisions
            BEGIN SELECT RAISE(ABORT, 'crosswalk history is append only'); END
            """,
            """
            CREATE TRIGGER IF NOT EXISTS bureau_crosswalk_revisions_no_delete
            BEFORE DELETE ON bureau_crosswalk_revisions
            BEGIN SELECT RAISE(ABORT, 'crosswalk history is append only'); END
            """,
        )
        with self._lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                for statement in statements:
                    connection.execute(statement)
                connection.commit()
            except Exception:
                connection.rollback()
                raise

    @staticmethod
    def _encode(record: GovernedCrosswalkRevision) -> str:
        payload = record.model_dump_json()
        if len(payload.encode("utf-8")) > MAX_CROSSWALK_REVISION_BYTES:
            raise CrosswalkGovernanceStateError(
                "Crosswalk revision exceeds its durable storage limit."
            )
        return payload

    @staticmethod
    def _decode(payload: str) -> GovernedCrosswalkRevision:
        try:
            record = GovernedCrosswalkRevision.model_validate_json(payload)
        except Exception as exc:
            raise CrosswalkGovernanceStateError(
                "Stored crosswalk revision violates its governed contract."
            ) from exc
        if calculate_revision_checksum(record) != record.revision_checksum:
            raise CrosswalkGovernanceStateError(
                "Stored crosswalk revision checksum verification failed."
            )
        return record

    @staticmethod
    def _validate_transition(
        record: GovernedCrosswalkRevision,
        current: GovernedCrosswalkRevision | None,
    ) -> None:
        if calculate_revision_checksum(record) != record.revision_checksum:
            raise CrosswalkGovernanceStateError(
                "Crosswalk revision checksum verification failed."
            )
        current_revision = current.revision if current else 0
        if record.revision != current_revision + 1:
            raise CrosswalkGovernanceStateError(
                "The appended revision must be exactly current revision plus one."
            )
        if current is None:
            if record.previous_revision_checksum is not None:
                raise CrosswalkGovernanceStateError(
                    "The first revision cannot reference a previous record."
                )
            return
        if record.previous_revision_checksum != current.revision_checksum:
            raise CrosswalkGovernanceStateError(
                "The previous-revision checksum is not the exact current checksum."
            )
        if (
            record.lineage,
            record.source_crosswalk_id,
            record.source_crosswalk_checksum,
        ) != (
            current.lineage,
            current.source_crosswalk_id,
            current.source_crosswalk_checksum,
        ):
            raise CrosswalkGovernanceStateError(
                "Crosswalk lineage and source identity are immutable across revisions."
            )

    def append(
        self,
        record: GovernedCrosswalkRevision,
        *,
        expected_revision: int,
    ) -> GovernedCrosswalkRevision:
        governance_id = _clean_governance_id(record.governance_id)
        if expected_revision < 0:
            raise CrosswalkGovernanceStateError(
                "expected_revision cannot be negative."
            )
        payload = self._encode(record)
        with self._lock, self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                head = connection.execute(
                    "SELECT * FROM bureau_crosswalk_heads WHERE governance_id=?",
                    (governance_id,),
                ).fetchone()
                current_revision = int(head["current_revision"]) if head else 0
                if expected_revision != current_revision:
                    raise CrosswalkGovernanceConflictError(
                        expected_revision=expected_revision,
                        current_revision=current_revision,
                    )
                current: GovernedCrosswalkRevision | None = None
                if head is not None:
                    row = connection.execute(
                        """
                        SELECT revision_json FROM bureau_crosswalk_revisions
                        WHERE governance_id=? AND revision=?
                        """,
                        (governance_id, current_revision),
                    ).fetchone()
                    if row is None:
                        raise CrosswalkGovernanceStateError(
                            "Crosswalk head references a missing revision."
                        )
                    current = self._decode(row["revision_json"])
                self._validate_transition(record, current)
                connection.execute(
                    """
                    INSERT INTO bureau_crosswalk_revisions (
                      governance_id, revision, revision_json, revision_checksum,
                      previous_revision_checksum, project_id, dataset_id,
                      dataset_version_id, catalog_checksum, created_at
                    ) VALUES (?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        governance_id,
                        record.revision,
                        payload,
                        record.revision_checksum,
                        record.previous_revision_checksum,
                        record.lineage.project_id,
                        record.lineage.dataset_id,
                        record.lineage.dataset_version_id,
                        record.lineage.catalog_checksum,
                        record.audit.occurred_at,
                    ),
                )
                if head is None:
                    connection.execute(
                        """
                        INSERT INTO bureau_crosswalk_heads(
                          governance_id, current_revision, current_checksum
                        ) VALUES (?,?,?)
                        """,
                        (governance_id, record.revision, record.revision_checksum),
                    )
                else:
                    changed = connection.execute(
                        """
                        UPDATE bureau_crosswalk_heads
                        SET current_revision=?, current_checksum=?
                        WHERE governance_id=? AND current_revision=?
                        """,
                        (
                            record.revision,
                            record.revision_checksum,
                            governance_id,
                            expected_revision,
                        ),
                    ).rowcount
                    if changed != 1:
                        raise CrosswalkGovernanceConflictError(
                            expected_revision=expected_revision,
                            current_revision=current_revision,
                        )
                connection.commit()
                return record
            except Exception:
                connection.rollback()
                raise

    def get_current(self, governance_id: str) -> GovernedCrosswalkRevision:
        exact_id = _clean_governance_id(governance_id)
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT r.revision_json
                FROM bureau_crosswalk_heads h
                JOIN bureau_crosswalk_revisions r
                  ON r.governance_id=h.governance_id
                 AND r.revision=h.current_revision
                WHERE h.governance_id=?
                """,
                (exact_id,),
            ).fetchone()
        if row is None:
            raise CrosswalkGovernanceNotFoundError(
                "The exact governed crosswalk was not found."
            )
        return self._decode(row["revision_json"])

    def get_revision(
        self,
        governance_id: str,
        revision: int,
    ) -> GovernedCrosswalkRevision:
        exact_id = _clean_governance_id(governance_id)
        if int(revision) < 1:
            raise CrosswalkGovernanceNotFoundError(
                "The exact governed crosswalk revision was not found."
            )
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT revision_json FROM bureau_crosswalk_revisions
                WHERE governance_id=? AND revision=?
                """,
                (exact_id, int(revision)),
            ).fetchone()
        if row is None:
            raise CrosswalkGovernanceNotFoundError(
                "The exact governed crosswalk revision was not found."
            )
        record = self._decode(row["revision_json"])
        if record.revision != int(revision):
            raise CrosswalkGovernanceStateError(
                "Stored crosswalk revision sequence is contradictory."
            )
        return record

    def history(self, governance_id: str) -> tuple[GovernedCrosswalkRevision, ...]:
        exact_id = _clean_governance_id(governance_id)
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT revision_json FROM bureau_crosswalk_revisions
                WHERE governance_id=? ORDER BY revision ASC
                """,
                (exact_id,),
            ).fetchall()
        if not rows:
            raise CrosswalkGovernanceNotFoundError(
                "The exact governed crosswalk was not found."
            )
        history = tuple(self._decode(row["revision_json"]) for row in rows)
        for index, record in enumerate(history, start=1):
            if record.revision != index:
                raise CrosswalkGovernanceStateError(
                    "Stored crosswalk revision sequence is contradictory."
                )
            if index > 1 and (
                record.previous_revision_checksum
                != history[index - 2].revision_checksum
            ):
                raise CrosswalkGovernanceStateError(
                    "Stored crosswalk checksum chain is contradictory."
                )
        return history


__all__ = [
    "CrosswalkGovernanceConflictError",
    "CROSSWALK_DATABASE_RELATIVE",
    "CrosswalkGovernanceNotFoundError",
    "CrosswalkGovernanceRepositoryError",
    "CrosswalkGovernanceStateError",
    "GovernedCrosswalkRepository",
    "InMemoryGovernedCrosswalkRepository",
    "MAX_CROSSWALK_REVISION_BYTES",
    "SQLiteGovernedCrosswalkRepository",
]
