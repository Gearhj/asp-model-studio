from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import tempfile
import unittest
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


# This module establishes isolated roots before importing any Dataset Library
# module.  It also uses explicit path objects in every test so collection order
# cannot redirect a write toward the checked-in runtime library.
_PREVIOUS_ENV = {
    name: os.environ.get(name)
    for name in (
        "ATLAS_ENV",
        "ATLAS_DATASET_LIBRARY_ROOT",
        "ATLAS_DATASET_LIBRARY_BACKUP_ROOT",
    )
}
_MODULE_TEMP = Path(tempfile.mkdtemp(prefix=f"atlas-dataset-integrity-{uuid.uuid4().hex}-"))
_IMPORT_ROOT = _MODULE_TEMP / "import-root"
_IMPORT_BACKUPS = _MODULE_TEMP / "import-backups"
os.environ["ATLAS_ENV"] = "test"
os.environ["ATLAS_DATASET_LIBRARY_ROOT"] = str(_IMPORT_ROOT)
os.environ["ATLAS_DATASET_LIBRARY_BACKUP_ROOT"] = str(_IMPORT_BACKUPS)

from server.datasets.dataset_integrity import (  # noqa: E402
    inspect_backup_state,
    run_bounded_integrity_scan,
)
from server.datasets.dataset_reconciliation import (  # noqa: E402
    ReconciliationLimits,
    ReconciliationState,
    scan_dataset_library,
)
from server.datasets.dataset_storage import (  # noqa: E402
    DatasetLibraryPaths,
    DatasetLibraryStorage,
    DatasetStorageError,
    DatasetStoreConflictError,
    DatasetStoreMalformedError,
    DatasetStoreMissingError,
    UnsafeTestStorageError,
    assert_test_storage_isolated,
    atomic_write_json,
    read_json_strict,
    sha256_file,
)
from server.datasets.dataset_integrity_router import (  # noqa: E402
    dataset_library_reconciliation,
)
from server.datasets import dataset_registry, dataset_storage  # noqa: E402
from fastapi import HTTPException  # noqa: E402


def _bind_dataset_library_paths(root: Path) -> None:
    owned_root = root.resolve()
    os.environ["ATLAS_DATASET_LIBRARY_ROOT"] = str(owned_root)
    dataset_registry.ARTIFACT_ROOT = owned_root
    dataset_registry.REGISTRY_PATH = owned_root / "registry.json"
    dataset_registry.USERS_PATH = owned_root / "users.json"
    dataset_registry.PROJECT_LINKS_PATH = owned_root / "project_links.json"


def tearDownModule() -> None:  # noqa: N802 - unittest hook
    shutil.rmtree(_MODULE_TEMP, ignore_errors=True)
    for name, value in _PREVIOUS_ENV.items():
        if value is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = value


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _canonical_hash(payload: object) -> str:
    rendered = json.dumps(
        payload,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(rendered).hexdigest()


def _create_directory_alias(alias: Path, target: Path) -> None:
    """Create a real directory symlink, or a Windows junction as fallback."""

    try:
        alias.symlink_to(target, target_is_directory=True)
        return
    except OSError as symlink_error:
        if os.name != "nt":
            raise unittest.SkipTest(
                f"Directory symlinks are unavailable: {type(symlink_error).__name__}"
            ) from symlink_error
    completed = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(alias), str(target)],
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        raise unittest.SkipTest("Directory symlinks and junctions are unavailable.")


def _remove_directory_alias(alias: Path) -> None:
    if alias.is_symlink():
        alias.unlink()
    elif alias.exists():
        # This branch is used only for a Windows junction created above.
        alias.rmdir()


