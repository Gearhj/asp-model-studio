"""Writable synthetic roots for tests running under the hermetic launcher.

On Windows, ``TemporaryDirectory`` and pytest's ``tmp_path`` can create an
owner-only directory that a restricted-token test worker cannot subsequently
traverse.  The hermetic launcher already owns an isolated external authority;
normal child directories below that authority inherit the worker-accessible
ACL while remaining disjoint from live and repository state.
"""

from __future__ import annotations

from contextlib import contextmanager
import os
from pathlib import Path
import tempfile
from typing import Iterator
import uuid


HERMETIC_MODE = "HERMETIC_REGRESSION"


def make_test_root(prefix: str, *, scope: str = "test-fixtures") -> Path:
    """Create one isolated writable root without an owner-only temp ACL."""

    if os.environ.get("ATLAS_HERMETIC_MODE") == HERMETIC_MODE:
        hermetic_root = Path(os.environ["ATLAS_HERMETIC_ROOT"]).resolve(strict=True)
        parent = hermetic_root / "authorities" / scope
        parent.mkdir(parents=True, exist_ok=True)
        root = parent / f"{prefix}{uuid.uuid4().hex}"
        root.mkdir(parents=False, exist_ok=False)
        return root.resolve(strict=True)
    return Path(tempfile.mkdtemp(prefix=prefix)).resolve(strict=True)


@contextmanager
def temporary_test_root(
    prefix: str,
    *,
    scope: str = "test-fixtures",
) -> Iterator[Path]:
    """Yield a test root, preserving hermetic children as run evidence."""

    if os.environ.get("ATLAS_HERMETIC_MODE") == HERMETIC_MODE:
        yield make_test_root(prefix, scope=scope)
        return
    with tempfile.TemporaryDirectory(prefix=prefix) as raw_root:
        yield Path(raw_root).resolve(strict=True)
