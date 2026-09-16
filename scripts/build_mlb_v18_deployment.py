"""Materialize a reviewed HEAD's small code/config snapshot without deleting files."""
from __future__ import annotations

import argparse
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import subprocess
import tarfile


EXTENSIONS = frozenset({".py", ".json", ".ps1", ".toml", ".yaml", ".yml"})
SOURCE_DIRECTORIES = ("scripts", "server")
EXCLUDED_DIRECTORIES = ("server/data/", "server/artifacts/", "server/static/")
SUPPORT_FILES = (
    "tools/__init__.py", "tools/bronze_acquisition/__init__.py",
    "tools/bronze_acquisition/sources.py", "tools/bronze_acquisition/safety.py",
)
REQUIRED_FILES = (
    "scripts/run_mlb_v18_unattended.py", "scripts/invoke_mlb_v18_unattended.ps1",
    "server/sports_current_statcast/mlb_v18_unattended.py",
    "tools/bronze_acquisition/__init__.py", "tools/bronze_acquisition/sources.py",
    "tools/bronze_acquisition/safety.py",
)


def git_bytes(repository: Path, *args: str) -> bytes:
    return subprocess.run(["git", "--literal-pathspecs", "-C", str(repository), *args],
                          check=True, capture_output=True).stdout


def select_committed_files(repository: Path, commit: str) -> dict[str, str]:
    entries = git_bytes(repository, "ls-tree", "-r", "-z", commit, "--",
                        *SOURCE_DIRECTORIES, *SUPPORT_FILES)
    selected = {}
    for entry in entries.split(b"\0"):
        if not entry:
            continue
        metadata, raw_path = entry.split(b"\t", 1)
        mode, kind, blob_id = metadata.decode("ascii").split()
        path = raw_path.decode("utf-8")
        relative = PurePosixPath(path)
        if (relative.suffix.lower() not in EXTENSIONS or path.startswith(EXCLUDED_DIRECTORIES)
                or "__pycache__" in relative.parts):
            continue
        if relative.is_absolute() or ".." in relative.parts or "\\" in path:
            raise ValueError(f"Unsafe committed path: {path}")
        if mode not in {"100644", "100755"} or kind != "blob":
            raise ValueError(f"Deployment input must be a regular Git blob: {path}")
        selected[path] = blob_id
    missing = set(REQUIRED_FILES) - selected.keys()
    if missing:
        raise ValueError("Commit the complete dispatcher before building: " + ", ".join(sorted(missing)))
    return dict(sorted(selected.items()))


def committed_payloads(repository: Path, commit: str, selected: dict[str, str]):
    """Archive only selected paths, batching beneath Windows' command-line limit."""
    batches, batch, size = [], [], 0
    for path in selected:
        if batch and size + len(path) + 3 > 12_000:
            batches.append(batch)
            batch, size = [], 0
        batch.append(path)
        size += len(path) + 3
    if batch:
        batches.append(batch)
    seen = set()
    total_bytes = 0
    for batch in batches:
        archive = git_bytes(repository, "archive", "--format=tar", commit, *batch)
        with tarfile.open(fileobj=io.BytesIO(archive), mode="r:") as bundle:
            for member in bundle:
                if member.isdir():
                    continue
                if not member.isfile() or member.name not in batch or member.name in seen:
                    raise ValueError("Git archive returned an unexpected or duplicate deployment member")
                if member.size > 20_000_000:
                    raise ValueError(f"Deployment file exceeds code/config size bound: {member.name}")
                total_bytes += member.size
                if total_bytes > 100_000_000:
                    raise ValueError("Deployment exceeds 100MB code/config bound")
                payload = bundle.extractfile(member).read()
                blob = b"blob " + str(len(payload)).encode("ascii") + b"\0" + payload
                algorithm = "sha1" if len(selected[member.name]) == 40 else "sha256"
                if hashlib.new(algorithm, blob).hexdigest() != selected[member.name]:
                    # Windows archive conversion can apply core.autocrlf. Read
                    # that exact committed blob directly instead; never rewrite
                    # source bytes or accept a checkout-converted hash.
                    payload = git_bytes(repository, "show", commit + ":" + member.name)
                    blob = b"blob " + str(len(payload)).encode("ascii") + b"\0" + payload
                    if hashlib.new(algorithm, blob).hexdigest() != selected[member.name]:
                        raise ValueError(f"Archive/raw bytes differ from committed Git blob: {member.name}")
                seen.add(member.name)
                yield member.name, payload
    if seen != selected.keys():
        raise ValueError("Git archive omitted committed deployment files")


def is_link(path: Path) -> bool:
    return path.is_symlink() or path.is_junction()


def plain_directory(path: Path, repository: Path):
    relative = path.relative_to(repository)
    current = repository
    for part in relative.parts:
        current = current / part
        if is_link(current):
            raise ValueError(f"Refusing to write through a deployment directory link: {current}")
        current.mkdir(exist_ok=True)
        if not current.is_dir():
            raise ValueError(f"Expected a deployment directory: {current}")


