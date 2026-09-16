"""Fast exact empirical NBA joint energy score on full integer populations.

The mathematical score is the same Euclidean V-statistic as the established
scorer: E||X-y|| - E||X-X'||/2, including all original draws with denominator N².
For a reasonably sized integer score lattice, full count autocorrelation gives
the number of ordered draw pairs at every score displacement. FFT roundoff is
checked before recovering integer pair counts. Sparse/oversized lattices or
failed count checks delegate to the existing exact weighted-unique scorer.

No tail is removed, draw is shuffled, score is quantized, or random draw added.
These are numerical scoring functions only: source/outcome eligibility belongs
to the caller, and no data, model, simulator, or cohort is loaded here.
"""
from __future__ import annotations

import numpy as np
from scipy.signal import fftconvolve as _fftconvolve

from .distribution import (
    DistributionUnsupported, _final_population, _nonnegative_integer,
    joint_energy_score as _reference_energy,
)


SCORER_VERSION = "NBA_GEN1_FULL_JOINT_COUNT_ENERGY_V1"
# Computation/memory guards only. Crossing them changes the numerical algorithm,
# never the population, score definition, or assessment eligibility.
MAX_GRID_CELLS = 262_144
MAX_CORRELATION_CELLS = 1_048_576
MAX_INTEGER_ROUNDING_ERROR = 1e-4
MAX_EXACT_FLOAT_INTEGER = 2**53


def energy_score(home, away, observed_home, observed_away) -> float:
    """Score aligned, nonnegative, untied integer HOME/AWAY final draws.

    Observations are untied nonnegative integer NBA final scores. The full
    supplied empirical population is scored, including duplicates. FFT count
    recovery must conserve N² ordered pairs, be nonnegative and symmetric, and
    have negligible distance from integer counts; otherwise use the established
    weighted-unique computation. Results agree to floating arithmetic precision,
    not a promise of bit-identical summation order across the two algorithms.
    """
    h, a = _final_population(home, away)
    oh = _nonnegative_integer(observed_home, "observed_home")
    oa = _nonnegative_integer(observed_away, "observed_away")
    if oh == oa:
        raise DistributionUnsupported("A governed FINAL NBA game cannot have a tied score")

    def fallback():
        return float(_reference_energy(h, a, [oh, oa]))

    count = len(h)
    home_min, away_min = float(h.min()), float(a.min())
    home_span, away_span = float(h.max() - home_min), float(a.max() - away_min)
    if (not np.isfinite(home_span) or not np.isfinite(away_span)
            or home_span >= MAX_GRID_CELLS or away_span >= MAX_GRID_CELLS
            or count * count > MAX_EXACT_FLOAT_INTEGER):
        return fallback()
    height, width = int(home_span) + 1, int(away_span) + 1
    if (height * width > MAX_GRID_CELLS
            or (2 * height - 1) * (2 * width - 1) > MAX_CORRELATION_CELLS):
        return fallback()

    # Subtract the integer-valued origins before casting: large absolute scores
    # with small finite spans must not overflow integer offset conversion.
    hi, ai = (h - home_min).astype(np.int64), (a - away_min).astype(np.int64)
    grid = np.bincount(hi * width + ai, minlength=height * width).reshape(height, width)
    if int(grid.sum()) != count:
        return fallback()
    try:
        correlation = _fftconvolve(grid, grid[::-1, ::-1], mode="full")
        if (correlation.shape != (2 * height - 1, 2 * width - 1)
                or not np.isfinite(correlation).all()):
            return fallback()
        rounded = np.rint(correlation)
        if np.max(np.abs(correlation - rounded)) > MAX_INTEGER_ROUNDING_ERROR:
            return fallback()
        ordered_pair_counts = rounded.astype(np.int64)
        if ((ordered_pair_counts < 0).any()
                or int(ordered_pair_counts.sum()) != count * count
                or not np.array_equal(ordered_pair_counts, ordered_pair_counts[::-1, ::-1])):
            return fallback()
        # Zero displacement includes repeated and self-pairs; its norm is zero.
        # Keeping N² here preserves the empirical V-statistic (not a U-statistic).
        home_offsets = np.arange(1 - height, height, dtype=np.float64)
        away_offsets = np.arange(1 - width, width, dtype=np.float64)
        displacement_distance = np.hypot(home_offsets[:, None], away_offsets[None, :])
        pair_distance = float(np.sum(ordered_pair_counts * displacement_distance) / (count * count))
        observed_distance = float(np.hypot(h - oh, a - oa).mean())
        score = observed_distance - pair_distance / 2
        return float(score) if np.isfinite(score) else fallback()
    except (MemoryError, ValueError, FloatingPointError, OverflowError):
        return fallback()
