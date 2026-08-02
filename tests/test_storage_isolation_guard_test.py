"""Focused tests for the Dataset Library source isolation guard.

Run:
    .venv/Scripts/python.exe tests/test_storage_isolation_guard_test.py
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import textwrap
import unittest
import uuid


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from scripts.check_test_storage_isolation import (  # noqa: E402
    scan_repository,
    scan_test_source,
)


def _rules(source: str, *, configured: tuple[Path, ...] = ()) -> set[str]:
    violations = scan_test_source(
        Path("synthetic_dataset_test.py"),
        textwrap.dedent(source),
        configured_live_roots=configured,
    )
    return {violation.rule for violation in violations}


SAFE_EMPTY_FIXTURE = """
import os
from pathlib import Path
import uuid

ROOT = Path(__file__).resolve().parent
TEST_ROOT = ROOT / ".tmp" / f"catalog-{uuid.uuid4().hex}"
ENV = {
    "ATLAS_TEST_MODE": "1",
    "ATLAS_DATASET_LIBRARY_ROOT": str(TEST_ROOT / "datasets"),
}
os.environ.update(ENV)

from server.datasets import dataset_registry

def _rebind_isolated_runtime():
    dataset_registry.ARTIFACT_ROOT = TEST_ROOT / "datasets"
    dataset_registry.REGISTRY_PATH = dataset_registry.ARTIFACT_ROOT / "registry.json"
    dataset_registry.USERS_PATH = dataset_registry.ARTIFACT_ROOT / "users.json"
    dataset_registry.PROJECT_LINKS_PATH = dataset_registry.ARTIFACT_ROOT / "project_links.json"

class CatalogTests:
    def setUp(self):
        _rebind_isolated_runtime()
        dataset_registry.save_registry({"datasets": []})
        dataset_registry.save_links({"links": []})