def write_new_or_verify(path: Path, payload: bytes):
    if is_link(path):
        raise ValueError(f"Refusing to write through a deployment file link: {path}")
    try:
        with path.open("xb") as output:
            output.write(payload)
    except FileExistsError:
        if hashlib.sha256(path.read_bytes()).digest() != hashlib.sha256(payload).digest():
            raise ValueError(f"Existing immutable deployment file differs: {path}") from None


def ensure_junction(link: Path, target: Path):
    if link.exists() or is_link(link):
        if not link.is_junction() or link.resolve(strict=True) != target.resolve(strict=True):
            raise ValueError(f"Existing deployment junction has the wrong target: {link}")
        return
    # Use PowerShell single-quoted literals, including escaping literal apostrophes.
    powershell = Path("C:/Windows/System32/WindowsPowerShell/v1.0/powershell.exe")
    quote = lambda value: "'" + str(value).replace("'", "''") + "'"
    command = (f"New-Item -ItemType Junction -Path {quote(link)} -Target {quote(target)} "
               "-ErrorAction Stop | Out-Null")
    subprocess.run([str(powershell), "-NoLogo", "-NoProfile", "-NonInteractive", "-WindowStyle", "Hidden",
                    "-Command", command], check=True, capture_output=True)
    if not link.is_junction() or link.resolve(strict=True) != target.resolve(strict=True):
        raise ValueError(f"Windows did not create the intended deployment junction: {link}")


def build(repository: Path, *, plan_only: bool = False) -> dict:
    repository = repository.resolve(strict=True)
    commit = git_bytes(repository, "rev-parse", "--verify", "HEAD^{commit}").decode().strip()
    selected = select_committed_files(repository, commit)
    code_root = repository / ".deployments" / "mlb-v18-unattended" / commit
    ancestor = repository
    for part in code_root.relative_to(repository).parts:
        ancestor /= part
        if is_link(ancestor):
            raise ValueError(f"Deployment root must not traverse links: {ancestor}")
    shared = {name: repository / name for name in ("outputs", ".runtime")}
    for target in shared.values():
        if not target.is_dir():
            raise ValueError(f"Expected existing shared evidence directory: {target}")
    if code_root.exists():
        # Check only ordinary code directories, never recurse through the shared junctions.
        actual = set()
        for directory in ("scripts", "server", "tools"):
            root = code_root / directory
            if root.exists():
                if is_link(root):
                    raise ValueError(f"Code directory must not be linked: {root}")
                for path in root.rglob("*"):
                    if is_link(path):
                        raise ValueError(f"Code/config input must not be linked: {path}")
                    if path.is_file() and path.suffix.lower() in EXTENSIONS:
                        actual.add(path.relative_to(code_root).as_posix())
        if actual - selected.keys():
            raise ValueError("Existing deployment contains unexpected code/config files")
    hashes = []
    for relative, payload in committed_payloads(repository, commit, selected):
        path = code_root / relative
        if plan_only:
            if path.exists() and (is_link(path) or hashlib.sha256(path.read_bytes()).digest() != hashlib.sha256(payload).digest()):
                raise ValueError(f"Existing immutable deployment file differs: {path}")
        else:
            plain_directory(path.parent, repository)
            write_new_or_verify(path, payload)
        hashes.append({"path": relative, "sha256": hashlib.sha256(payload).hexdigest(), "bytes": len(payload)})
    receipt = {"schema_version": 1, "commit": commit, "repository_root": str(repository),
               "code_root": str(code_root), "extensions": sorted(EXTENSIONS),
               "files": sorted(hashes, key=lambda row: row["path"]),
               "junctions": {name: str(target) for name, target in shared.items()}}
    receipt_payload = (json.dumps(receipt, indent=2, sort_keys=True) + "\n").encode("utf-8")
    receipt_path = code_root / "deployment-build.json"
    if plan_only and receipt_path.exists() and (is_link(receipt_path) or receipt_path.read_bytes() != receipt_payload):
        raise ValueError("Existing immutable deployment build receipt differs")
    if plan_only:
        for name, target in shared.items():
            link = code_root / name
            if (link.exists() or is_link(link)) and (not link.is_junction() or link.resolve(strict=True) != target.resolve(strict=True)):
                raise ValueError(f"Existing deployment junction has the wrong target: {link}")
    if not plan_only:
        for name, target in shared.items():
            ensure_junction(code_root / name, target)
        write_new_or_verify(receipt_path, receipt_payload)
    return {"status": "PLAN_ONLY_NO_WRITES" if plan_only else "DEPLOYMENT_BUILT_OR_IDENTICALLY_REUSED",
            "commit": commit, "code_root": str(code_root), "file_count": len(hashes),
            "total_bytes": sum(row["bytes"] for row in hashes), "deleted_files": 0,
            "junctions": receipt["junctions"], "task_registered": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--plan-only", action="store_true")
    args = parser.parse_args()
    print(json.dumps(build(args.repository_root, plan_only=args.plan_only), indent=2))


if __name__ == "__main__":
    main()
