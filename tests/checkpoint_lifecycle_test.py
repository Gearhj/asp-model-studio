"""Stage 6.1 checkpoint lifecycle, garbage-collection, and size-control tests.

Covers the repair of the confirmed platform defect from the Stage B.6 audit:
.runtime/workflow_checkpoint.json grew without bound (observed 322 MB / 37
scopes, all belonging to deleted temporary projects) because scopes had no
lifecycle -- deleting a project or user removed database rows but never the
in-memory modeling scopes, every save re-serialized every resident scope, and
every mutating request paid a synchronous full-file rewrite.

Follows the isolation conventions of tests/modeling_state_characterization_test.py:
isolated per-run security/persistence SQLite files via environment variables set
BEFORE importing server.main, CHECKPOINT_PATH monkeypatched to a temp directory
per test, and in-memory scope dicts snapshotted/restored around each test.

Run:  .venv/Scripts/python.exe tests/checkpoint_lifecycle_test.py
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import threading
import time
import unittest
import uuid
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT))

_TEST_DATA_ROOT = _REPO_ROOT / ".tmp"
_TEST_DATA_ROOT.mkdir(exist_ok=True)
_RUN_ID = uuid.uuid4().hex[:10]
_SECURITY_DB_PATH = _TEST_DATA_ROOT / f"atlas_checkpoint_lifecycle_security_{_RUN_ID}.db"
_PERSISTENCE_DB_PATH = _TEST_DATA_ROOT / f"atlas_checkpoint_lifecycle_persistence_{_RUN_ID}.db"
_LIBRARY_ROOT = _TEST_DATA_ROOT / f"atlas_checkpoint_lifecycle_library_{_RUN_ID}"
_BACKUP_ROOT = Path(tempfile.mkdtemp(prefix=f"atlas_checkpoint_lifecycle_backups_{_RUN_ID}_"))
os.environ["ATLAS_SECURITY_ROOT"] = str(_SECURITY_DB_PATH.parent)
os.environ["ATLAS_SECURITY_DB_PATH"] = str(_SECURITY_DB_PATH)
os.environ["ATLAS_SQLITE_PATH"] = str(_PERSISTENCE_DB_PATH)
os.environ["ATLAS_DATASET_LIBRARY_ROOT"] = str(_LIBRARY_ROOT)
os.environ["ATLAS_DATASET_LIBRARY_BACKUP_ROOT"] = str(_BACKUP_ROOT)
os.environ.setdefault("ATLAS_AUTH_ENABLED", "true")
os.environ["ATLAS_ALLOW_PUBLIC_REGISTRATION"] = "true"
# Isolate this suite's checkpoint writes from the real dev backend's file
# (full-snapshot last-writer-wins; see session_checkpoint.py). Individual
# tests additionally monkeypatch CHECKPOINT_PATH to per-test temp files.
_CHECKPOINT_ENV_PATH = _TEST_DATA_ROOT / f"atlas_checkpoint_lifecycle_env_{_RUN_ID}.json"
os.environ["ATLAS_CHECKPOINT_PATH"] = str(_CHECKPOINT_ENV_PATH)

import pandas as pd  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from server.main import app  # noqa: E402
from server.persistence import initialize_persistence  # noqa: E402
from server.persistence.service import get_persistence_service  # noqa: E402
from server.security.security_store import init_security_store  # noqa: E402
import server.security.security_store as security_store  # noqa: E402

import server.core.dataset_store as dataset_store_module  # noqa: E402
import server.core.result_store as result_store_module  # noqa: E402
import server.core.session_checkpoint as checkpoint  # noqa: E402
from server.core.checkpoint_inspect import inspect_checkpoint  # noqa: E402
from server.core.dataset_store import get_scoped_dataset_store  # noqa: E402
from server.core.result_store import get_scoped_result_store  # noqa: E402
from server.datasets import dataset_registry  # noqa: E402


def _bind_security_and_persistence_paths() -> None:
    """Rebind import-cached authorities after another collected test module."""
    expected_security_root = _SECURITY_DB_PATH.parent.resolve()
    expected_security_db = _SECURITY_DB_PATH.resolve()
    expected_persistence_db = _PERSISTENCE_DB_PATH.resolve()
    os.environ["ATLAS_SECURITY_ROOT"] = str(expected_security_root)
    os.environ["ATLAS_SECURITY_DB_PATH"] = str(expected_security_db)
    os.environ["ATLAS_SQLITE_PATH"] = str(expected_persistence_db)
    os.environ["ATLAS_AUTH_ENABLED"] = "true"
    os.environ["ATLAS_ALLOW_PUBLIC_REGISTRATION"] = "true"
    security_store.SECURITY_ROOT = expected_security_root
    security_store.DB_PATH = expected_security_db
    security_store.ATLAS_AUTH_ENABLED = True
    security_store.ATLAS_ALLOW_PUBLIC_REGISTRATION = True
    assert Path(os.environ["ATLAS_SECURITY_DB_PATH"]).resolve() == expected_security_db
    assert Path(os.environ["ATLAS_SQLITE_PATH"]).resolve() == expected_persistence_db
    assert security_store.SECURITY_ROOT.resolve() == expected_security_root
    assert security_store.DB_PATH.resolve() == expected_security_db


def _bind_dataset_library_paths() -> None:
    """Rebind every cached registry path to this suite's owned root."""
    expected_root = _LIBRARY_ROOT.resolve()
    expected_backup_root = _BACKUP_ROOT.resolve()
    os.environ["ATLAS_DATASET_LIBRARY_ROOT"] = str(expected_root)
    os.environ["ATLAS_DATASET_LIBRARY_BACKUP_ROOT"] = str(expected_backup_root)
    dataset_registry.ARTIFACT_ROOT = expected_root
    dataset_registry.REGISTRY_PATH = dataset_registry.ARTIFACT_ROOT / "registry.json"
    dataset_registry.USERS_PATH = dataset_registry.ARTIFACT_ROOT / "users.json"
    dataset_registry.PROJECT_LINKS_PATH = (
        dataset_registry.ARTIFACT_ROOT / "project_links.json"
    )
    assert Path(os.environ["ATLAS_DATASET_LIBRARY_ROOT"]).resolve() == expected_root
    assert Path(os.environ["ATLAS_DATASET_LIBRARY_BACKUP_ROOT"]).resolve() == expected_backup_root
    assert dataset_registry.ARTIFACT_ROOT.resolve() == expected_root
    assert dataset_registry.REGISTRY_PATH.resolve() == expected_root / "registry.json"
    assert dataset_registry.USERS_PATH.resolve() == expected_root / "users.json"
    assert dataset_registry.PROJECT_LINKS_PATH.resolve() == expected_root / "project_links.json"


