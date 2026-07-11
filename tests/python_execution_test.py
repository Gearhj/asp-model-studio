import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

os.environ["ATLAS_ENABLE_PYTHON_RUN"] = "1"
os.environ["ATLAS_PYTHON_RUNTIME_DIR"] = str(ROOT / ".tmp" / "python-execution")
os.environ.pop("ATLAS_HOSTED_MODE", None)
os.environ.pop("ATLAS_CODE_SANDBOX_COMMAND", None)

from server.python_execution import PythonRunRequest, run_python_request  # noqa: E402


class PythonExecutionTests(unittest.TestCase):
    def test_python_execution_requires_sandbox(self) -> None:
        result = run_python_request(
            PythonRunRequest(
                page="Smoke",
                workflowStep="test",
                userCode='print("ATLAS Python integration smoke test passed.")',
            )
        )
        self.assertFalse(result["ok"], result)
        self.assertEqual(result["status"], "unavailable")
        self.assertIn("ATLAS_CODE_SANDBOX_COMMAND", result["stderr"])
        self.assertIsInstance(result["runtimeMs"], int)

    def test_python_exception_is_not_executed_without_sandbox(self) -> None:
        result = run_python_request(
            PythonRunRequest(
                page="Smoke",
                workflowStep="test",
                userCode='raise ValueError("structured boom")',
            )
        )
        self.assertFalse(result["ok"], result)
        self.assertEqual(result["status"], "unavailable")
        self.assertNotIn("structured boom", result["stderr"])

    def test_user_edited_python_is_preserved_after_execution(self) -> None:
        source = (ROOT / "src/components/StepPythonPanel.tsx").read_text(encoding="utf-8")
        self.assertIn("Run User Python", source)
        self.assertNotIn("Run Full Page Python", source)
        self.assertNotIn("Run Generated Python", source)
        self.assertIn("persistDraftIfNeeded()", source)
        self.assertNotIn("setDraftCode(result", source)

    def test_notebook_export_includes_user_edited_python(self) -> None:
        source = (ROOT / "src/lib/notebookExport.ts").read_text(encoding="utf-8")
        self.assertIn("USER_STEP_PYTHON_CODE_KEY", source)
        self.assertIn("userCodeByStep[section.sectionKey]", source)
        self.assertIn("User-Edited Python Code", source)


if __name__ == "__main__":
    unittest.main(verbosity=2)
