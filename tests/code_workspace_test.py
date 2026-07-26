"""Multi-Language Code Workspace execution repair tests.

Covers CODE-DATAACQ-001..004: honest Python capability, approved-sandbox
enforcement, governed dataset binding (no placeholder paths), SAS table identity
bound to the active dataset, and honest SAS statement/status semantics.
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pandas as pd  # noqa: E402

from server.code_execution import sandbox_policy  # noqa: E402
from server.code_execution.sas_compatible import (  # noqa: E402
    active_table_identity,
    run_sas_compatible,
)


def _clear_sandbox_env(**overrides):
    """Context manager returning a patched environment with sandbox keys cleared."""
    base = {
        key: ""
        for key in ("ATLAS_CODE_SANDBOX_COMMAND", "ATLAS_CODE_SANDBOX_ALLOWLIST", "ATLAS_HOSTED_MODE", "ATLAS_ENABLE_PYTHON_RUN")
    }
    base.update(overrides)
    return mock.patch.dict(os.environ, base, clear=False)


class PythonCapabilityTests(unittest.TestCase):
    """CODE-DATAACQ-001: capability must reflect real backend configuration."""

    def test_absent_sandbox_reports_not_configured_and_never_executable(self):
        with _clear_sandbox_env(ATLAS_CODE_SANDBOX_COMMAND=""):
            capability = sandbox_policy.describe_capability()
        self.assertEqual(capability.state, "not_configured")
        self.assertFalse(capability.available)
        self.assertIn("governed code sandbox has not been configured", capability.reason)

    def test_hosted_mode_and_explicit_disable_report_disabled(self):
        with _clear_sandbox_env(ATLAS_HOSTED_MODE="1"):
            self.assertEqual(sandbox_policy.describe_capability().state, "disabled")
        with _clear_sandbox_env(ATLAS_ENABLE_PYTHON_RUN="0"):
            self.assertEqual(sandbox_policy.describe_capability().state, "disabled")

    def test_default_symbolic_command_resolves_to_the_project_interpreter(self):
        with _clear_sandbox_env(ATLAS_CODE_SANDBOX_COMMAND="default"):
            capability = sandbox_policy.describe_capability()
        self.assertEqual(capability.state, "executable")
        self.assertTrue(capability.available)
        self.assertTrue(capability.executable.endswith(("python.exe", "python")))

    def test_unapproved_executable_is_rejected_as_misconfigured(self):
        with _clear_sandbox_env(ATLAS_CODE_SANDBOX_COMMAND="C:\\Windows\\System32\\cmd.exe {script}"):
            capability = sandbox_policy.describe_capability()
        self.assertEqual(capability.state, "misconfigured")
        self.assertFalse(capability.available)
        self.assertIn("allowlist", capability.detail)

    def test_public_capability_never_leaks_server_command_detail(self):
        with _clear_sandbox_env(ATLAS_CODE_SANDBOX_COMMAND="C:\\Windows\\System32\\cmd.exe {script}"):
            capability = sandbox_policy.describe_capability()
        public = capability.public_dict()
        self.assertEqual(set(public), {"state", "available", "reason"})
        self.assertNotIn("cmd.exe", str(public))
        # Administrators may see the configuration key and approved interpreters.
        admin = capability.admin_dict()
        self.assertEqual(admin["configurationKey"], "ATLAS_CODE_SANDBOX_COMMAND")
        self.assertIn("approvedInterpreters", admin)


class SandboxPolicyTests(unittest.TestCase):
    """Part C: user code can never select an arbitrary executable."""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="atlas-sandbox-test-"))
        self.script = self.tmp / "atlas_step_code.py"
        self.script.write_text("print('x')", encoding="utf-8")

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_shell_metacharacters_are_refused(self):
        venv = sandbox_policy.default_venv_python()
        assert venv is not None
        for hostile in [
            f'"{venv}" {{script}} && calc.exe',
            f'"{venv}" {{script}} | more',
            f'"{venv}" {{script}} > out.txt',
            f'"{venv}" {{script}}; whoami',
            f'"{venv}" {{script}} `whoami`',
        ]:
            with self.assertRaises(sandbox_policy.SandboxPolicyError) as ctx:
                sandbox_policy.resolve_sandbox_command(hostile, self.script, self.tmp)
            self.assertIn("shell metacharacters", str(ctx.exception))

    def test_unapproved_interpreter_is_refused(self):
        with self.assertRaises(sandbox_policy.SandboxPolicyError) as ctx:
            sandbox_policy.resolve_sandbox_command("C:\\Windows\\System32\\cmd.exe {script}", self.script, self.tmp)
        self.assertIn("allowlist", str(ctx.exception))

    def test_template_must_reference_the_submitted_script(self):
        venv = sandbox_policy.default_venv_python()
        with self.assertRaises(sandbox_policy.SandboxPolicyError) as ctx:
            sandbox_policy.resolve_sandbox_command(f'"{venv}" -c print(1)', self.script, self.tmp)
        self.assertIn("{script}", str(ctx.exception))

    def test_approved_command_produces_an_argument_vector(self):
        venv = sandbox_policy.default_venv_python()
        argv = sandbox_policy.resolve_sandbox_command(f'"{venv}" -I {{script}}', self.script, self.tmp)
        self.assertIsInstance(argv, list)
        self.assertEqual(Path(argv[0]).resolve(), venv.resolve())
        self.assertIn(str(self.script), argv)
        # No single concatenated shell string is ever produced.
        self.assertTrue(all(isinstance(part, str) for part in argv))

    def test_empty_command_is_refused(self):
        for value in ["", "   "]:
            with self.assertRaises(sandbox_policy.SandboxPolicyError):
                sandbox_policy.resolve_sandbox_command(value, self.script, self.tmp)


class PythonExecutionTests(unittest.TestCase):
    """Parts D/E: governed dataset binding and execution results."""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="atlas-exec-test-"))
        frame = pd.DataFrame({
            "Class": [1 if i % 100 == 0 else 0 for i in range(1000)],
            "Amount": [i * 1.5 for i in range(1000)],
        })
        self.csv = self.tmp / "data_full.csv"
        frame.to_csv(self.csv, index=False)
        self.expected_events = int(frame["Class"].sum())

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _run(self, code: str, context: dict | None = None):
        from server.python_execution import PythonRunRequest, run_python_request

        with _clear_sandbox_env(ATLAS_CODE_SANDBOX_COMMAND="default"):
            return run_python_request(
                PythonRunRequest(page="Data Acquisition", userCode=code, projectId="", context=context or {})
            )

    def _bound_context(self):
        from server.code_execution.dataset_binding import BoundDataset

        return BoundDataset(
            dataset_id="ds-test", version_id="v-test", dataset_name="CLASS_TRAIN",
            artifact_path=self.csv, artifact_format="csv", row_count=1000,
            target="Class", selected_features=["Amount"],
        )

    def test_unavailable_sandbox_returns_unavailable_not_a_fake_success(self):
        from server.python_execution import PythonRunRequest, run_python_request

        with _clear_sandbox_env(ATLAS_CODE_SANDBOX_COMMAND=""):
            result = run_python_request(PythonRunRequest(userCode="print(1)"))
        self.assertEqual(result["status"], "unavailable")
        self.assertFalse(result["ok"])
        self.assertEqual(result["runtimeState"], "not_configured")

    def test_runtime_objects_are_predefined(self):
        result = self._run(
            "print('OBJ', sorted([n for n in ['df','TARGET','SELECTED_FEATURES','ATLAS_DATASET_PATH'] if n in dir()]))",
            {"previewRows": [{"a": 1}], "target": "a", "selectedFeatures": []},
        )
        self.assertEqual(result["status"], "success", result.get("stderr"))
        self.assertIn("df", result["stdout"])
        self.assertIn("TARGET", result["stdout"])
        self.assertIn("SELECTED_FEATURES", result["stdout"])

    def test_registered_version_binds_the_real_artifact(self):
        with mock.patch(
            "server.python_execution.resolve_bound_dataset", return_value=self._bound_context()
        ):
            result = self._run(
                "print('rows', len(df))\nprint('events', int((df['Class'] == 1).sum()))\nprint('target', TARGET)",
                {"datasetId": "ds-test", "versionId": "v-test", "target": "Class"},
            )
        self.assertEqual(result["status"], "success", result.get("stderr"))
        self.assertIn("rows 1000", result["stdout"])
        self.assertIn(f"events {self.expected_events}", result["stdout"])
        self.assertIn("target Class", result["stdout"])
        self.assertEqual(result["runtimeContract"]["source"], "registered_version")
        self.assertEqual(result["datasetId"], "ds-test")
        self.assertEqual(result["versionId"], "v-test")

    def test_generated_runtime_contains_no_placeholder_path(self):
        from server.code_execution.dataset_binding import build_runtime_prelude

        prelude = build_runtime_prelude(self._bound_context(), self.tmp / "atlas_dataset.csv")
        self.assertNotIn("path/to/", prelude)
        self.assertNotIn("dataset-library-export", prelude)
        # The sandbox receives only a workdir-relative filename, not a server path.
        # Values are embedded as quoted JSON string literals parsed at runtime
        # (see runtime_context.py), so assert the resulting value, not the syntax.
        namespace: dict = {}
        exec(compile("import json\n" + prelude.split("df = ")[0], "<prelude>", "exec"), namespace)  # noqa: S102
        self.assertEqual(namespace["ATLAS_DATASET_PATH"], "atlas_dataset.csv")
        self.assertNotIn("artifacts", str(namespace["ATLAS_DATASET_PATH"]))

    def test_syntax_error_is_reported_with_the_failing_line(self):
        result = self._run("def broken(:\n    pass", {"previewRows": []})
        self.assertEqual(result["status"], "error")
        self.assertNotEqual(result["returnCode"], 0)
        self.assertIn("SyntaxError", result["stderr"])

    def test_timeout_terminates_the_process(self):
        with mock.patch("server.python_execution.TIMEOUT_SECONDS", 2):
            result = self._run("import time\ntime.sleep(30)", {"previewRows": []})
        self.assertEqual(result["status"], "timeout")
        self.assertFalse(result["ok"])
        self.assertIn("timed out", result["stderr"])

    def test_stdout_is_bounded(self):
        with mock.patch("server.python_execution.MAX_STREAM_CHARS", 500):
            result = self._run("print('x' * 5000)", {"previewRows": []})
        self.assertEqual(result["status"], "success", result.get("stderr"))
        self.assertLessEqual(len(result["stdout"]), 500)
        self.assertTrue(result["truncated"])

    def test_working_directory_is_isolated_and_cleaned_up(self):
        result = self._run("import os\nprint('FILES', sorted(os.listdir('.')))", {"previewRows": [{"a": 1}]})
        self.assertEqual(result["status"], "success", result.get("stderr"))
        # Only this run's own script is present -- no server artifact tree.
        self.assertIn("atlas_step_code.py", result["stdout"])
        self.assertNotIn("registry.json", result["stdout"])


class SasIdentityTests(unittest.TestCase):
    """CODE-DATAACQ-003: one authoritative table identity for the active dataset."""

    def setUp(self) -> None:
        self.rows = [{"Class": 1 if i % 50 == 0 else 0, "Amount": i * 1.5, "Time": i} for i in range(200)]

    def _ctx(self, name="CLASS_TRAIN"):
        return {"previewRows": self.rows, "datasetName": name, "datasetId": "ds_class_train"}

    def test_active_table_is_derived_from_the_active_dataset(self):
        self.assertEqual(active_table_identity(self._ctx("CLASS_TRAIN")), "class_train")
        self.assertEqual(active_table_identity(self._ctx("REG_TRAIN")), "reg_train")
        self.assertEqual(active_table_identity({"datasetName": ""}), "atlas_dataset")

    def test_classification_project_never_receives_reg_train(self):
        result = run_sas_compatible("proc contents data=work.CLASS_TRAIN; run;", self._ctx())
        import json

        self.assertNotIn("reg_train", json.dumps(result))
        self.assertEqual(result["activeTable"], "class_train")

    def test_table_reference_is_case_insensitive(self):
        for reference in ["work.CLASS_TRAIN", "work.class_train", "WORK.Class_Train"]:
            result = run_sas_compatible(f"proc contents data={reference}; run;", self._ctx())
            self.assertEqual(result["status"], "completed", f"{reference} should resolve")

    def test_unavailable_table_guidance_names_the_active_table(self):
        result = run_sas_compatible("proc means data=work.reg_train; run;", self._ctx())
        message = result["statementReport"][0]["detail"]
        self.assertIn("work.class_train", message)
        self.assertEqual(result["statementReport"][0]["outcome"], "input_unavailable")

    def test_switching_dataset_switches_the_registered_table(self):
        first = run_sas_compatible("proc contents data=work.CLASS_TRAIN; run;", self._ctx("CLASS_TRAIN"))
        self.assertEqual(first["status"], "completed")
        # The same program against a different active dataset must not still resolve.
        second = run_sas_compatible("proc contents data=work.CLASS_TRAIN; run;", self._ctx("REG_TRAIN"))
        self.assertEqual(second["status"], "failed")
        self.assertEqual(second["activeTable"], "reg_train")


class SasStatusTests(unittest.TestCase):
    """CODE-DATAACQ-004: statement-level report and honest status semantics."""

    def setUp(self) -> None:
        self.ctx = {
            "previewRows": [{"Class": 1 if i % 50 == 0 else 0, "Amount": i * 1.5, "Time": i} for i in range(200)],
            "datasetName": "CLASS_TRAIN",
        }

    def test_fully_supported_program_is_completed_with_return_code_zero(self):
        result = run_sas_compatible(
            "proc contents data=work.CLASS_TRAIN; run;\nproc freq data=work.CLASS_TRAIN; tables Class; run;", self.ctx
        )
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["returnCode"], 0)
        self.assertEqual(result["statementCounts"]["executed"], 2)
        self.assertEqual(result["statementCounts"]["skipped_unsupported"], 0)

    def test_partial_is_not_reported_as_unqualified_success(self):
        result = run_sas_compatible(
            "proc contents data=work.CLASS_TRAIN; run;\nproc logistic data=work.CLASS_TRAIN; model Class=Amount; run;",
            self.ctx,
        )
        self.assertEqual(result["status"], "partial")
        self.assertNotEqual(result["returnCode"], 0, "a partial run must not return code 0")
        self.assertEqual(result["statementCounts"]["executed"], 1)
        self.assertEqual(result["statementCounts"]["skipped_unsupported"], 1)

    def test_no_material_statement_completed_is_failed_not_partial(self):
        result = run_sas_compatible("proc means data=work.does_not_exist; run;", self.ctx)
        self.assertEqual(result["status"], "failed")
        self.assertNotEqual(result["returnCode"], 0)
        self.assertEqual(result["statementCounts"]["executed"], 0)

    def test_every_statement_appears_exactly_once_with_an_outcome(self):
        program = (
            "proc contents data=work.CLASS_TRAIN; run;\n"
            "proc freq data=work.CLASS_TRAIN; tables Class; run;\n"
            "proc logistic data=work.CLASS_TRAIN; run;\n"
            "proc means data=work.missing_table; run;\n"
        )
        result = run_sas_compatible(program, self.ctx)
        outcomes = [row["outcome"] for row in result["statementReport"]]
        self.assertEqual(len(outcomes), 4)
        self.assertEqual(outcomes.count("executed"), 2)
        self.assertEqual(outcomes.count("skipped_unsupported"), 1)
        self.assertEqual(outcomes.count("input_unavailable"), 1)
        for row in result["statementReport"]:
            self.assertIn(row["outcome"], {"executed", "translated", "skipped_unsupported", "failed", "input_unavailable"})
            self.assertNotIn("Unsupported statement detected", row["statement"])

    def test_execution_is_labelled_translated_not_native_sas(self):
        result = run_sas_compatible("proc contents data=work.CLASS_TRAIN; run;", self.ctx)
        self.assertEqual(result["executionKind"], "sas_compatible_translated")
        self.assertIn("not a SASPy session", result["engineNote"])
        self.assertIn("licensed SAS", result["engineNote"])

    def test_empty_program_is_failed(self):
        result = run_sas_compatible("", self.ctx)
        self.assertEqual(result["status"], "failed")
        self.assertNotEqual(result["returnCode"], 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