def _set_checkpoint_path(path: Path) -> Path:
    expected = path.resolve()
    os.environ["ATLAS_CHECKPOINT_PATH"] = str(expected)
    checkpoint.CHECKPOINT_PATH = expected
    assert Path(os.environ["ATLAS_CHECKPOINT_PATH"]).resolve() == expected
    assert checkpoint.CHECKPOINT_PATH.resolve() == expected
    return expected


def _bind_checkpoint_path() -> None:
    _set_checkpoint_path(_CHECKPOINT_ENV_PATH)


_bind_security_and_persistence_paths()
_bind_dataset_library_paths()
_bind_checkpoint_path()


def setUpModule() -> None:
    _bind_security_and_persistence_paths()
    _bind_dataset_library_paths()
    _bind_checkpoint_path()


def _cleanup_db_files() -> None:
    checkpoint.flush_checkpoint()
    try:
        _CHECKPOINT_ENV_PATH.unlink(missing_ok=True)
    except PermissionError:
        pass
    for base in (_SECURITY_DB_PATH, _PERSISTENCE_DB_PATH):
        for suffix in ("", "-wal", "-shm"):
            target = Path(f"{base}{suffix}")
            for attempt in range(25):
                try:
                    target.unlink(missing_ok=True)
                    break
                except PermissionError:
                    if attempt < 24:
                        time.sleep(0.2)
    shutil.rmtree(_LIBRARY_ROOT, ignore_errors=True)
    shutil.rmtree(_BACKUP_ROOT, ignore_errors=True)


