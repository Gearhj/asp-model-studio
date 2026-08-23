"""Phase 7D.5A / 7D.5A.2 — deterministic, point-in-time-correct Silver feature transformation authority.

The prior hermetic "safe" feature was target-leaky; this module replaces it with a GENUINE point-in-time transform
whose value for a plate appearance depends only on strictly-earlier plate appearances for the SAME batter, never on
the current or any future row and never on the ``outcome`` target.

Phase 7D.5A.2 hardens the chronology into an EXPLICIT, TYPED contract (Repair 1):
  * every required chronology column must exist on EVERY row (no "whichever fields happen to exist" fallback);
  * ``at_bat_number`` is a STRICT integer (never bool/str/float/None) and is compared NUMERICALLY (2 before 10);
  * ``game_date`` is parsed+canonicalized to an ISO date; ``game_id`` / the ids are non-empty canonical strings;
  * ``plate_appearance_id`` is GLOBALLY unique within the publication (duplicates across batters fail closed);
  * EVERY row is scanned for the prohibited target / post-event columns (not just the first row);
  * every row season must be in the authorized set (default 2021-2024) — 2019 and sealed 2025/2026 fail closed.

Contract (frozen):
  prior_pa_count(row) = count of PAs for the same batter whose governed chronological key is STRICTLY EARLIER
                        than the current PA (the current PA never counts itself).
  log1p_prior_pa_count = log1p(prior_pa_count).      # no additive/outcome/class/current/future term.

Governed chronological key (deterministic total order, all required): (game_date, game_id, at_bat_number,
plate_appearance_id). ``game_id`` is only accepted as a temporal ordering component when it is itself
chronologically ordered within a (batter, game_date); otherwise the caller must supply the governed
``game_sequence`` authority. ``plate_appearance_id`` is the final stable tie-breaker.
"""
from __future__ import annotations

import datetime as _dt
import math
from typing import Any, Mapping, Sequence

TRANSFORM_ID = "MLB_SILVER_PRIOR_PA_TRANSFORM_V1"
TARGET_COLUMN = "outcome"
BATTER_KEY = "batter_canonical_player_uuid"

# The REQUIRED, TYPED chronology columns — every one must be present on every row (no partial-subset fallback).
GAME_DATE = "game_date"
GAME_ID = "game_id"
AT_BAT_NUMBER = "at_bat_number"
PLATE_APPEARANCE_ID = "plate_appearance_id"
REQUIRED_CHRONOLOGY = (BATTER_KEY, GAME_DATE, GAME_ID, AT_BAT_NUMBER, PLATE_APPEARANCE_ID)
# Optional governed same-day multi-game ordering authority (start-time / game-number); used between game_date and
# at_bat_number when present so lexical game_id order is never mistaken for temporal order.
GAME_SEQUENCE = "game_sequence"
_STABLE_TIEBREAKER = PLATE_APPEARANCE_ID

# Prohibited target / post-event columns — ANY of these on ANY row fails before transformation.
PROHIBITED_COLUMNS = frozenset({
    TARGET_COLUMN, "outcome_class", "outcome_code", "label", "target", "y", "result", "events", "description",
    "post_outcome", "next_pa", "future_pa", "delta_run_expectancy", "woba_value", "babip_value", "launch_speed",
    "launch_angle", "hit_distance", "estimated_woba",
})

# Default authorized source seasons (the Gen-3 research frame is 2021-2024; sealed 2025 / prospective 2026 excluded).
DEFAULT_AUTHORIZED_SEASONS = (2021, 2022, 2023, 2024)
SEALED_SEASONS = (2025, 2026)

PRIOR_PA_COUNT = "prior_pa_count"
LOG1P_PRIOR_PA_COUNT = "log1p_prior_pa_count"
OUTPUT_FEATURES = (PRIOR_PA_COUNT, LOG1P_PRIOR_PA_COUNT)


class SilverTransformError(RuntimeError):
    """A point-in-time transform precondition was violated (fail-closed)."""


