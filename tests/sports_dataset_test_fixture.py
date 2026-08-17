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
