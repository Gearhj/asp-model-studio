from __future__ import annotations

import hashlib
import itertools
import json
import math
from copy import deepcopy
from typing import Any, Callable

import pandas as pd


VifCalculator = Callable[[pd.DataFrame], list[dict[str, Any]]]


TIE_BREAKERS = [
    "development-population signal",
    "business interpretability",
    "data quality and missingness",
    "bureau special-value burden",
    "production availability and definition stability",
    "intended model-family behavior",
]


MODEL_FAMILY_POLICY = {
    "linear_scorecard": {
        "label": "Linear / scorecard",
        "exclusion_penalty": 0.55,
        "recommended_posture": "resolve_before_fit",
        "implication": "Resolve material multicollinearity before fitting; transparent exclusion or an interpretable combination is preferred.",
    },
    "generalized_linear": {
        "label": "Generalized linear",
        "exclusion_penalty": 0.7,
        "recommended_posture": "resolve_or_regularize_with_documentation",
        "implication": "Reduce unstable coefficient inflation; regularization may supplement, but does not replace, a governed redundancy decision.",
    },
    "tree_ensemble": {
        "label": "Tree ensemble",
        "exclusion_penalty": 1.8,
        "recommended_posture": "retain_or_defer_unless_operationally_costly",
        "implication": "Correlated predictors are less likely to destabilize predictions, so retain or defer is preferred unless production or explanation costs justify removal.",
    },
    "neural_network": {
        "label": "Neural network",
        "exclusion_penalty": 1.35,
        "recommended_posture": "retain_with_scaling_and_regularization_review",
        "implication": "Scaling and regularization can absorb redundancy; exclusions require stronger data-quality or production evidence.",
    },
    "mixed_bench": {
        "label": "Mixed model bench",
        "exclusion_penalty": 1.0,
        "recommended_posture": "preserve_common_contract_and_family_alternatives",
        "implication": "Use a conservative common feature contract and preserve documented alternatives for family-specific challengers.",
    },
}


