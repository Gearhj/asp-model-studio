"""Focused unit tests for the pure pre-import hermetic authority guard."""
from __future__ import annotations

from dataclasses import replace
import ctypes
import hashlib
import os
from pathlib import Path
import subprocess
import sys
import time
import unittest
import uuid

from scripts.hermetic_test_authority import (
    AUTHORITY_LAYOUT,
    ChildAuthority,
    HermeticAuthorityError,
    NODE_RUNTIME_PACKAGE_FILES,
    RunAuthority,
    build_child_environment,
    canonical_path,
    copy_root_package_json,
    copy_node_runtime_packages,
    create_child_authority,
    create_source_mirror,
    sitecustomize_guard,
    validate_child,
    validate_children_disjoint,
    validate_external_root,
)
from scripts.hermetic_test_bootstrap import assert_preimport_state
from scripts.run_hermetic_tests import (
    SuiteSpec,
    _node_runtime_packages_for,
    _run_bootstrap,
)
from scripts import run_security_tests as security_gate


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
        self.assertEqual(os.environ["PYTHONDONTWRITEBYTECODE"], "1")
        pycache_root = self.root / "authorities" / "pycache"
        self.assertFalse(any(pycache_root.rglob("*.pyc")))
        for name, (variable, _relative) in AUTHORITY_LAYOUT.items():
            configured = Path(os.environ[variable]).resolve()
            self.assertTrue(configured == self.root or self.root in configured.parents, name)
            expected = configured.parent if name.endswith("database") or name == "workflow_checkpoint" else configured
            self.assertTrue(expected.exists(), name)

    def test_catalog_authorities_are_explicit_preimport_child_pins(self) -> None:
        expected = {
            "bureau_catalog_registry_root": "ATLAS_BUREAU_CATALOG_REGISTRY_ROOT",
            "restricted_metadata_root": "ATLAS_RESTRICTED_METADATA_ROOT",
            "catalog_install_journal_root": "ATLAS_ISOLATED_CATALOG_INSTALL_JOURNAL_ROOT",
        }
        self.assertEqual(
            {name: AUTHORITY_LAYOUT[name][0] for name in expected},
            expected,
        )
        child = self.child("catalog-authority-pins")
        inherited = os.environ.copy()
        for variable in expected.values():
            inherited[variable] = str(self.live_repo / "server" / "artifacts")
        environment = build_child_environment(child, inherited)
        resolved = {
            name: Path(environment[variable]).resolve()
            for name, variable in expected.items()
        }
        self.assertEqual(resolved, {name: child.authorities[name] for name in expected})
        self.assertEqual(len(set(resolved.values())), len(expected))
        self.assertTrue(
            all(child.root in path.parents for path in resolved.values())
        )
        self.assertEqual(environment["PYTHONDONTWRITEBYTECODE"], "1")

    def test_security_child_environment_disables_disposable_bytecode(self) -> None:
        runtime_root = self.root / f"security-environment-{uuid.uuid4().hex}"
        environment = security_gate.isolated_environment(runtime_root)
        self.assertEqual(environment["PYTHONDONTWRITEBYTECODE"], "1")
        self.assertTrue(
            Path(environment["PYTHONPYCACHEPREFIX"]).resolve()
            == (runtime_root / "pycache").resolve()
        )

    def test_outer_bootstrap_timeout_returns_structured_result(self) -> None:
        started = time.monotonic()
        completed, timed_out = _run_bootstrap(
            [sys.executable, "-c", "import time; time.sleep(30)"],
            cwd=Path(os.environ["ATLAS_HERMETIC_SOURCE_ROOT"]),
            environment=os.environ.copy(),
            timeout_seconds=0.25,
        )
        self.assertTrue(timed_out)
        self.assertEqual(completed.returncode, 124)
        self.assertLess(time.monotonic() - started, 15)

    def test_security_entry_timeout_preserves_partial_log_and_stops_child(self) -> None:
        probe_root = self.root / f"security-timeout-{uuid.uuid4().hex}"
        probe_root.mkdir(parents=True)
        marker = probe_root / "late-marker.txt"
        script = probe_root / "sleeping-security-probe.py"
        script.write_text(
            "import pathlib, time\n"
            "print('probe-started', flush=True)\n"
            "time.sleep(30)\n"
            f"pathlib.Path({str(marker)!r}).write_text('late', encoding='utf-8')\n",
            encoding="utf-8",
        )
        gate_root = probe_root / "gate"
        gate_root.mkdir()
        with self.assertRaises(SystemExit) as caught:
            security_gate.run_entry(
                "behavioral",
                {
                    "path": str(script),
                    "description": "bounded timeout probe",
                    # Windows can spend more than 250 ms starting the isolated
                    # interpreter before the probe reaches its first flushed
                    # write. Give startup a bounded window while remaining far
                    # below the probe's intentional 30-second sleep.
                    "timeoutSeconds": 5.0,
                },
                gate_root,
            )
        self.assertEqual(caught.exception.code, 124)
        logs = list(gate_root.glob("*.log"))
        self.assertEqual(len(logs), 1)
        timeout_log = logs[0].read_text(encoding="utf-8")
        self.assertIn("ATLAS security entry started: kind=behavioral", timeout_log)
        time.sleep(0.25)
        self.assertFalse(marker.exists())

    def test_node_runtime_selection_is_explicit_and_bounded(self) -> None:
        self.assertEqual(set(NODE_RUNTIME_PACKAGE_FILES), {"typescript"})
        self.assertEqual(
            _node_runtime_packages_for(
                SuiteSpec("node", "tests/synthetic.test.mjs", "node-test")
            ),
            ("typescript",),
        )
        self.assertEqual(
            _node_runtime_packages_for(
                SuiteSpec(
                    "guard",
                    "tests/hermetic_test_harness_test.py",
                    "python-test",
                )
            ),
            ("typescript",),
        )
        self.assertEqual(
            _node_runtime_packages_for(
                SuiteSpec("python", "tests/synthetic_test.py", "python-test")
            ),
            (),
        )

    def test_source_mirror_contains_verified_read_only_root_package(self) -> None:
        child = self.child("root-package-mirror")
        source_package = (
            Path(os.environ["ATLAS_HERMETIC_SOURCE_ROOT"]) / "package.json"
        )
        source_stylesheet = (
            Path(os.environ["ATLAS_HERMETIC_SOURCE_ROOT"])
            / "src"
            / "components"
            / "preparation"
            / "preparation-premium.css"
        )
        source_before = source_package.stat()
        source_hash = hashlib.sha256(source_package.read_bytes()).hexdigest()
        stylesheet_hash = hashlib.sha256(source_stylesheet.read_bytes()).hexdigest()

        manifest = create_source_mirror(child)

        target = child.source_root / "package.json"
        target_mode = target.stat().st_mode
        self.assertTrue(target.is_file())
        self.assertFalse(target.is_symlink())
        self.assertFalse(os.path.samefile(source_package, target))
        self.assertEqual(hashlib.sha256(target.read_bytes()).hexdigest(), source_hash)
        self.assertEqual(
            target_mode & (0o200 | 0o020 | 0o002),
            0,
        )
        self.assertEqual(
            manifest["root_package_json"],
            {
                "path": "package.json",
                "sha256": source_hash,
                "child_local": True,
                "read_only": True,
            },
        )
        matching_entries = [
            entry for entry in manifest["files"] if entry["path"] == "package.json"
        ]
        self.assertEqual(matching_entries, [{"path": "package.json", "sha256": source_hash}])
        environment = build_child_environment(child)
        self.assertEqual(
            Path(environment["ATLAS_HERMETIC_PACKAGE_JSON"]).resolve(),
            target.resolve(),
        )
        self.assertEqual(
            environment["ATLAS_HERMETIC_PACKAGE_JSON_SHA256"],
            source_hash,
        )
        mirrored_stylesheet = (
            child.source_root
            / "src"
            / "components"
            / "preparation"
            / "preparation-premium.css"
        )
        self.assertTrue(mirrored_stylesheet.is_file())
        self.assertFalse(mirrored_stylesheet.is_symlink())
        self.assertFalse(os.path.samefile(source_stylesheet, mirrored_stylesheet))
        self.assertEqual(
            hashlib.sha256(mirrored_stylesheet.read_bytes()).hexdigest(),
            stylesheet_hash,
        )
        self.assertIn(
            {
                "path": "src/components/preparation/preparation-premium.css",
                "sha256": stylesheet_hash,
            },
            manifest["files"],
        )
        source_after = source_package.stat()
        self.assertEqual(source_after.st_size, source_before.st_size)
        self.assertEqual(source_after.st_mtime_ns, source_before.st_mtime_ns)
        self.assertEqual(hashlib.sha256(source_package.read_bytes()).hexdigest(), source_hash)

    def test_root_package_copy_rejects_an_existing_destination(self) -> None:
        child = self.child("root-package-existing")
        child.root.mkdir(parents=True)
        child.source_root.mkdir()
        target = child.source_root / "package.json"
        target.write_text("{}", encoding="utf-8")
        self.assert_category(
            "root-package-destination-exists",
            lambda: copy_root_package_json(child),
        )

    def test_typescript_runtime_is_a_verified_child_local_copy(self) -> None:
        child = self.child("node-runtime-copy")
        child.root.mkdir(parents=True)
        child.source_root.mkdir()
        source_entry = (
            Path(os.environ["ATLAS_HERMETIC_SOURCE_ROOT"])
            / "node_modules"
            / "typescript"
            / "lib"
            / "typescript.js"
        )
        source_before = source_entry.stat()
        source_hash = hashlib.sha256(source_entry.read_bytes()).hexdigest()

        copied = copy_node_runtime_packages(child, ("typescript",))

        target_entry = (
            child.source_root
            / "node_modules"
            / "typescript"
            / "lib"
            / "typescript.js"
        )
        self.assertEqual(len(copied), 2)
        self.assertTrue(target_entry.is_file())
        self.assertFalse(target_entry.is_symlink())
        self.assertFalse(os.path.samefile(source_entry, target_entry))
        self.assertEqual(hashlib.sha256(target_entry.read_bytes()).hexdigest(), source_hash)
        source_after = source_entry.stat()
        self.assertEqual(source_after.st_size, source_before.st_size)
        self.assertEqual(source_after.st_mtime_ns, source_before.st_mtime_ns)
        self.assertEqual(hashlib.sha256(source_entry.read_bytes()).hexdigest(), source_hash)

    def test_node_package_failure_isolated_from_an_independent_child(self) -> None:
        rejected = self.child("node-runtime-rejected")
        rejected.root.mkdir(parents=True)
        rejected.source_root.mkdir()
        self.assert_category(
            "unsupported-node-runtime-package",
            lambda: copy_node_runtime_packages(rejected, ("unapproved-package",)),
        )
        self.assertFalse((rejected.source_root / "node_modules").exists())

        accepted = self.child("node-runtime-independent")
        accepted.root.mkdir(parents=True)
        accepted.source_root.mkdir()
        copied = copy_node_runtime_packages(accepted, ("typescript",))
        self.assertEqual(len(copied), 2)
        self.assertTrue(
            (
                accepted.source_root
                / "node_modules"
                / "typescript"
                / "lib"
                / "typescript.js"
            ).is_file()
        )

    def test_node_compile_caches_are_disjoint_child_authorities(self) -> None:
        left = self.child("node-cache-left")
        right = self.child("node-cache-right")
        left_environment = build_child_environment(left)
        right_environment = build_child_environment(right)
        left_cache = Path(left_environment["NODE_COMPILE_CACHE"]).resolve()
        right_cache = Path(right_environment["NODE_COMPILE_CACHE"]).resolve()
        self.assertNotEqual(left_cache, right_cache)
        self.assertTrue(left.root in left_cache.parents)
        self.assertTrue(right.root in right_cache.parents)
        self.assertEqual(
            left_environment["ATLAS_HERMETIC_NODE_CACHE_ROOT"],
            left_environment["NODE_COMPILE_CACHE"],
        )
        self.assertEqual(
            right_environment["ATLAS_HERMETIC_NODE_CACHE_ROOT"],
            right_environment["NODE_COMPILE_CACHE"],
        )

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
            "catalog_registry": self.live_repo / "server" / "artifacts" / "bureau-catalog-registry",
            "restricted_catalog": self.live_repo / "server" / "artifacts" / "bureau-metadata",
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
