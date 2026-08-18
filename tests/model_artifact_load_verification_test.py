"""Regression: load_model_artifact must not deserialize unverified bytes.

Deep security audit finding (untrusted model deserialization). ``joblib.load``
executes the pickle opcodes in the file, so loading a model artifact whose
integrity has not been proven against the registry checksum is an arbitrary
code execution primitive. ``load_model_artifact`` previously called
``joblib.load`` on any path inside the governed artifact root without checking
the registry checksum. If the artifact root were ever tampered with (a future
model-bundle import, a filesystem compromise, or a stale/substituted artifact),
that load would execute attacker-controlled code.

These tests are hermetic: ``ARTIFACT_ROOT`` is patched to a temp directory, and
only a plain picklable object is used (no model training, no sklearn).
"""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from server.model_registry import model_artifacts


class LoadModelArtifactVerificationTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name).resolve()
        self._patch = patch.object(model_artifacts, "ARTIFACT_ROOT", self.root)
        self._patch.start()

    def tearDown(self) -> None:
        self._patch.stop()
        self._tmp.cleanup()

    def _write(self) -> dict:
        return model_artifacts.write_model_artifact(
            "mv_test_verification", {"payload": [1, 2, 3], "kind": "unit-test-object"}
        )

    def test_correct_checksum_loads(self) -> None:
        record = self._write()
        loaded = model_artifacts.load_model_artifact(
            record["path"], expected_checksum=record["checksum"]
        )
        self.assertEqual(loaded, {"payload": [1, 2, 3], "kind": "unit-test-object"})

    def test_wrong_checksum_is_rejected(self) -> None:
        record = self._write()
        with self.assertRaises(ValueError):
            model_artifacts.load_model_artifact(
                record["path"], expected_checksum="0" * 64
            )

    def test_empty_checksum_is_rejected(self) -> None:
        record = self._write()
        with self.assertRaises(ValueError):
            model_artifacts.load_model_artifact(record["path"], expected_checksum="")

    def test_tampered_artifact_is_refused_before_deserialization(self) -> None:
        record = self._write()
        artifact_path = model_artifacts.resolve_model_artifact_path(record["path"])
        # Overwrite the on-disk bytes with a *valid* pickle that would execute if
        # loaded -- but the registry checksum no longer matches, so it must be
        # refused before joblib.load is ever reached.
        artifact_path.write_bytes(b"tampered-not-the-registered-artifact")
        with patch.object(model_artifacts, "joblib") as joblib_mock:
            with self.assertRaises(ValueError):
                model_artifacts.load_model_artifact(
                    record["path"], expected_checksum=record["checksum"]
                )
            joblib_mock.load.assert_not_called()

    def test_checksum_verification_precedes_load(self) -> None:
        # Even with a correct-looking path, a mismatching checksum must stop the
        # load path entirely (no deserialization side effects).
        record = self._write()
        with patch.object(model_artifacts, "joblib") as joblib_mock:
            with self.assertRaises(ValueError):
                model_artifacts.load_model_artifact(
                    record["path"], expected_checksum="deadbeef"
                )
            joblib_mock.load.assert_not_called()


if __name__ == "__main__":
    print(json.dumps({"suite": "model_artifact_load_verification"}))
    unittest.main()