def _register(label: str) -> tuple[TestClient, str]:
    client = TestClient(app)
    suffix = uuid.uuid4().hex[:10]
    response = client.post(
        "/api/auth/register",
        json={
            "email": f"{label}-{suffix}@atlas-checkpoint-lifecycle-test.local",
            "displayName": f"Checkpoint Lifecycle Test {label} {suffix}",
            "password": "CheckpointLifecycleTestPass!",
            "role": "data_scientist",
        },
    )
    assert response.status_code == 200, response.text
    return client, response.json()["user"]["userId"]


def _create_project(client: TestClient, name: str) -> str:
    response = client.post("/api/projects", json={"projectName": name, "projectType": "predictive-modeling"})
    assert response.status_code == 200, response.text
    return response.json()["project"]["projectId"]


def _populate_dataset_scope(user_id: str, project_id: str, marker: str) -> None:
    frame = pd.DataFrame({"amount": [1.0, 2.0, 3.0], "marker": [marker] * 3})
    identity_token = uuid.uuid5(
        uuid.NAMESPACE_URL,
        # Active dataset selection is project-scoped. Collaborators may own
        # private runtime caches, but they cannot select different canonical
        # versions for the same project.
        f"atlas-checkpoint-lifecycle:{_RUN_ID}:{project_id}",
    ).hex
    dataset_id = f"checkpoint-dataset-{identity_token[:16]}"
    version_id = f"checkpoint-version-{identity_token[16:]}"
    relative_artifact = (
        Path(dataset_id) / "versions" / version_id / "data_full.csv"
    )
    artifact_path = dataset_registry.ARTIFACT_ROOT / relative_artifact
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    if not artifact_path.exists():
        frame.to_csv(artifact_path, index=False)

    registry = dataset_registry.load_registry()
    datasets = list(registry.get("datasets", []))
    existing_dataset = next(
        (item for item in datasets if item.get("datasetId") == dataset_id),
        None,
    )
    if existing_dataset is None:
        datasets.append(
            {
                "datasetId": dataset_id,
                "name": f"Checkpoint fixture {project_id}",
                "ownerUserId": user_id,
                "archived": False,
                "access": [{"userId": user_id, "role": "owner"}],
                "linkedProjects": [
                    {
                        "projectId": project_id,
                        "versionId": version_id,
                        "datasetRole": "modeling",
                    }
                ],
                "versions": [
                    {
                        "versionId": version_id,
                        "fullDataPath": relative_artifact.as_posix(),
                        "rowCount": len(frame),
                        "columnCount": len(frame.columns),
                        "hash": f"fixture-hash-{identity_token}",
                    }
                ],
            }
        )
    else:
        grants = list(existing_dataset.get("access") or [])
        if not any(item.get("userId") == user_id for item in grants):
            grants.append({"userId": user_id, "role": "viewer"})
        existing_dataset["access"] = grants
    dataset_registry.save_registry({"datasets": datasets})

    links = dataset_registry.load_links()
    exact_link = {
        "projectId": project_id,
        "datasetId": dataset_id,
        "versionId": version_id,
        "datasetRole": "modeling",
        "linkedBy": user_id,
    }
    links["links"] = [
        item
        for item in links.get("links", [])
        if not (
            item.get("projectId") == project_id
            and item.get("datasetId") == dataset_id
        )
    ] + [exact_link]
    dataset_registry.save_links(links)

    activation_revision = 0
    persistence = get_persistence_service()
    if persistence.projects.get(project_id) is not None:
        activation = persistence.project_dataset_activations.activate_exact(
            project_id=project_id,
            dataset_id=dataset_id,
            dataset_version_id=version_id,
            actor_user_id=user_id,
            metadata={"source": "checkpoint_lifecycle_fixture"},
        )
        activation_revision = int(
            (activation.get("active_selection") or {}).get("activation_revision")
            or 0
        )

    store = get_scoped_dataset_store((user_id, project_id))
    store.reset_all()
    store.set_raw(frame)
    store.set_target("amount")
    store.meta.update(
        {
            "project_id": project_id,
            "dataset_id": dataset_id,
            "dataset_version_id": version_id,
            "dataset_version": version_id,
            "dataset_identity_status": "current",
            "activation_revision": activation_revision,
            "dataset_content_hash": f"fixture-hash-{identity_token}",
            "selected_columns": ["marker"],
        }
    )


