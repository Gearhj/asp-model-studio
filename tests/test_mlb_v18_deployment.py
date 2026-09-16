import hashlib
import io
from pathlib import Path
import tarfile

import pytest

from scripts import build_mlb_v18_deployment as deployment


def test_archive_selection_is_code_only_and_keeps_required_helper_closure(monkeypatch):
    paths = set(deployment.REQUIRED_FILES) | {
        "server/sports_current_statcast/contract.json", "server/data/private.json",
        "server/artifacts/model.json", "server/static/assets.json", "scripts/payload.csv",
    }
    listing = b"\0".join(b"100644 blob " + b"1" * 40 + b"\t" + path.encode() for path in paths)
    monkeypatch.setattr(deployment, "git_bytes", lambda *args: listing)
    selected = deployment.select_committed_files(Path("unused"), "head")
    assert set(deployment.REQUIRED_FILES).issubset(selected)
    assert "server/sports_current_statcast/contract.json" in selected
    assert not any(path in selected for path in (
        "server/data/private.json", "server/artifacts/model.json", "server/static/assets.json", "scripts/payload.csv",
    ))


def test_committed_archive_verifies_blob_bytes_without_extracting_paths(monkeypatch):
    payload = b"print('reviewed bytes')\n"
    blob_id = hashlib.sha1(b"blob " + str(len(payload)).encode() + b"\0" + payload).hexdigest()
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as archive:
        member = tarfile.TarInfo("scripts/entry.py")
        member.size = len(payload)
        archive.addfile(member, io.BytesIO(payload))
    calls = []

    def archive_bytes(*args):
        calls.append(args)
        return buffer.getvalue()

    monkeypatch.setattr(deployment, "git_bytes", archive_bytes)
    assert list(deployment.committed_payloads(Path("unused"), "head", {"scripts/entry.py": blob_id})) == [
        ("scripts/entry.py", payload),
    ]
    assert calls[0][-1] == "scripts/entry.py"
    with pytest.raises(ValueError, match="differ from committed"):
        list(deployment.committed_payloads(Path("unused"), "head", {"scripts/entry.py": "0" * 40}))


def test_existing_release_file_is_preserved_on_mismatch(tmp_path):
    path = tmp_path / "entry.py"
    deployment.write_new_or_verify(path, b"original\n")
    deployment.write_new_or_verify(path, b"original\n")
    with pytest.raises(ValueError, match="immutable deployment file differs"):
        deployment.write_new_or_verify(path, b"different\n")
    assert path.read_bytes() == b"original\n"
