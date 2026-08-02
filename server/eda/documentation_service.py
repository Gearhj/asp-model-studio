"""Governed EDA documentation and confirmation source of truth.

This service is the boundary between the EDA workspace and Model Development
Documentation (MDD).  React never writes into the MDD document store directly.
Instead it submits one canonical, scoped EDA payload here.  Drafts are mutable;
confirmed snapshots are append-only and immutable except for lifecycle status
metadata that can mark a snapshot stale.

Security and governance invariants:

* project authorization is enforced by the router before every call;
* dataset, version, target, and predictor-manifest values are assertions
  checked against the active server-governed EDA context;
* the confirmation actor and timestamp are server-derived;
* deterministic target sources must be explicitly documented as excluded;
* an approved snapshot is never silently overwritten by later draft changes;
* retrying the same confirmation is idempotent and cannot create duplicates.
"""

from __future__ import annotations

import copy
from functools import wraps
import hashlib
import json
import math
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, Optional
from urllib.parse import quote

from ..core.dataset_store import DATASTORE
from ..core.modeling_scope import active_project_id
from ..datasets.dataset_identity import active_dataset_identity
from ..evidence.evidence_identity import has_complete_canonical_dataset_lineage
from ..evidence.evidence_store import get_evidence
from ..evidence.evidence_types import CANONICAL_DATASET_LINEAGE_CONTRACT
from ..security.security_store import audit_event
from .documentation_types import EDACompletionRequest, EDADocumentationPayload
from .workspace_service import eda_workspace_service
from .workspace_types import EDAWorkspaceRequest


EDA_DOCUMENTATION_ROOT = (
    Path(__file__).resolve().parents[1] / "artifacts" / "eda_documentation"
)
_STORE_SCHEMA_VERSION = 1
_MAX_CANONICAL_PAYLOAD_BYTES = 2_000_000
_READY_REVIEWER_STATUSES = {
    "approved",
    "reviewed",
    "ready",
    "ready_for_confirmation",
}
_UNRESOLVED_DUPLICATE_DECISIONS = {
    "",
    "none",
    "pending",
    "unresolved",
    "not reviewed",
    "not_reviewed",
    "tbd",
}
_GOVERNED_FINDING_DISPOSITIONS = {
    "unresolved",
    "accepted",
    "rejected",
    "deferred",
    "documented",
    "no_action_required",
    "not_applicable",
}
_REQUIRED_FINDING_DISPOSITIONS = _GOVERNED_FINDING_DISPOSITIONS - {
    "not_applicable"
}
_GOVERNED_PARENT_REQUIREMENTS = {
    "exact_duplicate_rows": "blocker",
    "bureau_special_value_policy": "required",
    "high_iv_strong_signal_review": "required",
    "valid_value_monotonicity_review": "required",
    "inquiry_multicollinearity_cluster": "required",
    "derogatory_public_record_multicollinearity_cluster": "required",
    "delinquency_multicollinearity_cluster": "required",
    "other_correlated_feature_groups": "required",
    "target_source_exclusion": "informational",
    "balanced_target": "informational",
    "stability_segments_unavailable": "informational",
    "target_quality_review": "blocker",
    "predictor_quality_review": "required",
    "data_quality_review": "required",
    "documentation_review": "informational",
}
_SEVERITY_RANK = {"info": 0, "moderate": 1, "high": 2}
_SECTION_NAMES = (
    "overview",
    "target",
    "predictors",
    "relationships",
    "stability_and_segments",
    "findings",
)
_VOLATILE_ANALYTICAL_FIELDS = {
    "created_at",
    "generated_at",
    "updated_at",
    "started_at",
    "completed_at",
    "duration_ms",
    "elapsed_ms",
    "cache",
    "cache_hit",
    "cache_status",
    "cached_at",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    )


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _stable_analytical_content(value: Any) -> Any:
    """Remove volatile execution metadata from analytical identity only.

    Full timestamps remain in persisted MDD snapshots. They do not create a
    new analytical version, duplicate confirmation, or false stale state after
    a backend restart when artifact IDs, hashes, methods, and values match.
    """

    if isinstance(value, list):
        return [_stable_analytical_content(item) for item in value]
    if isinstance(value, dict):
        return {
            key: _stable_analytical_content(nested)
            for key, nested in value.items()
            if str(key).strip().lower() not in _VOLATILE_ANALYTICAL_FIELDS
        }
    return value


def _relationship_finding_family(*features: Any) -> str:
    text = " ".join(str(value or "").lower() for value in features)
    if "inq" in text or "inquiry" in text:
        return "inquiry_multicollinearity_cluster"
    if "derog" in text or "publicrec" in text:
        return "derogatory_public_record_multicollinearity_cluster"
    if "delq" in text or "delinquen" in text:
        return "delinquency_multicollinearity_cluster"
    return "other_correlated_feature_groups"


def _stable_child_id(
    category: str,
    title: str,
    affected_variables: Iterable[str],
    metric_label: str,
) -> str:
    """Mirror the browser's stable FNV-1a finding identity."""

    source = "|".join(
        str(value or "").strip().lower()
        for value in (
            category,
            title,
            ",".join(str(value) for value in affected_variables),
            metric_label,
        )
    )
    value = 2166136261
    for character in source:
        value ^= ord(character)
        value = (value * 16777619) & 0xFFFFFFFF
    alphabet = "0123456789abcdefghijklmnopqrstuvwxyz"
    encoded = "0"
    if value:
        digits: list[str] = []
        while value:
            value, remainder = divmod(value, 36)
            digits.append(alphabet[remainder])
        encoded = "".join(reversed(digits))
    return f"eda-finding-{encoded}"


