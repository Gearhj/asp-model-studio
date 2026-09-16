"""Safety primitives for Bronze acquisition — hard year boundary, path containment, safe archive extraction,
and credential/secret redaction. Pure stdlib; no ASP imports."""
from __future__ import annotations

import re
import zipfile
from datetime import date
from pathlib import Path

from . import (
    CURRENT_STATCAST_MAX_DATE,
    CURRENT_STATCAST_MIN_DATE,
    MAX_YEAR,
    MIN_YEAR,
    NIGHTLY_CURRENT_STATCAST_MAX_DATE,
)


class BronzeBoundaryError(RuntimeError):
    """A request touched a prohibited year (>=2025) or escaped the staging root."""


_DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")
_YEARMONTH_RE = re.compile(r"^(\d{4})-(\d{2})$")
_SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9._=-]")
# redact obvious secrets/signed-url material from any logged string
_SECRET_PATTERNS = [
    re.compile(r"(?i)(api[_-]?key|token|secret|password|signature|x-amz-signature|awssecret)=([^&\s]+)"),
    re.compile(r"(?i)(authorization:\s*)(\S+)"),
    re.compile(r"([?&](sig|sign|signature|x-goog-signature|se|sr|sp)=)[^&\s]+"),
]


def assert_year_allowed(year: int) -> int:
    year = int(year)
    if year < MIN_YEAR:
        raise BronzeBoundaryError(f"year {year} precedes the acquisition window (min {MIN_YEAR})")
    if year > MAX_YEAR:
        raise BronzeBoundaryError(f"year {year} is prohibited: 2025 is sealed and 2026 is untouched (max {MAX_YEAR})")
    return year


def assert_date_allowed(date_str: str) -> str:
    m = _DATE_RE.match(str(date_str or ""))
    if not m:
        raise BronzeBoundaryError(f"malformed date {date_str!r}; expected YYYY-MM-DD")
    y = int(m.group(1))
    assert_year_allowed(y)
    # additionally forbid the exact ceiling boundary being crossed (and reject impossible calendar dates)
    try:
        parsed = date(y, int(m.group(2)), int(m.group(3)))
    except ValueError as exc:
        raise BronzeBoundaryError(f"malformed calendar date {date_str!r}: {exc}")
    if parsed > date(MAX_YEAR, 12, 31):
        raise BronzeBoundaryError(f"date {date_str} is after {MAX_YEAR}-12-31")
    return date_str


def assert_current_statcast_date_allowed(date_str: str) -> str:
    """Validate the separately authorized, date-bounded 2025-2026 Statcast extension.

    This deliberately does not change ``assert_date_allowed`` or ``assert_year_allowed``: every legacy
    Bronze planner remains sealed at 2024. The current extension is reachable only through its explicit
    date-based planner and cannot move beyond the frozen task cutoff.
    """

    m = _DATE_RE.match(str(date_str or ""))
    if not m:
        raise BronzeBoundaryError(f"malformed date {date_str!r}; expected YYYY-MM-DD")
    try:
        parsed = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError as exc:
        raise BronzeBoundaryError(f"malformed calendar date {date_str!r}: {exc}") from exc
    lower = date.fromisoformat(CURRENT_STATCAST_MIN_DATE)
    upper = date.fromisoformat(CURRENT_STATCAST_MAX_DATE)
    if parsed < lower or parsed > upper:
        raise BronzeBoundaryError(
            f"current Statcast date {date_str} is outside the authorized window "
            f"[{CURRENT_STATCAST_MIN_DATE}, {CURRENT_STATCAST_MAX_DATE}]"
        )
    return date_str


def assert_nightly_current_statcast_date_allowed(date_str: str) -> str:
    """Validate the 2026 nightly continuation without relaxing legacy paths."""

    m = _DATE_RE.match(str(date_str or ""))
    if not m:
        raise BronzeBoundaryError(f"malformed date {date_str!r}; expected YYYY-MM-DD")
    try:
        parsed = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError as exc:
        raise BronzeBoundaryError(f"malformed calendar date {date_str!r}: {exc}") from exc
    lower = date.fromisoformat(CURRENT_STATCAST_MIN_DATE)
    upper = date.fromisoformat(NIGHTLY_CURRENT_STATCAST_MAX_DATE)
    if parsed < lower or parsed > upper:
        raise BronzeBoundaryError(
            f"nightly current Statcast date {date_str} is outside the authorized window "
            f"[{CURRENT_STATCAST_MIN_DATE}, {NIGHTLY_CURRENT_STATCAST_MAX_DATE}]"
        )
    return date_str


def assert_yearmonth_allowed(ym: str) -> str:
    m = _YEARMONTH_RE.match(str(ym or ""))
    if not m:
        raise BronzeBoundaryError(f"malformed year-month {ym!r}; expected YYYY-MM")
    assert_year_allowed(int(m.group(1)))
    return ym


def safe_filename(name: str) -> str:
    """Normalize an arbitrary source name to a safe filename (no traversal, no separators, no absolutes)."""
    base = str(name or "").strip().replace("\\", "/").split("/")[-1]
    cleaned = _SAFE_NAME_RE.sub("_", base).strip("._")
    if not cleaned:
        raise BronzeBoundaryError("empty/invalid filename after normalization")
    if cleaned in (".", ".."):
        raise BronzeBoundaryError("invalid filename")
    return cleaned[:180]


def contained_path(root: Path, *parts: str) -> Path:
    """Resolve root/parts and require it to stay strictly under root (reject traversal / absolute injection)."""
    root = Path(root).resolve()
    for p in parts:
        if p is None or Path(p).is_absolute() or ".." in Path(str(p)).parts:
            raise BronzeBoundaryError(f"path component {p!r} is absolute or contains traversal")
    resolved = root.joinpath(*[str(p) for p in parts]).resolve()
    if root != resolved and root not in resolved.parents:
        raise BronzeBoundaryError("resolved path escapes the staging root")
    return resolved


def redact(text: str) -> str:
    """Remove credentials / signed-url material from a string before it is logged or manifested."""
    out = str(text)
    for pat in _SECRET_PATTERNS:
        out = pat.sub(lambda m: (m.group(1) + "<redacted>") if m.lastindex and m.lastindex >= 1 else "<redacted>", out)
    return out


def safe_extract_zip(zip_path: Path, dest_root: Path) -> list[str]:
    """Extract a zip archive rejecting path traversal, absolute members, and symlink members. Returns the
    list of extracted relative names. Never overwrites outside dest_root."""
    dest_root = Path(dest_root).resolve()
    dest_root.mkdir(parents=True, exist_ok=True)
    extracted: list[str] = []
    with zipfile.ZipFile(zip_path) as zf:
        for info in zf.infolist():
            name = info.filename
            if name.endswith("/"):
                continue
            if Path(name).is_absolute() or name.startswith(("/", "\\")) or ".." in Path(name.replace("\\", "/")).parts:
                raise BronzeBoundaryError(f"unsafe archive member (traversal/absolute): {name!r}")
            # reject symlink members (unix mode high bits 0xA000)
            if (info.external_attr >> 16) & 0o170000 == 0o120000:
                raise BronzeBoundaryError(f"symlink archive member rejected: {name!r}")
            target = contained_path(dest_root, *Path(name.replace("\\", "/")).parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(info) as src, open(target, "wb") as dst:
                dst.write(src.read())
            extracted.append(str(target.relative_to(dest_root)).replace("\\", "/"))
    return extracted
