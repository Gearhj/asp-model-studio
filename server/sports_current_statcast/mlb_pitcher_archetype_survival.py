"""Separate research extension of the frozen pregame starter survival model.

The operational HGB and its identity guards remain untouched. Profiles are
pregame covariates; only BF evolves in this reduced-state hazard. GAME_END is a
competing observed endpoint in the study and is never a second termination draw
inside a game simulator.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from itertools import combinations
from typing import Mapping

import numpy as np
import pandas as pd
from scipy.optimize import minimize_scalar
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.impute import SimpleImputer
from sklearn.metrics import adjusted_rand_score
from sklearn.mixture import GaussianMixture
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from .mlb_starter_survival_models import (
    ENDPOINTS, FLOOR, PREGAME_FIELDS, losses, target_codes,
    temperature_probabilities,
)

SCHEMA = "MLB_PITCHER_ARCHETYPE_SURVIVAL_RESEARCH_V1"
ARCHETYPE_FIELDS = tuple(f"archetype_p{i}" for i in range(6))
ESTIMATOR_PARAMETERS = {
    "max_iter": 100, "max_leaf_nodes": 15, "learning_rate": 0.06,
    "min_samples_leaf": 200, "l2_regularization": 10.0,
    "early_stopping": False, "random_state": 20260911,
}


class UnsupportedArchetypes(ValueError):
    """The predeclared training support/stability conditions were not met."""


def _style_fields():
    # Import lazily so reading this module does not load any source data.
    from .mlb_pitcher_style_profiles import STYLE_FEATURES
    return tuple(STYLE_FEATURES)


def _validate_feature_order(feature_order):
    order = tuple(feature_order)
    if (order[:len(PREGAME_FIELDS)] != tuple(PREGAME_FIELDS)
            or len(set(order)) != len(order)
            or set(order) - set(PREGAME_FIELDS + _style_fields() + ARCHETYPE_FIELDS)):
        raise ValueError("EXACT_BASE_FEATURE_PREFIX_AND_REGISTERED_PREGAME_PROFILE_FIELDS_REQUIRED")
    present_memberships = [name for name in order if name in ARCHETYPE_FIELDS]
    if present_memberships and tuple(present_memberships) != ARCHETYPE_FIELDS[:len(present_memberships)]:
        raise ValueError("ARCHETYPE_MEMBERSHIP_COLUMNS_MUST_BE_CONTIGUOUS_FROM_ZERO")
    return order


def _probabilities(values, count):
    p = np.asarray(values, dtype=float)
    if (p.shape != (count, 3) or not np.isfinite(p).all() or (p < 0).any()
            or not np.allclose(p.sum(axis=1), 1.0, atol=1e-10)):
        raise ValueError("INVALID_COMPETING_ENDPOINT_PROBABILITIES")
    return p


@dataclass
class ArchetypeHazard:
    """One pooled HGB; A/B/C differ only in their registered feature columns."""

    model_id: str
    feature_order: tuple
    temperature: float = 1.0
    metadata: dict = field(default_factory=dict)

    def __post_init__(self):
        self.feature_order = _validate_feature_order(self.feature_order)
        if not self.model_id or self.model_id == "HGB_PREGAME":
            raise ValueError("DISTINCT_RESEARCH_MODEL_ID_REQUIRED")

    def fit(self, frame, endpoints):
        self.feature_order = _validate_feature_order(self.feature_order)
        y = target_codes(endpoints)
        if set(y) != {0, 1, 2}:
            raise ValueError("TRAINING_REQUIRES_ALL_THREE_REAL_ENDPOINTS")
        self.pipeline = Pipeline([
            ("imputer", SimpleImputer(strategy="median", add_indicator=True)),
            ("estimator", HistGradientBoostingClassifier(**ESTIMATOR_PARAMETERS)),
        ])
        self.pipeline.fit(frame.loc[:, list(self.feature_order)], y)
        return self

    def predict_proba(self, frame, *, calibrated=True):
        raw = self.pipeline.predict_proba(frame.loc[:, list(self.feature_order)])
        p = np.zeros((len(frame), 3), dtype=float)
        for column, code in enumerate(self.pipeline.classes_):
            p[:, int(code)] = raw[:, column]
        p = _probabilities(p, len(frame))
        return temperature_probabilities(p, self.temperature) if calibrated else p

    def fit_temperature(self, calibration, endpoints):
        """The original one-scalar, disjoint-earlier-window specification."""
        raw = self.predict_proba(calibration, calibrated=False)
        y = target_codes(endpoints)
        result = minimize_scalar(
            lambda value: losses(temperature_probabilities(raw, value), y)[0].mean(),
            bounds=(0.5, 2.0), method="bounded", options={"xatol": 1e-5},
        )
        if not result.success:
            raise ValueError("BOUNDED_TEMPERATURE_OPTIMIZATION_FAILED")
        self.temperature = float(result.x)
        return {"temperature": self.temperature,
                "method": "DISJOINT_EARLIER_TEMPERATURE_ONLY",
                "iterations": int(result.nfev),
                "rawNll": float(losses(raw, y)[0].mean()),
                "calibratedNll": float(result.fun)}


@dataclass
class ArchetypeMembership:
    """Train-only style clustering with a fixed support/stability gate.

    One row must be one historical start. Workload, BF, outcome and support
    counts never enter the clustering transform. A failed gate leaves C
    unsupported; it does not manufacture a single cluster or hard assignment.
    """

    cluster_counts: tuple = (2, 3, 4, 5, 6)
    seeds: tuple = (20260914, 20260915, 20260916)
    minimum_starts: int = 100
    minimum_pitchers: int = 15
    minimum_soft_mass: float = 100.0
    minimum_stability: float = 0.8
    uncertain_below: float = 0.6

    def fit(self, starts, *, pitcher_column="pitcherId", start_column="startId"):
        if (starts[start_column].isna().any() or starts[start_column].duplicated().any()
                or starts[pitcher_column].isna().any()):
            raise ValueError("UNIQUE_IDENTIFIED_TRAINING_STARTS_REQUIRED")
        if "profileSupported" not in starts or not starts.profileSupported.eq(True).all():
            raise ValueError("CLUSTER_TRAINING_REQUIRES_SUPPORTED_PRIOR_PROFILES")
        if (tuple(self.cluster_counts) != tuple(sorted(set(self.cluster_counts)))
                or any(k not in range(2, 7) for k in self.cluster_counts)
                or len(self.seeds) != 3 or len(set(self.seeds)) != 3):
            raise ValueError("BOUNDED_CLUSTER_COUNTS_AND_THREE_DISTINCT_SEEDS_REQUIRED")
        self.feature_order = _style_fields()
        training_features = starts.loc[:, list(self.feature_order)]
        all_missing = training_features.columns[training_features.isna().all()].tolist()
        constant_observed = [name for name in self.feature_order
                             if name not in all_missing and training_features[name].nunique(dropna=True) <= 1]
        self.transform = Pipeline([
            ("imputer", SimpleImputer(strategy="median", keep_empty_features=True)),
            ("scale", StandardScaler()),
        ])
        x = self.transform.fit_transform(training_features)
        if len(starts) < max(self.cluster_counts) or not np.isfinite(x).all():
            raise ValueError("INSUFFICIENT_OR_NONFINITE_CLUSTER_TRAINING_SUPPORT")
        self.training_start_ids = tuple(starts[start_column].astype(str))
        self.training_pitcher_ids = tuple(starts[pitcher_column].astype(str))
        candidates, passing = [], []
        for k in self.cluster_counts:
            models = [GaussianMixture(
                n_components=k, covariance_type="diag", reg_covar=0.05,
                max_iter=200, tol=1e-3, n_init=3, random_state=seed,
            ).fit(x) for seed in self.seeds]
            assignments = [model.predict(x) for model in models]
            base, hard = models[0], assignments[0]
            soft = base.predict_proba(x)
            stability = [float(adjusted_rand_score(left, right))
                         for left, right in combinations(assignments, 2)]
            groups = [{"archetype": j, "starts": int((hard == j).sum()),
                       "distinctPitchers": int(starts.loc[hard == j, pitcher_column].nunique()),
                       "softMass": float(soft[:, j].sum())} for j in range(k)]
            reasons = []
            if not all(model.converged_ for model in models):
                reasons.append("MIXTURE_DID_NOT_CONVERGE")
            if any(g["starts"] < self.minimum_starts for g in groups):
                reasons.append("HARD_START_SUPPORT_BELOW_MINIMUM")
            if any(g["distinctPitchers"] < self.minimum_pitchers for g in groups):
                reasons.append("DISTINCT_PITCHER_SUPPORT_BELOW_MINIMUM")
            if any(g["softMass"] < self.minimum_soft_mass for g in groups):
                reasons.append("SOFT_START_MASS_BELOW_MINIMUM")
            if np.median(stability) < self.minimum_stability:
                reasons.append("SEED_ASSIGNMENT_STABILITY_BELOW_MINIMUM")
            item = {"clusterCount": k, "trainingBic": float(base.bic(x)),
                    "pairwiseAdjustedRandIndex": stability,
                    "medianAdjustedRandIndex": float(np.median(stability)),
                    "groups": groups, "passes": not reasons, "failureReasons": reasons,
                    "convergedBySeed": [bool(model.converged_) for model in models]}
            candidates.append(item)
            if not reasons:
                passing.append((item["trainingBic"], k, base))
        self.candidate_summary = candidates
        self.supported = bool(passing)
        self.selected_k = None
        self.selection = {
            "schemaVersion": SCHEMA + "_CLUSTER_SELECTION", "trainingOnly": True,
            "criterion": "MINIMUM_TRAINING_BIC_AMONG_SUPPORTED_STABLE_CANDIDATES_THEN_LOWER_K",
            "candidateCounts": list(self.cluster_counts), "seeds": list(self.seeds),
            "minimumStarts": self.minimum_starts, "minimumPitchers": self.minimum_pitchers,
            "minimumSoftMass": self.minimum_soft_mass, "minimumMedianAdjustedRandIndex": self.minimum_stability,
            "uncertainMaximumMembershipBelow": self.uncertain_below,
            "featureOrder": list(self.feature_order), "trainingStarts": len(starts),
            "allMissingTrainingColumns": all_missing,
            "constantObservedTrainingColumns": constant_observed,
            "constantAndMissingColumnTreatment": "RETAIN_COLUMNS; median imputation with all-missing=0; StandardScaler leaves zero variance unscaled",
            "distinctTrainingPitchers": int(starts[pitcher_column].nunique()),
            "candidates": candidates, "supported": self.supported,
        }
        if self.supported:
            _, self.selected_k, self.model = min(passing, key=lambda item: (item[0], item[1]))
            self.selection["selectedClusterCount"] = self.selected_k
            self.selection["groups"] = self.summarize(starts, pitcher_column=pitcher_column)
        else:
            self.selection["selectedClusterCount"] = None
            self.selection["disposition"] = "C_UNSUPPORTED_NO_CANDIDATE_PASSED_TRAINING_GATE"
        return self

    def predict_proba(self, starts):
        if not getattr(self, "supported", False):
            raise UnsupportedArchetypes("C_UNSUPPORTED_NO_CANDIDATE_PASSED_TRAINING_GATE")
        if "profileSupported" not in starts or not starts.profileSupported.eq(True).all():
            raise UnsupportedArchetypes("PROFILE_UNSUPPORTED_NO_IMPUTED_ARCHETYPE_ASSIGNMENT")
        x = self.transform.transform(starts.loc[:, list(self.feature_order)])
        p = self.model.predict_proba(x)
        if not np.isfinite(p).all() or not np.allclose(p.sum(axis=1), 1.0, atol=1e-12):
            raise ValueError("INCOHERENT_SOFT_ARCHETYPE_MEMBERSHIPS")
        return p

    def append_memberships(self, starts):
        p = self.predict_proba(starts)
        result = starts.copy()
        for index in range(self.selected_k):
            result[ARCHETYPE_FIELDS[index]] = p[:, index]
        return result

    def summarize(self, starts, *, pitcher_column="pitcherId"):
        p = self.predict_proba(starts)
        hard, uncertain = p.argmax(axis=1), p.max(axis=1) < self.uncertain_below
        values = starts.loc[:, list(self.feature_order)].to_numpy(dtype=float)
        groups = []
        for j in range(self.selected_k):
            means, medians = {}, {}
            assigned = hard == j
            for index, name in enumerate(self.feature_order):
                valid = np.isfinite(values[:, index])
                mass = p[valid, j].sum()
                means[name] = float(p[valid, j] @ values[valid, index] / mass) if mass else None
                observed = values[assigned & valid, index]
                medians[name] = float(np.median(observed)) if len(observed) else None
            hard_count = int(assigned.sum())
            hands = starts.loc[assigned, "style_throws_left"].to_numpy(dtype=float)
            hand_proportions = {
                "left": float((hands == 1).sum() / hard_count) if hard_count else None,
                "right": float((hands == 0).sum() / hard_count) if hard_count else None,
                "unknown": float((~np.isin(hands, [0, 1])).sum() / hard_count) if hard_count else None,
            }
            usage = {}
            for name in self.feature_order:
                if name.startswith("style_") and name.endswith("_usage"):
                    fraction = starts.loc[assigned, name].to_numpy(dtype=float)
                    fraction = fraction[np.isfinite(fraction)]
                    usage[name[len("style_"):-len("_usage")]] = float(fraction.mean()) if len(fraction) else None
            groups.append({"archetype": j, "hardStarts": hard_count,
                           "distinctPitchers": int(starts.loc[assigned, pitcher_column].nunique()),
                           "softMass": float(p[:, j].sum()),
                           "uncertainHardStarts": int((assigned & uncertain).sum()),
                           "softWeightedObservedFeatureMeans": means,
                           "hardGroupObservedFeatureMedians": medians,
                           "hardGroupThrowingHandProportions": hand_proportions,
                           "hardGroupMeanPriorPitchTypeUsageFractions": usage,
                           "descriptiveDenominators": {
                               "medians": "Finite prior-profile measurements among hard-assigned starts; each start once",
                               "throwingHand": "All hard-assigned starts; fractions sum to one when nonempty",
                               "pitchTypeUsage": "Equal-start mean of each prior-profile pitch-type fraction, not pooled raw-pitch counts",
                           }})
        return groups


def pregame_bf_distribution(model, starts, *, maximum_bf=100, calibrated=True):
    """Competing BF law, retaining unresolved tail instead of forcing a hook."""
    _validate_feature_order(model.feature_order)
    if maximum_bf < 1 or not isinstance(maximum_bf, int) or len(starts) == 0:
        raise ValueError("POSITIVE_BF_SUPPORT_AND_NONEMPTY_STARTS_REQUIRED")
    indexed = starts.reset_index(drop=True)
    expanded = indexed.loc[indexed.index.repeat(maximum_bf)].reset_index(drop=True).copy()
    expanded["bf"] = np.tile(np.arange(1, maximum_bf + 1), len(starts))
    p = _probabilities(model.predict_proba(expanded, calibrated=calibrated), len(expanded))
    p = p.reshape(len(starts), maximum_bf, 3)
    survival = np.concatenate([np.ones((len(starts), 1)), np.cumprod(p[:, :-1, 0], axis=1)], axis=1)
    cause = survival[:, :, None] * p[:, :, 1:]
    tail = np.prod(p[:, :, 0], axis=1)
    if not np.allclose(cause.sum(axis=(1, 2)) + tail, 1.0, atol=1e-10):
        raise ValueError("COMPETING_BF_MASS_NOT_CONSERVED")
    return {"pmf": cause.sum(axis=2), "causeMass": cause, "tail": tail}


def conditional_removal_probability(model, features, *, game_active, starter_active):
    """The original next-opportunity contract: R/(C+R), BF>=1 only."""
    _validate_feature_order(model.feature_order)
    games, starters = np.asarray(game_active, dtype=bool), np.asarray(starter_active, dtype=bool)
    if games.shape != (len(features),) or starters.shape != games.shape:
        raise ValueError("GAME_STARTER_STATE_SHAPE_MISMATCH")
    bf = features.bf.to_numpy(dtype=float)
    if not np.isfinite(bf).all() or (bf < 0).any() or (bf != np.floor(bf)).any():
        raise ValueError("NONNEGATIVE_INTEGER_SIMULATED_BF_REQUIRED")
    eligible = games & starters & (bf >= 1)
    result = np.zeros(len(features), dtype=float)
    if eligible.any():
        p = _probabilities(model.predict_proba(features.loc[eligible], calibrated=True), int(eligible.sum()))
        denominator = p[:, 0] + p[:, 1]
        if (denominator <= 0).any():
            raise ValueError("NO_SUPPORTED_NEXT_OPPORTUNITY_PROBABILITY")
        result[eligible] = p[:, 1] / denominator
    return result


def research_duration_lookup(model, home_inputs: Mapping, away_inputs: Mapping, *,
                             baseline_result, maximum_bf=200):
    """Produce a separate research lookup or return the exact baseline object.

    This seam does not bypass the frozen publisher's model/feature guards and
    does not claim that a fallback executed the candidate. Callers must also
    certify source authority, pregame clocks and baseline binding before use.
    """
    _validate_feature_order(model.feature_order)
    uses_profile = bool(set(model.feature_order) - set(PREGAME_FIELDS))
    unsupported = [side for side, values in (("HOME", home_inputs), ("AWAY", away_inputs))
                   if uses_profile and values.get("profileSupported") is not True]
    if unsupported:
        return {"status": "UNSUPPORTED_PROFILE_BASELINE_FALLBACK", "candidateExecuted": False,
                "fallback": True, "unsupportedSides": unsupported, "result": baseline_result,
                "lookup": None}
    if not isinstance(maximum_bf, int) or maximum_bf < 1:
        raise ValueError("POSITIVE_LOOKUP_BF_SUPPORT_REQUIRED")
    rows = []
    fixed = [name for name in model.feature_order if name != "bf"]
    for orientation, inputs in ((0, away_inputs), (1, home_inputs)):
        if inputs.get("homePitcher") != orientation or set(fixed) - set(inputs):
            raise ValueError("COMPLETE_ORIENTED_PREGAME_FEATURES_REQUIRED")
        rows.extend({**{name: inputs[name] for name in fixed}, "bf": bf}
                    for bf in range(1, maximum_bf + 1))
    frame = pd.DataFrame(rows, columns=model.feature_order)
    probabilities = conditional_removal_probability(
        model, frame, game_active=np.ones(len(frame), bool), starter_active=np.ones(len(frame), bool))
    lookup = np.zeros((2, maximum_bf + 1), dtype=float)
    lookup[:, 1:] = probabilities.reshape(2, maximum_bf)
    return {"status": "SUPPORTED_RESEARCH_LOOKUP", "candidateExecuted": False,
            "candidateHazardExecuted": True, "gameSimulationExecuted": False,
            "fallback": False, "lookup": lookup, "result": None,
            "conditionalContract": "REMOVAL/(CONTINUE+REMOVAL); simulator owns game end",
            "featureOrder": list(model.feature_order), "modelId": model.model_id,
            "scoredRows": len(frame), "bfGrid": [1, maximum_bf]}
