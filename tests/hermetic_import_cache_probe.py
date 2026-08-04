"""Hermetic child probe for import-time path caching and store writes.

This file is intentionally not named ``*_test.py``.  It is executed only by
``scripts/run_hermetic_tests.py`` after the standalone pre-import guard has
validated every authority.  The probe never prints configured environment
values or record payloads; it writes a relative-path result beneath the child
evidence root instead.
"""
from __future__ import annotations

import json
import hashlib
import os
from pathlib import Path
import sqlite3
from datetime import datetime, timezone


def _under(path: Path, root: Path) -> bool:
    path = path.expanduser().resolve()
    root = root.expanduser().resolve()
    return path == root or root in path.parents


def _require_under(label: str, path: Path, root: Path) -> None:
    if not _under(path, root):
        raise AssertionError(f"{label} escaped the hermetic child root")


def main() -> int:
    if os.environ.get("ATLAS_HERMETIC_GUARD_PASSED") != "1":
        raise AssertionError("pre-import hermetic guard did not run")
    run_id = os.environ.get("ATLAS_RUN_ID", "")
    if not run_id.startswith("atlas-hrt-"):
        raise AssertionError("hermetic run identifier is missing")
    root = Path(os.environ["ATLAS_HERMETIC_ROOT"]).resolve()
    source_root = Path(os.environ["ATLAS_HERMETIC_SOURCE_ROOT"]).resolve()
    child_id = os.environ.get("ATLAS_CHILD_ID", "missing-child")
    canary = f"{run_id}-{child_id}"

    # Import the complete application first.  All provider modules imported
    # transitively must already be bound to the child environment/source mirror.
    import server.main  # noqa: F401
    from server.core import session_checkpoint
    from server.core.dataset_store import get_scoped_dataset_store
    from server.datasets import dataset_registry
    from server.evidence import evidence_store
    from server.features import feature_manifest_store
    from server.model_documentation import documentation_store
    from server.model_registry import model_artifacts
    from server.notebooks import notebook_store
    from server.persistence.db import get_database
    from server.scoring_runs import scoring_run_artifacts
    from server.security import security_store

    provider_files = {
        "server.main": Path(server.main.__file__),
        "security": Path(security_store.__file__),
        "dataset": Path(dataset_registry.__file__),
        "checkpoint": Path(session_checkpoint.__file__),
        "evidence": Path(evidence_store.__file__),
        "mdd": Path(documentation_store.__file__),
        "feature_manifest": Path(feature_manifest_store.__file__),
    }
    import server.persistence.db as persistence_db_module
    provider_files["persistence"] = Path(persistence_db_module.__file__)
    for label, path in provider_files.items():
        _require_under(f"provider:{label}", path, source_root)

    configured_paths = {
        "persistence": Path(os.environ["ATLAS_SQLITE_PATH"]),
        "security": security_store.DB_PATH,
        "dataset": dataset_registry.ARTIFACT_ROOT,
        "checkpoint": session_checkpoint.CHECKPOINT_PATH,
        "evidence": evidence_store.EVIDENCE_ROOT,
        "feature_manifest": feature_manifest_store._root(),
        "model_artifacts": model_artifacts.ARTIFACT_ROOT,
        "scoring_artifacts": scoring_run_artifacts.ARTIFACT_ROOT,
        "mdd": documentation_store.DOCUMENTATION_ROOT,
        "notebooks": notebook_store.NOTEBOOK_ROOT,
    }
    for label, path in configured_paths.items():
        _require_under(f"authority:{label}", Path(path), root)

    # Exercise each store named by the import-cache regression contract.  No
    # training, evaluation, interpretation, promotion, or scoring API is used.
    security_store.init_security_store()
    security_store.create_user(
        user_id=f"{canary}-user",
        email=f"{canary}@invalid.example",
        display_name="Hermetic fixture",
        password=hashlib.sha256(canary.encode("utf-8")).hexdigest(),
        role="viewer",
    )
    security_store.audit_event(
        "hermetic.probe",
        "test_harness",
        canary,
        "success",
        metadata={"runId": canary},
    )

    database = get_database()
    database.initialize()
    with database.connection() as connection:
        applied_0028 = connection.execute(
            "SELECT COUNT(*) AS n FROM schema_migrations WHERE version LIKE ?",
            ("0028%",),
        ).fetchone()["n"]
    if applied_0028:
        raise AssertionError("migration 0028 was applied in a hermetic child")

    dataset_registry.ensure_store()
    dataset_registry.save_registry(
        {"datasets": [{"datasetId": f"{canary}-dataset", "name": canary}]}
    )
    dataset_registry.save_links(
        {"links": [{"projectId": f"{canary}-project", "datasetId": f"{canary}-dataset"}]}
    )

    scoped = get_scoped_dataset_store((f"{canary}-user", "unscoped"))
    scoped.meta["hermetic_run_id"] = canary
    if not session_checkpoint.save_checkpoint():
        raise AssertionError("checkpoint store did not persist inside the child")

    evidence_store.upsert_evidence(
        {
            "evidenceId": f"{canary}-evidence",
            "title": "Hermetic storage probe",
            "evidenceType": "test_harness",
            "sourcePage": "Hermetic Test Harness",
            "status": "draft",
            "projectId": f"{canary}-project",
            "datasetId": f"{canary}-dataset",
        }
    )

    now = datetime.now(timezone.utc).isoformat()
    documentation_store.save_document(
        {
            "documentId": f"{canary}-mdd",
            "projectId": f"{canary}-project",
            "projectName": "Hermetic fixture",
            "templateType": "predictive_modeling",
            "createdAt": now,
            "quality": {},
        }
    )

    identity = {
        "project_id": f"{canary}-project",
        "dataset_id": f"{canary}-dataset",
        "dataset_version_id": f"{canary}-version",
    }
    feature_result = feature_manifest_store.persist_manifest_version(
        identity,
        {
            "manifest_hash": f"fm-{canary}",
            "features": [],
            "pipeline_steps": [],
        },
    )

    # The notebook provider has no environment override.  A source-relative
    # write proves that the mirror, rather than the live repository, owns it.
    notebook_store.ensure_store()

    expected_files = [
        Path(os.environ["ATLAS_SQLITE_PATH"]),
        security_store.DB_PATH,
        dataset_registry.REGISTRY_PATH,
        dataset_registry.PROJECT_LINKS_PATH,
        session_checkpoint.CHECKPOINT_PATH,
        evidence_store.REGISTRY_PATH,
        documentation_store.DOCUMENT_INDEX_PATH,
        Path(feature_result["current_path"]),
    ]
    missing = [label for label, path in enumerate(expected_files) if not path.exists()]
    if missing:
        raise AssertionError("one or more hermetic stores did not create evidence")

    # Confirm the security canary is present only in this child's database.
    with sqlite3.connect(security_store.DB_PATH) as connection:
        count = connection.execute(
            "SELECT COUNT(*) FROM audit_events WHERE resource_id = ?",
            (canary,),
        ).fetchone()[0]
    if count != 1:
        raise AssertionError("security canary was not isolated to the child database")

    result = {
        "status": "passed",
        "run_id": run_id,
        "child_id": child_id,
        "providers": sorted(provider_files),
        "authorities": sorted(configured_paths),
        "migration_0028_applied": False,
        "store_write_count": len(expected_files),
    }
    output = root / "reports" / "import-cache-probe.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