def governed_sort_key() -> list[str]:
    """The deterministic total-order key columns, most-significant first. FIXED and complete — never a subset of
    whichever columns happen to exist. game_sequence (when present) orders same-day multiple games."""
    return [GAME_DATE, GAME_SEQUENCE, GAME_ID, AT_BAT_NUMBER, _STABLE_TIEBREAKER]


# --------------------------------------------------------------------------- strict typed field validators
def _canon_id(value: Any, field: str, row_index: int) -> str:
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise SilverTransformError(f"row {row_index}: '{field}' must be a non-empty canonical id, got {type(value).__name__}")
    s = str(value).strip()
    if not s:
        raise SilverTransformError(f"row {row_index}: '{field}' must be a non-empty canonical id")
    return s


def _canon_date(value: Any, row_index: int) -> str:
    if isinstance(value, _dt.datetime):
        return value.date().isoformat()
    if isinstance(value, _dt.date):
        return value.isoformat()
    if not isinstance(value, str) or not value.strip():
        raise SilverTransformError(f"row {row_index}: '{GAME_DATE}' must be a date or ISO date string, got {value!r}")
    try:
        return _dt.date.fromisoformat(value.strip()).isoformat()
    except ValueError:
        raise SilverTransformError(f"row {row_index}: '{GAME_DATE}' is not a valid ISO date: {value!r}")


def _canon_at_bat(value: Any, row_index: int) -> int:
    # STRICT integer: reject bool, string, float, None. Compared numerically so 2 sorts before 10.
    if isinstance(value, bool) or not isinstance(value, int):
        raise SilverTransformError(
            f"row {row_index}: '{AT_BAT_NUMBER}' must be a strict integer (not bool/str/float/None), got "
            f"{type(value).__name__} {value!r}")
    if value < 0:
        raise SilverTransformError(f"row {row_index}: '{AT_BAT_NUMBER}' must be non-negative, got {value}")
    return value


