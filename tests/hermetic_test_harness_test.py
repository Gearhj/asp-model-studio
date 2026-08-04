"""Focused unit tests for the pure pre-import hermetic authority guard."""
from __future__ import annotations

from dataclasses import replace
import ctypes
import os
from pathlib import Path
import subprocess
import sys
import unittest
import uuid

from scripts.hermetic_test_authority import (
    AUTHORITY_LAYOUT,
    ChildAuthority,
    HermeticAuthorityError,
    RunAuthority,
    canonical_path,
    create_child_authority,
    sitecustomize_guard,
    validate_child,
    validate_children_disjoint,
    validate_external_root,
)
from scripts.hermetic_test_bootstrap import assert_preimport_state


class HermeticAuthorityGuardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.root = Path(os.environ["ATLAS_HERMETIC_ROOT"]).resolve()
        cls.live_repo = Path(os.environ["ATLAS_LIVE_REPOSITORY_ROOT"]).resolve()
        cls.run_authority = RunAuthority(os.environ["ATLAS_RUN_ID"], cls.root)

    def child(self, label: str = "guard") -> ChildAuthority:
        return create_child_authority(
            self.run_authority, f"{label}-{uuid.uuid4().hex}"
        )

    def assert_category(self, category: str, callback) -> None:
        with self.assertRaises(HermeticAuthorityError) as caught:
            callback()
        self.assertEqual(caught.exception.category, category)

    def test_external_unique_plan_is_accepted(self) -> None:
        child = self.child("positive")
        validate_child(child)
        self.assertTrue(all(self.root in Path(path).parents for path in child.authorities.values()))

    def test_current_child_has_complete_metadata_and_precreated_authorities(self) -> None:
        self.assertEqual(os.environ["ATLAS_TEST_MODE"], "1")
        self.assertEqual(os.environ["ATLAS_PROCESS_ROLE"], "test")
        self.assertTrue(os.environ["ATLAS_RUN_ID"].startswith("atlas-hrt-"))
        self.assertTrue(os.environ["ATLAS_TEST_NAME"])
        for name, (variable, _relative) in AUTHORITY_LAYOUT.items():
            configured = Path(os.environ[variable]).resolve()
            self.assertTrue(configured == self.root or self.root in configured.parents, name)
            expected = configured.parent if name.endswith("database") or name == "workflow_checkpoint" else configured
            self.assertTrue(expected.exists(), name)

    def test_nested_child_inherited_sentinel_is_fully_revalidated(self) -> None:
        self.assertEqual(os.environ["ATLAS_HERMETIC_GUARD_PASSED"], "1")
        sitecustomize_guard()
        self.assertEqual(os.environ["ATLAS_HERMETIC_GUARD_PASSED"], "1")

    def test_rejected_fresh_launch_exits_before_application_import_or_write(self) -> None:
        marker = self.root / f"unsafe-launch-marker-{uuid.uuid4().hex}.txt"
        environment = os.environ.copy()
        environment["ATLAS_HERMETIC_GUARD_PASSED"] = "0"
        environment["ATLAS_SQLITE_PATH"] = str(
            self.live_repo / "server" / "data" / "atlas_local.db"
        )
        probe = (
            "from pathlib import Path; "
            f"Path({str(marker)!r}).write_text('unsafe', encoding='utf-8'); "
            "import server.main"
        )
        completed = subprocess.run(
            [sys.executable, "-c", probe],
            cwd=Path(os.environ["ATLAS_HERMETIC_SOURCE_ROOT"]),
            env=environment,
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
        self.assertEqual(completed.returncode, 86)
        self.assertEqual(
            completed.stderr.strip(),
            "HERMETIC_GUARD_REJECTED:authority-outside-root",
        )
        self.assertEqual(completed.stdout, "")
        self.assertFalse(marker.exists())

    def test_rejects_live_persistence_and_security_databases(self) -> None:
        for key, live in (
            ("persistence_database", self.live_repo / "server" / "data" / "atlas_local.db"),
            ("security_database", self.live_repo / "server" / "artifacts" / "security" / "atlas_security.db"),
        ):
            child = self.child(key)
            paths = dict(child.authorities)
            paths[key] = live
            unsafe = replace(child, authorities=paths)
            with self.subTest(key=key):
                self.assert_category("authority-outside-root", lambda: validate_child(unsafe))

    def test_rejects_every_named_live_root_category(self) -> None:
        candidates = {
            "dataset": self.live_repo / "server" / "artifacts" / "datasets",
            "checkpoint": self.live_repo / ".runtime" / "workflow_checkpoint.json",
            "evidence": self.live_repo / "server" / "artifacts" / "evidence",
            "mdd": self.live_repo / "server" / "artifacts" / "model_documentation",
            "feature": self.live_repo / "server" / "artifacts" / "feature_manifests",
            "repo_tmp": self.live_repo / ".tmp",
        }
        for label, candidate in candidates.items():
            with self.subTest(label=label):
                self.assert_category(
                    "live-or-repository-overlap",
                    lambda candidate=candidate: validate_external_root(candidate),
                )

    def test_rejects_parent_child_case_relative_traversal_and_unc_aliases(self) -> None:
        for candidate in (self.live_repo.parent, self.live_repo / "server"):
            self.assert_category(
                "live-or-repository-overlap",
                lambda candidate=candidate: validate_external_root(candidate),
            )
        case_alias = Path(str(self.live_repo).swapcase())
        self.assert_category(
            "live-or-repository-overlap",
            lambda: validate_external_root(case_alias),
        )
        self.assert_category("relative-path", lambda: canonical_path("relative/path"))
        self.assert_category(
            "path-traversal",
            lambda: canonical_path(str(self.root / "child" / ".." / "escape")),
        )
        self.assert_category(
            "unc-or-device-alias",
            lambda: canonical_path(r"\\localhost\c$\atlas-hermetic"),
        )

    def test_rejects_dataset_backup_overlap_and_missing_authority(self) -> None:
        child = self.child("backup-overlap")
        paths = dict(child.authorities)
        paths["dataset_backups"] = paths["dataset_library"] / "backups"
        self.assert_category(
            "test-authority-overlap",
            lambda: validate_child(replace(child, authorities=paths)),
        )
        paths = dict(child.authorities)
        paths.pop("evidence_root")
        self.assert_category(
            "missing-authority",
            lambda: validate_child(replace(child, authorities=paths)),
        )

    def test_rejects_missing_run_id_and_shared_database_configuration(self) -> None:
        child = self.child("metadata")
        self.assert_category("run-id", lambda: validate_child(replace(child, run_id="")))
        other = self.child("other")
        paths = dict(other.authorities)
        paths["persistence_database"] = child.authorities["persistence_database"]
        with self.assertRaises(HermeticAuthorityError) as caught:
            validate_children_disjoint([child, replace(other, authorities=paths)])
        self.assertIn(caught.exception.category, {"authority-outside-root", "shared-writable-database"})

    def test_rejects_symlink_to_live_authority(self) -> None:
        link = self.root / "guard-aliases" / f"symlink-{uuid.uuid4().hex}"
        link.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.symlink(self.live_repo, link, target_is_directory=True)
        except (OSError, NotImplementedError) as exc:
            self.skipTest(f"symlink creation unavailable: {type(exc).__name__}")
        self.assert_category("linked-or-reparse-path", lambda: canonical_path(link))

    @unittest.skipUnless(os.name == "nt", "Windows junction regression")
    def test_rejects_junction_to_live_authority(self) -> None:
        link = self.root / "guard-aliases" / f"junction-{uuid.uuid4().hex}"
        link.parent.mkdir(parents=True, exist_ok=True)
        completed = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(link), str(self.live_repo)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        if completed.returncode:
            self.skipTest("junction creation unavailable")
        self.assert_category("linked-or-reparse-path", lambda: canonical_path(link))

    @unittest.skipUnless(os.name == "nt", "Windows short-name regression")
    def test_detects_short_name_alias_where_available(self) -> None:
        buffer = ctypes.create_unicode_buffer(32768)
        length = ctypes.windll.kernel32.GetShortPathNameW(
            str(self.live_repo), buffer, len(buffer)
        )
        if not length or not buffer.value or buffer.value.casefold() == str(self.live_repo).casefold():
            self.skipTest("8.3 alias unavailable")
        self.assert_category(
            "live-or-repository-overlap",
            lambda: validate_external_root(Path(buffer.value)),
        )

    def test_preimport_regression_rejects_cached_server_provider(self) -> None:
        import types

        key = "server.hermetic_unsafe_probe"
        sys.modules[key] = types.ModuleType(key)
        try:
            self.assert_category("atlas-preimport", assert_preimport_state)
        finally:
            sys.modules.pop(key, None)


if __name__ == "__main__":
    unittest.main()
