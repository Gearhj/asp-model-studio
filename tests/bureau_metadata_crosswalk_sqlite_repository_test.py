from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
import sqlite3
from threading import Barrier
import tempfile

import pytest

import server.bureau_metadata.crosswalk_governance_repository as repository_module
from server.bureau_metadata.crosswalk_governance import (
    CrosswalkAuditMetadata,
    CrosswalkEvidenceReference,
    CrosswalkLineage,
    GovernedMappingDecision,
    build_governed_revision,
)
from server.bureau_metadata.crosswalk_governance_repository import (
    CrosswalkGovernanceConflictError,
    CrosswalkGovernanceNotFoundError,
    CrosswalkGovernanceStateError,
    SQLiteGovernedCrosswalkRepository,
)
from server.bureau_metadata.types import BureauCatalogKey


NOW = "2026-08-05T12:00:00Z"
GOVERNANCE_ID = "gcw_synthetic_sqlite_contract"


def _lineage() -> CrosswalkLineage:
    return CrosswalkLineage(
        project_id="project-synthetic-sqlite",
        dataset_id="dataset-synthetic-sqlite",
        dataset_version_id="version-synthetic-sqlite-1",
        activation_revision=3,
        target_contract_id="target-contract-synthetic",
        predictor_authorization_id="predictor-authorization-synthetic",
        schema_checksum="a" * 64,
        catalog_key=BureauCatalogKey(
            provider="Synthetic Bureau",
            product="Synthetic Product",
            edition="Test",
            dictionary_version="1.0",
        ),
        catalog_checksum="b" * 64,
    )


def _evidence(kind: str) -> CrosswalkEvidenceReference:
    return CrosswalkEvidenceReference(
        evidence_id=f"evidence-{kind}",
        evidence_kind=kind,
        authority_id=f"authority-{kind}",
        checksum="c" * 64,
        created_by="analyst-synthetic",
        created_at=NOW,
    )


def _decision() -> GovernedMappingDecision:
    return GovernedMappingDecision(
        dataset_field="synthetic_score",
        mapping_state="exact_verified",
        candidate_attribute_code="SYNTH_001",
        evidence=(
            _evidence("catalog_definition"),
            _evidence("exact_match"),
            _evidence("analyst_review"),
        ),
        analyst_confirmed=True,
        rationale="Synthetic exact-code review.",
        reviewer_id="analyst-synthetic",
    )


def _revision(
    revision: int,
    *,
    previous_checksum: str | None,
    request_suffix: str,
):
    return build_governed_revision(
        governance_id=GOVERNANCE_ID,
        revision=revision,
        lifecycle_state="draft" if revision == 1 else "confirmed",
        lineage=_lineage(),
        source_crosswalk_id="candidate-crosswalk-synthetic",
        source_crosswalk_checksum="d" * 64,
        decisions=(_decision(),),
        audit=CrosswalkAuditMetadata(
            actor_id="analyst-synthetic",
            request_id=f"request-{request_suffix}",
            occurred_at=NOW,
            reason=f"Synthetic revision {revision} persistence test.",
        ),
        previous_revision_checksum=previous_checksum,
    )


@pytest.fixture
def restricted_root(
    request: pytest.FixtureRequest,
    monkeypatch: pytest.MonkeyPatch,
) -> Path:
    # The hermetic launcher pre-creates its authority tree with ACLs shared by
    # the parent and restricted child token.  pytest's Windows ``tmp_path``
    # parent is owner-only, which can make it inaccessible to that child token;
    # keep this SQLite fixture in the existing hermetic authority instead.
    hermetic_root = os.environ.get("ATLAS_HERMETIC_ROOT")
    if hermetic_root:
        restricted = (
            Path(hermetic_root)
            / "authorities"
            / "crosswalk-sqlite-tests"
            / request.node.name
        )
        restricted.mkdir(parents=True, exist_ok=False)
    else:
        restricted = Path(
            tempfile.mkdtemp(prefix="atlas-crosswalk-sqlite-test-")
        ) / "restricted-bureau-metadata"
        restricted.mkdir()

    def validate_exact_test_root(value, **_kwargs):  # type: ignore[no-untyped-def]
        candidate = Path(value).resolve(strict=True)
        if candidate != restricted.resolve(strict=True):
            raise AssertionError(
                "The synthetic validator permits one exact isolated test root."
            )
        return candidate

    monkeypatch.setattr(
        repository_module,
        "validate_restricted_metadata_root",
        validate_exact_test_root,
    )
    return restricted


