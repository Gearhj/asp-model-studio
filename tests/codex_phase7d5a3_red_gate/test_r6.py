"""Repair 6 red gate: every required sensitive boundary uses a real Windows junction."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pytest

from scripts import quarantine_incomplete_test_namespace as Q
from server.sports_cockpit import gen3_authority as A
from server.sports_cockpit.path_containment import ContainmentError
from server.sports_modeling import silver_publish as SP
from tests._silver_fixture import SRC_ID, publish_silver_hermetic, publish_source

from ._helpers import assert_external_temp, make_junction, redirected_state, remove_junction


REPARSE_ERROR = r"reparse|junction"


def _state_root(root: Path) -> Path:
    return root / "runtime" / "sports-modeling" / "mlb-pa-gen3-v2" / "authority"


def _incomplete_namespace(state_root: Path, project_id: str) -> tuple[Path, str, str, str]:
    key = A._project_key(project_id)
    base = state_root / key
    binding, request, authority = "binding-red", "a" * 64, "authority-red"
    for directory, name in (("bindings", binding), ("requests", request), ("authorities", authority)):
        path = base / directory
        path.mkdir(parents=True, exist_ok=True)
        (path / f"{name}.json").write_text("{}", encoding="utf-8")
    return base, binding, request, authority


def test_source_object_directory_junction_rejected_before_read(tmp_path):
    root = assert_external_temp(tmp_path)
    source_root = root / "source"
    publish_source(source_root)
    registry = json.loads((source_root / "silver-source-registry.json").read_text(encoding="utf-8"))
    logical = registry["datasets"][SRC_ID]["logicalSha256"]
    object_dir = source_root / "objects" / "sha256" / logical
    outside = root / "outside-source-object"
    object_dir.rename(outside)
    make_junction(object_dir, outside)
    try:
        with pytest.raises(ContainmentError, match=REPARSE_ERROR):
            SP.resolve_verified_source(source_root, SRC_ID)
    finally:
        remove_junction(object_dir)


def test_silver_staging_root_junction_rejected_before_create_or_write(tmp_path):
    root = assert_external_temp(tmp_path)
    objects_root = root / "silver" / "objects" / "sha256"
    outside = root / "outside-staging-root"
    make_junction(objects_root, outside)
    try:
        with pytest.raises(ContainmentError, match=REPARSE_ERROR):
            SP._atomic_publish_children(objects_root, objects_root / ("b" * 64), {"child.json": b"{}"}, manifest_name="child.json")
        assert list(outside.iterdir()) == []
    finally:
        remove_junction(objects_root)


def test_silver_final_object_directory_junction_rejected_before_iteration(tmp_path):
    root = assert_external_temp(tmp_path)
    published = publish_silver_hermetic(root)
    object_dir = published["object_dir"]
    outside = root / "outside-silver-final"
    object_dir.rename(outside)
    make_junction(object_dir, outside)
    try:
        with pytest.raises(ContainmentError, match=REPARSE_ERROR):
            SP.verify_silver(published["silver_root"], published["manifest_sha"])
    finally:
        remove_junction(object_dir)


def test_silver_registry_parent_junction_rejected_before_write(tmp_path):
    root = assert_external_temp(tmp_path)
    silver_root = root / "silver"
    outside = root / "outside-registry-parent"
    make_junction(silver_root, outside)
    try:
        with pytest.raises(ContainmentError, match=REPARSE_ERROR):
            SP._register(silver_root, "source", "c" * 64, "d" * 64, 1, [2023])
        assert list(outside.iterdir()) == []
    finally:
        remove_junction(silver_root)


def test_registry_lock_parent_junction_rejected_before_lock_create(tmp_path):
    root = assert_external_temp(tmp_path) / "registry-root"
    root.mkdir(parents=True)
    lock_parent = root / "locks"
    outside = root.parent / "outside-lock-parent"
    make_junction(lock_parent, outside)
    try:
        with pytest.raises(ContainmentError, match=REPARSE_ERROR):
            SP._locked_registry_put(
                root / "registry.json",
                lock_parent / ".registry.lock",
                root,
                "RED_REGISTRY_V1",
                "key",
                {"value": 1},
            )
        assert list(outside.iterdir()) == []
    finally:
        remove_junction(lock_parent)


def test_v2_evidence_directory_junction_rejected_before_manifest_read(tmp_path):
    root = assert_external_temp(tmp_path)
    state_root = _state_root(root)
    project_id = "red-v2-directory"
    manifest_bytes = b"{}"
    manifest_sha = hashlib.sha256(manifest_bytes).hexdigest()
    parent = state_root / A._project_key(project_id) / "evidence-v2" / "objects" / "sha256"
    parent.mkdir(parents=True)
    outside = root / "outside-v2-directory"
    outside.mkdir()
    (outside / A._V2_MANIFEST_NAME).write_bytes(manifest_bytes)
    bundle = parent / manifest_sha
    make_junction(bundle, outside)
    try:
        with redirected_state(A, state_root):
            with pytest.raises(A.AuthorityError, match=REPARSE_ERROR):
                A._load_v2_bundle(project_id, manifest_sha)
    finally:
        remove_junction(bundle)


def test_v2_evidence_child_junction_rejected_before_resolve(tmp_path):
    root = assert_external_temp(tmp_path)
    state_root = _state_root(root)
    project_id = "red-v2-child"
    malicious = "model.artifact"
    names = [malicious] + sorted(A._V2_MANDATORY_CHILDREN - {malicious})
    children = {name: {"file": name, "sha256": hashlib.sha256(b"x").hexdigest()} for name in names}
    manifest = {
        "bundleContract": A.RUN_EVIDENCE_BUNDLE_V2,
        "bundleVersion": "2.0.0",
        "runId": "red-run",
        "status": "COMPLETE",
        "children": children,
    }
    manifest_bytes = A.canonical_json_bytes(manifest)
    manifest_sha = hashlib.sha256(manifest_bytes).hexdigest()
    final = state_root / A._project_key(project_id) / "evidence-v2" / "objects" / "sha256" / manifest_sha
    final.mkdir(parents=True)
    outside = root / "outside-v2-child"
    for name in names:
        if name == malicious:
            make_junction(final / name, outside)
        else:
            (final / name).write_bytes(b"x")
    (final / A._V2_MANIFEST_NAME).write_bytes(manifest_bytes)
    try:
        with redirected_state(A, state_root):
            with pytest.raises(A.AuthorityError, match=REPARSE_ERROR):
                A._load_v2_bundle(project_id, manifest_sha)
    finally:
        remove_junction(final / malicious)


def test_request_receipt_parent_junction_rejected_before_exists_or_read(tmp_path):
    root = assert_external_temp(tmp_path)
    state_root = _state_root(root)
    project_id = "red-request-receipt"
    request_sha = "e" * 64
    project_root = state_root / A._project_key(project_id)
    project_root.mkdir(parents=True)
    outside = root / "outside-request-receipt"
    outside.mkdir()
    (outside / f"{request_sha}.json").write_text("{}", encoding="utf-8")
    make_junction(project_root / "requests", outside)
    authority = {"modelRequestReceiptSha256": request_sha, "featureSetName": "custom"}
    binding = {"generation": "GEN3", "datasetVersionId": "synthetic", "datasetContentSha256": "f" * 64}
    contracts = {name: {} for name in ("target", "population", "temporal", "preprocessing", "knowledgeTime")}
    metrics = {
        "perClass": {},
        "classwiseBrier": {},
        "classwiseEce": {},
        "confusionMatrix": [],
        "confusionMatrixAxes": [],
    }
    try:
        with redirected_state(A, state_root):
            with pytest.raises(A.AuthorityError, match=REPARSE_ERROR):
                A._build_v2_content_children(
                    authority=authority,
                    binding=binding,
                    object_receipt={},
                    contracts=contracts,
                    feature_order=[],
                    model_artifact={},
                    preprocessor_state={},
                    estimator_bytes=b"model",
                    proba=np.zeros((0, 1)),
                    val_ids=[],
                    val_game_ids=[],
                    val_dates=[],
                    val_encoded=[],
                    val_labels=[],
                    full_metrics=metrics,
                    scalar_metrics={},
                    convergence={},
                    code={"codeRevision": "red", "worktreeContentSha256": "1" * 64},
                    env_sha="2" * 64,
                    runtime_seconds=0.0,
                    feature_evidence={},
                    project_id=project_id,
                )
    finally:
        remove_junction(project_root / "requests")


def test_run_receipt_directory_junction_rejected_before_receipt_read(tmp_path):
    root = assert_external_temp(tmp_path)
    state_root = _state_root(root)
    project_id, run_id = "red-run-receipt", "1" * 32
    payload = {
        "receiptContract": A.RUN_RECEIPT_V1,
        "receiptVersion": "1.0.0",
        "runId": run_id,
        "status": "INCOMPLETE",
        "projectId": project_id,
        "projectStorageKey": A._project_key(project_id),
        "bundleManifestSha256": "3" * 64,
    }
    receipt_sha = A.sha256_bytes(A.canonical_json_bytes(payload))
    receipt = {**payload, "receiptSha256": receipt_sha}
    project_root = state_root / A._project_key(project_id)
    evidence_root = project_root / "evidence-v2"
    (evidence_root / "receipts" / "sha256").mkdir(parents=True)
    (evidence_root / "registry.json").write_text(
        json.dumps({"schemaVersion": A.EVIDENCE_REGISTRY_V1, "runs": {run_id: receipt_sha}}),
        encoding="utf-8",
    )
    outside = root / "outside-run-receipt"
    outside.mkdir()
    (outside / "receipt.json").write_text(json.dumps(receipt), encoding="utf-8")
    receipt_dir = evidence_root / "receipts" / "sha256" / receipt_sha
    make_junction(receipt_dir, outside)
    try:
        with redirected_state(A, state_root):
            with pytest.raises(A.AuthorityError, match=REPARSE_ERROR):
                A.verify_model_run_receipt(project_id=project_id, run_id=run_id)
    finally:
        remove_junction(receipt_dir)


def test_transformation_receipt_junction_rejected_before_reuse_read(tmp_path):
    root = assert_external_temp(tmp_path)
    objects_root = root / "silver" / "objects" / "sha256"
    final = objects_root / ("4" * 64)
    final.mkdir(parents=True)
    outside = root / "outside-transformation-receipt"
    make_junction(final / "transformation-receipt.json", outside)
    try:
        with pytest.raises(ContainmentError, match=REPARSE_ERROR):
            SP._atomic_publish_children(
                objects_root,
                final,
                {"transformation-receipt.json": b"{}"},
                manifest_name="transformation-receipt.json",
            )
    finally:
        remove_junction(final / "transformation-receipt.json")


def test_quarantine_source_junction_rejected_before_iteration(tmp_path):
    root = assert_external_temp(tmp_path)
    state_root = _state_root(root)
    project_id = "red-quarantine-source"
    base, binding, request, authority = _incomplete_namespace(state_root, project_id)
    outside = root / "outside-quarantine-source"
    outside.mkdir()
    (outside / "complete.json").write_text("{}", encoding="utf-8")
    make_junction(base / "runs", outside)
    try:
        with redirected_state(A, state_root):
            with pytest.raises((ContainmentError, Q.NamespaceCleanupError), match=REPARSE_ERROR):
                Q.verify_incomplete(project_id, binding, request, authority)
    finally:
        remove_junction(base / "runs")


def test_quarantine_destination_junction_rejected_before_move(tmp_path):
    root = assert_external_temp(tmp_path)
    state_root = _state_root(root)
    project_id = "red-quarantine-destination"
    _base, binding, request, authority = _incomplete_namespace(state_root, project_id)
    runtime_root = state_root.resolve().parents[2]
    qroot = runtime_root / "quarantine" / "incomplete-test-namespaces"
    outside = root / "outside-quarantine-destination"
    make_junction(qroot, outside)
    try:
        with redirected_state(A, state_root):
            with pytest.raises((ContainmentError, Q.NamespaceCleanupError), match=REPARSE_ERROR):
                Q.quarantine(project_id, binding, request, authority, "red-gate synthetic probe", apply=True)
    finally:
        remove_junction(qroot)
