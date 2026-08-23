"""Phase 7D.5A — deterministic, point-in-time-correct Silver feature transformation authority.

The prior hermetic "safe" feature was target-leaky: it fabricated ``log1p_prior_pa_count`` as
``log1p(random) + 0.001 * outcome_class_index`` — i.e. from the current row's target. This module replaces that
with a GENUINE point-in-time transform whose value for a plate appearance depends only on strictly-earlier plate
appearances for the same batter, never on the current or any future row and never on the ``outcome`` target.

Contract (frozen):
  prior_pa_count(row) = count of PAs for the same batter whose governed chronological key is STRICTLY EARLIER
                        than the current PA (the current PA never counts itself).
  log1p_prior_pa_count = log1p(prior_pa_count).      # no additive/outcome/class/current/future term.

Governed chronological key (deterministic, total order): (game_date, game_id, at_bat_number, plate_appearance_id),
using whichever of these governed columns exist; plate_appearance_id is the stable final tie-breaker so ties in the
earlier components are resolved deterministically. The transform NEVER reads ``outcome`` — the caller must project
only the authorized source columns, and the transform raises if the target column is present.
"""
from __future__ import annotations

import math
from typing import Any, Mapping, Sequence

TRANSFORM_ID = "MLB_SILVER_PRIOR_PA_TRANSFORM_V1"
TARGET_COLUMN = "outcome"
BATTER_KEY = "batter_canonical_player_uuid"
# the ordered chronological key columns, most-significant first; only those present are used, in this order,
# and plate_appearance_id is always appended as the final stable tie-breaker.
_ORDER_COLUMNS = ("game_date", "game_id", "at_bat_number", "plate_appearance_id")
_STABLE_TIEBREAKER = "plate_appearance_id"

PRIOR_PA_COUNT = "prior_pa_count"
LOG1P_PRIOR_PA_COUNT = "log1p_prior_pa_count"
OUTPUT_FEATURES = (PRIOR_PA_COUNT, LOG1P_PRIOR_PA_COUNT)


class SilverTransformError(RuntimeError):
    """A point-in-time transform precondition was violated (fail-closed)."""


def governed_sort_key(columns_present: Sequence[str]) -> list[str]:
    """The deterministic total-order key: the present ordered columns + the stable id tie-breaker (always last)."""
    key = [c for c in _ORDER_COLUMNS if c in columns_present and c != _STABLE_TIEBREAKER]
    if _STABLE_TIEBREAKER not in columns_present:
        raise SilverTransformError(f"stable tie-breaker column '{_STABLE_TIEBREAKER}' is required for a total order")
    key.append(_STABLE_TIEBREAKER)
    return key


def _row_sort_tuple(row: Mapping[str, Any], key_cols: Sequence[str]) -> tuple:
    return tuple(str(row[c]) for c in key_cols)


def compute_prior_pa(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, float]]:
    """Compute the point-in-time features for a list of source rows (each a mapping of the AUTHORIZED source
    columns). Returns, in the SAME order as the input rows, a list of {prior_pa_count, log1p_prior_pa_count}.

    Fail-closed if the target column is present (it must be projected away before calling this), if the batter
    key or the stable id is missing, or if two distinct rows collide on the full governed key (which would make
    the order non-deterministic)."""
    if not rows:
        return []
    present = set(rows[0].keys())
    if TARGET_COLUMN in present:
        raise SilverTransformError("point-in-time transform must not receive the target column 'outcome'")
    if BATTER_KEY not in present:
        raise SilverTransformError(f"source is missing the batter key '{BATTER_KEY}'")
    key_cols = governed_sort_key(sorted(present))

    # tag each row with its original index + governed key, sort by (batter, key), assign strictly-earlier counts
    tagged = []
    seen_keys: dict[tuple, int] = {}
    for i, row in enumerate(rows):
        for c in key_cols + [BATTER_KEY]:
            if c not in row:
                raise SilverTransformError(f"row {i} missing required column '{c}'")
        gkey = _row_sort_tuple(row, key_cols)
        if gkey in seen_keys and str(rows[seen_keys[gkey]][BATTER_KEY]) != str(row[BATTER_KEY]):
            # same full governed key across two different batters is fine; same key for SAME batter is a collision
            pass
        tagged.append((str(row[BATTER_KEY]), gkey, i))

    # detect duplicate (batter, gkey) -> ambiguous order for the SAME player at the SAME point in time
    per_batter_keys: dict[tuple, int] = {}
    for batter, gkey, i in tagged:
        bk = (batter, gkey)
        if bk in per_batter_keys:
            raise SilverTransformError(
                f"non-deterministic order: batter {batter!r} has two PAs with identical governed key {gkey} "
                f"(rows {per_batter_keys[bk]} and {i}); the stable tie-breaker must make every key unique")
        per_batter_keys[bk] = i

    # for each batter, sort its rows by gkey; the strictly-earlier count is the 0-based position in that order
    out: list[dict[str, float]] = [None] * len(rows)  # type: ignore[list-item]
    by_batter: dict[str, list[tuple]] = {}
    for batter, gkey, i in tagged:
        by_batter.setdefault(batter, []).append((gkey, i))
    for batter, items in by_batter.items():
        items.sort(key=lambda t: t[0])
        for position, (gkey, i) in enumerate(items):
            prior = float(position)                     # strictly-earlier PAs for this batter; excludes self
            out[i] = {PRIOR_PA_COUNT: prior, LOG1P_PRIOR_PA_COUNT: float(math.log1p(prior))}
    return out