def _authoritative_child(
    *,
    family: str,
    title: str,
    category: str,
    severity: str,
    affected_variables: Iterable[str],
    metric_label: str,
    evidence_references: Iterable[str],
    analytical_basis: str,
    metric_value: str,
    recommended_action: str,
    downstream_destination: str,
    suggested_transformations: Iterable[str],
    documentation_impact: str,
    importance: int,
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    affected = [str(value) for value in affected_variables]
    references = [str(value) for value in evidence_references]
    projection: Dict[str, Any] = {
        "id": _stable_child_id(category, title, affected, metric_label),
        "title": title,
        "category": category,
        "severity": severity,
        "affectedVariables": affected,
        "analyticalBasis": analytical_basis,
        "metricLabel": metric_label,
        "metricValue": metric_value,
        "recommendedAction": recommended_action,
        "downstreamDestination": downstream_destination,
        "suggestedTransformations": [
            str(value) for value in suggested_transformations
        ],
        "evidenceReferences": references,
        "documentationImpact": documentation_impact,
        "status": "open",
        "importance": int(importance),
    }
    projection.update(copy.deepcopy(extra or {}))
    return {
        "family": family,
        **projection,
        "authoritative_hash": _digest(projection),
    }


def _js_round(value: float) -> int:
    return int(math.floor(value + 0.5))


def _display_number(value: float, digits: int) -> str:
    rendered = f"{value:,.{digits}f}"
    if "." in rendered:
        rendered = rendered.rstrip("0").rstrip(".")
    return rendered


def _display_percent(value: float, digits: int = 1) -> str:
    return f"{_display_number(value * 100, digits)}%"


def _expected_child_inventory_from_contract(
    contract: Dict[str, Any],
    *,
    duplicate_rows: int,
    target_source_exclusions: Iterable[str],
    include_stability_not_available: bool = False,
) -> Dict[str, list[Dict[str, Any]]]:
    """Derive the immutable finding inventory from backend-owned evidence.

    Only development-population target/predictor/relationship artifacts may
    create decision-facing children. Full-population distributions, outliers,
    and structural special-value inventories are deliberately ignored.
    """

    expected: Dict[str, list[Dict[str, Any]]] = {}

    def add(child: Dict[str, Any]) -> None:
        expected.setdefault(str(child["family"]), []).append(child)

    if duplicate_rows > 0:
        add(
            _authoritative_child(
                family="exact_duplicate_rows",
                title="Exact duplicate rows require a governed treatment decision",
                category="Data quality",
                severity="high",
                affected_variables=[],
                metric_label="Duplicate rows",
                evidence_references=["findings.findings.exact_duplicate_rows"],
                analytical_basis="The development population contains rows that are exact duplicates across the governed analysis frame.",
                metric_value=f"{duplicate_rows:,}",
                recommended_action="Confirm whether these are ingestion duplicates or valid repeated observations; record exclusion or retention without mutating data from EDA.",
                downstream_destination="Feature Engineering",
                suggested_transformations=["No transformation", "Investigate further"],
                documentation_impact="The reviewer decision and rationale enter the EDA decision history and downstream queue.",
                importance=300 + min(duplicate_rows, 99),
            )
        )

    exclusions = sorted(
        str(value).strip()
        for value in target_source_exclusions
        if str(value).strip()
    )
    if exclusions:
        add(
            _authoritative_child(
                family="target_source_exclusion",
                title="Deterministic target-source fields remain excluded",
                category="Target",
                severity="info",
                affected_variables=exclusions,
                metric_label="Excluded target-source fields",
                evidence_references=[
                    "overview.predictor_authorization.target_source_excluded"
                ],
                analytical_basis="Server predictor authorization identifies deterministic target sources separately from model-eligible predictors.",
                metric_value=", ".join(exclusions),
                recommended_action="Retain the governed exclusion. Review evidence if upstream lineage changes; do not reintroduce these fields from EDA.",
                downstream_destination="Documentation",
                suggested_transformations=["No transformation"],
                documentation_impact="The exclusion is disclosed in target lineage, predictor authorization, and the approved EDA record.",
                importance=120,
                extra={
                    "targetSourceStatus": "excluded",
                    "leakageEvidence": "Deterministic source relationship documented by governed target lineage.",
                },
            )
        )

    target_artifact = contract.get("target_artifact") or {}
    target_name = str(target_artifact.get("target") or contract.get("target") or "target")
    event_rate = target_artifact.get("event_rate")
    if (
        target_artifact.get("problem_type") == "classification"
        and event_rate is not None
    ):
        rate = float(event_rate)
        rare = rate < 0.01
        imbalanced = rate < 0.1 or rate > 0.9
        family = "balanced_target" if not imbalanced else "target_quality_review"
        add(
            _authoritative_child(
                family=family,
                title=(
                    f"{target_name} has a rare observed event"
                    if rare
                    else f"{target_name} has a materially imbalanced class distribution"
                    if imbalanced
                    else f"{target_name} class balance is measurable"
                ),
                category="Target",
                severity="high" if rare else "moderate" if imbalanced else "info",
                affected_variables=[target_name],
                metric_label="Event rate",
                evidence_references=["target.governed_target_artifact.event_rate"],
                analytical_basis="Event prevalence is computed only over non-missing target-bearing rows in the governed development population.",
                metric_value=(
                    f"{_display_percent(rate)} ({int(target_artifact.get('event_count') or 0):,} events / "
                    f"{int(target_artifact.get('valid_count') or 0):,} target-bearing rows)"
                ),
                recommended_action=(
                    "Use stratified splitting and ranking, lift, calibration, and threshold metrics; do not rely on accuracy alone."
                    if rare
                    else "Carry the observed prevalence into split design and model evaluation."
                ),
                downstream_destination="Balance and Split",
                suggested_transformations=["No transformation"],
                documentation_impact="Development class balance and the selected evaluation implications enter the target narrative.",
                importance=300 if rare else 200 if imbalanced else 100,
            )
        )
    if int(target_artifact.get("missing_count") or 0) > 0:
        add(
            _authoritative_child(
                family="target_quality_review",
                title="The target contains missing values",
                category="Target",
                severity="high",
                affected_variables=[target_name],
                metric_label="Missing target values",
                evidence_references=["target.governed_target_artifact.missing_count"],
                analytical_basis="The governed development target artifact contains missing target values.",
                metric_value=f"{int(target_artifact.get('missing_count') or 0):,}",
                recommended_action="Resolve the target-quality concern before training and preserve the reviewer rationale in documentation.",
                downstream_destination="Validation",
                suggested_transformations=["Investigate further"],
                documentation_impact="The accepted disposition enters target-quality evidence and validation carry-forward.",
                importance=300,
            )
        )

    for feature, artifact in sorted(
        (contract.get("predictor_artifacts") or {}).items()
    ):
        if not isinstance(artifact, dict):
            continue
        feature = str(feature)
        iv_value = float(artifact.get("iv") or 0)
        monotonicity_value = str(
            (artifact.get("monotonicity") or {}).get("valid_value_shape")
            or ""
        ).strip()
        ordinary_bins = [
            row
            for row in ((artifact.get("iv_woe") or {}).get("bins") or [])
            if isinstance(row, dict)
            and str(row.get("bin_type") or "")
            in {"ordinary_valid_range", "ordinary_category"}
        ]
        event_rates = [
            float(row["event_rate"])
            for row in ordinary_bins
            if row.get("event_rate") is not None
        ]
        event_shape = (
            f"{len(ordinary_bins)} governed groups; "
            f"{_display_percent(min(event_rates))}\u2013{_display_percent(max(event_rates))} event rate"
            if event_rates
            else "Not available"
        )
        if iv_value >= 0.5:
            add(
                _authoritative_child(
                    family="high_iv_strong_signal_review",
                    title=f"{feature} has unusually high information value",
                    category="Predictors",
                    severity="high",
                    affected_variables=[feature],
                    metric_label="Information value",
                    evidence_references=[
                        f"predictors.governed_predictor_artifacts.{feature}.iv"
                    ],
                    analytical_basis="IV is calculated from governed development-population target-event aggregates. A high value is a review signal only and is not proof of leakage.",
                    metric_value=_display_number(iv_value, 3),
                    recommended_action="Review lineage, availability at decision time, event-rate shape, and target-source status before retaining the predictor.",
                    downstream_destination="Validation",
                    suggested_transformations=[
                        "No transformation",
                        "Binning",
                        "Investigate further",
                    ],
                    documentation_impact="The reviewer disposition, rationale, event-rate shape, and leakage evidence enter predictor findings.",
                    importance=300 + min(_js_round(iv_value * 20), 40),
                    extra={
                        "iv": iv_value,
                        "eventRateShape": event_shape,
                        "monotonicity": monotonicity_value or "Not classified",
                        "targetSourceStatus": "not_target_source",
                        "leakageEvidence": "No deterministic target-source match. High IV alone does not establish leakage.",
                    },
                )
            )
        shape = monotonicity_value.lower().replace("-", "_").replace(" ", "_")
        if "non_monotonic" in shape or "mixed" in shape:
            add(
                _authoritative_child(
                    family="valid_value_monotonicity_review",
                    title=f"{feature} has a non-monotonic target shape",
                    category="Predictors",
                    severity="moderate",
                    affected_variables=[feature],
                    metric_label="Monotonicity",
                    evidence_references=[
                        f"predictors.governed_predictor_artifacts.{feature}.monotonicity.valid_value_shape"
                    ],
                    analytical_basis="Governed development-population quantile or level aggregates change direction across the observed event-rate shape.",
                    metric_value=monotonicity_value,
                    recommended_action="Review whether governed binning improves interpretability without hiding meaningful non-linearity.",
                    downstream_destination="Feature Engineering",
                    suggested_transformations=[
                        "Binning",
                        "No transformation",
                        "Investigate further",
                    ],
                    documentation_impact="An accepted recommendation enters the feature-engineering queue as a draft, never an automatic mutation.",
                    importance=200,
                    extra={
                        "eventRateShape": event_shape,
                        "monotonicity": monotonicity_value,
                    },
                )
            )
        development_counts = (
            (artifact.get("value_classification") or {}).get(
                "development_counts"
            )
            or {}
        )
        denominator = sum(
            int(development_counts.get(key) or 0)
            for key in (
                "true_null",
                "bureau_special_value",
                "ordinary_valid_value",
                "parse_failure",
            )
        )
        missing_rate = int(development_counts.get("true_null") or 0) / max(
            denominator, 1
        )
        if missing_rate >= 0.1:
            add(
                _authoritative_child(
                    family="predictor_quality_review",
                    title=f"{feature} has material missingness",
                    category="Predictors",
                    severity="moderate",
                    affected_variables=[feature],
                    metric_label="Missing rate",
                    evidence_references=[
                        f"predictors.governed_predictor_artifacts.{feature}.value_classification.development_counts.true_null"
                    ],
                    analytical_basis="Null-only missingness is measured separately from bureau special values in the governed development population.",
                    metric_value=_display_percent(missing_rate),
                    recommended_action="Compare present and missing event rates, then select an evidence-based treatment on Missing Values.",
                    downstream_destination="Missing Values",
                    suggested_transformations=[
                        "Special-value separation",
                        "Investigate further",
                        "No transformation",
                    ],
                    documentation_impact="The accepted recommendation enters the missing-value queue as a draft.",
                    importance=200 + min(_js_round(missing_rate * 100), 30),
                )
            )
        special_groups = (
            (artifact.get("special_values") or {}).get("groups") or []
        )
        special_rate = sum(
            float(group.get("population_share") or 0)
            for group in special_groups
            if isinstance(group, dict)
        )
        if special_rate >= 0.05:
            add(
                _authoritative_child(
                    family="bureau_special_value_policy",
                    title=f"{feature} has material bureau special-value prevalence",
                    category="Predictors",
                    severity="moderate",
                    affected_variables=[feature],
                    metric_label="Special-value prevalence",
                    evidence_references=[
                        f"predictors.governed_predictor_artifacts.{feature}.special_values.groups"
                    ],
                    analytical_basis="Recognized bureau special values are counted separately from nulls and ordinary numeric values in the governed development population.",
                    metric_value=_display_percent(special_rate),
                    recommended_action="Preserve special values as labeled meaning-bearing categories unless governed evidence supports another treatment.",
                    downstream_destination="Feature Engineering",
                    suggested_transformations=[
                        "Special-value separation",
                        "Categorical conversion",
                        "No transformation",
                    ],
                    documentation_impact="The accepted semantic treatment enters feature engineering and predictor documentation.",
                    importance=200 + min(_js_round(special_rate * 100), 30),
                )
            )

    relationship = contract.get("relationship_artifact") or {}
    correlation = relationship.get("correlation") or {}
    columns = [str(value) for value in correlation.get("columns") or []]
    matrix = correlation.get("pearson_matrix") or []
    pairs: list[tuple[float, str, str, float]] = []
    for left_index, left in enumerate(columns):
        for right_index in range(left_index + 1, len(columns)):
            try:
                coefficient = float(matrix[left_index][right_index])
            except (IndexError, TypeError, ValueError):
                continue
            if math.isfinite(coefficient) and abs(coefficient) >= 0.7:
                pairs.append(
                    (
                        -abs(coefficient),
                        left,
                        columns[right_index],
                        coefficient,
                    )
                )
    for _magnitude, left, right, coefficient in sorted(pairs)[:12]:
        add(
            _authoritative_child(
                family=_relationship_finding_family(left, right),
                title=f"{left} and {right} are strongly correlated",
                category="Relationships",
                severity="high" if abs(coefficient) >= 0.9 else "moderate",
                affected_variables=[left, right],
                metric_label="Correlation",
                evidence_references=[
                    f"relationships.governed_relationship_artifact.correlation.{left}.{right}"
                ],
                analytical_basis="Pairwise Pearson correlation is calculated over governed development-population numeric predictors with pairwise non-missing support.",
                metric_value=_display_number(coefficient, 3),
                recommended_action="Inspect overlap, business meaning, and VIF before deciding to retain, drop, or combine either predictor.",
                downstream_destination="Feature Engineering",
                suggested_transformations=["No transformation", "Investigate further"],
                documentation_impact="The reviewer rationale records any retain, drop, or combine recommendation; no action is automatic.",
                importance=(
                    300 if abs(coefficient) >= 0.9 else 200
                ) + _js_round(abs(coefficient) * 25),
            )
        )
    for row in (relationship.get("vif") or [])[:12]:
        if not isinstance(row, dict):
            continue
        value = row.get("vif")
        if row.get("is_infinite") or (
            value is not None and float(value) >= 5
        ):
            feature = str(row.get("feature") or "")
            add(
                _authoritative_child(
                    family=_relationship_finding_family(feature),
                    title=f"{feature} requires multicollinearity review",
                    category="Relationships",
                    severity=(
                        "high"
                        if row.get("is_infinite") or float(value or 0) >= 10
                        else "moderate"
                    ),
                    affected_variables=[feature],
                    metric_label="VIF",
                    evidence_references=[
                        f"relationships.governed_relationship_artifact.vif.{feature}"
                    ],
                    analytical_basis="VIF is computed on the governed development-population complete-case predictor cohort; it is a relationship diagnostic, not an exclusion rule.",
                    metric_value=(
                        "Infinite"
                        if row.get("is_infinite")
                        else _display_number(float(value), 2)
                    ),
                    recommended_action="Review correlated partners and run a non-mutating exclusion scenario before recording a downstream recommendation.",
                    downstream_destination="Feature Engineering",
                    suggested_transformations=["No transformation", "Investigate further"],
                    documentation_impact="The accepted relationship decision and rationale enter the MDD relationship narrative.",
                    importance=(
                        300
                        if row.get("is_infinite") or float(value or 0) >= 10
                        else 200
                    ) + min(_js_round(float(value) if value is not None else 50), 50),
                )
            )

    if include_stability_not_available:
        add(
            _authoritative_child(
                family="stability_segments_unavailable",
                title="Stability and segment analysis is unavailable for this dataset",
                category="Stability",
                severity="info",
                affected_variables=[],
                metric_label="Available governed analyses",
                evidence_references=[
                    "stability.time_profile",
                    "stability.segment_profile",
                ],
                analytical_basis="No governed observation-date or reusable business-segment field was selected or returned. ATLAS did not invent time or segment results.",
                metric_value="0 time / 0 segment",
                recommended_action="Register an observation date or designate approved cohort, product, channel, or region metadata in a future dataset version.",
                downstream_destination="Documentation",
                suggested_transformations=["No transformation"],
                documentation_impact="The approved EDA record states that stability evidence is unavailable and does not block confirmation.",
                importance=100,
            )
        )

    return {
        family: sorted(children, key=lambda item: str(item["id"]))
        for family, children in sorted(expected.items())
    }


def _expected_parent_families_from_contract(
    contract: Dict[str, Any],
    *,
    duplicate_rows: int,
    target_source_exclusions: Iterable[str],
    event_rate: Optional[float] = None,
) -> set[str]:
    # Compatibility helper retained for existing direct tests. Event rate is
    # ignored because the contract's development-only target artifact is the
    # sole authority for target findings.
    del event_rate
    return set(
        _expected_child_inventory_from_contract(
            contract,
            duplicate_rows=duplicate_rows,
            target_source_exclusions=target_source_exclusions,
        )
    )


def _payload_digest(canonical: Dict[str, Any]) -> str:
    """Identity of the governed analytical/documentation content.

    Performance timing is persisted in each snapshot, but is deliberately not
    part of idempotency or staleness. A retry with a newly measured request
    duration must not create a second documentation version.
    """

    identity = _stable_analytical_content(copy.deepcopy(canonical))
    identity.pop("performance_metadata", None)
    return _digest(identity)


def _actor(user: Dict[str, Any]) -> Dict[str, str]:
    """Return the only actor metadata allowed in confirmation records."""

    user_id = str(user.get("userId") or user.get("user_id") or "").strip()
    if not user_id:
        raise EDADocumentationValidationError(
            "confirmation_actor_missing",
            ["The authenticated server session does not contain a user ID."],
        )
    display_name = str(
        user.get("displayName")
        or user.get("display_name")
        or user_id
    ).strip()
    return {"user_id": user_id, "display_name": display_name or user_id}


def _changed_paths(old: Any, new: Any, prefix: str = "") -> list[str]:
    """Return stable, human-readable source paths without exposing values."""

    if _digest(old) == _digest(new):
        return []
    if isinstance(old, dict) and isinstance(new, dict):
        paths: list[str] = []
        for key in sorted(set(old) | set(new)):
            path = f"{prefix}.{key}" if prefix else str(key)
            paths.extend(_changed_paths(old.get(key), new.get(key), path))
        return paths
    return [prefix or "root"]


def _narrative_only_path(path: str) -> bool:
    return any(
        marker in path
        for marker in (
            "reviewer_commentary",
            "overall_conclusion",
            "open_nonblocking_items",
            "required_conditions",
        )
    )


def _dataset_state_locked(function):
    """Serialize documentation reads/writes with dataset activation."""

    @wraps(function)
    def wrapped(*args, **kwargs):
        scoped_store = DATASTORE.current()
        with scoped_store.state_lock:
            return function(*args, **kwargs)

    return wrapped


class EDADocumentationValidationError(ValueError):
    """Structured validation failure returned by the API boundary."""

    def __init__(self, code: str, blockers: Iterable[str]) -> None:
        self.code = str(code)
        self.blockers = [str(item) for item in blockers]
        super().__init__(" ".join(self.blockers) or self.code)


class EDADocumentationService:
    """Durable project-scoped EDA documentation lifecycle."""

    def __init__(
        self,
        root: Path | None = None,
        context_provider: Optional[Callable[[str], Dict[str, Any]]] = None,
        evidence_provider: Optional[
            Callable[[str], Optional[Dict[str, Any]]]
        ] = None,
    ) -> None:
        self.root = Path(root or EDA_DOCUMENTATION_ROOT)
        self._context_provider = context_provider or self._active_context
        self._evidence_provider = evidence_provider or get_evidence
        self._lock = threading.RLock()

    # ------------------------------------------------------------------
    # Durable store
    # ------------------------------------------------------------------
    def _path(self, project_id: str) -> Path:
        # The project identity is retained inside the record and checked on
        # every read. A hash avoids path traversal and information-bearing
        # filenames without weakening project-level authorization.
        slug = hashlib.sha256(project_id.encode("utf-8")).hexdigest()
        return self.root / f"{slug}.json"

    def _blank(self, project_id: str) -> Dict[str, Any]:
        return {
            "schema_version": _STORE_SCHEMA_VERSION,
            "project_id": project_id,
            "created_at": _now(),
            "updated_at": _now(),
            "draft": None,
            "current_confirmation_id": None,
            "approvals": [],
        }

    def _read(self, project_id: str) -> Dict[str, Any]:
        path = self._path(project_id)
        if not path.exists():
            return self._blank(project_id)
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(
                "The governed EDA documentation record could not be read."
            ) from exc
        if not isinstance(value, dict) or value.get("project_id") != project_id:
            raise RuntimeError(
                "The governed EDA documentation record failed its project-scope check."
            )
        value.setdefault("draft", None)
        value.setdefault("approvals", [])
        value.setdefault("current_confirmation_id", None)
        return value

    def _write(self, record: Dict[str, Any]) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        record["updated_at"] = _now()
        path = self._path(str(record["project_id"]))
        tmp_path = path.with_suffix(f"{path.suffix}.{uuid.uuid4().hex}.tmp")
        try:
            tmp_path.write_text(
                json.dumps(record, indent=2, sort_keys=True, ensure_ascii=False),
                encoding="utf-8",
            )
            tmp_path.replace(path)
        finally:
            if tmp_path.exists():
                tmp_path.unlink()

    # ------------------------------------------------------------------
    # Active governed context
    # ------------------------------------------------------------------
    @_dataset_state_locked
    def _active_context(self, project_id: str) -> Dict[str, Any]:
        # DATASTORE is an ambient proxy keyed by the authenticated user and
        # ACTIVE_PROJECT_ID. Routers set that project context immediately after
        # authorization; assert it again at this service boundary before any
        # dataset access so an internal/misordered caller can never validate a
        # project against another project's active frame.
        scoped_project_id = str(active_project_id() or "").strip()
        if scoped_project_id != str(project_id).strip():
            raise EDADocumentationValidationError(
                "eda_project_scope_mismatch",
                [
                    "The active server modeling scope does not match the "
                    "requested EDA documentation project."
                ],
            )
        identity = active_dataset_identity(project_id)
        dataset_id = str(identity["dataset_id"])
        dataset_version_id = str(identity["dataset_version_id"])
        df, target, y, problem, event, authorization = (
            eda_workspace_service.authorized_dataset(
                EDAWorkspaceRequest(
                    project_id=project_id,
                    expected_dataset_id=dataset_id,
                    expected_dataset_version_id=dataset_version_id,
                    dataset_version=dataset_version_id,
                )
            )
        )
        manifest_id = str(authorization.get("manifest_version") or "").strip()
        if not dataset_id or not dataset_version_id or not manifest_id:
            raise EDADocumentationValidationError(
                "eda_governed_context_incomplete",
                [
                    "EDA confirmation requires a registered dataset ID, dataset "
                    "version, and server-authored predictor manifest."
                ],
            )
        contract_request = EDAWorkspaceRequest(
            project_id=project_id,
            expected_dataset_id=dataset_id,
            expected_dataset_version_id=dataset_version_id,
            dataset_version=dataset_version_id,
            target=str(target),
            event_value=event,
            problem_type=problem,
        )
        contract = eda_workspace_service._governed_contract(
            request=contract_request,
            df=df,
            target=str(target),
            event=event,
            authorization=authorization,
        )
        scoped_store = DATASTORE.current()
        development_features = scoped_store.X_train
        development_target = scoped_store.y_train
        duplicate_rows = 0
        if development_features is not None and development_target is not None:
            development_frame = development_features.copy()
            target_key = "__eda_governed_target__"
            while target_key in development_frame.columns:
                target_key = f"_{target_key}"
            development_frame[target_key] = development_target
            duplicate_rows = int(development_frame.duplicated().sum())
        target_source_exclusions = sorted(
            str(value)
            for value in authorization.get("target_source_excluded", [])
        )
        expected_child_inventory = _expected_child_inventory_from_contract(
            contract,
            duplicate_rows=duplicate_rows,
            target_source_exclusions=target_source_exclusions,
        )
        return {
            "project_id": project_id,
            "dataset_id": dataset_id,
            "dataset_version_id": dataset_version_id,
            # Transitional persisted alias; it is always the canonical immutable
            # Dataset Library version and is never sourced independently.
            "dataset_version": dataset_version_id,
            "target": str(target),
            "predictor_manifest_id": manifest_id,
            "authorized_predictors": sorted(
                str(value)
                for value in authorization.get("authorized_predictors", [])
            ),
            "target_source_exclusions": target_source_exclusions,
            "population_rows": int(len(df)),
            "duplicate_rows": duplicate_rows,
            "data_revision": int(getattr(DATASTORE, "data_revision", 0)),
            "governed_analytical_contract_id": contract.get("artifact_id"),
            "governed_analytical_contract_hash": contract.get("artifact_hash"),
            "governed_target_artifact_id": (
                contract.get("target_artifact") or {}
            ).get("artifact_id"),
            "governed_target_artifact_hash": (
                contract.get("target_artifact") or {}
            ).get("artifact_hash"),
            "governed_predictor_artifact_identity": {
                feature: {
                    "artifact_id": artifact.get("artifact_id"),
                    "artifact_hash": artifact.get("artifact_hash"),
                }
                for feature, artifact in (
                    contract.get("predictor_artifacts") or {}
                ).items()
                if isinstance(artifact, dict)
            },
            "governed_relationship_artifact_id": (
                contract.get("relationship_artifact") or {}
            ).get("artifact_id"),
            "governed_relationship_artifact_hash": (
                contract.get("relationship_artifact") or {}
            ).get("artifact_hash"),
            "expected_parent_families": sorted(expected_child_inventory),
            "expected_child_evidence_by_family": expected_child_inventory,
        }

    @staticmethod
    def _lineage(context: Dict[str, Any]) -> Dict[str, str]:
        dataset_version_id = str(context.get("dataset_version_id") or "")
        return {
            "project_id": str(context.get("project_id") or ""),
            "dataset_id": str(context.get("dataset_id") or ""),
            "dataset_version_id": dataset_version_id,
            # Compatibility output only; never recover canonical lineage from
            # an older alias-only record.
            "dataset_version": dataset_version_id,
            "target": str(context.get("target") or ""),
            "predictor_manifest_id": str(
                context.get("predictor_manifest_id") or ""
            ),
        }

    @staticmethod
    def _assert_expected_identity(
        context: Dict[str, Any],
        *,
        expected_dataset_id: Optional[str] = None,
        expected_dataset_version_id: Optional[str] = None,
    ) -> None:
        lineage = EDADocumentationService._lineage(context)
        if (
            (
                expected_dataset_id
                and str(expected_dataset_id) != lineage["dataset_id"]
            )
            or (
                expected_dataset_version_id
                and str(expected_dataset_version_id)
                != lineage["dataset_version_id"]
            )
        ):
            raise EDADocumentationValidationError(
                "eda_documentation_context_mismatch",
                [
                    "The requested EDA documentation state does not match "
                    "the exact active Dataset Library version."
                ],
            )

    def _assert_active_scope(
        self,
        payload: EDADocumentationPayload,
        context: Dict[str, Any],
    ) -> None:
        asserted = {
            "project_id": payload.project_id,
            "dataset_id": payload.dataset_id,
            "dataset_version_id": payload.dataset_version_id,
            "target": payload.target,
            "predictor_manifest_id": payload.predictor_manifest_id,
        }
        current = self._lineage(context)
        labels = {
            "project_id": "project",
            "dataset_id": "dataset",
            "dataset_version_id": "dataset version",
            "target": "target",
            "predictor_manifest_id": "predictor manifest",
        }
        mismatches = [
            (
                f"The submitted {labels[key]} does not match the active "
                "server-governed EDA context."
            )
            for key in asserted
            if str(asserted[key]) != str(current[key])
        ]
        if (
            payload.dataset_version
            and payload.dataset_version != current["dataset_version_id"]
        ):
            mismatches.append(
                "The submitted legacy dataset version alias does not mirror "
                "the active immutable dataset version."
            )
        if mismatches:
            raise EDADocumentationValidationError(
                "eda_documentation_context_mismatch",
                mismatches,
            )

    # ------------------------------------------------------------------
    # Canonicalization and readiness
    # ------------------------------------------------------------------
    def _canonical_evidence_references(
        self,
        references: Iterable[Dict[str, Any]],
        context: Dict[str, Any],
    ) -> list[Dict[str, Any]]:
        """Resolve evidence IDs against the exact governed dataset version.

        Evidence metadata supplied by the browser is display-only and cannot
        establish lineage. Each referenced item is reloaded from the governed
        evidence store, checked against the active canonical triple, and then
        projected into the documentation snapshot from server-owned values.
        """

        expected = self._lineage(context)
        expected_identity = {
            "project_id": expected["project_id"],
            "dataset_id": expected["dataset_id"],
            "dataset_version_id": expected["dataset_version_id"],
        }
        invalid_ids: list[str] = []
        canonical: list[Dict[str, Any]] = []
        seen: set[str] = set()

        for reference in references:
            evidence_id = str(reference.get("evidence_id") or "").strip()
            if evidence_id in seen:
                continue
            seen.add(evidence_id)
            stored = self._evidence_provider(evidence_id)
            stored_id = (
                str(
                    (stored or {}).get("evidenceId")
                    or (stored or {}).get("evidence_id")
                    or ""
                ).strip()
                if isinstance(stored, dict)
                else ""
            )
            identity_matches = bool(
                isinstance(stored, dict)
                and stored_id == evidence_id
                and has_complete_canonical_dataset_lineage(stored)
                and all(
                    str(stored.get(key) or "").strip() == value
                    for key, value in expected_identity.items()
                )
            )

            # Canonical evidence writers mirror the triple into lineage for
            # graph compatibility. Treat a present contradictory alias as
            # corruption instead of silently preferring either representation.
            lineage = (
                stored.get("lineage")
                if isinstance(stored, dict)
                and isinstance(stored.get("lineage"), dict)
                else {}
            )
            compatibility_claims = (
                ("project_id", "project_id"),
                ("dataset_id", "dataset_id"),
                ("dataset_version_id", "dataset_version_id"),
                ("projectId", "project_id"),
                ("datasetId", "dataset_id"),
                ("datasetVersion", "dataset_version_id"),
            )
            if identity_matches:
                identity_matches = all(
                    not str(lineage.get(alias) or "").strip()
                    or str(lineage.get(alias) or "").strip()
                    == expected_identity[canonical_key]
                    for alias, canonical_key in compatibility_claims
                )
                nested_contract = str(
                    lineage.get("lineage_contract") or ""
                ).strip()
                identity_matches = identity_matches and (
                    not nested_contract
                    or nested_contract
                    == CANONICAL_DATASET_LINEAGE_CONTRACT
                )

            if not identity_matches:
                invalid_ids.append(evidence_id)
                continue

            checksum = (
                stored.get("checksum")
                or stored.get("artifactChecksum")
                or stored.get("artifact_checksum")
                or lineage.get("artifactChecksum")
                or lineage.get("artifact_checksum")
            )
            canonical.append(
                {
                    "evidence_id": evidence_id,
                    "title": str(stored.get("title") or evidence_id)[:500],
                    "uri": (
                        "/evidence-graph?evidenceId="
                        f"{quote(evidence_id, safe='')}"
                    ),
                    "checksum": (
                        str(checksum)[:256] if checksum is not None else None
                    ),
                    "evidence_type": (
                        str(
                            stored.get("evidenceType")
                            or stored.get("evidence_type")
                            or ""
                        )[:120]
                        or None
                    ),
                }
            )

        if invalid_ids:
            raise EDADocumentationValidationError(
                "eda_evidence_context_mismatch",
                [
                    "Every EDA evidence reference must resolve to a governed "
                    "evidence item for the exact active project, dataset, and "
                    "immutable dataset version."
                ],
            )
        return sorted(canonical, key=lambda item: item["evidence_id"])

    def _canonical_payload(
        self,
        payload: EDADocumentationPayload,
        context: Dict[str, Any],
    ) -> Dict[str, Any]:
        value = payload.model_dump(mode="json")
        # Persist the legacy alias only as a projection of the canonical
        # immutable version; the browser can never define it independently.
        value["dataset_version"] = value["dataset_version_id"]
        value["evidence_references"] = self._canonical_evidence_references(
            value.get("evidence_references", []),
            context,
        )
        # A section-level audit is display/documentation material only. Build
        # it from the typed, extra-forbid top-level actions so arbitrary
        # browser fields such as actor_hint/occurred_at can never survive as
        # authoritative-looking audit identity or time. Confirmation projects
        # the actual authenticated actor and server time back into both views.
        sections = value.setdefault("sections", {})
        finding_section = sections.setdefault("findings", {})
        finding_section["bulk_disposition_audit"] = copy.deepcopy(
            value.get("bulk_disposition_actions", [])
        )
        encoded = _canonical_json(value).encode("utf-8")
        if len(encoded) > _MAX_CANONICAL_PAYLOAD_BYTES:
            raise EDADocumentationValidationError(
                "eda_documentation_payload_too_large",
                [
                    "The EDA documentation payload exceeds the governed "
                    "two-megabyte limit."
                ],
            )
        seen_decisions: set[str] = set()
        decisions = []
        for item in value.get("decisions", []):
            decision_id = str(item.get("decision_id") or "")
            if decision_id in seen_decisions:
                continue
            seen_decisions.add(decision_id)
            decisions.append(item)
        value["decisions"] = sorted(
            decisions,
            key=lambda item: str(item.get("decision_id") or ""),
        )
        return value

    @staticmethod
    def _selected_predictors(sections: Dict[str, Any]) -> list[str]:
        predictor_section = sections.get("predictors")
        if not isinstance(predictor_section, dict):
            return []
        raw = (
            predictor_section.get("selected_predictors")
            or predictor_section.get("selectedPredictors")
            or predictor_section.get("predictor_inventory")
            or []
        )
        if not isinstance(raw, list):
            return []
        selected: list[str] = []
        for value in raw:
            if isinstance(value, dict):
                name = value.get("feature") or value.get("name")
            else:
                name = value
            if name is not None and str(name).strip():
                selected.append(str(name).strip())
        return sorted(set(selected))

    def _readiness_blockers(
        self,
        canonical: Dict[str, Any],
        context: Dict[str, Any],
    ) -> list[str]:
        blockers: list[str] = []
        sections = canonical.get("sections") or {}
        for name in _SECTION_NAMES:
            value = sections.get(name)
            if not isinstance(value, dict) or not value:
                blockers.append(
                    f"The documentation-ready {name.replace('_', ' ')} section is required."
                )

        submitted_exclusions = sorted(
            str(value)
            for value in canonical.get("target_source_exclusions", [])
        )
        current_exclusions = sorted(
            str(value)
            for value in context.get("target_source_exclusions", [])
        )
        if submitted_exclusions != current_exclusions:
            blockers.append(
                "The documented target-source exclusions do not exactly match "
                "the server-authorized predictor manifest."
            )

        selected = set(self._selected_predictors(sections))
        authorized = set(context.get("authorized_predictors", []))
        target_sources = set(current_exclusions)
        unauthorized = sorted(selected - authorized)
        unsafe = sorted(selected & target_sources)
        if unauthorized:
            blockers.append(
                "The documentation contains predictors that are not authorized "
                f"by the current manifest: {', '.join(unauthorized)}."
            )
        if unsafe:
            blockers.append(
                "Deterministic target sources cannot appear in the selected "
                f"predictor inventory: {', '.join(unsafe)}."
            )

        if int(context.get("duplicate_rows") or 0) > 0:
            decision = str(canonical.get("duplicate_decision") or "").strip()
            if decision.lower() in _UNRESOLVED_DUPLICATE_DECISIONS:
                blockers.append(
                    "A documented duplicate-row treatment decision is required "
                    "because the active dataset contains duplicates."
                )

        unresolved = canonical.get("unresolved_blocking_findings") or []
        if unresolved:
            blockers.append(
                f"{len(unresolved)} unresolved blocking EDA finding(s) must be "
                "resolved before confirmation."
            )

        reviewer_status = str(
            canonical.get("reviewer_status") or ""
        ).strip().lower()
        if reviewer_status not in _READY_REVIEWER_STATUSES:
            blockers.append(
                "Reviewer status must be reviewed or approved before EDA confirmation."
            )
        if canonical.get("governance_contract_version") == "eda-governance-v2":
            blockers.extend(self._governed_artifact_blockers(canonical, context))
            blockers.extend(self._governance_v2_blockers(canonical, context))
        return blockers

    @staticmethod
    def _governed_artifact_blockers(
        canonical: Dict[str, Any],
        context: Dict[str, Any],
    ) -> list[str]:
        blockers: list[str] = []
        expected_contract_id = str(
            context.get("governed_analytical_contract_id") or ""
        )
        if not expected_contract_id:
            return blockers
        sections = canonical.get("sections") or {}
        contract = (sections.get("overview") or {}).get(
            "governed_analytical_contract"
        ) or {}
        if (
            str(contract.get("artifact_id") or "") != expected_contract_id
            or str(contract.get("artifact_hash") or "")
            != str(context.get("governed_analytical_contract_hash") or "")
        ):
            blockers.append(
                "The EDA documentation must use the exact current governed analytical contract artifact."
            )
        target_artifact = (sections.get("target") or {}).get(
            "governed_target_artifact"
        ) or {}
        if (
            str(target_artifact.get("artifact_id") or "")
            != str(context.get("governed_target_artifact_id") or "")
            or str(target_artifact.get("artifact_hash") or "")
            != str(context.get("governed_target_artifact_hash") or "")
        ):
            blockers.append(
                "The EDA documentation target artifact does not exactly match the current governed analytical contract."
            )
        submitted_predictors = (sections.get("predictors") or {}).get(
            "governed_predictor_artifacts"
        )
        expected_predictors = (
            context.get("governed_predictor_artifact_identity") or {}
        )
        submitted_identity = {
            str(feature): {
                "artifact_id": (artifact or {}).get("artifact_id"),
                "artifact_hash": (artifact or {}).get("artifact_hash"),
            }
            for feature, artifact in (
                submitted_predictors.items()
                if isinstance(submitted_predictors, dict)
                else []
            )
            if isinstance(artifact, dict)
        }
        if submitted_identity != expected_predictors:
            blockers.append(
                "The EDA documentation predictor artifacts do not exactly match the current governed analytical contract."
            )
        relationship = (sections.get("relationships") or {}).get(
            "governed_relationship_artifact"
        ) or {}
        if (
            str(relationship.get("artifact_id") or "")
            != str(context.get("governed_relationship_artifact_id") or "")
            or str(relationship.get("artifact_hash") or "")
            != str(context.get("governed_relationship_artifact_hash") or "")
        ):
            blockers.append(
                "The EDA documentation relationship artifact does not exactly match the current governed analytical contract."
            )
        return blockers

    @staticmethod
    def _governance_v2_blockers(
        canonical: Dict[str, Any],
        context: Dict[str, Any],
    ) -> list[str]:
        blockers: list[str] = []
        reviewer = canonical.get("reviewer_record")
        if not isinstance(reviewer, dict):
            return ["The governed reviewer record is required."]
        if not str(reviewer.get("overall_conclusion") or "").strip():
            blockers.append("Reviewer conclusion is required.")
        if not str(reviewer.get("reviewer_commentary") or "").strip():
            blockers.append("Reviewer commentary is required.")
        overall_status = str(
            reviewer.get("overall_review_status") or ""
        ).strip().lower()
        if overall_status not in {"accepted", "accepted_with_conditions"}:
            blockers.append(
                "Overall EDA status must be Accepted or Accepted with Conditions."
            )
        if (
            overall_status == "accepted_with_conditions"
            and not reviewer.get("required_conditions")
        ):
            blockers.append(
                "Accepted with Conditions requires at least one documented condition."
            )

        sections = canonical.get("sections") or {}
        findings = sections.get("findings") or {}
        parent_rows = findings.get("parent_findings") or []
        if not isinstance(parent_rows, list):
            blockers.append("Governed parent findings must be a structured list.")
            parent_rows = []
        if not parent_rows:
            blockers.append(
                "The current governed parent-finding inventory is required and cannot be empty."
            )
        stability = sections.get("stability_and_segments") or {}
        expected_inventory = copy.deepcopy(
            context.get("expected_child_evidence_by_family") or {}
        )
        if stability.get("analysis_status") == "not_available":
            stability_inventory = _expected_child_inventory_from_contract(
                {},
                duplicate_rows=0,
                target_source_exclusions=[],
                include_stability_not_available=True,
            )
            expected_inventory.update(stability_inventory)
        expected_families = {
            str(value).strip()
            for value in expected_inventory
            if str(value).strip()
        }
        unresolved_required = 0
        required_count = 0
        informational_count = 0
        eligible_count = 0
        child_count = 0
        seen_parent_ids: set[str] = set()
        seen_families: set[str] = set()
        seen_child_ids: set[str] = set()
        parent_by_id: Dict[str, Dict[str, Any]] = {}
        for row in parent_rows:
            if not isinstance(row, dict):
                blockers.append("Every parent finding must be a structured record.")
                continue
            parent_id = str(row.get("parent_id") or "").strip()
            if not parent_id or parent_id in seen_parent_ids:
                blockers.append("Parent finding IDs must be present and unique.")
                continue
            seen_parent_ids.add(parent_id)
            family = str(row.get("family") or "").strip()
            requirement = _GOVERNED_PARENT_REQUIREMENTS.get(family)
            if requirement is None:
                blockers.append(
                    f"Parent finding {parent_id} uses an unknown governed family and cannot be confirmed."
                )
                unresolved_required += 1
                continue
            seen_families.add(family)
            expected_parent_id = f"eda-parent-{family.replace('_', '-')}"
            if parent_id != expected_parent_id:
                blockers.append(
                    f"Parent finding {parent_id} does not match the canonical ID for {family}."
                )
            submitted_requirement = str(row.get("requirement") or "").strip()
            if submitted_requirement != requirement:
                blockers.append(
                    f"Parent finding {parent_id} cannot change its canonical {requirement} requirement."
                )
            if requirement == "informational":
                informational_count += 1
            else:
                required_count += 1
            disposition = str(row.get("reviewer_disposition") or "unresolved")
            allowed_dispositions = {
                str(value).strip()
                for value in (row.get("allowed_dispositions") or [])
                if str(value).strip()
            }
            rationale = str(row.get("reviewer_rationale") or "").strip()
            if row.get("mutation_applied") is not False:
                blockers.append(
                    f"Parent finding {parent_id} cannot mutate the dataset or feature set."
                )
            child_ids = row.get("child_ids") or []
            child_evidence = row.get("child_evidence") or []
            if not isinstance(child_ids, list) or not isinstance(
                child_evidence, list
            ) or not child_ids:
                blockers.append(
                    f"Parent finding {parent_id} requires nonempty immutable child evidence."
                )
                child_ids = []
                child_evidence = []
            evidence_ids = {
                str(item.get("id") or "")
                for item in child_evidence
                if isinstance(item, dict)
            }
            if set(str(value) for value in child_ids) != evidence_ids:
                blockers.append(
                    f"Parent finding {parent_id} must preserve every immutable child evidence record."
                )
            expected_children = expected_inventory.get(family) or []
            expected_by_id = {
                str(item.get("id") or ""): item
                for item in expected_children
                if isinstance(item, dict)
            }
            submitted_by_id = {
                str(item.get("id") or ""): item
                for item in child_evidence
                if isinstance(item, dict)
            }
            submitted_id_set = set(str(value) for value in child_ids)
            if submitted_id_set != set(expected_by_id):
                blockers.append(
                    f"Parent finding {parent_id} does not exactly cover the backend-authoritative immutable child inventory."
                )
            for child_id in sorted(set(submitted_by_id).intersection(expected_by_id)):
                submitted_child = submitted_by_id[child_id]
                expected_child = expected_by_id[child_id]
                expected_payload = {
                    key: value
                    for key, value in expected_child.items()
                    if key not in {"family", "authoritative_hash"}
                }
                if (
                    set(submitted_child) != set(expected_payload)
                    or _digest(submitted_child)
                    != str(expected_child.get("authoritative_hash") or "")
                ):
                    blockers.append(
                        f"Immutable child evidence {child_id} does not exactly match the complete backend-authoritative analytical record."
                    )
            normalized_child_ids = {str(value) for value in child_ids}
            if seen_child_ids.intersection(normalized_child_ids):
                blockers.append(
                    "Immutable child evidence cannot be assigned to more than one parent finding."
                )
            seen_child_ids.update(normalized_child_ids)
            child_count += len(normalized_child_ids)
            child_severities = [
                str(item.get("severity") or "").strip().lower()
                for item in child_evidence
                if isinstance(item, dict)
            ]
            if any(value not in _SEVERITY_RANK for value in child_severities):
                blockers.append(
                    f"Parent finding {parent_id} contains an invalid immutable child severity."
                )
            derived_severity = max(
                child_severities or ["high"],
                key=lambda value: _SEVERITY_RANK.get(value, 2),
            )
            if str(row.get("severity") or "").strip().lower() != derived_severity:
                blockers.append(
                    f"Parent finding {parent_id} severity must equal the maximum immutable child-evidence severity."
                )
            canonical_allowed = (
                _GOVERNED_FINDING_DISPOSITIONS
                if requirement == "informational"
                else _REQUIRED_FINDING_DISPOSITIONS
            )
            if (
                allowed_dispositions != canonical_allowed
                or disposition not in _GOVERNED_FINDING_DISPOSITIONS
                or disposition not in canonical_allowed
            ):
                blockers.append(
                    f"Parent finding {parent_id} has a disposition outside its governed allowed dispositions."
                )
                if requirement != "informational":
                    unresolved_required += 1
                continue
            if requirement == "informational":
                system_disposition = {
                    "target_source_exclusion": "documented",
                    "balanced_target": "no_action_required",
                    "stability_segments_unavailable": "not_applicable",
                    "documentation_review": "documented",
                }.get(family)
                if system_disposition and disposition != system_disposition:
                    blockers.append(
                        f"Informational parent finding {parent_id} must retain its canonical system disposition."
                    )
                eligible_count += 1
                parent_by_id[parent_id] = row
                continue
            eligible = disposition in {
                "accepted",
                "rejected",
                "deferred",
                "documented",
                "no_action_required",
            }
            if requirement == "blocker" and disposition == "deferred":
                eligible = False
            requires_rationale = (
                disposition in {"rejected", "deferred"}
                or requirement == "blocker"
                or (disposition == "accepted" and derived_severity == "high")
            )
            if requires_rationale and not rationale:
                eligible = False
            if row.get("eligible_for_completion") is not eligible:
                blockers.append(
                    f"Parent finding {parent_id} submitted an incorrect completion-eligibility assertion."
                )
            if not eligible:
                unresolved_required += 1
            else:
                eligible_count += 1
            parent_by_id[parent_id] = row
        missing_families = sorted(expected_families - seen_families)
        if missing_families:
            blockers.append(
                "The parent-finding inventory omitted current governed families: "
                + ", ".join(missing_families)
                + "."
            )
        unexpected_families = sorted(seen_families - expected_families)
        if unexpected_families:
            blockers.append(
                "The parent-finding inventory contains families that are not present in the current governed evidence: "
                + ", ".join(unexpected_families)
                + "."
            )

        submitted_counts = {
            "required_parent_finding_count": required_count,
            "unresolved_parent_finding_count": unresolved_required,
            "eligible_parent_finding_count": eligible_count,
            "informational_parent_finding_count": informational_count,
            "child_evidence_count": child_count,
        }
        for field, derived in submitted_counts.items():
            try:
                submitted = int(findings.get(field))
            except (TypeError, ValueError):
                submitted = -1
            if submitted != derived:
                blockers.append(
                    f"The submitted {field.replace('_', ' ')} does not match the authoritative parent inventory."
                )

        finding_groups = findings.get("finding_groups") or []
        grouped_families = {
            str(item.get("family") or "").strip()
            for item in finding_groups
            if isinstance(item, dict)
        }
        if grouped_families != seen_families:
            blockers.append(
                "Finding groups must exactly cover the current governed parent-finding families."
            )

        expected_carry_forward = {
            parent_id
            for parent_id, row in parent_by_id.items()
            if row.get("reviewer_disposition") in {"accepted", "deferred"}
            and str(row.get("downstream_destination") or "").strip()
        }
        submitted_carry_forward: set[str] = set()
        for item in findings.get("carry_forward") or []:
            if not isinstance(item, dict):
                blockers.append(
                    "Every carry-forward recommendation must be a structured parent decision."
                )
                continue
            parent_id = str(item.get("parent_id") or "").strip()
            if (
                not parent_id
                or "finding_id" in item
                or item.get("mutation_applied") is not False
            ):
                blockers.append(
                    "Carry-forward recommendations must reference a non-mutating governed parent decision only."
                )
                continue
            submitted_carry_forward.add(parent_id)
        if submitted_carry_forward != expected_carry_forward:
            blockers.append(
                "Carry-forward recommendations must exactly match accepted or deferred parent decisions with a downstream destination."
            )
        if unresolved_required:
            blockers.append(
                f"{unresolved_required} required parent finding(s) need an eligible governed disposition and rationale."
            )

        if stability.get("analysis_status") == "not_available":
            limitation = stability.get("limitation") or {}
            if (
                limitation.get("status") != "not_applicable"
                or limitation.get("blocks_completion") is not False
                or limitation.get("reason")
                != "no_approved_field_or_comparison_population"
            ):
                blockers.append(
                    "Unavailable Stability and Segments analysis requires a nonblocking structured limitation."
                )

        for action in canonical.get("bulk_disposition_actions") or []:
            if not str(action.get("rationale") or "").strip():
                blockers.append("Every bulk disposition requires a rationale.")
            if action.get("mutation_applied") is not False:
                blockers.append("Bulk dispositions cannot mutate the governed dataset.")
        return blockers

    @staticmethod
    def _changed_sections(
        approved: Optional[Dict[str, Any]],
        canonical: Dict[str, Any],
    ) -> list[str]:
        if not approved:
            return list(_SECTION_NAMES)
        old_sections = approved.get("sections") or {}
        new_sections = canonical.get("sections") or {}
        return [
            name
            for name in _SECTION_NAMES
            if _digest(_stable_analytical_content(old_sections.get(name)))
            != _digest(_stable_analytical_content(new_sections.get(name)))
        ]

    @staticmethod
    def _mdd_staleness(
        approved: Optional[Dict[str, Any]],
        canonical: Dict[str, Any],
        changed_sections: list[str],
    ) -> Dict[str, Any]:
        old_sections = (approved or {}).get("sections") or {}
        new_sections = canonical.get("sections") or {}
        stale_sections = []
        changed_source_fields: list[str] = []
        for section in changed_sections:
            paths = _changed_paths(
                _stable_analytical_content(old_sections.get(section)),
                _stable_analytical_content(new_sections.get(section)),
                section,
            )
            classification = (
                "narrative_only"
                if paths and all(_narrative_only_path(path) for path in paths)
                else "analytical"
            )
            stale_sections.append(
                {
                    "section": section,
                    "classification": classification,
                    "changed_source_fields": paths,
                }
            )
            changed_source_fields.extend(paths)
        lineage_fields = _changed_paths(
            EDADocumentationService._lineage(approved or {}),
            EDADocumentationService._lineage(canonical),
            "governed_lineage",
        )
        changed_source_fields.extend(lineage_fields)
        analytical = bool(lineage_fields) or any(
            item["classification"] == "analytical" for item in stale_sections
        )
        narrative = bool(stale_sections) and not analytical
        return {
            "stale_sections": stale_sections,
            "changed_source_fields": sorted(set(changed_source_fields)),
            "analytical_staleness": analytical,
            "narrative_only_staleness": narrative,
            "review_action": "Review stale documentation",
        }

    @staticmethod
    def _structured_mdd_payload(canonical: Dict[str, Any]) -> Dict[str, Any]:
        sections = copy.deepcopy(canonical.get("sections") or {})
        overview = sections.get("overview") or {}
        predictors = sections.get("predictors") or {}
        relationships = sections.get("relationships") or {}
        return {
            "schema_version": "eda-mdd-v2",
            "source_identity": EDADocumentationService._lineage(canonical),
            "governed_analytical_contract": copy.deepcopy(
                overview["governed_analytical_contract"]
                if "governed_analytical_contract" in overview
                else canonical.get("governed_analytical_contract")
            ),
            "governed_target_artifact": copy.deepcopy(
                (sections.get("target") or {}).get(
                    "governed_target_artifact"
                )
            ),
            "governed_predictor_artifacts": copy.deepcopy(
                predictors["governed_predictor_artifacts"]
                if "governed_predictor_artifacts" in predictors
                else canonical.get("governed_predictor_artifacts")
            ),
            "governed_relationship_artifact": copy.deepcopy(
                relationships["governed_relationship_artifact"]
                if "governed_relationship_artifact" in relationships
                else canonical.get("governed_relationship_artifact")
            ),
            "target_identity": copy.deepcopy(sections.get("target") or {}),
            "predictor_analysis": copy.deepcopy(predictors),
            "relationships": copy.deepcopy(relationships),
            "stability_limitation": copy.deepcopy(
                (sections.get("stability_and_segments") or {}).get("limitation")
            ),
            "findings_and_dispositions": copy.deepcopy(
                sections.get("findings") or {}
            ),
            "reviewer_record": copy.deepcopy(canonical.get("reviewer_record")),
            "bulk_disposition_actions": copy.deepcopy(
                canonical.get("bulk_disposition_actions") or []
            ),
            "evidence_references": copy.deepcopy(
                canonical.get("evidence_references") or []
            ),
            "automatic_mutation_applied": False,
        }

    def _completion_stage(
        self,
        stage: str,
        *,
        artifact_count: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Test seam for an all-or-nothing governed completion sequence."""

        value: Dict[str, Any] = {"stage": stage, "status": "completed"}
        if artifact_count is not None:
            value["artifact_count"] = int(artifact_count)
        return value

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    def _current_approval(
        self,
        record: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        confirmation_id = record.get("current_confirmation_id")
        return next(
            (
                item
                for item in reversed(record.get("approvals", []))
                if item.get("confirmation_id") == confirmation_id
            ),
            None,
        )

    def _mark_current_stale(
        self,
        record: Dict[str, Any],
        reason: str,
        *,
        upstream_revision: Optional[str] = None,
        changed_source_fields: Optional[list[str]] = None,
        stale_sections: Optional[list[Dict[str, Any]]] = None,
    ) -> bool:
        current = self._current_approval(record)
        if current is None:
            return False
        normalized_reason = str(reason).strip()
        reasons = current.setdefault("stale_reasons", [])
        changed = False
        if normalized_reason and normalized_reason not in reasons:
            reasons.append(normalized_reason)
            changed = True
        if current.get("status") != "stale":
            current["status"] = "stale"
            current["stale_at"] = _now()
            current["stale_reason"] = normalized_reason
            current["next_step_eligible"] = False
            changed = True
        if upstream_revision and current.get("stale_upstream_revision") != upstream_revision:
            current["stale_upstream_revision"] = upstream_revision
            changed = True
        if changed_source_fields or stale_sections:
            fields = sorted(set(changed_source_fields or []))
            sections = copy.deepcopy(stale_sections or [])
            structured = {
                "stale_sections": sections,
                "changed_source_fields": fields,
                "analytical_staleness": any(
                    item.get("classification") == "analytical"
                    for item in sections
                )
                or any(field.startswith("governed_lineage.") for field in fields),
                "narrative_only_staleness": bool(sections)
                and all(
                    item.get("classification") == "narrative_only"
                    for item in sections
                ),
                "review_action": "Review stale documentation",
            }
            if current.get("mdd_staleness") != structured:
                current["mdd_staleness"] = structured
                changed = True
        return changed

    def _auto_invalidate(
        self,
        record: Dict[str, Any],
        context: Dict[str, Any],
    ) -> bool:
        current = self._current_approval(record)
        if not current or current.get("status") == "stale":
            return False
        active_lineage = self._lineage(context)
        approved_lineage = self._lineage(current)
        changed_fields = [
            key
            for key in active_lineage
            if active_lineage[key] != approved_lineage[key]
        ]
        if not changed_fields:
            return False
        readable = ", ".join(name.replace("_", " ") for name in changed_fields)
        return self._mark_current_stale(
            record,
            f"The active governed EDA lineage changed after confirmation ({readable}).",
            upstream_revision=str(context.get("data_revision") or ""),
            changed_source_fields=[
                f"governed_lineage.{field}" for field in changed_fields
            ],
            stale_sections=[
                {
                    "section": "overview",
                    "classification": "analytical",
                    "changed_source_fields": [
                        f"governed_lineage.{field}" for field in changed_fields
                    ],
                }
            ],
        )

    @_dataset_state_locked
    def upsert_draft(
        self,
        payload: EDADocumentationPayload,
        user: Dict[str, Any],
    ) -> Dict[str, Any]:
        actor = _actor(user)
        context = self._context_provider(payload.project_id)
        self._assert_active_scope(payload, context)
        canonical = self._canonical_payload(payload, context)
        payload_digest = _payload_digest(canonical)
        blockers = self._readiness_blockers(canonical, context)
        with self._lock:
            record = self._read(payload.project_id)
            self._auto_invalidate(record, context)
            current = self._current_approval(record)
            changed_sections = self._changed_sections(current, canonical)
            mdd_staleness = self._mdd_staleness(
                current,
                canonical,
                changed_sections,
            )
            draft = {
                **copy.deepcopy(canonical),
                "status": "ready_for_confirmation" if not blockers else "draft",
                "payload_digest": payload_digest,
                "drafted_at": _now(),
                "drafted_by": actor["user_id"],
                "drafted_by_display_name": actor["display_name"],
                "changed_sections": changed_sections,
                "mdd_staleness": mdd_staleness,
                "mdd_structured_payload": self._structured_mdd_payload(canonical),
                "validation": {
                    "ready_for_confirmation": not blockers,
                    "blockers": blockers,
                },
                "governed_context": copy.deepcopy(context),
            }
            record["draft"] = draft
            if (
                current
                and current.get("status") == "confirmed"
                and current.get("payload_digest") != payload_digest
            ):
                self._mark_current_stale(
                    record,
                    "Draft EDA documentation changed after the approved confirmation.",
                    upstream_revision=payload.eda_analysis_version,
                    changed_source_fields=mdd_staleness[
                        "changed_source_fields"
                    ],
                    stale_sections=mdd_staleness["stale_sections"],
                )
            self._write(record)

        audit_event(
            "eda.documentation.draft.saved",
            "eda_documentation",
            payload.project_id,
            "success",
            user_id=actor["user_id"],
            metadata={
                "projectId": payload.project_id,
                "datasetId": payload.dataset_id,
                "datasetVersionId": payload.dataset_version_id,
                "datasetVersion": payload.dataset_version_id,
                "status": draft["status"],
                "changedSections": changed_sections,
                "changedSourceFields": mdd_staleness[
                    "changed_source_fields"
                ],
            },
        )
        return self.get_state(payload.project_id, context=context)

    @_dataset_state_locked
    def confirm(
        self,
        payload: EDADocumentationPayload,
        user: Dict[str, Any],
    ) -> Dict[str, Any]:
        actor = _actor(user)
        context = self._context_provider(payload.project_id)
        self._assert_active_scope(payload, context)
        canonical = self._canonical_payload(payload, context)
        blockers = self._readiness_blockers(canonical, context)
        if blockers:
            raise EDADocumentationValidationError(
                "eda_confirmation_blocked",
                blockers,
            )
        payload_digest = _payload_digest(canonical)

        with self._lock:
            record = self._read(payload.project_id)
            self._auto_invalidate(record, context)
            current = self._current_approval(record)
            if (
                current
                and current.get("status") == "confirmed"
                and current.get("payload_digest") == payload_digest
                and self._lineage(current) == self._lineage(context)
            ):
                # Network retries and duplicate clicks return the original
                # confirmation; no second approval/history row is created.
                record["draft"] = None
                self._write(record)
                return self._confirmation_response(
                    current,
                    idempotent=True,
                )

            documentation_version = len(record.get("approvals", [])) + 1
            confirmed_at = _now()
            completion_id = f"eda-complete-{payload_digest[:20]}"
            confirmation_id = (
                f"eda-confirm-{documentation_version:04d}-"
                f"{payload_digest[:16]}"
            )
            persisted = copy.deepcopy(canonical)
            reviewer_record = copy.deepcopy(persisted.get("reviewer_record") or {})
            reviewer_record.update(
                {
                    "reviewer_identity": actor["user_id"],
                    "reviewer_display_name": actor["display_name"],
                    "reviewed_at": confirmed_at,
                }
            )
            persisted["reviewer_record"] = reviewer_record
            persisted["bulk_disposition_actions"] = [
                {
                    **copy.deepcopy(action),
                    "actor": actor["user_id"],
                    "actor_display_name": actor["display_name"],
                    "timestamp": confirmed_at,
                }
                for action in persisted.get("bulk_disposition_actions", [])
            ]
            (
                persisted.setdefault("sections", {})
                .setdefault("findings", {})
            )["bulk_disposition_audit"] = copy.deepcopy(
                persisted["bulk_disposition_actions"]
            )
            carry_forward = (
                (persisted.get("sections") or {})
                .get("findings", {})
                .get("carry_forward", [])
            )
            stage_name = "validate"
            try:
                completion_sequence = [
                    self._completion_stage("validate"),
                ]
                stage_name = "persist_reviewer_record"
                completion_sequence.append(
                    self._completion_stage(
                        stage_name,
                        artifact_count=1,
                    )
                )
                stage_name = "persist_dispositions"
                completion_sequence.append(
                    self._completion_stage(
                        stage_name,
                        artifact_count=len(persisted.get("decisions", [])),
                    )
                )
                stage_name = "persist_carry_forward_recommendations"
                completion_sequence.append(
                    self._completion_stage(
                        stage_name,
                        artifact_count=len(carry_forward),
                    )
                )
                stage_name = "record_evidence"
                completion_sequence.append(
                    self._completion_stage(
                        stage_name,
                        artifact_count=len(
                            persisted.get("evidence_references", [])
                        ),
                    )
                )
                stage_name = "update_mdd"
                mdd_structured_payload = self._structured_mdd_payload(persisted)
                completion_sequence.append(
                    self._completion_stage(stage_name, artifact_count=1)
                )
                stage_name = "mark_eda_complete"
                completion_sequence.append(self._completion_stage(stage_name))
            except EDADocumentationValidationError:
                raise
            except Exception as exc:
                raise EDADocumentationValidationError(
                    f"eda_completion_{stage_name}_failed",
                    [
                        f"EDA completion stopped safely at {stage_name.replace('_', ' ')}. "
                        "No completion snapshot or downstream mutation was persisted."
                    ],
                ) from exc

            snapshot = {
                **persisted,
                "status": "confirmed",
                "confirmation_id": confirmation_id,
                "completion_id": completion_id,
                "completion_sequence": completion_sequence,
                "documentation_version": f"eda-doc-{documentation_version:04d}",
                "payload_digest": payload_digest,
                "confirmed_at": confirmed_at,
                "confirmed_by": actor["user_id"],
                "confirmed_by_display_name": actor["display_name"],
                "next_step_eligible": True,
                "governed_context": copy.deepcopy(context),
                "stale_at": None,
                "stale_reason": None,
                "stale_reasons": [],
                "mdd_staleness": {
                    "stale_sections": [],
                    "changed_source_fields": [],
                    "analytical_staleness": False,
                    "narrative_only_staleness": False,
                    "review_action": "Review stale documentation",
                },
                "mdd_structured_payload": mdd_structured_payload,
                "dataset_mutated": False,
                "feature_manifest_mutated": False,
            }
            record.setdefault("approvals", []).append(snapshot)
            record["current_confirmation_id"] = confirmation_id
            record["draft"] = None
            self._write(record)

        audit_event(
            "eda.confirmation.approved",
            "eda_documentation",
            confirmation_id,
            "success",
            user_id=actor["user_id"],
            metadata={
                "projectId": payload.project_id,
                "datasetId": payload.dataset_id,
                "datasetVersionId": payload.dataset_version_id,
                "datasetVersion": payload.dataset_version_id,
                "target": payload.target,
                "predictorManifestId": payload.predictor_manifest_id,
                "documentationVersion": snapshot["documentation_version"],
                "evidenceIds": [
                    item["evidence_id"]
                    for item in snapshot["evidence_references"]
                ],
            },
        )
        return self._confirmation_response(snapshot, idempotent=False)

    def complete(
        self,
        request: EDACompletionRequest,
        user: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Run the typed, idempotent governed completion transaction.

        The existing ``confirm`` method remains the compatibility boundary.
        Both paths use the same canonical payload digest and one atomic store
        write, so a retry cannot duplicate reviewer, disposition, evidence, or
        MDD records.
        """

        result = self.confirm(request.payload, user)
        return {
            **result,
            "request_idempotency_key": request.idempotency_key,
        }

    @_dataset_state_locked
    def invalidate(
        self,
        project_id: str,
        reason: str,
        user: Dict[str, Any],
        *,
        upstream_revision: Optional[str] = None,
        expected_dataset_id: Optional[str] = None,
        expected_dataset_version_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        actor = _actor(user)
        context = self._context_provider(project_id)
        self._assert_expected_identity(
            context,
            expected_dataset_id=expected_dataset_id,
            expected_dataset_version_id=expected_dataset_version_id,
        )
        with self._lock:
            record = self._read(project_id)
            changed = self._mark_current_stale(
                record,
                reason,
                upstream_revision=upstream_revision,
                changed_source_fields=["upstream_revision"],
                stale_sections=[
                    {
                        "section": "overview",
                        "classification": "analytical",
                        "changed_source_fields": ["upstream_revision"],
                    }
                ],
            )
            if changed:
                self._write(record)
        if changed:
            current = self._current_approval(record)
            audit_event(
                "eda.documentation.marked_stale",
                "eda_documentation",
                str((current or {}).get("confirmation_id") or project_id),
                "success",
                user_id=actor["user_id"],
                metadata={
                    "projectId": project_id,
                    "reason": reason,
                    "upstreamRevision": upstream_revision,
                },
            )
        return self.get_state(project_id, context=context)

    @_dataset_state_locked
    def get_state(
        self,
        project_id: str,
        *,
        context: Optional[Dict[str, Any]] = None,
        expected_dataset_id: Optional[str] = None,
        expected_dataset_version_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        with self._lock:
            record = self._read(project_id)
            active_context = (
                context
                if context is not None
                else self._context_provider(project_id)
            )
            if expected_dataset_id or expected_dataset_version_id:
                if active_context is None:
                    raise EDADocumentationValidationError(
                        "eda_governed_context_incomplete",
                        [
                            "The exact active Dataset Library version is "
                            "required to read EDA documentation state."
                        ],
                    )
                self._assert_expected_identity(
                    active_context,
                    expected_dataset_id=expected_dataset_id,
                    expected_dataset_version_id=(
                        expected_dataset_version_id
                    ),
                )
            if active_context is not None and self._auto_invalidate(
                record,
                active_context,
            ):
                # A view route may report the derived stale state but must not
                # mutate durable documentation. Explicit invalidation and edit
                # routes own persistence.
                pass

            current = self._current_approval(record)
            draft = record.get("draft")
            if current and current.get("status") == "stale":
                status = "stale"
            elif current and current.get("status") == "confirmed":
                status = "confirmed"
            elif draft and draft.get("status") == "ready_for_confirmation":
                status = "ready_for_confirmation"
            else:
                status = "draft"

            if active_context is not None:
                source_lineage = self._lineage(active_context)
            elif draft:
                source_lineage = self._lineage(draft)
            elif current:
                source_lineage = self._lineage(current)
            else:
                source_lineage = {"project_id": project_id}

            history = [
                {
                    "confirmation_id": item.get("confirmation_id"),
                    "documentation_version": item.get("documentation_version"),
                    "eda_analysis_version": item.get("eda_analysis_version"),
                    "status": item.get("status"),
                    "confirmed_at": item.get("confirmed_at"),
                    "confirmed_by": item.get("confirmed_by"),
                    "confirmed_by_display_name": item.get(
                        "confirmed_by_display_name"
                    ),
                    "dataset_id": item.get("dataset_id"),
                    "dataset_version_id": item.get("dataset_version_id"),
                    "dataset_version": item.get("dataset_version_id"),
                    "target": item.get("target"),
                    "predictor_manifest_id": item.get(
                        "predictor_manifest_id"
                    ),
                    "stale_at": item.get("stale_at"),
                    "stale_reason": item.get("stale_reason"),
                }
                for item in reversed(record.get("approvals", []))
            ]
            return {
                "ok": True,
                "project_id": source_lineage.get("project_id", project_id),
                "dataset_id": source_lineage.get("dataset_id"),
                "dataset_version_id": source_lineage.get(
                    "dataset_version_id"
                ),
                "dataset_version": source_lineage.get(
                    "dataset_version_id"
                ),
                "status": status,
                "draft": copy.deepcopy(draft),
                "current_approved": copy.deepcopy(current),
                "history": history,
                "source_lineage": source_lineage,
            }

    @staticmethod
    def _confirmation_response(
        snapshot: Dict[str, Any],
        *,
        idempotent: bool,
    ) -> Dict[str, Any]:
        return {
            "ok": True,
            "confirmation_id": snapshot["confirmation_id"],
            "documentation_version": snapshot["documentation_version"],
            "evidence_ids": [
                item["evidence_id"]
                for item in snapshot.get("evidence_references", [])
            ],
            "next_step_eligible": bool(snapshot.get("next_step_eligible")),
            "status": snapshot.get("status"),
            "idempotent": idempotent,
            "completion_id": snapshot.get("completion_id"),
            "completion_sequence": copy.deepcopy(
                snapshot.get("completion_sequence") or []
            ),
            "mdd_staleness": copy.deepcopy(snapshot.get("mdd_staleness")),
            "dataset_mutated": False,
            "feature_manifest_mutated": False,
            "record": copy.deepcopy(snapshot),
        }


eda_documentation_service = EDADocumentationService()
