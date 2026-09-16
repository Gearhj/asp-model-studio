"""Local discrete NBA margin transport; original point and residual code unchanged.

The caller supplies matched, strictly earlier Development calibration counts.
This module does not load games, outcomes, models, or source data. Its population
order is canonical HOME/AWAY cell plus replica order, not original draw order.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any

import numpy as np


CONFIGURATION = "NBA_GEN1_CLOSE_MARGIN_PARITY_TRANSPORT_R8_V1"
RADIUS = 8
MIN_CALIBRATION_GAMES = 200
MIN_OBSERVED_PER_PARITY = 20
MASTER_SEED = 20260914


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _canonical_bytes(value: dict[str, Any]) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def _count_vector(values: Any, name: str) -> np.ndarray:
    result = np.asarray(values)
    _require(result.shape == (RADIUS,), f"{name} must have one count for each absolute margin1..8")
    _require(np.issubdtype(result.dtype, np.integer), f"{name} must contain integer counts")
    _require((result >= 0).all(), f"{name} contains negative counts")
    _require(all(int(x) <= np.iinfo(np.int64).max for x in result), f"{name} exceeds integer storage")
    return result.astype(np.int64)


def _cdf(probabilities: np.ndarray) -> np.ndarray:
    result = np.cumsum(probabilities, dtype=float)
    result[-1] = 1.0  # Floating summation reconciliation, not additional mass.
    return result


def fit_kernel(source_counts: Any, observed_counts: Any, calibration_games: int) -> dict[str, Any]:
    """Fit one empirical conditional CDF coupling, with no pseudocounts.

    Both length8 vectors use absolute margins1..8 on the SAME intact calibration
    games. Source counts are full simulated cell counts; observed counts count
    games. Every source game must have the same original draw count. The caller
    enforces source identities, this shared denominator, and strict chronology.
    """
    source = _count_vector(source_counts, "source_counts")
    observed = _count_vector(observed_counts, "observed_counts")
    _require(isinstance(calibration_games, (int, np.integer)) and not isinstance(calibration_games, bool),
             "calibration_games must be an integer")
    games = int(calibration_games)
    _require(games >= 0 and sum(int(x) for x in observed) <= games, "Observed close counts exceed whole calibration games")
    reasons = []
    if games < MIN_CALIBRATION_GAMES:
        reasons.append("FEWER_THAN_200_EARLIER_DEVELOPMENT_GAMES")
    transition = np.eye(RADIUS, dtype=float)
    groups = {}
    unsupported_bins = []
    for parity, margins in (("odd", (1, 3, 5, 7)), ("even", (2, 4, 6, 8))):
        indices = np.array(margins) - 1
        s, o = source[indices], observed[indices]
        s_total, o_total = sum(int(x) for x in s), sum(int(x) for x in o)
        if o_total < MIN_OBSERVED_PER_PARITY:
            reasons.append(f"FEWER_THAN_20_OBSERVED_CLOSE_FINISHES_{parity.upper()}")
        if s_total == 0:
            reasons.append(f"NO_SOURCE_CLOSE_MASS_{parity.upper()}")
        p = s.astype(float) / s_total if s_total else None
        q = o.astype(float) / o_total if o_total else None
        pcdf, qcdf = (_cdf(p) if p is not None else None), (_cdf(q) if q is not None else None)
        if p is not None and q is not None:
            p_low, q_low = np.r_[0.0, pcdf[:-1]], np.r_[0.0, qcdf[:-1]]
            for position, index in enumerate(indices):
                if s[position] == 0:
                    unsupported_bins.append(int(index + 1))
                    continue  # A future unseen source bin uses exact identity.
                overlap = np.maximum(0.0, np.minimum(pcdf[position], qcdf) - np.maximum(p_low[position], q_low))
                row = overlap / p[position]
                _require(row.sum() > 0, "Conditional transport row lost all mass")
                row /= row.sum()  # Reconcile only floating division roundoff.
                transition[index] = 0.0
                transition[index, indices] = row
        groups[parity] = {
            "absoluteMargins": list(margins), "sourceCloseDraws": s_total,
            "observedCloseGames": o_total,
            "sourceConditionalProbabilities": None if p is None else p.tolist(),
            "targetConditionalProbabilities": None if q is None else q.tolist(),
            "sourceCdf": None if pcdf is None else pcdf.tolist(),
            "targetCdf": None if qcdf is None else qcdf.tolist(),
        }
    ready = not reasons
    # No partial correction when a calibration prerequisite is unavailable.
    if not ready:
        transition = np.eye(RADIUS, dtype=float)
    result = {
        "schema": "NBA_GEN1_CLOSE_SCORE_KERNEL_V1", "configuration": CONFIGURATION,
        "radius": RADIUS, "minimumCalibrationGames": MIN_CALIBRATION_GAMES,
        "minimumObservedCloseGamesPerParity": MIN_OBSERVED_PER_PARITY,
        "calibrationGames": games, "sourceCounts": source.tolist(), "observedCounts": observed.tolist(),
        "ready": ready, "disposition": "SUPPORTED_EMPIRICAL_TRANSPORT" if ready else "EXACT_BASELINE_FALLBACK",
        "reasons": reasons, "pseudocounts": 0, "parities": groups,
        "unsupportedSourceAbsoluteMargins": unsupported_bins,
        "transitionProbabilities": transition.tolist(),
        "chronologyResponsibility": "Caller: matched earlier Development games only; exclude target and same/later dates. Freeze post2023 kernels using Development only.",
        "scopeSelectionQualification": "Radius8 was selected from already inspected Development CDFs; chronological kernel fitting does not make Development an untouched assessment.",
    }
    result["kernelSha256"] = hashlib.sha256(_canonical_bytes(result)).hexdigest()
    return result


def _validate_draws(draws: Any) -> np.ndarray:
    array = np.asarray(draws)
    _require(array.ndim == 2 and array.shape[1] == 2 and len(array) > 0, "Nonempty HOME/AWAY draw pairs required")
    _require(np.issubdtype(array.dtype, np.integer), "Original integer scores required")
    _require((array >= 0).all() and (array[:, 0] != array[:, 1]).all(), "Original scores must be nonnegative and untied")
    _require(all(int(x) <= np.iinfo(np.int64).max // 2 for x in array.max(axis=0)), "Score sum exceeds supported int64 representation")
    return array.astype(np.int64, copy=False)


def canonical_population(draws: Any) -> np.ndarray:
    """Canonical cell/replica order; preserve the full original score multiset."""
    array = _validate_draws(draws)
    return array[np.lexsort((array[:, 1], array[:, 0]))].copy()


def seed(game_id: str) -> int:
    _require(isinstance(game_id, str) and bool(game_id.strip()), "Stable game identity required")
    token = f"{CONFIGURATION}|{MASTER_SEED}|{game_id}|canonical-cell-replica-transport".encode("utf-8")
    return int.from_bytes(hashlib.sha256(token).digest()[:8], "big")


def _validate_kernel(kernel: dict[str, Any]) -> np.ndarray:
    _require(isinstance(kernel, dict) and kernel.get("configuration") == CONFIGURATION, "Different support configuration")
    body = {key: value for key, value in kernel.items() if key != "kernelSha256"}
    _require(hashlib.sha256(_canonical_bytes(body)).hexdigest() == kernel.get("kernelSha256"), "Kernel identity mismatch")
    matrix = np.asarray(kernel["transitionProbabilities"], dtype=float)
    _require(matrix.shape == (RADIUS, RADIUS) and np.isfinite(matrix).all() and (matrix >= 0).all(), "Invalid transition matrix")
    _require(np.allclose(matrix.sum(axis=1), 1.0, rtol=0, atol=1e-12), "Transport row mass differs from1")
    _require(all(matrix[i, j] == 0 for i in range(RADIUS) for j in range(RADIUS) if (i - j) % 2), "Transport changes total parity")
    return matrix


def _apply_with_uniforms(draws: Any, kernel: dict[str, Any], uniforms: Any) -> tuple[np.ndarray, dict[str, Any]]:
    """Shared-uniform test seam: swaps HOME/AWAY without changing magnitudes."""
    original = _validate_draws(draws)
    matrix = _validate_kernel(kernel)
    randoms = np.asarray(uniforms, dtype=float)
    _require(randoms.shape == (len(original),) and np.isfinite(randoms).all()
             and (randoms >= 0).all() and (randoms < 1).all(), "One [0,1) uniform per canonical replica required")
    changed = original.copy()
    margin = original[:, 0] - original[:, 1]
    magnitude, total = np.abs(margin), original.sum(axis=1)
    close = magnitude <= RADIUS
    unsupported = np.isin(magnitude, kernel["unsupportedSourceAbsoluteMargins"]) & close
    support_fallback = np.zeros(len(original), dtype=bool)
    if kernel["ready"]:
        for source_margin in range(1, RADIUS + 1):
            positions = np.flatnonzero(magnitude == source_margin)
            if not len(positions):
                continue
            proposed = np.searchsorted(_cdf(matrix[source_margin - 1]), randoms[positions], side="right") + 1
            invalid = proposed > total[positions]
            support_fallback[positions[invalid]] = True
            valid_positions, proposed = positions[~invalid], proposed[~invalid]
            signed = np.sign(margin[valid_positions]) * proposed
            changed[valid_positions, 0] = (total[valid_positions] + signed) // 2
            changed[valid_positions, 1] = (total[valid_positions] - signed) // 2
    final_margin = changed[:, 0] - changed[:, 1]
    _require(np.array_equal(changed.sum(axis=1), total), "Transport changed a draw total")
    _require(np.array_equal(np.sign(final_margin), np.sign(margin)), "Transport changed a draw winner")
    _require((changed >= 0).all() and (final_margin != 0).all(), "Transport violated final-score support")
    _require(np.array_equal(changed[~close], original[~close]), "Outer-margin draw changed")
    draw_changed = np.any(changed != original, axis=1)
    before_mean, after_mean = original.mean(axis=0), changed.mean(axis=0)
    return changed, {
        "configuration": CONFIGURATION, "kernelSha256": kernel["kernelSha256"],
        "kernelReady": kernel["ready"], "disposition": kernel["disposition"],
        "drawCount": len(original), "retainedDrawCount": len(changed),
        "closeDrawCount": int(close.sum()), "changedDrawCount": int(draw_changed.sum()),
        "changedDrawFraction": float(draw_changed.mean()),
        "nonnegativeSupportFallbackDrawCount": int(support_fallback.sum()),
        "unseenSourceBinIdentityDrawCount": int(unsupported.sum()) if kernel["ready"] else 0,
        "exactWholePopulationFallback": not kernel["ready"],
        "totalsPerDrawExact": True, "winnerPerDrawExact": True, "outerMarginsExact": True,
        "inputUnmodified": True, "noDrawDropped": True,
        "homeMeanBefore": float(before_mean[0]), "awayMeanBefore": float(before_mean[1]),
        "homeMeanAfter": float(after_mean[0]), "awayMeanAfter": float(after_mean[1]),
        "homeMeanChange": float(after_mean[0] - before_mean[0]),
        "awayMeanChange": float(after_mean[1] - before_mean[1]),
        "maximumAbsoluteTeamScoreChange": int(np.abs(changed - original).max()),
        "centerInterpretation": "Underlying Ridge/paired-residual center unchanged; support transport can change HOME/AWAY empirical means. Every original total and winner is unchanged.",
    }


def transform(draws: Any, game_id: str, kernel: dict[str, Any]) -> tuple[np.ndarray, dict[str, Any]]:
    """Apply in lexicographic HOME/AWAY cell plus replica order, without refitting."""
    original = _validate_draws(draws)
    _require(np.array_equal(np.lexsort((original[:, 1], original[:, 0])), np.arange(len(original))),
             "Use canonical_population: canonical HOME/AWAY cell plus replica order required")
    _validate_kernel(kernel)
    value = seed(game_id)
    randoms = np.random.default_rng(value).random(len(original)) if kernel["ready"] else np.zeros(len(original))
    result, summary = _apply_with_uniforms(original, kernel, randoms)
    summary.update({"gameId": game_id, "seed": value, "masterSeed": MASTER_SEED,
                    "uniformsGenerated": len(original) if kernel["ready"] else 0,
                    "order": "LEXICOGRAPHIC_HOME_AWAY_CELL_THEN_REPLICA; not original temporal draw order",
                    "originalDrawOrderClaimed": False})
    return result, summary
