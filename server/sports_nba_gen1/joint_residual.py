"""Research-only full-game residual distribution. Not the OT-period simulator.

HOME, AWAY column order throughout. Targets and donors are reconstructed
historical records; date ordering does not certify historical source availability.
"""
from __future__ import annotations

import hashlib
import numpy as np

ENGINE = 'NBA_GEN1_JOINT_FINAL_PAIRED_OOF_LATTICE_V1'
BENCHMARK = 'NBA_GEN1_JOINT_FINAL_PERMUTED_MARGINAL_OOF_LATTICE_V1'
DRAW_COUNT = 10_000
MIN_DONORS = 200
MASTER_SEED = 20260914
QUANTILES = (.005, .01, .05, .25, .5, .75, .95, .99, .995)


def seed(game_id, stream):
    token = f'{ENGINE}|{MASTER_SEED}|{game_id}|{stream}'.encode()
    return int.from_bytes(hashlib.sha256(token).digest()[:8], 'big')


def project_final_scores(latent, rng):
    """Minimum-distance projection to nonnegative, unequal integer score pairs.

    Coordinate nearest rounding followed, only for ties, by the closest valid
    one-coordinate neighbor. Exact cost ties use a seeded symmetric choice.
    This is quantization/support repair, not simulated overtime or score clipping
    fitted to outcomes. No draw is rejected. Positive upper tails are unbounded.
    """
    x = np.asarray(latent, dtype=float)
    if x.ndim != 2 or x.shape[1] != 2 or not np.isfinite(x).all():
        raise ValueError('Finite HOME/AWAY latent pairs required')
    floored = np.maximum(x, 0)
    rounded = np.floor(floored + .5).astype(np.int64)
    final = rounded.copy()
    mask = rounded[:, 0] == rounded[:, 1]
    if mask.any():
        tied = rounded[mask]
        neighbors = tied[:, None, :] + np.array([[1, 0], [-1, 0], [0, 1], [0, -1]])[None, :, :]
        cost = ((neighbors - x[mask, None, :]) ** 2).sum(axis=2)
        cost[(neighbors < 0).any(axis=2)] = np.inf
        minimum = cost.min(axis=1, keepdims=True)
        eligible = np.isclose(cost, minimum, rtol=0, atol=1e-12)
        # Uniform random ranks resolve only equal-distance minimizers.
        choice = np.where(eligible, rng.random(cost.shape), -1).argmax(axis=1)
        final[mask] = neighbors[np.arange(len(tied)), choice]
    if (final < 0).any() or (final[:, 0] == final[:, 1]).any() or len(final) != len(x):
        raise AssertionError('Final-score support or probability mass lost')
    return final, {'latent': x, 'floored': floored, 'rounded': rounded, 'final': final}


def eligible_bank(residuals, target_date, target_game_id):
    """Exclude the target and every same/later-date donor before sampling."""
    bank = residuals[residuals.game_date < target_date]
    if target_game_id in set(bank.game_id):
        raise ValueError('Target appeared in its residual bank')
    if len(bank) < MIN_DONORS:
        raise ValueError(f'Unsupported: {len(bank)} earlier OOF donors; require {MIN_DONORS}')
    if not (bank.training_last_date < bank.game_date).all():
        raise ValueError('Residual donor was not predicted out of fold chronologically')
    if bank.game_id.duplicated().any():
        raise ValueError('Duplicate whole-game residual donor')
    return bank.sort_values(['game_date', 'game_id'])


def simulate_pair(expected, bank_pairs, game_id):
    """10k complete paired draws and a matched marginal-permutation benchmark.

    Both use identical Ridge points, column-centered expanding OOF bank, sample
    size and support rule. Permuting the same sampled away vector preserves
    exact pre-support marginal samples while removing its pairing in expectation.
    """
    bank = np.asarray(bank_pairs, float)
    expected = np.asarray(expected, float)
    if bank.ndim != 2 or bank.shape[1] != 2 or len(bank) < MIN_DONORS or not np.isfinite(bank).all():
        raise ValueError('Supported finite paired OOF bank required')
    if expected.shape != (2,) or not np.isfinite(expected).all():
        raise ValueError('Finite original Ridge HOME/AWAY expectation required')
    offset = bank.mean(axis=0)
    index = np.random.default_rng(seed(game_id, 'paired-donors')).integers(len(bank), size=DRAW_COUNT)
    sampled = bank[index] - offset
    perm = np.random.default_rng(seed(game_id, 'benchmark-away-permutation')).permutation(DRAW_COUNT)
    result = {}
    for name, residual in [('paired', sampled), ('benchmark', np.column_stack((sampled[:, 0], sampled[perm, 1])))]:
        latent = expected + residual
        final, stages = project_final_scores(latent, np.random.default_rng(seed(game_id, name+'-support')))
        result[name] = {'draws': final, 'stages': stages}
    return result, offset


def joint_counts(draws):
    pairs, counts = np.unique(np.asarray(draws, np.int64), axis=0, return_counts=True)
    if counts.sum() != len(draws):
        raise AssertionError('Joint frequency count mismatch')
    return pairs, counts


def totals_query(draws, line):
    """All probabilities are fractions; no price or expectation-only inference."""
    if not np.isfinite(line) or line < 0 or line * 2 != round(line * 2):
        raise ValueError('Nonnegative integer or half-point line required')
    x = np.asarray(draws)
    if x.ndim != 2 or x.shape[1] != 2 or len(x) == 0 or not np.isfinite(x).all() or (x != np.floor(x)).any():
        raise ValueError('Complete integer joint population required')
    total = x.sum(axis=1)
    over = int((total > line).sum())
    push = int((total == line).sum())
    under = int((total < line).sum())
    if over + push + under != len(total):
        raise AssertionError('Totals probability mass mismatch')
    n = len(total)
    return {'line': float(line), 'lineClassification': 'ILLUSTRATIVE_NOT_RECORDED_MARKET', 'drawCount': n,
            'probabilityUnits': 'FRACTIONS_0_TO_1', 'over': {'win': over/n, 'push': push/n, 'loss': under/n},
            'under': {'win': under/n, 'push': push/n, 'loss': over/n}}


def stage_summary(stages, low_total, high_total):
    out = {}
    for name, x in stages.items():
        h, a = x.T
        total, margin = h+a, h-a
        out[name] = {'home_mean': float(h.mean()), 'away_mean': float(a.mean()),
                     'total_mean': float(total.mean()), 'margin_mean': float(margin.mean()),
                     'home_win_fraction': float((h > a).mean()), 'tie_fraction': float((h == a).mean()),
                     'negative_draw_fraction': float((x < 0).any(axis=1).mean()),
                     'one_point_fraction': float((abs(margin) == 1).mean()),
                     'covariance': float(np.cov(x.T, ddof=0)[0, 1]),
                     'total_low_fraction': float((total <= low_total).mean()),
                     'total_high_fraction': float((total >= high_total).mean())}
        for variable, values in [('home', h), ('away', a), ('total', total), ('margin', margin)]:
            for q, v in zip(QUANTILES, np.quantile(values, QUANTILES, method='inverted_cdf')):
                out[name][f'{variable}_q{q:g}'] = float(v)
    out['winner_order_reversal_fraction'] = float(((stages['latent'][:, 0]-stages['latent'][:, 1]) *
                                                   (stages['final'][:, 0]-stages['final'][:, 1]) < 0).mean())
    return out