def _finite(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _maximum(rows: list[dict[str, Any]]) -> float | None:
    values = [_finite(row.get("vif")) for row in rows]
    finite = [value for value in values if value is not None]
    return max(finite) if finite else None


def _summary(rows: list[dict[str, Any]], predictor_count: int) -> dict[str, Any]:
    maximum = _maximum(rows)
    return {
        "predictor_count": predictor_count,
        "maximum_vif": maximum,
        "count_above_5": sum(1 for row in rows if (_finite(row.get("vif")) or 0) > 5),
        "count_above_10": sum(1 for row in rows if (_finite(row.get("vif")) or 0) > 10),
    }


def _clusters(frame: pd.DataFrame, threshold: float) -> list[dict[str, Any]]:
    if frame.shape[1] < 2:
        return []
    correlation = frame.corr(numeric_only=True).abs()
    adjacency: dict[str, set[str]] = {str(column): set() for column in correlation.columns}
    edges: list[tuple[str, str, float]] = []
    for left_index, left in enumerate(correlation.columns):
        for right in correlation.columns[left_index + 1 :]:
            value = _finite(correlation.loc[left, right])
            if value is None or value < threshold:
                continue
            left_name, right_name = str(left), str(right)
            adjacency[left_name].add(right_name)
            adjacency[right_name].add(left_name)
            edges.append((left_name, right_name, value))
    result: list[dict[str, Any]] = []
    visited: set[str] = set()
    for feature in sorted(adjacency):
        if feature in visited or not adjacency[feature]:
            continue
        stack = [feature]
        component: set[str] = set()
        while stack:
            current = stack.pop()
            if current in component:
                continue
            component.add(current)
            stack.extend(adjacency[current] - component)
        visited.update(component)
        component_edges = [
            {"left": left, "right": right, "correlation": value}
            for left, right, value in edges
            if left in component and right in component
        ]
        features = sorted(component)
        digest = hashlib.sha256("|".join(features).encode("utf-8")).hexdigest()[:10]
        result.append(
            {
                "cluster_id": f"vif-cluster-{digest}",
                "features": features,
                "maximum_correlation": max(edge["correlation"] for edge in component_edges),
                "edges": component_edges,
            }
        )
    return sorted(result, key=lambda row: (-row["maximum_correlation"], row["cluster_id"]))


def _profile_penalty(
    feature: str,
    profiles: dict[str, dict[str, Any]],
    weights: dict[str, float],
) -> float:
    profile = profiles.get(feature, {})
    signal = _finite(profile.get("development_signal")) or 0.0
    interpretability = _finite(profile.get("interpretability")) or 0.5
    missingness = _finite(profile.get("missingness")) or 0.0
    special = _finite(profile.get("special_value_burden")) or 0.0
    production = _finite(profile.get("production_availability")) or 0.5
    return (
        weights.get("signal", 1.0) * signal
        + weights.get("interpretability", 1.0) * interpretability
        + weights.get("production_availability", 1.0) * production
        + weights.get("data_quality", 1.0) * max(0.0, 1.0 - missingness)
        - weights.get("special_value_burden", 1.0) * special
    )


def _candidate_score(
    *,
    current: dict[str, Any],
    proposed: dict[str, Any],
    feature: str,
    profiles: dict[str, dict[str, Any]],
    weights: dict[str, float],
    objective: str,
    family_policy: dict[str, Any],
) -> float:
    before_max = _finite(current.get("maximum_vif")) or 0.0
    after_max = _finite(proposed.get("maximum_vif")) or before_max
    improvement = max(0.0, before_max - after_max)
    material_reduction = max(0, int(current.get("count_above_10", 0)) - int(proposed.get("count_above_10", 0)))
    review_reduction = max(0, int(current.get("count_above_5", 0)) - int(proposed.get("count_above_5", 0)))
    objective_multiplier = {
        "reduce_max_vif": 1.6,
        "minimize_exclusions": 0.85,
        "preserve_signal": 0.9,
        "maximize_interpretability": 1.0,
        "balanced": 1.15,
    }.get(objective, 1.0)
    preservation_cost = _profile_penalty(feature, profiles, weights)
    return (
        objective_multiplier * improvement
        + material_reduction * 18.0
        + review_reduction * 4.0
        - float(family_policy["exclusion_penalty"]) * preservation_cost
    )


def _vif_delta_rows(
    before: list[dict[str, Any]],
    after: list[dict[str, Any]],
    removed: list[str],
) -> list[dict[str, Any]]:
    before_map = {str(row.get("feature")): row for row in before}
    after_map = {str(row.get("feature")): row for row in after}
    result: list[dict[str, Any]] = []
    for feature in sorted(set(before_map) | set(after_map) | set(removed)):
        before_vif = _finite(before_map.get(feature, {}).get("vif"))
        after_vif = _finite(after_map.get(feature, {}).get("vif"))
        result.append(
            {
                "feature": feature,
                "current_vif": before_vif,
                "proposed_vif": after_vif,
                "delta": (
                    after_vif - before_vif
                    if before_vif is not None and after_vif is not None
                    else None
                ),
                "proposed_action": "exclude" if feature in removed else "retain",
            }
        )
    return sorted(
        result,
        key=lambda row: (
            row["proposed_action"] != "exclude",
            -float(row["current_vif"] or 0),
            row["feature"],
        ),
    )


def _retained_profile(
    current_features: list[str],
    retained_features: list[str],
    profiles: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    current_signal = sum(abs(_finite(profiles.get(feature, {}).get("development_signal")) or 0.0) for feature in current_features)
    retained_signal = sum(abs(_finite(profiles.get(feature, {}).get("development_signal")) or 0.0) for feature in retained_features)
    def average(key: str) -> float | None:
        values = [_finite(profiles.get(feature, {}).get(key)) for feature in retained_features]
        finite = [value for value in values if value is not None]
        return sum(finite) / len(finite) if finite else None
    return {
        "development_signal_retained": retained_signal,
        "development_signal_retained_ratio": retained_signal / current_signal if current_signal else None,
        "average_missingness": average("missingness"),
        "average_special_value_burden": average("special_value_burden"),
        "average_interpretability": average("interpretability"),
        "average_production_availability": average("production_availability"),
    }


def build_vif_resolution_plan(
    *,
    frame: pd.DataFrame,
    vif_calculator: VifCalculator,
    profiles: dict[str, dict[str, Any]],
    model_family: str,
    target_threshold: float,
    objective: str,
    protected_predictors: list[str],
    allowed_actions: list[str],
    correlation_threshold: float,
    preference_weights: dict[str, float],
    maximum_removals: int,
) -> dict[str, Any]:
    """Build a non-mutating, cluster-aware VIF recommendation plan."""

    working = frame.copy(deep=True)
    original_columns = [str(column) for column in working.columns]
    original_digest = hashlib.sha256(
        pd.util.hash_pandas_object(working, index=True).values.tobytes()
    ).hexdigest()
    protected = sorted({feature for feature in protected_predictors if feature in original_columns})
    clusters = _clusters(working, correlation_threshold)
    current_rows = vif_calculator(working)
    current_summary = _summary(current_rows, len(original_columns))
    family_policy = MODEL_FAMILY_POLICY.get(model_family, MODEL_FAMILY_POLICY["mixed_bench"])
    calculation_count = 1
    simulations: list[dict[str, Any]] = []
    path: list[str] = []
    current_work = working
    current_path_rows = current_rows
    current_path_summary = current_summary

    clustered_candidates = sorted(
        {
            feature
            for cluster in clusters
            for feature in cluster["features"]
            if feature not in protected
        }
    )
    for depth in range(maximum_removals):
        if "exclude" not in allowed_actions or not clustered_candidates:
            break
        depth_results: list[dict[str, Any]] = []
        for feature in clustered_candidates:
            if feature in path or feature not in current_work.columns:
                continue
            candidate_frame = current_work.drop(columns=[feature], errors="ignore")
            candidate_rows = vif_calculator(candidate_frame)
            calculation_count += 1
            candidate_summary = _summary(candidate_rows, candidate_frame.shape[1])
            score = _candidate_score(
                current=current_path_summary,
                proposed=candidate_summary,
                feature=feature,
                profiles=profiles,
                weights=preference_weights,
                objective=objective,
                family_policy=family_policy,
            )
            result = {
                "calculation_index": calculation_count,
                "path": [*path, feature],
                "removed_feature": feature,
                "summary": candidate_summary,
                "score": score,
                "complete_vif": candidate_rows,
            }
            simulations.append(result)
            depth_results.append(result)
        if not depth_results:
            break
        depth_results.sort(
            key=lambda row: (
                -float(row["score"]),
                float(row["summary"].get("maximum_vif") or math.inf),
                row["removed_feature"],
            )
        )
        best = depth_results[0]
        path = list(best["path"])
        current_work = working.drop(columns=path, errors="ignore")
        current_path_rows = deepcopy(best["complete_vif"])
        current_path_summary = deepcopy(best["summary"])
        if (_finite(current_path_summary.get("maximum_vif")) or 0.0) <= target_threshold:
            break

    proposed_rows = current_path_rows
    proposed_summary = current_path_summary

    alternatives = sorted(
        (
            {
                "path": row["path"],
                "maximum_vif": row["summary"].get("maximum_vif"),
                "count_above_5": row["summary"].get("count_above_5"),
                "count_above_10": row["summary"].get("count_above_10"),
                "predictor_count": row["summary"].get("predictor_count"),
                "score": row["score"],
            }
            for row in simulations
        ),
        key=lambda row: (
            len(row["path"]),
            float(row["maximum_vif"] or math.inf),
            -float(row["score"]),
            row["path"],
        ),
    )[:12]

    ties: list[dict[str, Any]] = []
    single_by_cluster: dict[str, list[dict[str, Any]]] = {}
    for cluster in clusters:
        rows = [
            row
            for row in alternatives
            if len(row["path"]) == 1 and row["path"][0] in cluster["features"]
        ]
        if len(rows) < 2:
            continue
        best_max = _finite(rows[0].get("maximum_vif"))
        equivalent = [
            row for row in rows
            if best_max is not None
            and _finite(row.get("maximum_vif")) is not None
            and abs(float(row["maximum_vif"]) - best_max)
            <= max(0.05, abs(best_max) * 0.0001)
            and row.get("count_above_10") == rows[0].get("count_above_10")
        ]
        single_by_cluster[cluster["cluster_id"]] = rows
        if len(equivalent) >= 2:
            features = sorted(row["path"][0] for row in equivalent)
            inquiry_pair = {"NumInqLast6M", "NumInqLast6Mexcl7days"}.issubset(features)
            ties.append(
                {
                    "cluster_id": cluster["cluster_id"],
                    "features": features,
                    "equivalent_maximum_vif": best_max,
                    "message": (
                        "VIF alone cannot distinguish the preferred inquiry variable."
                        if inquiry_pair
                        else "VIF alone cannot distinguish the preferred variable in this cluster."
                    ),
                    "required_tie_breakers": TIE_BREAKERS,
                }
            )

    tied_features = {feature for tie in ties for feature in tie["features"]}
    cluster_recommendations: list[dict[str, Any]] = []
    proposed_combinations: list[dict[str, Any]] = []
    for cluster in clusters:
        cluster_tie = next((tie for tie in ties if tie["cluster_id"] == cluster["cluster_id"]), None)
        cluster_path = [feature for feature in path if feature in cluster["features"]]
        if cluster_tie:
            action = "defer" if "defer" in allowed_actions else "retain"
            rationale = cluster_tie["message"]
        elif (
            cluster_path
            and model_family in {"tree_ensemble", "neural_network"}
            and objective != "reduce_max_vif"
            and "defer" in allowed_actions
        ):
            action = "defer"
            rationale = (
                "The model-family policy treats the exclusion path as an alternative, "
                "not the primary recommendation, because regularized nonlinear models "
                "can tolerate predictor redundancy."
            )
        elif cluster_path:
            action = "exclude"
            rationale = "The illustrative iterative path provides the strongest weighted VIF reduction under the selected policy."
        elif "combine" in allowed_actions and len(cluster["features"]) >= 2:
            action = "combine"
            rationale = "Review an interpretable combination before excluding either correlated source predictor."
        else:
            action = "retain"
            rationale = "No permitted action improved the selected objective enough to recommend an exclusion."
        if "combine" in allowed_actions and len(cluster["features"]) >= 2:
            pair = sorted(cluster["features"])[:2]
            proposed_combinations.append(
                {
                    "cluster_id": cluster["cluster_id"],
                    "source_features": pair,
                    "status": "draft_recommendation",
                    "rationale": "Combine only if business meaning and development-population validation support a transparent derived feature.",
                }
            )
        cluster_recommendations.append(
            {
                **cluster,
                "recommended_action": action,
                "proposed_exclusions": cluster_path,
                "protected_features": [feature for feature in cluster["features"] if feature in protected],
                "tie_case": cluster_tie,
                "rationale": rationale,
            }
        )

    proposed_exclusions = [
        {
            "feature": feature,
            "status": "requires_tie_breaker" if feature in tied_features else "draft_recommendation",
            "cluster_id": next(
                (cluster["cluster_id"] for cluster in clusters if feature in cluster["features"]),
                None,
            ),
        }
        for feature in path
    ]
    unresolved = []
    material_features = {
        str(row.get("feature"))
        for row in proposed_rows
        if (_finite(row.get("vif")) or 0.0) > target_threshold
    }
    for cluster in cluster_recommendations:
        remaining = sorted(material_features.intersection(cluster["features"]))
        if remaining:
            unresolved.append(
                {
                    "cluster_id": cluster["cluster_id"],
                    "features": remaining,
                    "reason": "The illustrative path remains above the reviewer-selected VIF threshold.",
                }
            )

    retained = [feature for feature in original_columns if feature not in path]
    final_digest = hashlib.sha256(
        pd.util.hash_pandas_object(frame, index=True).values.tobytes()
    ).hexdigest()
    return {
        "current": {**current_summary, "vif": current_rows},
        "proposed": {
            **proposed_summary,
            "vif": proposed_rows,
            "illustrative_path": path,
            "target_vif_threshold": target_threshold,
            "threshold_met": (_finite(proposed_summary.get("maximum_vif")) or 0.0) <= target_threshold,
        },
        "calculation_count": {
            "governed_feature_set_calculations": 1,
            "simulated_complete_vif_recalculations": max(0, calculation_count - 1),
            "total_complete_vif_calculations": calculation_count,
            "governed_predictor_count": len(original_columns),
            "simulated_proposed_predictor_count": len(retained),
        },
        "per_feature_vif_deltas": _vif_delta_rows(current_rows, proposed_rows, path),
        "clusters": cluster_recommendations,
        "alternatives": alternatives,
        "ties": ties,
        "protected_predictors": protected,
        "proposed_exclusions": proposed_exclusions,
        "proposed_combinations": proposed_combinations,
        "remaining_unresolved_clusters": unresolved,
        "retained_profile": _retained_profile(original_columns, retained, profiles),
        "feature_profiles": profiles,
        "model_family": {
            "id": model_family,
            "label": family_policy["label"],
            "recommended_posture": family_policy["recommended_posture"],
            "implication": family_policy["implication"],
        },
        "policy": {
            "resolution_objective": objective,
            "allowed_actions": allowed_actions,
            "correlation_threshold": correlation_threshold,
            "preference_weights": preference_weights,
            "maximum_removals": maximum_removals,
        },
        "analysis_scope": {
            "target_informed_evidence": "development_population_only",
            "final_holdout_accessed": False,
            "final_holdout_used_for_selection": False,
        },
        "governed_feature_set_changed": False,
        "dataset_mutated": False,
        "explicit_statement": "The governed feature set has not changed. This plan contains recommendations only.",
        "input_frame_unchanged": original_digest == final_digest,
    }


def plan_hash(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
