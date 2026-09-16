"""Phase 7D.5A (Workstream G) — reusable Windows-reparse-safe path containment.

The prior containment used ``Path.is_symlink()`` to reject reparse points, but on Windows a directory JUNCTION
(``mklink /J``, no admin needed) is NOT a symlink — ``is_symlink()`` returns False for it — so an intermediate or
final junction could evade the explicit reparse rejection. This helper checks the actual reparse attribute
(``FILE_ATTRIBUTE_REPARSE_POINT``) on every EXISTING component between a trusted root and the candidate path,
BEFORE any ``resolve()`` or file open, so junctions (and POSIX symlinks) are rejected at object / evidence /
registry / receipt load boundaries. Containment is by lexical normalization (never ``resolve()``, which would
silently follow a junction), so a reparse point can never redirect an in-root-looking path to elsewhere.
"""
from __future__ import annotations

import os
import stat
from pathlib import Path
from typing import Iterable


class ContainmentError(RuntimeError):
    """A candidate path escaped its trusted root or traversed a reparse point (fail-closed)."""


def is_reparse_point(path: Path | str) -> bool:
    """True if ``path`` itself is a reparse point — a Windows junction OR symlink, or a POSIX symlink. Uses lstat
    so the link/junction is inspected, never its target. A nonexistent path is not a reparse point."""
    try:
        st = os.lstat(str(path))
    except OSError:
        return False
    if os.name == "nt":
        return bool(getattr(st, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT)
    return stat.S_ISLNK(st.st_mode)


def _norm(p: Path | str) -> Path:
    return Path(os.path.normpath(str(Path(p).absolute())))


def contained_no_reparse(candidate: Path | str, roots: Iterable[Path | str]) -> Path:
    """Return the lexically-normalized ``candidate`` iff it is contained under one of ``roots`` AND no existing
    component from that root down to the candidate is a reparse point. Fail-closed otherwise. Does not resolve
    (never follows a junction/symlink) and opens nothing."""
    cand = _norm(candidate)
    root: Path | None = None
    for r in roots:
        rn = _norm(r)
        if cand == rn or rn in cand.parents:
            root = rn
            break
    if root is None:
        raise ContainmentError("path escapes the allowed roots")
    if is_reparse_point(root):
        raise ContainmentError(f"trusted root is itself a reparse point: {root}")
    cur = root
    for part in cand.relative_to(root).parts:
        cur = cur / part
        if is_reparse_point(cur):
            raise ContainmentError(f"reparse point (junction/symlink) rejected in path component: {cur}")
    return cand
