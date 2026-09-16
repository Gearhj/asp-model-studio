"""Synthetic checks for the exact nested-metadata disclosure risk."""
from pathlib import Path
from unittest.mock import patch

import pytest

from scripts.inspect_mlb_archetype_metadata import inspect_receipt, project_metadata


def test_nested_records_and_references_never_escape_projection():
    synthetic = {
        "schemaVersion": "SYNTHETIC", "createdAtUtc": "2026-09-13T00:00:00Z",
        "parsed2026Dispositions": [{"totalBf": "DO_NOT_EXPOSE", "attribution": ["DO_NOT_EXPOSE"]}],
        "sourceReferences": [{"path": "DO_NOT_FOLLOW"}],
        "qualification": {"rawProtectedOrSealedEvaluationArtifactOpened": False,
                          "nestedUnknown": {"payload": "DO_NOT_EXPOSE"}},
    }
    assert project_metadata(synthetic) == {
        "schemaVersion": "SYNTHETIC", "createdAtUtc": "2026-09-13T00:00:00Z",
        "qualification.rawProtectedOrSealedEvaluationArtifactOpened": False,
    }


@pytest.mark.parametrize("name", ["starter-history", "../starter-history/current.json", "C:/protected/manifest.json"])
def test_unknown_name_denied_before_file_read(name):
    with patch.object(Path, "read_bytes", side_effect=AssertionError("read attempted")):
        with pytest.raises(ValueError, match="ONLY_FIXED_ARCHETYPE_RECEIPTS_ALLOWED"):
            inspect_receipt(name)


def test_selected_leaf_cannot_be_replaced_by_nested_object():
    with pytest.raises(ValueError, match="METADATA_LEAF_MUST_BE_SCALAR"):
        project_metadata({"createdAtUtc": {"unrecognizedPayload": "DO_NOT_EXPOSE"}})


def test_changed_receipt_rejected_before_json_projection():
    with patch.object(Path, "read_bytes", return_value=b'{"parsed2026Dispositions":[]}'):
        with pytest.raises(ValueError, match="FIXED_RECEIPT_BYTES_CHANGED"):
            inspect_receipt("profiles")
