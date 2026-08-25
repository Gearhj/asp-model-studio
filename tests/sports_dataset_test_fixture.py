from __future__ import annotations

import os
import threading
import unittest
import uuid
from pathlib import Path

from server.sports_datasets.access import approved_package_root
from server.sports_datasets.consumer import SportsDatasetManifestConsumer, ValidatedPackage


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
_LOCK = threading.Lock()
_VALIDATED: ValidatedPackage | None = None
_PACKAGE_ROOT: Path | None = None
_CACHE_PATH: Path | None = None


def golden_corpus_available() -> bool:
    """True iff a USABLE golden model-exchange corpus is actually present. ``ASP_MODEL_EXCHANGE_ROOT`` being merely SET
    is not enough: an isolated / disabled exchange root (e.g. an empty ``model-exchange-disabled`` dir inherited by the
    isolated gate) resolves to no golden package, so these suites must SKIP cleanly rather than error on a strict
    resolve of a nonexistent package. This is a side-effect-free availability probe used by the class skip decorators;
    the exact skip reason is unchanged, so the governed skip policy is preserved."""
    exchange = os.getenv("ASP_MODEL_EXCHANGE_ROOT", "").strip()
    if not exchange:
        return False
    try:
        package_root = approved_package_root(Path(exchange))
    except Exception:
        return False
    try:
        return package_root.is_dir() and any(package_root.iterdir())
    except OSError:
        return False


def golden_package() -> tuple[ValidatedPackage, Path, Path]:
    global _VALIDATED, _PACKAGE_ROOT, _CACHE_PATH
    with _LOCK:
        if _VALIDATED is None:
            exchange = os.getenv("ASP_MODEL_EXCHANGE_ROOT", "").strip()
            if not exchange:
                raise unittest.SkipTest("ASP_MODEL_EXCHANGE_ROOT is required for golden exchange tests")
            scratch = REPOSITORY_ROOT / ".tmp" / f"sports-shared-golden-{uuid.uuid4().hex}"
            scratch.mkdir(parents=True, exist_ok=False)
            _PACKAGE_ROOT = approved_package_root(Path(exchange))
            _CACHE_PATH = scratch / "validation-cache.json"
            _VALIDATED = SportsDatasetManifestConsumer(_PACKAGE_ROOT, cache_path=_CACHE_PATH).validate()
        assert _PACKAGE_ROOT is not None and _CACHE_PATH is not None
        return _VALIDATED, _PACKAGE_ROOT, _CACHE_PATH