def _tree_snapshot(root: Path) -> dict[str, str]:
    if not root.exists():
        return {}
    return {
        str(path.relative_to(root)): sha256_file(path)
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


class DatasetStorageReconciliationTest(unittest.TestCase):
    def setUp(self) -> None:
        suffix = uuid.uuid4().hex
        self.root = _MODULE_TEMP / f"library-{suffix}"
        self.backups = _MODULE_TEMP / f"backups-{suffix}"
        self.paths = DatasetLibraryPaths(
            root=self.root,
            registry_path=self.root / "registry.json",
            project_links_path=self.root / "project_links.json",
            users_path=self.root / "users.json",
            lock_path=self.root / ".dataset-library.lock",
            backup_root=self.backups,
        )
        self.storage = DatasetLibraryStorage(self.paths)
        os.environ["ATLAS_DATASET_LIBRARY_ROOT"] = str(self.root)
        os.environ["ATLAS_DATASET_LIBRARY_BACKUP_ROOT"] = str(self.backups)
        _bind_dataset_library_paths(self.root)

    def _create_registered_version(self) -> tuple[str, str, Path]:
        dataset_id = f"ds_test_{uuid.uuid4().hex}"
        version_id = f"v_test_{uuid.uuid4().hex}"
        owner_id = "owner-test"
        version_directory = self.root / dataset_id / "versions" / version_id
        version_directory.mkdir(parents=True)
        artifact = version_directory / "full.csv"
        artifact.write_bytes(b"feature,target\n1,0\n2,1\n")
        content_hash = sha256_file(artifact)
        schema = {
            "columns": [
                {"name": "feature", "type": "int64"},
                {"name": "target", "type": "int64"},
            ]
        }
        schema_hash = _canonical_hash(schema)
        _write_json(
            version_directory / "metadata.json",
            {
                "datasetId": dataset_id,
                "versionId": version_id,
                "originalFilename": "test.csv",
            },
        )
        _write_json(
            version_directory / "lineage.json",
            {
                "hash": content_hash,
                "registeredBy": owner_id,
                "registeredAt": "2026-07-31T00:00:00+00:00",
                "sourceType": "upload",
            },
        )
        _write_json(version_directory / "schema.json", schema)
        _write_json(
            version_directory / "profile.json",
            {"rowCount": 2, "columnCount": 2},
        )
        _write_json(
            self.paths.registry_path,
            {
                "datasets": [
                    {
                        "datasetId": dataset_id,
                        "name": "Isolated test dataset",
                        "ownerUserId": owner_id,
                        "sourceType": "upload",
                        "datasetRole": "training",
                        "target": "target",
                        "access": [{"userId": owner_id, "role": "owner"}],
                        "versions": [
                            {
                                "versionId": version_id,
                                "hash": content_hash,
                                "schemaHash": schema_hash,
                                "rowCount": 2,
                                "columnCount": 2,
                                "originalFilename": "test.csv",
                                "createdAt": "2026-07-31T00:00:00+00:00",
                                "createdBy": owner_id,
                                "fullDataPath": str(
                                    artifact.relative_to(self.root)
                                ),
                            }
                        ],
                    }
                ]
            },
        )
        _write_json(self.paths.project_links_path, {"links": []})
        return dataset_id, version_id, artifact

    @staticmethod
    def _resolve_owner(user_id: str) -> dict[str, str] | None:
        if user_id != "owner-test":
            return None
        return {"userId": user_id, "status": "active"}

    def test_strict_read_never_creates_or_defaults_missing_store(self) -> None:
        missing = self.root / "absent" / "registry.json"
        with self.assertRaises(DatasetStoreMissingError):
            read_json_strict(missing, "datasets")
        self.assertFalse(missing.parent.exists())
        self.assertIsNone(read_json_strict(missing, "datasets", allow_missing=True))
        self.assertFalse(missing.parent.exists())

    def test_strict_read_surfaces_malformed_store_without_rewriting_it(self) -> None:
        self.root.mkdir(parents=True)
        original = b'{"datasets": ['
        self.paths.registry_path.write_bytes(original)
        with self.assertRaises(DatasetStoreMalformedError):
            self.storage.read_registry()
        self.assertEqual(self.paths.registry_path.read_bytes(), original)

    def test_strict_read_enforces_byte_limit_before_json_parse(self) -> None:
        self.root.mkdir(parents=True)
        payload = b'{"datasets": []}\n'
        self.paths.registry_path.write_bytes(payload)
        with self.assertRaises(DatasetStoreMalformedError):
            read_json_strict(
                self.paths.registry_path,
                "datasets",
                max_bytes=len(payload) - 1,
            )
        self.assertEqual(self.paths.registry_path.read_bytes(), payload)

    def test_atomic_write_backs_up_and_replaces_valid_document(self) -> None:
        self.root.mkdir(parents=True)
        _write_json(self.paths.registry_path, {"datasets": []})
        before_hash = sha256_file(self.paths.registry_path)
        result = atomic_write_json(
            self.paths.registry_path,
            {"datasets": [{"datasetId": "ds_new", "versions": []}]},
            backup_root=self.backups,
            expected_sha256=before_hash,
        )
        self.assertTrue(result["changed"])
        self.assertEqual(
            read_json_strict(self.paths.registry_path, "datasets")["datasets"][0][
                "datasetId"
            ],
            "ds_new",
        )
        backup = result["backup"]
        self.assertIsNotNone(backup)
        backup_file = Path(backup["bundlePath"]) / "snapshots" / "registry.json"
        self.assertEqual(sha256_file(backup_file), before_hash)
        self.assertFalse(any(self.root.glob(".*.tmp")))

    def test_optimistic_conflict_and_failed_validator_leave_store_unchanged(self) -> None:
        self.root.mkdir(parents=True)
        _write_json(self.paths.registry_path, {"datasets": []})
        before = self.paths.registry_path.read_bytes()
        with self.assertRaises(DatasetStoreConflictError):
            atomic_write_json(
                self.paths.registry_path,
                {"datasets": [{"datasetId": "conflict"}]},
                backup_root=self.backups,
                expected_sha256="0" * 64,
            )
        self.assertEqual(self.paths.registry_path.read_bytes(), before)
        with self.assertRaises(DatasetStoreMalformedError):
            self.storage.atomic_write_json(
                self.paths.registry_path,
                {"datasets": [{"datasetId": "rejected"}]},
                shape_validator=lambda _payload: False,
            )
        self.assertEqual(self.paths.registry_path.read_bytes(), before)

    def test_test_storage_guard_rejects_checked_in_library(self) -> None:
        live_root = Path(__file__).resolve().parents[1] / "server" / "artifacts" / "datasets"
        with self.assertRaises(UnsafeTestStorageError):
            assert_test_storage_isolated(live_root)

    def test_test_storage_guard_rejects_a_physical_alias_of_live_library(
        self,
    ) -> None:
        self.root.mkdir(parents=True)
        live_root = (
            Path(__file__).resolve().parents[1]
            / "server"
            / "artifacts"
            / "datasets"
        ).resolve()
        original_samefile = os.path.samefile

        def samefile_with_alias(left: object, right: object) -> bool:
            if (
                Path(left) == self.root
                and Path(right).resolve() == live_root
            ):
                return True
            return original_samefile(left, right)

        with patch.object(
            dataset_storage.os.path,
            "samefile",
            side_effect=samefile_with_alias,
        ):
            with self.assertRaises(UnsafeTestStorageError):
                assert_test_storage_isolated(self.root)

    def test_registry_mutators_reject_physical_alias_before_any_write(self) -> None:
        self.root.mkdir(parents=True)
        _write_json(self.paths.registry_path, {"datasets": []})
        _write_json(self.paths.project_links_path, {"links": []})
        _write_json(self.paths.users_path, {"users": []})
        before = _tree_snapshot(self.root)
        live_root = (
            Path(__file__).resolve().parents[1]
            / "server"
            / "artifacts"
            / "datasets"
        ).resolve()
        original_samefile = os.path.samefile

        def samefile_with_alias(left: object, right: object) -> bool:
            if (
                Path(left) == self.root
                and Path(right).resolve() == live_root
            ):
                return True
            return original_samefile(left, right)

        patched_paths = {
            "ARTIFACT_ROOT": self.root,
            "REGISTRY_PATH": self.paths.registry_path,
            "PROJECT_LINKS_PATH": self.paths.project_links_path,
            "USERS_PATH": self.paths.users_path,
        }
        with patch.multiple(dataset_registry, **patched_paths), patch.object(
            dataset_storage.os.path,
            "samefile",
            side_effect=samefile_with_alias,
        ):
            with self.assertRaisesRegex(
                DatasetStorageError,
                "physically aliases protected ATLAS storage",
            ):
                dataset_registry.save_registry({"datasets": [{"datasetId": "x"}]})
            with self.assertRaisesRegex(
                DatasetStorageError,
                "physically aliases protected ATLAS storage",
            ):
                dataset_registry.create_dataset_from_dataframe(
                    dataset_registry.pd.DataFrame({"feature": [1]}),
                    "must-not-write",
                )
        self.assertEqual(_tree_snapshot(self.root), before)

    def test_external_backup_rejects_physical_repository_alias(self) -> None:
        self.backups.mkdir(parents=True)
        repository = Path(__file__).resolve().parents[1]
        original_samefile = os.path.samefile

        def samefile_with_alias(left: object, right: object) -> bool:
            if (
                Path(left) == self.backups
                and Path(right).resolve() == repository.resolve()
            ):
                return True
            return original_samefile(left, right)

        with patch.object(
            dataset_storage.os.path,
            "samefile",
            side_effect=samefile_with_alias,
        ):
            with self.assertRaisesRegex(
                DatasetStorageError,
                "physically aliases protected ATLAS storage",
            ):
                dataset_storage._assert_external_backup_root(
                    self.backups,
                    library_root=self.root,
                )

    def test_external_backup_rejects_same_device_bind_mount_identity(self) -> None:
        self.backups.mkdir(parents=True)
        original_is_mount = Path.is_mount

        def is_mount_with_alias(path: Path) -> bool:
            return Path(path) == self.backups or original_is_mount(path)

        with patch.object(Path, "is_mount", is_mount_with_alias):
            with self.assertRaisesRegex(
                DatasetStorageError,
                "physically aliases protected ATLAS storage",
            ):
                dataset_storage._assert_external_backup_root(
                    self.backups,
                    library_root=self.root,
                )

    def test_configured_roots_reject_linked_parent_before_resolution(self) -> None:
        requested_root = self.root / "linked-parent" / "library"
        requested_backup = self.backups / "linked-parent" / "backups"
        linked_components = {
            Path(os.path.abspath(str(requested_root.parent))),
            Path(os.path.abspath(str(requested_backup.parent))),
        }

        with patch.object(
            dataset_storage,
            "_is_link_or_junction",
            side_effect=lambda path: Path(path) in linked_components,
        ), patch.dict(
            os.environ,
            {
                "ATLAS_DATASET_LIBRARY_ROOT": str(requested_root),
                "ATLAS_DATASET_LIBRARY_BACKUP_ROOT": str(requested_backup),
            },
            clear=False,
        ):
            with self.assertRaisesRegex(
                DatasetStorageError,
                "cannot traverse filesystem links",
            ):
                DatasetLibraryPaths.from_environment()

    def test_dataset_registry_read_rejects_configured_root_alias(self) -> None:
        target = _MODULE_TEMP / f"registry-alias-target-{uuid.uuid4().hex}"
        alias = _MODULE_TEMP / f"registry-alias-{uuid.uuid4().hex}"
        target.mkdir(parents=True)
        registry_payload = {"datasets": [{"datasetId": "must-not-be-read"}]}
        _write_json(target / "registry.json", registry_payload)
        _write_json(target / "project_links.json", {"links": []})
        _write_json(target / "users.json", {"users": []})
        _create_directory_alias(alias, target)
        patched_paths = {
            "ARTIFACT_ROOT": alias,
            "REGISTRY_PATH": alias / "registry.json",
            "PROJECT_LINKS_PATH": alias / "project_links.json",
            "USERS_PATH": alias / "users.json",
        }
        try:
            with patch.multiple(dataset_registry, **patched_paths), patch.dict(
                os.environ,
                {"ATLAS_DATASET_LIBRARY_ROOT": str(alias)},
                clear=False,
            ):
                with self.assertRaisesRegex(
                    DatasetStorageError,
                    "cannot traverse filesystem links",
                ):
                    dataset_registry.load_registry()
        finally:
            _remove_directory_alias(alias)
        self.assertEqual(
            json.loads((target / "registry.json").read_text(encoding="utf-8")),
            registry_payload,
        )

    def test_configured_backup_root_alias_is_rejected_independently(self) -> None:
        requested_root = _MODULE_TEMP / f"safe-library-{uuid.uuid4().hex}"
        backup_target = _MODULE_TEMP / f"backup-target-{uuid.uuid4().hex}"
        backup_alias = _MODULE_TEMP / f"backup-alias-{uuid.uuid4().hex}"
        backup_target.mkdir(parents=True)
        _create_directory_alias(backup_alias, backup_target)
        try:
            with patch.dict(
                os.environ,
                {
                    "ATLAS_DATASET_LIBRARY_ROOT": str(requested_root),
                    "ATLAS_DATASET_LIBRARY_BACKUP_ROOT": str(backup_alias),
                },
                clear=False,
            ):
                with self.assertRaisesRegex(
                    DatasetStorageError,
                    "cannot traverse filesystem links",
                ):
                    DatasetLibraryPaths.from_environment()
        finally:
            _remove_directory_alias(backup_alias)

    def test_backup_root_cannot_overlap_live_library(self) -> None:
        self.root.mkdir(parents=True)
        _write_json(self.paths.registry_path, {"datasets": []})
        with self.assertRaises(DatasetStorageError):
            atomic_write_json(
                self.paths.registry_path,
                {"datasets": [{"datasetId": "ds_overlap", "versions": []}]},
                backup_root=self.root / "backups",
            )
        self.assertEqual(
            read_json_strict(self.paths.registry_path, "datasets"),
            {"datasets": []},
        )

    def test_dataset_registry_save_is_atomic_backed_and_strict_on_corruption(self) -> None:
        self.root.mkdir(parents=True)
        _write_json(self.paths.registry_path, {"datasets": []})
        _write_json(self.paths.project_links_path, {"links": []})
        _write_json(self.paths.users_path, {"users": []})
        before_hash = sha256_file(self.paths.registry_path)
        patched_paths = {
            "ARTIFACT_ROOT": self.root,
            "REGISTRY_PATH": self.paths.registry_path,
            "PROJECT_LINKS_PATH": self.paths.project_links_path,
            "USERS_PATH": self.paths.users_path,
        }
        with patch.multiple(dataset_registry, **patched_paths), patch.dict(
            os.environ,
            {"ATLAS_DATASET_LIBRARY_BACKUP_ROOT": str(self.backups)},
            clear=False,
        ):
            dataset_registry.save_registry(
                {"datasets": [{"datasetId": "ds_integrated", "versions": []}]}
            )
            self.paths.registry_path.write_bytes(b'{"datasets": [')
            malformed = self.paths.registry_path.read_bytes()
            with self.assertRaises(DatasetStoreMalformedError):
                dataset_registry.load_registry()
            self.assertEqual(self.paths.registry_path.read_bytes(), malformed)

        bundles = [path for path in self.backups.iterdir() if path.is_dir()]
        self.assertEqual(len(bundles), 1)
        snapshot = bundles[0] / "snapshots" / "registry.json"
        self.assertEqual(sha256_file(snapshot), before_hash)

    def test_dataset_registry_missing_catalog_with_artifacts_fails_closed(self) -> None:
        artifact_directory = self.root / "orphan" / "versions" / "v1"
        artifact_directory.mkdir(parents=True)
        (artifact_directory / "data_full.csv").write_bytes(b"x\n1\n")
        patched_paths = {
            "ARTIFACT_ROOT": self.root,
            "REGISTRY_PATH": self.paths.registry_path,
            "PROJECT_LINKS_PATH": self.paths.project_links_path,
            "USERS_PATH": self.paths.users_path,
        }
        with patch.multiple(dataset_registry, **patched_paths):
            with self.assertRaises(DatasetStoreMissingError):
                dataset_registry.load_registry()
        self.assertFalse(self.paths.registry_path.exists())

    def test_dataset_registry_missing_catalog_with_legacy_link_fails_closed(self) -> None:
        self.root.mkdir(parents=True)
        _write_json(
            self.paths.project_links_path,
            {"links": [{"projectId": "p1", "datasetId": "d1"}]},
        )
        patched_paths = {
            "ARTIFACT_ROOT": self.root,
            "REGISTRY_PATH": self.paths.registry_path,
            "PROJECT_LINKS_PATH": self.paths.project_links_path,
            "USERS_PATH": self.paths.users_path,
        }
        with patch.multiple(dataset_registry, **patched_paths):
            with self.assertRaises(DatasetStoreMissingError):
                dataset_registry.ensure_store()
        self.assertFalse(self.paths.registry_path.exists())

    def test_dataset_registry_missing_catalog_with_durable_link_fails_closed(self) -> None:
        database_path = _MODULE_TEMP / f"bootstrap-authority-{uuid.uuid4().hex}.db"
        connection = sqlite3.connect(database_path)
        try:
            connection.execute(
                "CREATE TABLE project_dataset_links "
                "(project_id TEXT, dataset_id TEXT)"
            )
            connection.execute(
                "INSERT INTO project_dataset_links VALUES ('p1', 'd1')"
            )
            connection.commit()
        finally:
            connection.close()
        patched_paths = {
            "ARTIFACT_ROOT": self.root,
            "REGISTRY_PATH": self.paths.registry_path,
            "PROJECT_LINKS_PATH": self.paths.project_links_path,
            "USERS_PATH": self.paths.users_path,
        }
        with patch.multiple(dataset_registry, **patched_paths), patch.dict(
            os.environ,
            {"ATLAS_SQLITE_PATH": str(database_path)},
            clear=False,
        ):
            with self.assertRaises(DatasetStoreMissingError):
                dataset_registry.ensure_store()
        self.assertFalse(self.paths.registry_path.exists())

    def test_dataset_registry_missing_link_store_with_durable_authority_fails_closed(self) -> None:
        self.root.mkdir(parents=True)
        _write_json(self.paths.registry_path, {"datasets": []})
        database_path = _MODULE_TEMP / f"link-authority-{uuid.uuid4().hex}.db"
        connection = sqlite3.connect(database_path)
        try:
            connection.execute(
                "CREATE TABLE project_dataset_links "
                "(project_id TEXT, dataset_id TEXT)"
            )
            connection.execute(
                "INSERT INTO project_dataset_links VALUES ('p1', 'd1')"
            )
            connection.commit()
        finally:
            connection.close()
        patched_paths = {
            "ARTIFACT_ROOT": self.root,
            "REGISTRY_PATH": self.paths.registry_path,
            "PROJECT_LINKS_PATH": self.paths.project_links_path,
            "USERS_PATH": self.paths.users_path,
        }
        with patch.multiple(dataset_registry, **patched_paths), patch.dict(
            os.environ,
            {"ATLAS_SQLITE_PATH": str(database_path)},
            clear=False,
        ):
            with self.assertRaises(DatasetStoreMissingError):
                dataset_registry.ensure_store()
        self.assertFalse(self.paths.project_links_path.exists())

    def test_link_projection_transaction_commits_both_documents(self) -> None:
        dataset_id, version_id, _artifact = self._create_registered_version()
        patched_paths = {
            "ARTIFACT_ROOT": self.root,
            "REGISTRY_PATH": self.paths.registry_path,
            "PROJECT_LINKS_PATH": self.paths.project_links_path,
            "USERS_PATH": self.paths.users_path,
        }
        actor = {"userId": "owner-test", "role": "admin"}
        with patch.multiple(dataset_registry, **patched_paths), patch.dict(
            os.environ,
            {"ATLAS_DATASET_LIBRARY_BACKUP_ROOT": str(self.backups)},
            clear=False,
        ), patch.object(
            dataset_registry, "current_user", return_value=actor
        ), patch.object(dataset_registry, "audit_event"):
            result = dataset_registry.link_project(
                "project-test", dataset_id, version_id
            )
        self.assertEqual(result["versionId"], version_id)
        links = self.storage.read_links()
        registry = self.storage.read_registry()
        self.assertEqual(links["links"][0]["versionId"], version_id)
        self.assertEqual(
            registry["datasets"][0]["linkedProjects"][0]["versionId"],
            version_id,
        )
        journal = self.storage.read_recovery_journal(required=True)
        self.assertEqual(journal["status"], "committed")
        manifests = list(self.backups.glob("*/manifest.json"))
        self.assertEqual(len(manifests), 1)
        manifest = read_json_strict(manifests[0])
        self.assertEqual(
            {record["sourceRelativePath"] for record in manifest["files"]},
            {"registry.json", "project_links.json"},
        )

    def test_link_projection_compensates_when_write_raises_after_replace(self) -> None:
        dataset_id, version_id, _artifact = self._create_registered_version()
        registry_before = self.paths.registry_path.read_bytes()
        links_before = self.paths.project_links_path.read_bytes()
        patched_paths = {
            "ARTIFACT_ROOT": self.root,
            "REGISTRY_PATH": self.paths.registry_path,
            "PROJECT_LINKS_PATH": self.paths.project_links_path,
            "USERS_PATH": self.paths.users_path,
        }
        actor = {"userId": "owner-test", "role": "admin"}
        original_write = DatasetLibraryStorage.atomic_write_json

        def fail_after_link_replace(storage, path, payload, **kwargs):
            result = original_write(storage, path, payload, **kwargs)
            if Path(path).resolve() == self.paths.project_links_path.resolve():
                raise RuntimeError("fault after atomic replacement")
            return result

        with patch.multiple(dataset_registry, **patched_paths), patch.dict(
            os.environ,
            {"ATLAS_DATASET_LIBRARY_BACKUP_ROOT": str(self.backups)},
            clear=False,
        ), patch.object(
            dataset_registry, "current_user", return_value=actor
        ), patch.object(dataset_registry, "audit_event"), patch.object(
            DatasetLibraryStorage,
            "atomic_write_json",
            new=fail_after_link_replace,
        ):
            with self.assertRaises(RuntimeError):
                dataset_registry.link_project(
                    "project-test", dataset_id, version_id
                )
        self.assertEqual(self.paths.registry_path.read_bytes(), registry_before)
        self.assertEqual(self.paths.project_links_path.read_bytes(), links_before)
        journal = self.storage.read_recovery_journal(required=True)
        self.assertEqual(journal["status"], "aborted")

    def test_dataset_registry_pristine_first_run_can_initialize(self) -> None:
        patched_paths = {
            "ARTIFACT_ROOT": self.root,
            "REGISTRY_PATH": self.paths.registry_path,
            "PROJECT_LINKS_PATH": self.paths.project_links_path,
            "USERS_PATH": self.paths.users_path,
        }
        with patch.multiple(dataset_registry, **patched_paths), patch.dict(
            os.environ,
            {},
            clear=False,
        ):
            os.environ.pop("ATLAS_SQLITE_PATH", None)
            dataset_registry.ensure_store()
        self.assertEqual(self.storage.read_registry(), {"datasets": []})
        self.assertEqual(self.storage.read_links(), {"links": []})

    def test_dataset_registry_rejects_dot_path_segments(self) -> None:
        with self.assertRaises(HTTPException):
            dataset_registry.version_dir(".", "v1")
        with self.assertRaises(HTTPException):
            dataset_registry.version_dir("dataset", "..")

    def test_healthy_scan_is_read_only_and_marks_registered_version_healthy(self) -> None:
        dataset_id, version_id, artifact = self._create_registered_version()
        before = _tree_snapshot(self.root)
        report = scan_dataset_library(
            self.storage,
            user_resolver=self._resolve_owner,
            deep_checksums=True,
            limits=ReconciliationLimits(
                max_checksum_bytes=sum(
                    path.stat().st_size
                    for path in artifact.parent.iterdir()
                    if path.is_file()
                )
            ),
        )
        after = _tree_snapshot(self.root)
        self.assertEqual(after, before)
        self.assertTrue(report.healthy, report.to_dict())
        self.assertFalse(report.scan_truncated)
        record = report.exact_record(dataset_id, version_id)
        self.assertIsNotNone(record)
        self.assertIn(ReconciliationState.HEALTHY, record.states)
        self.assertNotIn(ReconciliationState.RECOVERABLE, record.states)
        self.assertTrue(record.artifact_state["checksum_verified"])
        self.assertTrue(record.artifact_state["schema_verified"])

    def test_missing_project_links_store_makes_scan_and_startup_unhealthy(self) -> None:
        self._create_registered_version()
        self.paths.project_links_path.unlink()
        report = scan_dataset_library(
            self.storage,
            user_resolver=self._resolve_owner,
        )
        self.assertFalse(report.healthy)
        self.assertTrue(report.storage_errors)
        self.assertFalse(report.warnings)
        integrity = run_bounded_integrity_scan(
            storage=self.storage,
            user_resolver=self._resolve_owner,
        )
        self.assertEqual(integrity["status"], "degraded")
        self.assertFalse(integrity["reconciliation"]["healthy"])

    def test_malformed_project_links_store_makes_scan_and_admin_unhealthy(self) -> None:
        self._create_registered_version()
        malformed = b'{"links": ['
        self.paths.project_links_path.write_bytes(malformed)
        report = scan_dataset_library(
            self.storage,
            user_resolver=self._resolve_owner,
        )
        self.assertFalse(report.healthy)
        self.assertTrue(report.storage_errors)
        self.assertFalse(report.warnings)
        self.assertEqual(self.paths.project_links_path.read_bytes(), malformed)
        integrity = run_bounded_integrity_scan(
            storage=self.storage,
            user_resolver=self._resolve_owner,
        )
        self.assertEqual(integrity["status"], "degraded")
        self.assertFalse(integrity["reconciliation"]["healthy"])

    def test_checksum_and_schema_mismatches_are_detected(self) -> None:
        dataset_id, version_id, artifact = self._create_registered_version()
        artifact.write_bytes(artifact.read_bytes() + b"3,1\n")
        schema_path = artifact.parent / "schema.json"
        _write_json(schema_path, {"columns": [{"name": "wrong", "type": "text"}]})
        report = scan_dataset_library(
            self.storage,
            user_resolver=self._resolve_owner,
        )
        record = report.exact_record(dataset_id, version_id)
        self.assertIsNotNone(record)
        self.assertIn(ReconciliationState.CHECKSUM_MISMATCH, record.states)
        self.assertIn(ReconciliationState.SCHEMA_MISMATCH, record.states)
        self.assertFalse(report.healthy)

    def test_orphan_artifact_is_not_recovered_or_treated_as_authoritative(self) -> None:
        dataset_id, version_id, _artifact = self._create_registered_version()
        _write_json(self.paths.registry_path, {"datasets": []})
        before = _tree_snapshot(self.root)
        report = scan_dataset_library(
            self.storage,
            user_resolver=self._resolve_owner,
        )
        self.assertEqual(_tree_snapshot(self.root), before)
        record = report.exact_record(dataset_id, version_id)
        self.assertIsNotNone(record)
        self.assertIn(ReconciliationState.ARTIFACT_WITHOUT_REGISTRY, record.states)
        self.assertIn(ReconciliationState.OWNERSHIP_UNRESOLVED, record.states)
        self.assertIn(ReconciliationState.ACL_UNRESOLVED, record.states)
        self.assertFalse(record.recovery_eligibility)
        self.assertFalse(report.to_dict()["healthy"])

    def test_unreferenced_duplicate_artifact_directory_is_not_hidden_by_ids(self) -> None:
        dataset_id, version_id, artifact = self._create_registered_version()
        duplicate = self.root / "unregistered-copy" / "versions" / "copy"
        shutil.copytree(artifact.parent, duplicate)
        report = scan_dataset_library(
            self.storage,
            user_resolver=self._resolve_owner,
        )
        duplicates = [
            record
            for record in report.records
            if record.dataset_id == dataset_id
            and record.dataset_version_id == version_id
            and record.artifact_state.get("directory_only")
        ]
        self.assertEqual(len(duplicates), 1)
        self.assertIn(
            ReconciliationState.ARTIFACT_WITHOUT_REGISTRY,
            duplicates[0].states,
        )
        self.assertIn(ReconciliationState.AMBIGUOUS_IDENTITY, duplicates[0].states)

    def test_legacy_project_link_without_dataset_is_reported(self) -> None:
        self.root.mkdir(parents=True)
        _write_json(self.paths.registry_path, {"datasets": []})
        _write_json(
            self.paths.project_links_path,
            {
                "links": [
                    {
                        "projectId": "project-orphan-link",
                        "datasetId": "dataset-not-registered",
                        "versionId": "version-not-registered",
                    }
                ]
            },
        )
        report = scan_dataset_library(self.storage)
        record = report.exact_record(
            "dataset-not-registered",
            "version-not-registered",
        )
        self.assertIsNotNone(record)
        self.assertIn(ReconciliationState.PROJECT_LINK_WITHOUT_DATASET, record.states)
        self.assertFalse(report.healthy)

    def test_registry_entry_with_missing_artifact_is_detected(self) -> None:
        dataset_id, version_id, artifact = self._create_registered_version()
        artifact.unlink()
        report = scan_dataset_library(
            self.storage,
            user_resolver=self._resolve_owner,
        )
        record = report.exact_record(dataset_id, version_id)
        self.assertIsNotNone(record)
        self.assertIn(ReconciliationState.REGISTRY_WITHOUT_ARTIFACT, record.states)

    def test_registered_dataset_without_versions_is_not_healthy(self) -> None:
        self.root.mkdir(parents=True)
        _write_json(
            self.paths.registry_path,
            {
                "datasets": [
                    {
                        "datasetId": "ds_without_version",
                        "ownerUserId": "owner-test",
                        "access": [{"userId": "owner-test", "role": "owner"}],
                        "versions": [],
                    }
                ]
            },
        )
        _write_json(self.paths.project_links_path, {"links": []})
        report = scan_dataset_library(
            self.storage,
            user_resolver=self._resolve_owner,
        )
        self.assertFalse(report.healthy)
        self.assertIn(
            ReconciliationState.DATASET_WITHOUT_VERSION,
            report.records[0].states,
        )

    def test_active_selection_without_link_is_detected_without_database_write(self) -> None:
        dataset_id, version_id, _artifact = self._create_registered_version()
        database_path = _MODULE_TEMP / f"authority-{uuid.uuid4().hex}.db"
        connection = sqlite3.connect(database_path)
        try:
            connection.executescript(
                """
                CREATE TABLE project_dataset_links (
                  project_id TEXT, dataset_id TEXT, link_status TEXT,
                  linked_by TEXT, linked_at TEXT
                );
                CREATE TABLE active_modeling_dataset_versions (
                  project_id TEXT, dataset_id TEXT, dataset_version_id TEXT,
                  activation_revision INTEGER, activation_status TEXT
                );
                """
            )
            connection.execute(
                "INSERT INTO active_modeling_dataset_versions VALUES (?, ?, ?, ?, ?)",
                ("project-test", dataset_id, version_id, 1, "active"),
            )
            connection.commit()
        finally:
            connection.close()
        database_hash = sha256_file(database_path)
        report = scan_dataset_library(
            self.storage,
            database=SimpleNamespace(path=database_path),
            user_resolver=self._resolve_owner,
        )
        self.assertEqual(sha256_file(database_path), database_hash)
        record = report.exact_record(dataset_id, version_id)
        self.assertIsNotNone(record)
        self.assertIn(ReconciliationState.ACTIVE_SELECTION_WITHOUT_LINK, record.states)

    def test_bounded_integrity_report_never_auto_recovers_and_reports_backups(self) -> None:
        dataset_id, version_id, _artifact = self._create_registered_version()
        self.storage.mutate_registry(
            lambda payload: payload,
            reason="No-op should not create a backup",
        )
        # Force one real mutation so backup inventory has a checksummed bundle.
        self.storage.mutate_registry(
            lambda payload: {**payload, "maintenanceMarker": "test"},
            reason="Isolated integrity test",
        )
        before = _tree_snapshot(self.root)
        integrity = run_bounded_integrity_scan(
            storage=self.storage,
            user_resolver=self._resolve_owner,
        )
        self.assertEqual(_tree_snapshot(self.root), before)
        self.assertFalse(integrity["automatic_recovery_performed"])
        self.assertEqual(
            integrity["reconciliation"]["records"][0]["dataset_id"],
            dataset_id,
        )
        self.assertEqual(
            integrity["reconciliation"]["records"][0]["dataset_version_id"],
            version_id,
        )
        backup_state = inspect_backup_state(self.storage)
        self.assertEqual(backup_state["bundle_count"], 1)
        self.assertEqual(backup_state["self_consistent_bundle_count"], 1)
        self.assertEqual(backup_state["audit_bound_verified_bundle_count"], 0)
        self.assertEqual(backup_state["invalid_bundle_count"], 0)

    def test_recovery_backup_is_verified_only_when_bound_to_durable_audit(self) -> None:
        self.root.mkdir(parents=True)
        _write_json(self.paths.registry_path, {"datasets": []})
        _write_json(self.paths.project_links_path, {"links": []})
        backup = self.storage.create_backup_bundle(
            reason="Isolated audit-bound backup test"
        )
        bundle = Path(backup["bundlePath"])
        persistence_copy = bundle / "atlas_persistence_before.sqlite3"
        connection = sqlite3.connect(persistence_copy)
        try:
            for table in (
                "projects",
                "project_dataset_links",
                "active_modeling_dataset_versions",
                "project_dataset_activation_events",
                "schema_migrations",
            ):
                connection.execute(f'CREATE TABLE "{table}" (id TEXT)')
            connection.commit()
        finally:
            connection.close()
        persistence = {
            "logical_name": "persistence_database",
            "file": persistence_copy.name,
            "sha256": sha256_file(persistence_copy),
            "bytes": persistence_copy.stat().st_size,
        }
        operation_id = f"recovery-{uuid.uuid4().hex}"
        safety_path = bundle / "recovery_safety_manifest.json"
        _write_json(
            safety_path,
            {
                "schema_version": "atlas.dataset-library-recovery-backup.v1",
                "operation_id": operation_id,
                "created_at": "2026-07-31T00:00:00+00:00",
                "reason": "Isolated audit binding test",
                "storage_bundle_manifest": backup["manifestPath"],
                "storage_bundle_manifest_sha256": backup["manifestSha256"],
                "persistence_database": persistence,
                "before": {},
            },
        )
        safety_sha = sha256_file(safety_path)
        audit_database = _MODULE_TEMP / f"audit-{uuid.uuid4().hex}.db"
        connection = sqlite3.connect(audit_database)
        try:
            connection.execute(
                "CREATE TABLE dataset_library_maintenance_events "
                "(backup_manifest_sha256 TEXT, operation_id TEXT, created_at TEXT)"
            )
            connection.execute(
                "INSERT INTO dataset_library_maintenance_events VALUES (?, ?, ?)",
                (safety_sha, operation_id, "2026-07-31T00:01:00+00:00"),
            )
            connection.commit()
        finally:
            connection.close()
        state = inspect_backup_state(
            self.storage,
            database=SimpleNamespace(path=audit_database),
        )
        self.assertTrue(state["audit_binding_available"])
        self.assertEqual(state["self_consistent_bundle_count"], 1)
        self.assertEqual(state["recovery_safety_bundle_count"], 1)
        self.assertEqual(state["audit_bound_verified_bundle_count"], 1)
        self.assertEqual(state["audit_bound_invalid_bundle_count"], 0)

    def test_incomplete_backup_discard_rejects_linked_bundle(self) -> None:
        self.backups.mkdir(parents=True)
        outside = _MODULE_TEMP / f"outside-backup-{uuid.uuid4().hex}"
        outside.mkdir()
        sentinel = outside / "must-survive.txt"
        sentinel.write_text("preserve", encoding="utf-8")
        alias = self.backups / f"atlas-dataset-library-{uuid.uuid4().hex}"
        _create_directory_alias(alias, outside)
        try:
            with self.assertRaises(DatasetStorageError):
                self.storage.discard_incomplete_backup_bundle(alias)
            self.assertEqual(sentinel.read_text(encoding="utf-8"), "preserve")
        finally:
            _remove_directory_alias(alias)
            shutil.rmtree(outside, ignore_errors=True)

    def test_incomplete_backup_discard_rejects_swapped_backup_root_alias(self) -> None:
        outside = _MODULE_TEMP / f"outside-root-{uuid.uuid4().hex}"
        outside.mkdir()
        bundle = outside / f"atlas-dataset-library-{uuid.uuid4().hex}"
        bundle.mkdir()
        sentinel = bundle / "must-survive.txt"
        sentinel.write_text("preserve", encoding="utf-8")
        _create_directory_alias(self.backups, outside)
        try:
            with self.assertRaises(DatasetStorageError):
                self.storage.discard_incomplete_backup_bundle(
                    self.backups / bundle.name
                )
            self.assertEqual(sentinel.read_text(encoding="utf-8"), "preserve")
        finally:
            _remove_directory_alias(self.backups)
            shutil.rmtree(outside, ignore_errors=True)

    def test_admin_reconciliation_endpoint_rejects_non_admin_before_scanning(self) -> None:
        with patch(
            "server.datasets.dataset_integrity_router.run_bounded_integrity_scan"
        ) as scan:
            with self.assertRaises(HTTPException) as raised:
                dataset_library_reconciliation({"role": "viewer"})
        self.assertEqual(raised.exception.status_code, 403)
        scan.assert_not_called()


if __name__ == "__main__":
    unittest.main()
