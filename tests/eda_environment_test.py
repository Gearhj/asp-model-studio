"""EDA usability, environment inventory, and mixed stdout/error reporting.

Covers EDA-UX-002/004 (frontend contract), PYENV-001 (honest package
inventory), and PYTHON-TEST-001 / Part J (valid stdout must never imply success).
"""
from __future__ import annotations

import importlib.metadata as metadata
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from server.code_execution.environment_inventory import (  # noqa: E402
    APPROVED,
    EXPECTED_PACKAGES,
    NOT_INSTALLED,
    build_environment_inventory,
)
from server.python_execution import _describe_failure  # noqa: E402


class EnvironmentInventoryTests(unittest.TestCase):
    """PYENV-001: never claim a package is installed without checking."""

    def setUp(self) -> None:
        self.inventory = build_environment_inventory()

    def test_reports_the_live_interpreter_version(self):
        self.assertEqual(self.inventory["pythonVersion"], ".".join(str(part) for part in sys.version_info[:3]))
        self.assertTrue(self.inventory["environmentId"].startswith("env-"))

    def test_versions_match_the_actually_installed_distributions(self):
        checked = 0
        for package in self.inventory["packages"]:
            if not package["installed"]:
                continue
            try:
                actual = metadata.version(package["name"])
            except metadata.PackageNotFoundError:
                continue
            self.assertEqual(package["version"], actual, f"reported version differs for {package['name']}")
            checked += 1
        self.assertGreater(checked, 5, "expected to verify several real package versions")

    def test_absent_packages_are_reported_not_installed_rather_than_claimed(self):
        for package in self.inventory["packages"]:
            if package["status"] != NOT_INSTALLED:
                continue
            with self.assertRaises(metadata.PackageNotFoundError, msg=f"{package['name']} is actually installed"):
                metadata.version(package["name"])
            self.assertFalse(package["installed"])
            self.assertEqual(package["version"], "")

    def test_a_missing_package_is_never_marked_approved(self):
        with mock.patch(
            "server.code_execution.environment_inventory._installed_distributions", return_value={}
        ):
            inventory = build_environment_inventory()
        expected_names = {name for names in EXPECTED_PACKAGES.values() for name in names}
        for package in inventory["packages"]:
            if package["name"] in expected_names:
                self.assertEqual(package["status"], NOT_INSTALLED)
                self.assertNotEqual(package["status"], APPROVED)
        self.assertEqual(inventory["installedCount"], 0)

    def test_no_filesystem_paths_or_secrets_are_exposed(self):
        serialized = str(self.inventory)
        for leak in (str(ROOT), sys.executable, os.sep + "Users", "site-packages", "PASSWORD", "SECRET"):
            self.assertNotIn(leak, serialized, f"inventory leaked: {leak}")

    def test_core_analytical_packages_are_present_in_this_environment(self):
        by_name = {package["name"]: package for package in self.inventory["packages"]}
        for name in ("pandas", "numpy", "duckdb", "pyarrow"):
            self.assertTrue(by_name[name]["installed"], f"{name} should be installed in the governed environment")

    def test_installation_policy_denies_user_code_installation(self):
        policy = self.inventory["installationPolicy"]
        self.assertIn("administrator", policy)
        self.assertIn("cannot install", policy)


class FailureReportingTests(unittest.TestCase):
    """Part J: valid stdout must never imply success."""

    ASSERTION_TRACEBACK = (
        "Traceback (most recent call last):\n"
        '  File "C:\\tmp\\atlas_step_code.py", line 19, in <module>\n'
        "    assert abs(event_rate - 0.0021067178) < 1e-8\n"
        "           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^\n"
        "AssertionError: constant mismatch\n"
    )

    def test_assertion_failure_is_described_honestly(self):
        failure = _describe_failure(self.ASSERTION_TRACEBACK)
        self.assertEqual(failure["exceptionType"], "AssertionError")
        self.assertEqual(failure["exceptionMessage"], "constant mismatch")
        self.assertEqual(failure["failedLineNumber"], 19)
        self.assertIn("assert abs(event_rate", failure["failedSource"])
        # The explanation is derived from the exception type, not hard-coded to
        # any particular program.
        self.assertIn("assertion did not hold", failure["explanation"])
        self.assertNotIn("event_rate", failure["explanation"])
        self.assertNotIn("170884", failure["explanation"])

    def test_other_exception_types_are_reported_without_an_assertion_explanation(self):
        failure = _describe_failure(
            'Traceback (most recent call last):\n  File "x.py", line 4, in <module>\n    df["nope"]\nKeyError: \'nope\'\n'
        )
        self.assertEqual(failure["exceptionType"], "KeyError")
        self.assertEqual(failure["failedLineNumber"], 4)
        self.assertEqual(failure["explanation"], "", "only AssertionError gets the assertion explanation")

    def test_empty_stderr_produces_no_failure_description(self):
        self.assertIsNone(_describe_failure(""))
        self.assertIsNone(_describe_failure("   \n  "))


class MixedOutputTests(unittest.TestCase):
    """A program that prints results and then fails is not a success."""

    def _run(self, code: str):
        from server.python_execution import PythonRunRequest, run_python_request

        with mock.patch.dict(os.environ, {"ATLAS_CODE_SANDBOX_COMMAND": "default", "ATLAS_HOSTED_MODE": ""}):
            return run_python_request(
                PythonRunRequest(userCode=code, context={"previewRows": [{"a": 1}]})
            )

    def test_output_then_assertion_failure_is_labelled_failed_after_output(self):
        result = self._run('print("computed:", 1/3)\nassert 1 == 2, "mismatch"')
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["outcome"], "failed_after_output")
        self.assertEqual(result["failurePhase"], "user_code")
        self.assertNotEqual(result["returnCode"], 0)
        self.assertIn("computed:", result["stdout"], "output produced before failure must be preserved")
        self.assertEqual(result["failure"]["exceptionType"], "AssertionError")
        self.assertFalse(result["ok"], "valid stdout must never imply success")

    def test_failure_with_no_output_is_labelled_failed(self):
        result = self._run('raise ValueError("boom")')
        self.assertEqual(result["outcome"], "failed")
        self.assertEqual(result["failure"]["exceptionType"], "ValueError")

    def test_successful_run_reports_completed_with_no_failure(self):
        result = self._run('print("fine")')
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["outcome"], "completed")
        self.assertIsNone(result["failure"])
        self.assertIsNone(result["failurePhase"])


class AuthoritativeEventRateTests(unittest.TestCase):
    """PART A: preserve the authoritative rate; never bend data to a bad constant."""

    def test_authoritative_event_rate_uses_exact_counts(self):
        event_rate = 360 / 170_884
        self.assertLess(abs(event_rate - (360 / 170_884)), 1e-12)
        # The previously-used constant is provably imprecise beyond 1e-8.
        self.assertGreater(abs(event_rate - 0.0021067178), 1e-8)
        self.assertAlmostEqual(event_rate, 0.002106692259, places=12)


if __name__ == "__main__":
    unittest.main(verbosity=2)
