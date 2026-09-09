"""Focused regression protection for read-only laboratory evidence serving."""
import hashlib
import json
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi import HTTPException

from server.sports_nfl_m1 import laboratory_ui as ui


def test_artifact_reference_rejects_outside_roots_and_changed_bytes():
    with tempfile.TemporaryDirectory(prefix="nfl-lab-links-") as directory:
        root = Path(directory)
        published = root / "published"
        published.mkdir()
        path = published / "result.json"
        raw = b'{"status":"COMPLETE"}'
        path.write_bytes(raw)
        digest = hashlib.sha256(raw).hexdigest()
        with patch.object(ui, "ALLOWED_ROOTS", (published,)):
            assert ui._checked(path, digest)[2] == digest
            path.write_bytes(b'{"status":"REPLACED"}')
            with pytest.raises(ValueError, match="checksum"):
                ui._checked(path, digest)
            with pytest.raises(ValueError, match="outside"):
                ui._checked(published / ".." / "other.json")


def test_incomplete_publication_not_advertised_and_project_permission_required():
    with tempfile.TemporaryDirectory(prefix="nfl-lab-incomplete-") as directory:
        root = Path(directory)
        folders = tuple(root / str(index) for index in range(5))
        folders[1].mkdir()
        (folders[1] / "CURRENT.json").write_text(json.dumps({"status": "RUNNING", "path": str(root / "absent.json"), "sha256": "0" * 64}))
        with patch.object(ui, "LOCAL_OUTPUTS", folders):
            catalog, _ = ui.laboratory_catalog()
        assert not any(group["id"] == "semantic" for group in catalog["groups"])
        assert "Semantic laboratory: publication is not complete." in catalog["warnings"]
    with patch.object(ui, "SharingService") as service:
        service.return_value.check_permission.return_value = {"allowed": False}
        with pytest.raises(HTTPException) as error:
            ui._permission({"userId": "no-project-access", "role": "analyst"})
        assert error.value.status_code == 403