def _canon_seq(value: Any, row_index: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise SilverTransformError(f"row {row_index}: '{GAME_SEQUENCE}' must be a non-negative strict integer, got {value!r}")
    return value


def _typed_key(row: Mapping[str, Any], row_index: int, *, has_sequence: bool) -> tuple:
    """Build the strongly-typed, numerically-comparable governed key for one row. Every component is validated;
    the tuple mixes a canonical date string, an int game_sequence (or the game_id string when no sequence), the
    game_id string, an int at_bat_number, and the id tie-breaker — comparisons are therefore numeric where numeric."""
    date = _canon_date(row[GAME_DATE], row_index)
    gid = _canon_id(row[GAME_ID], GAME_ID, row_index)
    ab = _canon_at_bat(row[AT_BAT_NUMBER], row_index)
    pid = _canon_id(row[PLATE_APPEARANCE_ID], PLATE_APPEARANCE_ID, row_index)
    seq = _canon_seq(row[GAME_SEQUENCE], row_index) if has_sequence else 0
    # when no governed game_sequence is supplied, game_id must NOT be relied on as temporal beyond tie-breaking:
    # we keep it in the key ONLY as a deterministic (non-temporal) discriminator after date, and same (batter,date)
    # spanning multiple distinct games without a sequence is rejected below.
    return (date, seq, gid, ab, pid)


def compute_prior_pa(rows: Sequence[Mapping[str, Any]], *,
                     authorized_seasons: Sequence[int] | None = None,
                     season_of_row=None) -> list[dict[str, float]]:
    """Compute the point-in-time features for a list of AUTHORIZED source rows (each a mapping of the authorized
    source columns). Returns, in the SAME order as the input rows, a list of {prior_pa_count, log1p_prior_pa_count}.

    Fail-closed (Repair 1) if: ANY row carries a prohibited target/post-event column; any required chronology
    column is missing / null / blank / mistyped; at_bat_number is not a strict int; game_date is unparseable;
    plate_appearance_id is not globally unique; a (batter, game_date) spans multiple games with no governed
    game_sequence; or any row's season is outside the authorized set (2019 / sealed 2025-2026 rejected)."""
    if not rows:
        return []
    authorized = tuple(authorized_seasons) if authorized_seasons is not None else DEFAULT_AUTHORIZED_SEASONS
    has_sequence = all(GAME_SEQUENCE in r for r in rows)

    # 1) EVERY row: required columns present, no prohibited column, season authorized.
    for i, row in enumerate(rows):
        prohibited = PROHIBITED_COLUMNS & set(row.keys())
        if prohibited:
            raise SilverTransformError(
                f"row {i}: prohibited target/post-event column(s) present: {sorted(prohibited)} "
                f"(the point-in-time transform must receive only authorized pre-outcome source columns)")
        for c in REQUIRED_CHRONOLOGY:
            if c not in row:
                raise SilverTransformError(f"row {i}: missing required chronology column '{c}'")
            if row[c] is None:
                raise SilverTransformError(f"row {i}: required chronology column '{c}' is null")
        if season_of_row is not None:
            s = season_of_row(row)
            if isinstance(s, bool) or not isinstance(s, int):
                raise SilverTransformError(f"row {i}: season must be a strict integer, got {s!r}")
            if s in SEALED_SEASONS:
                raise SilverTransformError(f"row {i}: SEAL VIOLATION — sealed/prospective season {s} may not be transformed")
            if s not in authorized:
                raise SilverTransformError(
                    f"row {i}: season {s} is not in the authorized source seasons {authorized} (e.g. 2019 is not authorized)")

    # 2) typed keys + GLOBAL plate_appearance_id uniqueness + per-batter same-key collision detection.
    tagged: list[tuple[str, tuple, int]] = []
    seen_pid: dict[str, int] = {}
    for i, row in enumerate(rows):
        batter = _canon_id(row[BATTER_KEY], BATTER_KEY, i)
        key = _typed_key(row, i, has_sequence=has_sequence)
        pid = key[-1]
        if pid in seen_pid:
            raise SilverTransformError(
                f"duplicate plate_appearance_id {pid!r} (rows {seen_pid[pid]} and {i}); "
                f"plate_appearance_id must be globally unique within a publication")
        seen_pid[pid] = i
        tagged.append((batter, key, i))

    # 3) same-day multiple-game guard: without a governed game_sequence, a (batter, game_date) that spans two
    #    DISTINCT game_ids has no reliable temporal order — fail closed rather than trust lexical game_id order.
    if not has_sequence:
        by_bd: dict[tuple, set] = {}
        for batter, key, i in tagged:
            date, _seq, gid, _ab, _pid = key
            by_bd.setdefault((batter, date), set()).add(gid)
        for (batter, date), gids in by_bd.items():
            if len(gids) > 1:
                raise SilverTransformError(
                    f"batter {batter!r} has plate appearances in multiple games on {date} but no governed "
                    f"'{GAME_SEQUENCE}' ordering authority; lexical game_id order is not temporal — supply game_sequence")

    # 4) per-batter same-key collision (identical governed key for the SAME batter -> ambiguous order).
    per_batter: dict[tuple, int] = {}
    for batter, key, i in tagged:
        bk = (batter, key)
        if bk in per_batter:
            raise SilverTransformError(
                f"non-deterministic order: batter {batter!r} has two PAs with identical governed key {key} "
                f"(rows {per_batter[bk]} and {i})")
        per_batter[bk] = i

    # 5) for each batter, sort by the typed key; the strictly-earlier count is the 0-based position (excludes self).
    out: list[dict[str, float]] = [None] * len(rows)  # type: ignore[list-item]
    by_batter: dict[str, list[tuple]] = {}
    for batter, key, i in tagged:
        by_batter.setdefault(batter, []).append((key, i))
    for batter, items in by_batter.items():
        items.sort(key=lambda t: t[0])          # numeric where numeric (at_bat 2 < 10), stable id tie-breaker
        for position, (key, i) in enumerate(items):
            prior = float(position)
            out[i] = {PRIOR_PA_COUNT: prior, LOG1P_PRIOR_PA_COUNT: float(math.log1p(prior))}
    return out