def test_sqlite_repository_persists_exact_history_across_reopen(
    restricted_root: Path,
) -> None:
    restricted = restricted_root
    first_repository = SQLiteGovernedCrosswalkRepository(restricted)
    first = _revision(1, previous_checksum=None, request_suffix="first")
    second = _revision(
        2,
        previous_checksum=first.revision_checksum,
        request_suffix="second",
    )
    first_repository.append(first, expected_revision=0)
    first_repository.append(second, expected_revision=1)

    reopened = SQLiteGovernedCrosswalkRepository(restricted)

    assert reopened.get_current(GOVERNANCE_ID) == second
    assert reopened.get_revision(GOVERNANCE_ID, 1) == first
    assert reopened.history(GOVERNANCE_ID) == (first, second)


def test_sqlite_history_table_is_database_enforced_append_only(
    restricted_root: Path,
) -> None:
    restricted = restricted_root
    repository = SQLiteGovernedCrosswalkRepository(restricted)
    first = _revision(1, previous_checksum=None, request_suffix="first")
    repository.append(first, expected_revision=0)

    with sqlite3.connect(repository.database_path) as connection:
        with pytest.raises(sqlite3.DatabaseError, match="append only"):
            connection.execute(
                "UPDATE bureau_crosswalk_revisions SET project_id=? WHERE governance_id=?",
                ("tampered-project", GOVERNANCE_ID),
            )
        connection.rollback()

    with sqlite3.connect(repository.database_path) as connection:
        with pytest.raises(sqlite3.DatabaseError, match="append only"):
            connection.execute(
                "DELETE FROM bureau_crosswalk_revisions WHERE governance_id=?",
                (GOVERNANCE_ID,),
            )
        connection.rollback()

    assert repository.get_revision(GOVERNANCE_ID, 1) == first


def test_sqlite_exact_revision_lookup_never_falls_back(
    restricted_root: Path,
) -> None:
    repository = SQLiteGovernedCrosswalkRepository(restricted_root)
    first = _revision(1, previous_checksum=None, request_suffix="first")
    second = _revision(
        2,
        previous_checksum=first.revision_checksum,
        request_suffix="second",
    )
    repository.append(first, expected_revision=0)
    repository.append(second, expected_revision=1)

    assert repository.get_revision(GOVERNANCE_ID, 1).revision == 1
    assert repository.get_current(GOVERNANCE_ID).revision == 2
    with pytest.raises(CrosswalkGovernanceNotFoundError):
        repository.get_revision(GOVERNANCE_ID, 3)
    with pytest.raises(CrosswalkGovernanceNotFoundError):
        repository.get_revision("gcw_missing_synthetic", 1)
    with pytest.raises(CrosswalkGovernanceNotFoundError):
        repository.get_current("gcw_missing_synthetic")


def test_sqlite_append_rejects_broken_checksum_chain_atomically(
    restricted_root: Path,
) -> None:
    repository = SQLiteGovernedCrosswalkRepository(restricted_root)
    first = _revision(1, previous_checksum=None, request_suffix="first")
    repository.append(first, expected_revision=0)
    broken = _revision(
        2,
        previous_checksum="e" * 64,
        request_suffix="broken-chain",
    )

    with pytest.raises(CrosswalkGovernanceStateError, match="previous-revision checksum"):
        repository.append(broken, expected_revision=1)

    assert repository.get_current(GOVERNANCE_ID) == first
    assert repository.history(GOVERNANCE_ID) == (first,)


def test_sqlite_competing_writers_allow_exactly_one_revision(
    restricted_root: Path,
) -> None:
    restricted = restricted_root
    first_repository = SQLiteGovernedCrosswalkRepository(restricted)
    second_repository = SQLiteGovernedCrosswalkRepository(restricted)
    first = _revision(1, previous_checksum=None, request_suffix="first")
    first_repository.append(first, expected_revision=0)
    barrier = Barrier(2)

    def compete(repository: SQLiteGovernedCrosswalkRepository, suffix: str):
        candidate = _revision(
            2,
            previous_checksum=first.revision_checksum,
            request_suffix=suffix,
        )
        barrier.wait(timeout=5)
        return repository.append(candidate, expected_revision=1)

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = (
            pool.submit(compete, first_repository, "writer-one"),
            pool.submit(compete, second_repository, "writer-two"),
        )

    successes = []
    failures = []
    for future in futures:
        try:
            successes.append(future.result())
        except BaseException as exc:  # noqa: BLE001 - exact error asserted below
            failures.append(exc)

    assert len(successes) == 1
    assert len(failures) == 1
    assert isinstance(failures[0], CrosswalkGovernanceConflictError)
    reopened = SQLiteGovernedCrosswalkRepository(restricted)
    assert reopened.get_current(GOVERNANCE_ID) == successes[0]
    assert [record.revision for record in reopened.history(GOVERNANCE_ID)] == [1, 2]