def _populate_result_scope(user_id: str, project_id: str, marker: str) -> None:
    store = get_scoped_result_store((user_id, project_id))
    store.set_last_summary({"marker": marker, "ranked": []})


def _checkpoint_scope_keys(payload_key: str = "datastore_scopes") -> set[tuple[str, str]]:
    payload = json.loads(checkpoint.CHECKPOINT_PATH.read_text(encoding="utf-8"))
    return {(entry["owner_user_id"], entry["project_id"]) for entry in payload[payload_key]}


def _simulate_restart() -> bool:
    dataset_store_module._DATASTORES.clear()
    result_store_module._RESULT_STORES.clear()
    return checkpoint.load_checkpoint()


class CheckpointLifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        _bind_security_and_persistence_paths()
        _cleanup_db_files()
        init_security_store()
        initialize_persistence()

    @classmethod
    def tearDownClass(cls) -> None:
        _cleanup_db_files()

    def setUp(self) -> None:
        _bind_dataset_library_paths()
        self._datasets_snapshot = dict(dataset_store_module._DATASTORES)
        self._results_snapshot = dict(result_store_module._RESULT_STORES)
        dataset_store_module._DATASTORES.clear()
        result_store_module._RESULT_STORES.clear()
        self._original_checkpoint_path = checkpoint.CHECKPOINT_PATH
        self._temp_dir = (
            _TEST_DATA_ROOT
            / f"atlas_checkpoint_lifecycle_case_{uuid.uuid4().hex}"
        )
        self._temp_dir.mkdir(parents=True, exist_ok=False)
        _set_checkpoint_path(self._temp_dir / "workflow_checkpoint.json")
        self._original_debounce = checkpoint.CHECKPOINT_DEBOUNCE_SECONDS
        self._original_max_pending = checkpoint.CHECKPOINT_MAX_PENDING_SECONDS
        self._original_warning = checkpoint.CHECKPOINT_SIZE_WARNING_BYTES

    def tearDown(self) -> None:
        # Absorb any pending scheduled save while CHECKPOINT_PATH still points
        # at the temp directory, so the background writer can never write to
        # the real checkpoint after this test ends.
        checkpoint.flush_checkpoint()
        _set_checkpoint_path(self._original_checkpoint_path)
        checkpoint.CHECKPOINT_DEBOUNCE_SECONDS = self._original_debounce
        checkpoint.CHECKPOINT_MAX_PENDING_SECONDS = self._original_max_pending
        checkpoint.CHECKPOINT_SIZE_WARNING_BYTES = self._original_warning
        shutil.rmtree(self._temp_dir, ignore_errors=True)
        dataset_store_module._DATASTORES.clear()
        dataset_store_module._DATASTORES.update(self._datasets_snapshot)
        result_store_module._RESULT_STORES.clear()
        result_store_module._RESULT_STORES.update(self._results_snapshot)

    # ------------------------------------------------------------------
    # Project deletion lifecycle
    # ------------------------------------------------------------------
    def test_project_deletion_removes_scopes_from_memory_checkpoint_and_restart(self) -> None:
        """Phase 7 items 1, 5, 6, 12: deleting project B removes B's scopes
        (owner AND collaborator-private) from memory and from the checkpoint
        file immediately, does not disturb the same owner's project A, and B
        is not restored after a restart. Deleting through the normal API is
        also the sanctioned temporary-E2E-scope cleanup path."""
        client, user_id = _register("owner")
        _, collaborator_id = _register("collaborator")
        project_a = _create_project(client, "Lifecycle Keep A")
        project_b = _create_project(client, "Lifecycle Delete B")

        _populate_dataset_scope(user_id, project_a, "keep-A")
        _populate_result_scope(user_id, project_a, "keep-A")
        _populate_dataset_scope(user_id, project_b, "delete-B")
        _populate_result_scope(user_id, project_b, "delete-B")
        # Collaborator-private scope on project B: removed with the project.
        _populate_dataset_scope(collaborator_id, project_b, "delete-B-collab")

        self.assertTrue(checkpoint.save_checkpoint())
        saved = _checkpoint_scope_keys()
        self.assertIn((user_id, project_a), saved)
        self.assertIn((user_id, project_b), saved)
        self.assertIn((collaborator_id, project_b), saved)

        response = client.delete(f"/api/projects/{project_b}")
        self.assertEqual(response.status_code, 200, response.text)

        # In-memory scopes for project B are gone (all owners); A is intact.
        self.assertNotIn((user_id, project_b), dataset_store_module._DATASTORES)
        self.assertNotIn((collaborator_id, project_b), dataset_store_module._DATASTORES)
        self.assertNotIn((user_id, project_b), result_store_module._RESULT_STORES)
        self.assertIn((user_id, project_a), dataset_store_module._DATASTORES)

        # The deletion flushed the checkpoint synchronously: file already
        # reflects the removal without any additional save call.
        saved_after = _checkpoint_scope_keys()
        self.assertNotIn((user_id, project_b), saved_after)
        self.assertNotIn((collaborator_id, project_b), saved_after)
        self.assertIn((user_id, project_a), saved_after)

        # Restart: A restores with its data, B does not return.
        self.assertTrue(_simulate_restart())
        restored_a = get_scoped_dataset_store((user_id, project_a))
        self.assertIsNotNone(restored_a.raw_df)
        self.assertEqual(restored_a.raw_df["marker"].iloc[0], "keep-A")
        self.assertNotIn((user_id, project_b), dataset_store_module._DATASTORES)
        self.assertNotIn((collaborator_id, project_b), dataset_store_module._DATASTORES)

    def test_collaborator_private_scope_removable_independently(self) -> None:
        """Phase 7 item 6: discarding one collaborator's private scope leaves
        the owner's scope for the same project untouched."""
        client, owner_id = _register("owner")
        _, collab_id = _register("collab")
        project = _create_project(client, "Lifecycle Collab Independent")
        _populate_dataset_scope(owner_id, project, "owner-copy")
        _populate_dataset_scope(collab_id, project, "collab-copy")

        removed = checkpoint.discard_modeling_scopes(project_id=project, user_id=collab_id)
        self.assertEqual(removed["datastore_scopes_removed"], 1)
        self.assertIn((owner_id, project), dataset_store_module._DATASTORES)
        self.assertNotIn((collab_id, project), dataset_store_module._DATASTORES)

    # ------------------------------------------------------------------
    # Deleted/nonexistent user filtering
    # ------------------------------------------------------------------
    def test_scopes_of_nonexistent_user_filtered_on_save_and_load(self) -> None:
        """Phase 7 items 2 and 11: a scope owned by a user that does not
        exist in the security store is excluded at save time; a checkpoint
        record for such a user is skipped at load time."""
        client, user_id = _register("real-user")
        project = _create_project(client, "Lifecycle Ghost Owner")
        _populate_dataset_scope(user_id, project, "real-owner")
        _populate_dataset_scope("user_ghost_never_registered", project, "ghost-owner")

        self.assertTrue(checkpoint.save_checkpoint())
        saved = _checkpoint_scope_keys()
        self.assertIn((user_id, project), saved)
        self.assertNotIn(("user_ghost_never_registered", project), saved)

        # Load-time skip: hand-craft a checkpoint containing the ghost scope.
        payload = json.loads(checkpoint.CHECKPOINT_PATH.read_text(encoding="utf-8"))
        payload["datastore_scopes"].append({
            "owner_user_id": "user_ghost_never_registered",
            "project_id": project,
            "dataset": {"raw_df": None, "processed_df": None, "target": "smuggled",
                        "X_train": None, "X_test": None, "y_train": None, "y_test": None, "meta": {}},
        })
        checkpoint.CHECKPOINT_PATH.write_text(json.dumps(payload), encoding="utf-8")
        self.assertTrue(_simulate_restart())
        self.assertIn((user_id, project), dataset_store_module._DATASTORES)
        self.assertNotIn(("user_ghost_never_registered", project), dataset_store_module._DATASTORES)

    def test_deleted_project_record_skipped_on_load(self) -> None:
        """Phase 7 items 1 (restart half), 11: a checkpoint record for a
        project that no longer exists is not restored -- a deleted project
        cannot be resurrected from a stale checkpoint file."""
        client, user_id = _register("loader")
        project = _create_project(client, "Lifecycle Load Skip")
        _populate_dataset_scope(user_id, project, "live")
        _populate_dataset_scope(user_id, "project_deleted_long_ago", "stale")
        # Bypass save-time filtering to craft a file that CONTAINS the stale
        # record, as a pre-Stage-6.1 checkpoint would.
        live_store = {
            "schema_version": checkpoint.CHECKPOINT_SCHEMA_VERSION,
            "saved_at": "2026-07-23T00:00:00+00:00",
            "datastore_scopes": [
                {"owner_user_id": user_id, "project_id": project,
                 "dataset": checkpoint._encode_dataset(get_scoped_dataset_store((user_id, project)))},
                {"owner_user_id": user_id, "project_id": "project_deleted_long_ago",
                 "dataset": checkpoint._encode_dataset(get_scoped_dataset_store((user_id, "project_deleted_long_ago")))},
            ],
            "results_scopes": [],
        }
        checkpoint.CHECKPOINT_PATH.write_text(json.dumps(live_store), encoding="utf-8")
        self.assertTrue(_simulate_restart())
        self.assertIn((user_id, project), dataset_store_module._DATASTORES)
        self.assertNotIn((user_id, "project_deleted_long_ago"), dataset_store_module._DATASTORES)

    # ------------------------------------------------------------------
    # Empty scopes
    # ------------------------------------------------------------------
    def test_empty_scopes_not_serialized_but_config_only_drafts_kept(self) -> None:
        """Phase 7 item 3 (and Phase 3 item 9): lazily-created empty husk
        scopes are excluded from the checkpoint, but a scope holding ONLY
        draft meta configuration is legitimate draft state and is kept."""
        client, user_id = _register("empty")
        project_empty = _create_project(client, "Lifecycle Empty Scope")
        project_draft = _create_project(client, "Lifecycle Config Only Draft")

        get_scoped_dataset_store((user_id, project_empty))  # lazy husk
        get_scoped_result_store((user_id, project_empty))   # lazy husk
        draft = get_scoped_dataset_store((user_id, project_draft))
        draft.meta["selected_columns"] = ["planned_column"]  # config-only draft

        self.assertTrue(checkpoint.save_checkpoint())
        payload = json.loads(checkpoint.CHECKPOINT_PATH.read_text(encoding="utf-8"))
        dataset_keys = {(e["owner_user_id"], e["project_id"]) for e in payload["datastore_scopes"]}
        results_keys = {(e["owner_user_id"], e["project_id"]) for e in payload["results_scopes"]}
        self.assertNotIn((user_id, project_empty), dataset_keys)
        self.assertNotIn((user_id, project_empty), results_keys)
        self.assertIn((user_id, project_draft), dataset_keys)
        self.assertEqual(checkpoint.LAST_SAVE_REPORT["skipped_empty"], 2)

    # ------------------------------------------------------------------
    # Valid scopes survive
    # ------------------------------------------------------------------
    def test_valid_scopes_round_trip_restart(self) -> None:
        """Phase 7 items 4 and 13: live, non-empty scopes survive save and
        restart with data intact -- the Stage 6 restore contract is not
        weakened by the new filtering."""
        client, user_id = _register("survivor")
        project = _create_project(client, "Lifecycle Survivor")
        _populate_dataset_scope(user_id, project, "survives")
        _populate_result_scope(user_id, project, "survives")

        self.assertTrue(checkpoint.save_checkpoint())
        self.assertTrue(_simulate_restart())
        store = get_scoped_dataset_store((user_id, project))
        self.assertEqual(store.target, "amount")
        self.assertEqual(store.raw_df["marker"].iloc[0], "survives")
        self.assertEqual(get_scoped_result_store((user_id, project)).get_last_summary()["marker"], "survives")

    # ------------------------------------------------------------------
    # Save frequency / coalescing / performance
    # ------------------------------------------------------------------
    def test_rapid_scheduled_saves_coalesce_into_bounded_writes(self) -> None:
        """Phase 7 items 7 and 14: many rapid schedule_checkpoint_save()
        calls are non-blocking and produce a bounded number of physical
        writes (not one write per mutation)."""
        client, user_id = _register("burst")
        project = _create_project(client, "Lifecycle Burst")
        _populate_dataset_scope(user_id, project, "burst")

        checkpoint.CHECKPOINT_DEBOUNCE_SECONDS = 0.3
        checkpoint.CHECKPOINT_MAX_PENDING_SECONDS = 10.0
        before = checkpoint.CHECKPOINT_WRITE_COUNT

        started = time.perf_counter()
        for _ in range(200):
            self.assertTrue(checkpoint.schedule_checkpoint_save())
        scheduling_elapsed = time.perf_counter() - started
        self.assertLess(scheduling_elapsed, 0.5, "scheduling must not block on serialization")

        deadline = time.time() + 5.0
        while checkpoint.CHECKPOINT_WRITE_COUNT == before and time.time() < deadline:
            time.sleep(0.05)
        time.sleep(0.6)  # allow any (incorrect) extra writes to surface
        writes = checkpoint.CHECKPOINT_WRITE_COUNT - before
        self.assertGreaterEqual(writes, 1, "the coalesced write must eventually happen")
        self.assertLessEqual(writes, 2, f"200 rapid mutations caused {writes} physical writes")
        self.assertTrue(checkpoint.CHECKPOINT_PATH.exists())

    def test_flush_absorbs_pending_scheduled_save(self) -> None:
        """Phase 7 item 8 (shutdown half): flush_checkpoint() performs the
        write synchronously and absorbs the pending mark -- shutdown cannot
        lose the most recent scheduled draft state."""
        client, user_id = _register("flush")
        project = _create_project(client, "Lifecycle Flush")
        checkpoint.CHECKPOINT_DEBOUNCE_SECONDS = 60.0  # pending would linger without flush
        _populate_dataset_scope(user_id, project, "flushed")
        self.assertTrue(checkpoint.schedule_checkpoint_save())
        self.assertFalse(checkpoint.CHECKPOINT_PATH.exists())
        self.assertTrue(checkpoint.flush_checkpoint())
        self.assertIn((user_id, project), _checkpoint_scope_keys())

    def test_concurrent_direct_saves_produce_valid_checkpoint(self) -> None:
        """Phase 7 item 8: concurrent synchronous savers cannot corrupt the
        file or lose resident scopes -- every write serializes the full
        snapshot under one lock."""
        client, user_id = _register("concurrent")
        projects = [_create_project(client, f"Lifecycle Concurrent {i}") for i in range(3)]
        for index, project in enumerate(projects):
            _populate_dataset_scope(user_id, project, f"concurrent-{index}")

        errors: list[Exception] = []

        def worker() -> None:
            try:
                for _ in range(3):
                    assert checkpoint.save_checkpoint()
            except Exception as exc:  # pragma: no cover
                errors.append(exc)

        threads = [threading.Thread(target=worker) for _ in range(6)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(errors, [])
        saved = _checkpoint_scope_keys()
        for project in projects:
            self.assertIn((user_id, project), saved)

    def test_failed_save_preserves_previous_checkpoint(self) -> None:
        """Phase 7 item 9: a failing save leaves the previous good file
        byte-for-byte intact (atomic temp-file + replace)."""
        client, user_id = _register("atomic")
        project = _create_project(client, "Lifecycle Atomic")
        _populate_dataset_scope(user_id, project, "good-state")
        self.assertTrue(checkpoint.save_checkpoint())
        good_bytes = checkpoint.CHECKPOINT_PATH.read_bytes()

        class _FailingJson:
            loads = staticmethod(json.loads)
            dump = staticmethod(json.dump)

            @staticmethod
            def dumps(*args, **kwargs):
                # Fail only the FINAL full-payload serialization (the one
                # inside save_checkpoint's guarded write phase, identifiable
                # by its indent kwarg) -- _encode()'s probe calls use plain
                # json.dumps(value) and must keep working so payload
                # construction succeeds first.
                if kwargs.get("indent") is not None:
                    raise RuntimeError("simulated serialization failure")
                return json.dumps(*args, **kwargs)

        original_json = checkpoint.json
        checkpoint.json = _FailingJson()
        try:
            self.assertFalse(checkpoint.save_checkpoint())
        finally:
            checkpoint.json = original_json
        self.assertEqual(checkpoint.CHECKPOINT_PATH.read_bytes(), good_bytes)
        self.assertEqual(list(self._temp_dir.glob("*.tmp")), [])

    # ------------------------------------------------------------------
    # Size control
    # ------------------------------------------------------------------
    def test_size_warning_logged_without_discarding_state(self) -> None:
        """Phase 7 item 10: crossing the size warning threshold logs a
        warning but never drops valid scopes."""
        client, user_id = _register("size")
        project = _create_project(client, "Lifecycle Size Warning")
        _populate_dataset_scope(user_id, project, "large")
        checkpoint.CHECKPOINT_SIZE_WARNING_BYTES = 10  # force the warning
        with self.assertLogs("atlas.checkpoint", level="WARNING") as captured:
            self.assertTrue(checkpoint.save_checkpoint())
        self.assertTrue(any("large" in message.lower() for message in captured.output))
        self.assertIn((user_id, project), _checkpoint_scope_keys())
        self.assertGreater(checkpoint.LAST_SAVE_REPORT["size_bytes"], 10)

    def test_inspection_utility_reports_scopes_and_fields(self) -> None:
        """Phase 5 item 7: the inspection helper reports scope count, the
        largest scopes, and per-field byte totals for a real checkpoint."""
        client, user_id = _register("inspect")
        project = _create_project(client, "Lifecycle Inspect")
        _populate_dataset_scope(user_id, project, "inspected")
        _populate_result_scope(user_id, project, "inspected")
        self.assertTrue(checkpoint.save_checkpoint())

        report = inspect_checkpoint(checkpoint.CHECKPOINT_PATH)
        self.assertEqual(report["scope_count"], 2)
        self.assertEqual(report["orphaned_scope_count"], 0)
        self.assertTrue(report["largest_scopes"])
        self.assertIn("datastore.raw_df", report["field_totals"])

    # ------------------------------------------------------------------
    # Unscoped sentinel exemption
    # ------------------------------------------------------------------
    def test_unscoped_service_caller_scope_still_persisted(self) -> None:
        """The ('anonymous', 'unscoped') sentinel used by direct service
        callers (e.g. tests/predictive_modeling_repair_test.py) cannot be
        validated against the projects table and must NOT be dropped by the
        existence filter."""
        _populate_dataset_scope("anonymous", dataset_store_module.UNSCOPED_PROJECT, "service-caller")
        self.assertTrue(checkpoint.save_checkpoint())
        self.assertIn(("anonymous", dataset_store_module.UNSCOPED_PROJECT), _checkpoint_scope_keys())


if __name__ == "__main__":
    unittest.main(verbosity=2)
