"""Frozen lagged-QB-usage weighting of complete NFL M1 residual pairs.

This research module does not fit point models or recenter conditional residuals.
The existing pooled score simulator performs all clipping, integerization and tie
handling. Only its residual-index uniform is mapped to the weighted donor CDF.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
import hashlib
import json
from typing import Any, Mapping, Sequence

import numpy as np

from .distributions import (
    CommonRandomNumbers, PairedResidualAuthority, ScoreDistributionError,
    SimulatedScores, make_common_random_numbers, simulate_joint_scores,
)

SCHEMA = "NFL_M1_LAGGED_QB_USAGE_PAIRED_RESIDUAL_V1"
STATES = ("STABLE", "MIXED", "UNKNOWN")
GROUPS = tuple(f"{home}|{away}" for home in STATES for away in STATES)
MINIMUM_LOCAL_DONORS = 40
SHRINKAGE_PSEUDO_COUNT = 100.0
MINIMUM_EFFECTIVE_SAMPLE_SIZE = 100.0
SEED_SCHEME = "SHA256(UTF8('NFL_M1_QB_CONTEXT_V1|' + decimal(master_seed) + '|' + canonical_game_id)); first8 bytes unsigned little-endian"


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                    allow_nan=False).encode("utf-8")).hexdigest()


def _readonly(value: Any, *, dtype: Any = np.float64) -> np.ndarray:
    array = np.array(value, dtype=dtype, order="C", copy=True)
    array.setflags(write=False)
    return array


def _contexts(values: Sequence[str], *, count: int) -> tuple[str, ...]:
    result = tuple(str(value) for value in values)
    if len(result) != count or any(value not in GROUPS for value in result):
        raise ScoreDistributionError("aligned declared HOME|AWAY context groups required")
    return result


def game_seed(game_id: str, master_seed: int = 731001) -> int:
    """Stable per-game stream, independent of batch ordering and membership."""
    if not isinstance(game_id, str) or not game_id.strip():
        raise ScoreDistributionError("nonempty canonical game identity required")
    raw = f"NFL_M1_QB_CONTEXT_V1|{int(master_seed)}|{game_id}".encode("utf-8")
    return int.from_bytes(hashlib.sha256(raw).digest()[:8], "little", signed=False)


def context_weights(donor_contexts: Sequence[str], target_context: str) -> tuple[np.ndarray, dict[str, Any]]:
    """One declared shrinkage law, with exact pooled fallback dispositions."""
    donors = _contexts(donor_contexts, count=len(donor_contexts))
    _contexts([target_context], count=1)
    count = len(donors)
    if count < 2:
        raise ScoreDistributionError("at least two complete paired donors required")
    match = np.asarray([value == target_context for value in donors], dtype=bool)
    local = int(match.sum())
    weights = np.full(count, 1.0 / count)
    alpha = 0.0
    if "UNKNOWN" in target_context.split("|"):
        status = "POOLED_FALLBACK_UNKNOWN_CONTEXT"
    elif local < MINIMUM_LOCAL_DONORS:
        status = "POOLED_FALLBACK_INSUFFICIENT_LOCAL_DONORS"
    else:
        alpha = local / (local + SHRINKAGE_PSEUDO_COUNT)
        proposed = (1.0-alpha)/count + alpha*match/local
        proposed /= proposed.sum()
        proposed_ess = float(1.0 / np.square(proposed).sum())
        if proposed_ess + 1e-10 < MINIMUM_EFFECTIVE_SAMPLE_SIZE:
            status = "POOLED_FALLBACK_INSUFFICIENT_EFFECTIVE_SUPPORT"
            alpha = 0.0
        else:
            weights = proposed
            status = "CONDITIONED_SUPPORTED"
    ess = float(1.0/np.square(weights).sum())
    metadata = {
        "contextGroup": target_context, "status": status,
        "supportedConditioning": status == "CONDITIONED_SUPPORTED",
        "donorCount": count, "localDonorCount": local,
        "effectiveSampleSize": ess, "shrinkageAlpha": alpha,
        "minimumLocalDonors": MINIMUM_LOCAL_DONORS,
        "minimumEffectiveSampleSize": MINIMUM_EFFECTIVE_SAMPLE_SIZE,
        "shrinkagePseudoCount": SHRINKAGE_PSEUDO_COUNT,
        "maximumDonorWeight": float(weights.max()),
        "weightSum": float(weights.sum()),
        "weightsSha256": hashlib.sha256(weights.astype("<f8").tobytes()).hexdigest(),
    }
    return _readonly(weights), metadata


def fit_conditioning(*, residual_authority: PairedResidualAuthority,
                     donor_contexts: Sequence[str], declaration_sha256: str,
                     frozen_at_utc: str | None = None) -> dict[str, Any]:
    """Freeze a JSON-serializable bank and fixed weights; no outcome-based tuning."""
    if len(declaration_sha256) != 64 or any(char not in "0123456789abcdef" for char in declaration_sha256):
        raise ScoreDistributionError("physical declaration SHA256 required")
    frozen = frozen_at_utc or datetime.now(timezone.utc).isoformat()
    if datetime.fromisoformat(frozen.replace("Z", "+00:00")).tzinfo is None:
        raise ScoreDistributionError("timezone-aware fitted configuration freeze clock required")
    contexts = _contexts(donor_contexts, count=residual_authority.row_count)
    if (residual_authority.home.shape != residual_authority.away.shape
            or residual_authority.home.ndim != 1 or residual_authority.row_count < 2
            or not np.isfinite(residual_authority.home).all()
            or not np.isfinite(residual_authority.away).all()
            or len(residual_authority.row_ids) != residual_authority.row_count
            or len(set(residual_authority.row_ids)) != residual_authority.row_count):
        raise ScoreDistributionError("valid aligned paired residual authority required")
    if abs(float(residual_authority.home.mean())) > 1e-10 or abs(float(residual_authority.away.mean())) > 1e-10:
        raise ScoreDistributionError("one shared pooled-centered authority required")
    groups = {}
    for context in GROUPS:
        weights, meta = context_weights(contexts, context)
        meta["weightedResidualMeanHome"] = float(weights @ residual_authority.home)
        meta["weightedResidualMeanAway"] = float(weights @ residual_authority.away)
        groups[context] = meta
    config = {
        "schemaVersion": SCHEMA, "declarationSha256": declaration_sha256,
        "frozenAtUtc": frozen,
        "parameters": {"minimumLocalDonors": MINIMUM_LOCAL_DONORS,
                       "shrinkagePseudoCount": SHRINKAGE_PSEUDO_COUNT,
                       "minimumEffectiveSampleSize": MINIMUM_EFFECTIVE_SAMPLE_SIZE},
        "groups": groups, "donorContexts": list(contexts),
        "pairedResidualAuthority": {
            "home": residual_authority.home.tolist(), "away": residual_authority.away.tolist(),
            "rowIds": list(residual_authority.row_ids),
            "trainingStart": residual_authority.training_start,
            "trainingEnd": residual_authority.training_end,
            "residualCorrelation": residual_authority.residual_correlation,
            "sha256": residual_authority.sha256,
            "contractVersion": residual_authority.contract_version,
        },
        "sharedPooledCentering": True, "weightedRecentering": False,
        "outcomeBasedTuning": False, "configurationCount": 1,
        "pointModelsChanged": False, "productionAuthority": False,
        "seedScheme": SEED_SCHEME,
        "scoreTransform": "Existing simulate_joint_scores: max(0, mean+paired residual), same independent stochastic-round uniforms, retain tied scores",
        "expectedScoreMeaning": "Conditional residual weights may change expected scores; no mean preservation is imposed.",
    }
    config["configurationSha256"] = _digest(config)
    return config


def authority_from_config(fitted_config: Mapping[str, Any]) -> PairedResidualAuthority:
    """Reload only the complete bank bound inside a validated fitted config."""
    config = dict(fitted_config)
    digest = config.pop("configurationSha256", None)
    if config.get("schemaVersion") != SCHEMA or digest != _digest(config):
        raise ScoreDistributionError("fitted residual configuration identity differs")
    raw = config["pairedResidualAuthority"]
    authority = PairedResidualAuthority(
        home=_readonly(raw["home"]), away=_readonly(raw["away"]),
        row_ids=tuple(raw["rowIds"]), training_start=raw["trainingStart"],
        training_end=raw["trainingEnd"], residual_correlation=raw["residualCorrelation"],
        sha256=raw["sha256"], contract_version=raw["contractVersion"],
    )
    expected = fit_conditioning(residual_authority=authority,
                                donor_contexts=config["donorContexts"],
                                declaration_sha256=config["declarationSha256"],
                                frozen_at_utc=config["frozenAtUtc"])
    if expected != fitted_config:
        raise ScoreDistributionError("fitted residual configuration semantics differ")
    return authority


def _summary(home: np.ndarray, away: np.ndarray) -> dict[str, Any]:
    h, a = home.astype(float), away.astype(float)
    margin, total = h-a, h+a
    covariance = float(np.cov(h, a, ddof=0)[0, 1])
    scale = float(h.std()*a.std())
    result = {"meanHome": float(h.mean()), "meanAway": float(a.mean()),
              "meanMargin": float(margin.mean()), "meanTotal": float(total.mean()),
              "varianceHome": float(h.var()), "varianceAway": float(a.var()),
              "varianceMargin": float(margin.var()), "varianceTotal": float(total.var()),
              "covarianceHomeAway": covariance,
              "correlationHomeAway": covariance/scale if scale else None,
              "homeWinProbability": float((margin > 0).mean()),
              "awayWinProbability": float((margin < 0).mean()),
              "tieProbability": float((margin == 0).mean()),
              "tails": {"absoluteMarginAtLeast21": float((abs(margin) >= 21).mean()),
                        "awayAtMost10": float((a <= 10).mean()),
                        "homeAtMost10": float((h <= 10).mean()),
                        "totalAtLeast60": float((total >= 60).mean()),
                        "tie": float((margin == 0).mean())},
              "intervals": {}}
    for field, values in (("home", h), ("away", a), ("margin", margin), ("total", total)):
        result["intervals"][field] = {}
        for level in (0.8, 0.9):
            lower, upper = np.quantile(values, [(1-level)/2, (1+level)/2])
            result["intervals"][field][str(level)] = {
                "lower": float(lower), "upper": float(upper), "width": float(upper-lower)}
    return result


@dataclass(frozen=True)
class QbResidualComparison:
    baseline: SimulatedScores
    candidate: SimulatedScores
    diagnostics: tuple[dict[str, Any], ...]


def simulate_comparison(*, predicted_home_mean: Sequence[float], predicted_away_mean: Sequence[float],
                        target_contexts: Sequence[str], target_game_ids: Sequence[str],
                        target_game_dates: Sequence[str], residual_authority: PairedResidualAuthority,
                        fitted_config: Mapping[str, Any], draws: int = 10000,
                        seed: int = 731001) -> QbResidualComparison:
    """Same point means, pair bank, random variates, score mechanics and budget."""
    checked = authority_from_config(fitted_config)
    if (checked.sha256 != residual_authority.sha256
            or checked.row_ids != residual_authority.row_ids
            or not np.array_equal(checked.home, residual_authority.home)
            or not np.array_equal(checked.away, residual_authority.away)):
        raise ScoreDistributionError("runtime paired residual authority differs from fitted bank")
    ids = tuple(str(value) for value in target_game_ids)
    count = len(ids)
    if (not count or len(set(ids)) != count or set(ids).intersection(checked.row_ids)
            or any(not value.strip() for value in ids)
            or len(predicted_home_mean) != count or len(predicted_away_mean) != count
            or len(target_game_dates) != count):
        raise ScoreDistributionError("unique assessment identities aligned and separate from donors required")
    contexts = _contexts(target_contexts, count=count)
    days = np.asarray(target_game_dates, dtype="datetime64[D]")
    cutoff = np.datetime64(checked.training_end, "D")
    if np.isnat(days).any() or np.isnat(cutoff) or np.any(days <= cutoff):
        raise ScoreDistributionError("target games must occur strictly after the donor-bank cutoff")
    if draws < 2:
        raise ScoreDistributionError("at least two simulation draws required")
    original = [make_common_random_numbers(n_games=1, draws=draws,
                                          seed=game_seed(identity, seed)) for identity in ids]
    randoms = CommonRandomNumbers(
        _readonly(np.concatenate([value.residual_uniform for value in original])),
        _readonly(np.concatenate([value.home_round_uniform for value in original])),
        _readonly(np.concatenate([value.away_round_uniform for value in original])), int(seed))
    baseline = simulate_joint_scores(predicted_home_mean=predicted_home_mean,
                                    predicted_away_mean=predicted_away_mean,
                                    residual_authority=checked, draws=draws,
                                    common_random_numbers=randoms)
    mapped = randoms.residual_uniform.copy()
    metadata = []
    for index, (identity, context) in enumerate(zip(ids, contexts, strict=True)):
        weights, meta = context_weights(fitted_config["donorContexts"], context)
        if meta["supportedConditioning"]:
            cdf = np.cumsum(weights)
            cdf[-1] = 1.0
            donors = np.searchsorted(cdf, randoms.residual_uniform[index], side="right")
            # Midpoints select the exact chosen integer donor in the unchanged
            # uniform pooled implementation. No home/away pair can be separated.
            mapped[index] = (donors.astype(float)+0.5)/checked.row_count
        metadata.append({**meta, "canonicalGameId": identity, "gameSeed": game_seed(identity, seed),
                         "drawsPerArm": draws,
                         "weightedResidualMeanHome": float(weights @ checked.home),
                         "weightedResidualMeanAway": float(weights @ checked.away)})
    candidate_randoms = CommonRandomNumbers(_readonly(mapped), randoms.home_round_uniform,
                                            randoms.away_round_uniform, int(seed))
    candidate = simulate_joint_scores(predicted_home_mean=predicted_home_mean,
                                     predicted_away_mean=predicted_away_mean,
                                     residual_authority=checked, draws=draws,
                                     common_random_numbers=candidate_randoms)
    candidate = replace(candidate, contract_version=SCHEMA)
    for index, meta in enumerate(metadata):
        h0, a0 = baseline.home[index].astype(float), baseline.away[index].astype(float)
        h1, a1 = candidate.home[index].astype(float), candidate.away[index].astype(float)
        identical = bool(np.array_equal(h0, h1) and np.array_equal(a0, a1))
        if not meta["supportedConditioning"] and not identical:
            raise ScoreDistributionError("pooled fallback changed a numerical draw")
        meta.update({"exactPooledNumericalFallback": identical if not meta["supportedConditioning"] else None,
                     "baseline": _summary(h0, a0), "candidate": _summary(h1, a1),
                     "pairedSimulationDifference": {},
                     "mcseMeaning": "Sampling precision of coupled draws only; not model or observed-game improvement uncertainty."})
        quantities = {"homeMean": h1-h0, "awayMean": a1-a0,
                      "marginMean": (h1-a1)-(h0-a0), "totalMean": (h1+a1)-(h0+a0),
                      "homeWinProbability": (h1>a1).astype(float)-(h0>a0),
                      "awayWinProbability": (h1<a1).astype(float)-(h0<a0),
                      "tieProbability": (h1==a1).astype(float)-(h0==a0)}
        for name, values in quantities.items():
            meta["pairedSimulationDifference"][name] = {
                "candidateMinusControl": float(values.mean()),
                "monteCarloStandardError": float(values.std(ddof=1)/np.sqrt(draws))}
    return QbResidualComparison(baseline, candidate, tuple(metadata))