"""


class TestStorageIsolationGuardTests(unittest.TestCase):
    def test_safe_uuid_fixture_with_preimport_rebind_passes(self) -> None:
        self.assertEqual(_rules(SAFE_EMPTY_FIXTURE), set())

    def test_root_configured_after_server_import_fails(self) -> None:
        rules = _rules(
            """
            import os
            from pathlib import Path
            import uuid
            from server.datasets import dataset_registry
            ROOT = Path(__file__).parent / f"catalog-{uuid.uuid4().hex}"
            os.environ["ATLAS_DATASET_LIBRARY_ROOT"] = str(ROOT)
            dataset_registry.save_registry({"datasets": ["sentinel"]})
            """
        )
        self.assertIn("TSI002", rules)

    def test_inherited_or_checked_in_live_root_fails(self) -> None:
        inherited = _rules(
            """
            import os
            import uuid
            ROOT = f"catalog-{uuid.uuid4().hex}"
            os.environ["ATLAS_DATASET_LIBRARY_ROOT"] = os.getenv(
                "ATLAS_DATASET_LIBRARY_ROOT", ROOT
            )
            from server.datasets import dataset_registry
            dataset_registry.save_registry({"datasets": ["sentinel"]})
            """
        )
        checked_in = _rules(
            """
            import os
            import uuid
            from pathlib import Path
            ROOT = Path(__file__).parents[1]
            RUN_ID = uuid.uuid4().hex
            os.environ["ATLAS_DATASET_LIBRARY_ROOT"] = str(
                ROOT / "server" / "artifacts" / "datasets" / RUN_ID
            )
            from server.datasets import dataset_registry
            dataset_registry.save_registry({"datasets": ["sentinel"]})
            """
        )
        self.assertIn("TSI004", inherited)
        self.assertIn("TSI004", checked_in)

    def test_configured_absolute_live_root_fails(self) -> None:
        configured = (Path("C:/atlas-configured-live-datasets"),)
        rules = _rules(
            """
            import os
            import uuid
            RUN_ID = uuid.uuid4().hex
            os.environ["ATLAS_DATASET_LIBRARY_ROOT"] = "C:/atlas-configured-live-datasets"
            from server.datasets import dataset_registry
            dataset_registry.save_registry({"datasets": ["sentinel"]})
            """,
            configured=configured,
        )
        self.assertIn("TSI004", rules)

    def test_exact_empty_catalog_leak_signature_requires_rebind(self) -> None:
        rules = _rules(
            """
            import os
            from pathlib import Path
            import uuid
            ROOT = Path(__file__).parent / f"catalog-{uuid.uuid4().hex}"
            os.environ["ATLAS_TEST_MODE"] = "1"
            os.environ["ATLAS_DATASET_LIBRARY_ROOT"] = str(ROOT)
            from server.datasets import dataset_registry

            class CatalogTests:
                def setUp(self):
                    dataset_registry.save_registry({"datasets": []})
                    dataset_registry.save_links({"links": []})
            """
        )
        self.assertIn("TSI006", rules)

    def test_every_dataset_mutator_requires_all_cached_path_rebindings(self) -> None:
        missing_users = _rules(
            """
            import os
            from pathlib import Path
            import uuid
            ROOT = Path(__file__).parent / ".tmp" / f"catalog-{uuid.uuid4().hex}"
            os.environ["ATLAS_DATASET_LIBRARY_ROOT"] = str(ROOT)
            from server.datasets import dataset_registry

            def mutate():
                dataset_registry.ARTIFACT_ROOT = ROOT
                dataset_registry.REGISTRY_PATH = ROOT / "registry.json"
                dataset_registry.PROJECT_LINKS_PATH = ROOT / "project_links.json"
                dataset_registry.save_registry({"datasets": ["sentinel"]})
            """
        )
        late_rebind = _rules(
            """
            import os
            from pathlib import Path
            import uuid
            ROOT = Path(__file__).parent / ".tmp" / f"catalog-{uuid.uuid4().hex}"
            os.environ["ATLAS_DATASET_LIBRARY_ROOT"] = str(ROOT)
            from server.datasets import dataset_registry

            def mutate():
                dataset_registry.save_registry({"datasets": ["sentinel"]})
                dataset_registry.ARTIFACT_ROOT = ROOT
                dataset_registry.REGISTRY_PATH = ROOT / "registry.json"
                dataset_registry.USERS_PATH = ROOT / "users.json"
                dataset_registry.PROJECT_LINKS_PATH = ROOT / "project_links.json"
            """
        )
        self.assertIn("TSI006", missing_users)
        self.assertIn("TSI006", late_rebind)

    def test_complete_cached_path_rebind_allows_nonempty_mutation(self) -> None:
        rules = _rules(
            """
            import os
            from pathlib import Path
            import uuid
            ROOT = Path(__file__).parent / ".tmp" / f"catalog-{uuid.uuid4().hex}"
            os.environ["ATLAS_DATASET_LIBRARY_ROOT"] = str(ROOT)
            from server.datasets import dataset_registry

            def mutate():
                dataset_registry.ARTIFACT_ROOT = ROOT
                dataset_registry.REGISTRY_PATH = ROOT / "registry.json"
                dataset_registry.USERS_PATH = ROOT / "users.json"
                dataset_registry.PROJECT_LINKS_PATH = ROOT / "project_links.json"
                dataset_registry.save_registry({"datasets": ["sentinel"]})
            """
        )
        self.assertNotIn("TSI006", rules)

    def test_cached_dataset_rebind_requires_owned_root_and_exact_children(self) -> None:
        unowned_root = _rules(
            """
            import os
            import tempfile
            from pathlib import Path
            import uuid
            ROOT = Path(__file__).parent / ".tmp" / f"catalog-{uuid.uuid4().hex}"
            os.environ["ATLAS_DATASET_LIBRARY_ROOT"] = str(ROOT)
            from server.datasets import dataset_registry

            def mutate():
                dataset_registry.ARTIFACT_ROOT = Path(tempfile.gettempdir()) / "shared"
                dataset_registry.REGISTRY_PATH = dataset_registry.ARTIFACT_ROOT / "registry.json"
                dataset_registry.USERS_PATH = dataset_registry.ARTIFACT_ROOT / "users.json"
                dataset_registry.PROJECT_LINKS_PATH = dataset_registry.ARTIFACT_ROOT / "project_links.json"
                dataset_registry.save_registry({"datasets": ["sentinel"]})
            """
        )
        mismatched_child = _rules(
            """
            import os
            from pathlib import Path
            import uuid
            ROOT = Path(__file__).parent / ".tmp" / f"catalog-{uuid.uuid4().hex}"
            OTHER = Path(__file__).parent / ".tmp" / f"other-{uuid.uuid4().hex}"
            os.environ["ATLAS_DATASET_LIBRARY_ROOT"] = str(ROOT)
            from server.datasets import dataset_registry

            def mutate():
                dataset_registry.ARTIFACT_ROOT = ROOT
                dataset_registry.REGISTRY_PATH = OTHER / "registry.json"
                dataset_registry.USERS_PATH = ROOT / "users.json"
                dataset_registry.PROJECT_LINKS_PATH = ROOT / "project_links.json"
                dataset_registry.save_registry({"datasets": ["sentinel"]})
            """
        )
        self.assertIn("TSI006", unowned_root)
        self.assertIn("TSI006", mismatched_child)

    def test_uncalled_dataset_rebind_helper_does_not_satisfy_guard(self) -> None:
        rules = _rules(
            """
            import os
            from pathlib import Path
            import uuid
            ROOT = Path(__file__).parent / ".tmp" / f"catalog-{uuid.uuid4().hex}"
            os.environ["ATLAS_DATASET_LIBRARY_ROOT"] = str(ROOT)
            from server.datasets import dataset_registry

            def never_called():
                dataset_registry.ARTIFACT_ROOT = ROOT
                dataset_registry.REGISTRY_PATH = ROOT / "registry.json"
                dataset_registry.USERS_PATH = ROOT / "users.json"
                dataset_registry.PROJECT_LINKS_PATH = ROOT / "project_links.json"

            dataset_registry.save_registry({"datasets": ["sentinel"]})
            """
        )
        self.assertIn("TSI006", rules)

    def test_endpoint_only_dataset_mutation_requires_isolated_root(self) -> None:
        rules = _rules(
            """
            from fastapi.testclient import TestClient
            from server.main import app

            client = TestClient(app)
            client.post("/api/datasets/register", json={"name": "unsafe"})
            """
        )
        self.assertIn("TSI001", rules)
        self.assertIn("TSI003", rules)

    def test_request_api_and_indirect_registration_endpoint_are_detected(self) -> None:
        rules = _rules(
            """
            from fastapi.testclient import TestClient
            from server.main import app

            ENDPOINT = "/api/scoring/register-scored-dataset"
            client = TestClient(app)
            client.request("POST", ENDPOINT, json={"rows": [{"score": 1}]})
            """
        )
        self.assertIn("TSI001", rules)

    def test_registry_mutators_omitted_by_the_old_allowlist_are_detected(self) -> None:
        module_call = _rules(
            """
            from server.datasets import dataset_registry
            dataset_registry.archive_dataset("dataset-test")
            """
        )
        imported_alias = _rules(
            """
            def remove_links():
                from server.datasets.dataset_registry import unlink_all_project_datasets as unlink_all
                unlink_all("project-test")

            remove_links()
            """
        )
        self.assertIn("TSI001", module_call)
        self.assertIn("TSI001", imported_alias)

    def test_nonmutating_or_unrelated_testclient_calls_do_not_trigger(self) -> None:
        rules = _rules(
            """
            from fastapi.testclient import TestClient
            from server.main import app

            client = TestClient(app)
            client.get("/api/datasets")
            client.post("/api/projects", json={"projectName": "isolated"})
            """
        )
        self.assertEqual(rules, set())

    def test_project_delete_requires_isolated_checkpoint_path(self) -> None:
        rules = _rules(
            """
            from fastapi.testclient import TestClient
            from server.main import app

            client = TestClient(app)
            client.delete(f"/api/projects/{'project-test'}")
            """
        )
        self.assertIn("TSI007", rules)
        self.assertIn("TSI009", rules)

    def test_prefixed_outlier_apply_requires_isolated_checkpoint_path(self) -> None:
        rules = _rules(
            """
            from fastapi.testclient import TestClient
            from server.main import app

            client = TestClient(app)
            client.post("/api/outliers/apply", json={})
            """
        )
        self.assertIn("TSI007", rules)
        self.assertIn("TSI009", rules)

    def test_checkpoint_path_configured_after_import_fails(self) -> None:
        rules = _rules(
            """
            import os
            import uuid
            from pathlib import Path
            from server.main import app

            RUN_ID = uuid.uuid4().hex
            os.environ["ATLAS_CHECKPOINT_PATH"] = str(
                Path(__file__).parent / ".tmp" / f"checkpoint-{RUN_ID}.json"
            )
            app.state.client.delete(f"/api/projects/{'project-test'}")
            """
        )
        self.assertIn("TSI008", rules)

    def test_checkpoint_path_must_be_uuid_specific_and_not_live(self) -> None:
        nonunique = _rules(
            """
            import os
            os.environ["ATLAS_CHECKPOINT_PATH"] = ".tmp/checkpoint.json"
            from server.main import app
            app.state.client.delete("/api/projects/project-test")
            """
        )
        live = _rules(
            """
            import os
            import uuid
            RUN_ID = uuid.uuid4().hex
            os.environ["ATLAS_CHECKPOINT_PATH"] = ".runtime/workflow_checkpoint.json"
            from server.main import app
            app.state.client.delete("/api/projects/project-test")
            """
        )
        self.assertIn("TSI009", nonunique)
        self.assertIn("TSI010", live)

    def test_direct_checkpoint_path_symbol_mutation_is_detected(self) -> None:
        rules = _rules(
            """
            from server.core.session_checkpoint import CHECKPOINT_PATH as cp
            cp.write_text("{}", encoding="utf-8")
            """
        )
        self.assertIn("TSI007", rules)
        self.assertIn("TSI009", rules)

    def test_uuid_checkpoint_path_before_import_passes(self) -> None:
        rules = _rules(
            """
            import os
            import uuid
            from pathlib import Path

            RUN_ID = uuid.uuid4().hex
            os.environ["ATLAS_CHECKPOINT_PATH"] = str(
                Path(__file__).parent / ".tmp" / f"checkpoint-{RUN_ID}.json"
            )
            from server.main import app
            from server.core import session_checkpoint
            session_checkpoint.CHECKPOINT_PATH = Path(
                os.environ["ATLAS_CHECKPOINT_PATH"]
            ).resolve()
            assert session_checkpoint.CHECKPOINT_PATH == Path(
                os.environ["ATLAS_CHECKPOINT_PATH"]
            ).resolve()
            app.state.client.delete(f"/api/projects/{'project-test'}")
            """
        )
        self.assertNotIn("TSI007", rules)
        self.assertNotIn("TSI008", rules)
        self.assertNotIn("TSI009", rules)
        self.assertNotIn("TSI010", rules)

    def test_cached_checkpoint_rebind_rejects_live_or_unowned_alias(self) -> None:
        live = _rules(
            """
            import os
            import uuid
            from pathlib import Path
            RUN_ID = uuid.uuid4().hex
            os.environ["ATLAS_CHECKPOINT_PATH"] = str(
                Path(__file__).parent / ".tmp" / f"checkpoint-{RUN_ID}.json"
            )
            from server.core import session_checkpoint
            session_checkpoint.CHECKPOINT_PATH = Path(".runtime/workflow_checkpoint.json")
            session_checkpoint.save_checkpoint()
            """
        )
        inherited = _rules(
            """
            import os
            from pathlib import Path
            from server.core import session_checkpoint
            session_checkpoint.CHECKPOINT_PATH = Path(
                os.environ["ATLAS_CHECKPOINT_PATH"]
            ).resolve()
            session_checkpoint.save_checkpoint()
            """
        )
        self.assertIn("TSI010", live)
        self.assertIn("TSI010", inherited)

    def test_cached_checkpoint_rebind_requires_uuid_temp_ownership(self) -> None:
        rules = _rules(
            """
            from pathlib import Path
            from server.core import session_checkpoint
            session_checkpoint.CHECKPOINT_PATH = Path(".tmp/checkpoint.json")
            session_checkpoint.save_checkpoint()
            """
        )
        self.assertIn("TSI009", rules)
        self.assertIn("TSI010", rules)

    def test_checkpoint_setdefault_or_uncalled_rebind_cannot_claim_ownership(self) -> None:
        setdefault = _rules(
            """
            import os
            import uuid
            from pathlib import Path
            RUN_ID = uuid.uuid4().hex
            os.environ.setdefault(
                "ATLAS_CHECKPOINT_PATH",
                str(Path(__file__).parent / ".tmp" / f"checkpoint-{RUN_ID}.json"),
            )
            from server.core import session_checkpoint
            session_checkpoint.CHECKPOINT_PATH = Path(
                os.environ["ATLAS_CHECKPOINT_PATH"]
            ).resolve()
            session_checkpoint.save_checkpoint()
            """
        )
        uncalled = _rules(
            """
            import uuid
            from pathlib import Path
            ROOT = Path(__file__).parent / ".tmp" / f"checkpoint-{uuid.uuid4().hex}.json"
            from server.core import session_checkpoint

            def never_called():
                session_checkpoint.CHECKPOINT_PATH = ROOT

            session_checkpoint.save_checkpoint()
            """
        )
        self.assertIn("TSI010", setdefault)
        self.assertIn("TSI008", uncalled)
        self.assertIn("TSI009", uncalled)

    def test_repository_source_scan_passes(self) -> None:
        paths, violations = scan_repository(REPO_ROOT)
        self.assertGreater(len(paths), 0)
        self.assertEqual(
            [violation.render() for violation in violations],
            [],
        )

    def test_phase2a_fixture_rebinds_a_preimported_registry(self) -> None:
        """Reproduce the prior module-cache signature without touching live data."""

        root = (
            REPO_ROOT / f".storage-isolation-guard-{uuid.uuid4().hex}"
        ).resolve()
        self.assertEqual(root.parent, REPO_ROOT)
        root.mkdir(exist_ok=False)
        try:
            preimported = root / "preimported-catalog"
            preimported.mkdir(parents=True)
            registry_sentinel = {"datasets": [{"datasetId": "must-survive"}]}
            links_sentinel = {"links": [{"projectId": "must-survive"}]}
            (preimported / "registry.json").write_text(
                json.dumps(registry_sentinel), encoding="utf-8"
            )
            (preimported / "project_links.json").write_text(
                json.dumps(links_sentinel), encoding="utf-8"
            )

            environment = os.environ.copy()
            environment.update(
                {
                    "ATLAS_TEST_MODE": "1",
                    "ATLAS_DATASET_LIBRARY_ROOT": str(preimported),
                    "ATLAS_DATASET_LIBRARY_BACKUP_ROOT": str(root / "backups"),
                    "ATLAS_SECURITY_ROOT": str(root / "security"),
                    "ATLAS_SECURITY_DB_PATH": str(root / "security" / "security.db"),
                    "ATLAS_SQLITE_PATH": str(root / "persistence" / "atlas.db"),
                    "ATLAS_CHECKPOINT_PATH": str(root / "checkpoint" / "checkpoint.json"),
                    "ATLAS_EVIDENCE_ROOT": str(root / "evidence"),
                    "ATLAS_MODEL_REGISTRY_ARTIFACT_ROOT": str(root / "models"),
                    "ATLAS_SCORING_RUN_ARTIFACT_ROOT": str(root / "scoring"),
                    "PYTHONPATH": str(REPO_ROOT),
                }
            )
            phase2a_path = REPO_ROOT / "tests" / "phase2a_registration_external_identity_test.py"
            probe = textwrap.dedent(
                f"""
                import importlib.util
                import json
                from pathlib import Path
                from server.datasets import dataset_registry

                preimported = Path({str(preimported)!r}).resolve()
                phase2a_path = Path({str(phase2a_path)!r})
                assert dataset_registry.ARTIFACT_ROOT.resolve() == preimported
                spec = importlib.util.spec_from_file_location("phase2a_guard_probe", phase2a_path)
                module = importlib.util.module_from_spec(spec)
                assert spec.loader is not None
                spec.loader.exec_module(module)
                assert dataset_registry.ARTIFACT_ROOT.resolve() == preimported

                case = module.Phase2ARegistrationAndExternalIdentityTests(
                    "test_mutable_runtime_bindings_never_target_checked_in_roots"
                )
                case.setUp()
                assert dataset_registry.ARTIFACT_ROOT.resolve() == module._LIBRARY_ROOT.resolve()
                assert dataset_registry.ARTIFACT_ROOT.resolve() != preimported
                assert json.loads((preimported / "registry.json").read_text(encoding="utf-8")) == {registry_sentinel!r}
                assert json.loads((preimported / "project_links.json").read_text(encoding="utf-8")) == {links_sentinel!r}
                module.Phase2ARegistrationAndExternalIdentityTests.tearDownClass()
                """
            )
            completed = subprocess.run(
                [sys.executable, "-c", probe],
                cwd=REPO_ROOT,
                env=environment,
                capture_output=True,
                text=True,
                timeout=90,
                check=False,
            )
            self.assertEqual(
                completed.returncode,
                0,
                msg=f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}",
            )
        finally:
            if root.parent == REPO_ROOT:
                shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
