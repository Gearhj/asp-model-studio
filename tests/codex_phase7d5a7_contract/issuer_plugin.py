"""Read-only pytest guard for the runner-seeded synthetic issuer authority.

The plugin validates bytes and addresses only.  It never patches or intercepts
production and therefore cannot turn a red production behavior green.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any


_COMMITTED = Path(__file__).resolve().with_name("canonical_synthetic_issuer_registry.json")
_INITIAL_SEED_SHA: str | None = None


def _canonical_sha(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _file_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def pytest_configure(config: Any) -> None:
    del config
    global _INITIAL_SEED_SHA
    configured = os.environ.get("CODEX_PHASE7D5A7_ISSUER_REGISTRY", "").strip()
    if not configured:
        raise RuntimeError("CODEX_PHASE7D5A7_ISSUER_REGISTRY must name the runner-owned issuer fixture")
    seed = Path(configured).resolve()
    committed = json.loads(_COMMITTED.read_text(encoding="utf-8"))
    actual = json.loads(seed.read_text(encoding="utf-8"))
    if actual != committed:
        raise RuntimeError("runner-owned issuer fixture differs from the committed acceptance authority")
    if actual.get("registrySha256") != _canonical_sha(
        {key: value for key, value in actual.items() if key != "registrySha256"}
    ):
        raise RuntimeError("runner-owned issuer fixture is not canonically self-addressed")
    _INITIAL_SEED_SHA = _file_sha(seed)


def pytest_sessionfinish(session: Any, exitstatus: int) -> None:
    del session, exitstatus
    configured = os.environ.get("CODEX_PHASE7D5A7_ISSUER_REGISTRY", "").strip()
    if not configured or _INITIAL_SEED_SHA is None:
        raise RuntimeError("issuer fixture guard was not initialized")
    if _file_sha(Path(configured).resolve()) != _INITIAL_SEED_SHA:
        raise RuntimeError("runner-owned issuer fixture changed during the test session")
