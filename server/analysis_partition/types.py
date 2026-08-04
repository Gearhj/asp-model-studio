from __future__ import annotations

from typing import Any, Dict, List, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


ANALYSIS_PARTITION_REQUIRED = "analysis_partition_required"
ANALYSIS_PARTITION_STALE = "analysis_partition_stale"
ANALYSIS_PARTITION_CONTRADICTORY = "analysis_partition_contradictory"
PREDICTOR_AUTHORIZATION_REQUIRED = "predictor_authorization_required"
TARGET_CONTRACT_STALE = "target_contract_stale"
DATASET_IDENTITY_UNAVAILABLE = "dataset_identity_unavailable"
ANALYSIS_PARTITION_INTEGRITY_FAILED = "analysis_partition_integrity_failed"
ANALYSIS_PARTITION_RESET_INVALIDATION_FAILED = (
    "analysis_partition_reset_invalidation_failed"
)
ANALYSIS_PARTITION_PREVIEW_STALE = "analysis_partition_preview_stale"
ANALYSIS_PARTITION_SUFFICIENCY_FAILED = "analysis_partition_sufficiency_failed"
ANALYSIS_PARTITION_DOCUMENTATION_PENDING = (
    "analysis_partition_documentation_pending"
)
ANALYSIS_PARTITION_TARGET_AUTHORITY_UNVERIFIED = (
    "analysis_partition_target_authority_unverified"
)


SUPPORTED_ANALYSIS_PARTITION_RATIOS = (
    (0.7, 0.3),
    (0.8, 0.2),
    (0.9, 0.1),
)


class _AnalysisPartitionDecisionRequest(BaseModel):
    """Shared, non-mutating inputs for preview and durable confirmation."""

    model_config = ConfigDict(extra="forbid")

    project_id: str = Field(min_length=1)
    dataset_id: str = Field(min_length=1)
    dataset_version_id: str = Field(min_length=1)
    target_contract_id: str = ""
    target: str = Field(min_length=1)
    positive_value: Any = None
    negative_value: Any = None
    predictor_authorization_id: str = ""
    problem_type: Literal["classification", "regression"] = "classification"
    development_share: float = Field(default=0.8, gt=0.0, lt=1.0)
    holdout_share: float = Field(default=0.2, gt=0.0, lt=1.0)
    random_seed: int = Field(default=42, ge=0, le=2_147_483_647)
    stratification_policy: Literal["target", "none"] = "target"
    stratification_field: str = ""
    partition_method: Literal["deterministic_random"] = "deterministic_random"

    @field_validator(
        "project_id",
        "dataset_id",
        "dataset_version_id",
        "target_contract_id",
        "target",
        "predictor_authorization_id",
        "stratification_field",
        mode="before",
    )
    @classmethod
    def strip_decision_text(cls, value: Any) -> str:
        return str(value or "").strip()

    @model_validator(mode="after")
    def validate_standard_ratio(self):
        pair = (float(self.development_share), float(self.holdout_share))
        if not any(
            abs(pair[0] - development) <= 1e-9
            and abs(pair[1] - holdout) <= 1e-9
            for development, holdout in SUPPORTED_ANALYSIS_PARTITION_RATIOS
        ):
            raise ValueError(
                "Analysis Partition ratio must be exactly 70/30, 80/20, or 90/10."
            )
        return self


class AnalysisPartitionPreviewRequest(_AnalysisPartitionDecisionRequest):
    """Read-only deterministic preview against the exact governed target."""

    pass


class AnalysisPartitionResetPreviewRequest(_AnalysisPartitionDecisionRequest):
    """Read-only alternate preview bound to one exact current partition."""

    expected_current_partition_id: str = Field(min_length=1)
    expected_current_revision: int = Field(ge=1)

    @field_validator("expected_current_partition_id", mode="before")
    @classmethod
    def strip_expected_partition_id(cls, value: Any) -> str:
        return str(value or "").strip()


class AnalysisPartitionError(ValueError):
    """A precise governed-readiness failure for the pre-EDA partition."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        recovery: str = "",
        impacts: List[str] | None = None,
        stale_artifacts: List[str] | None = None,
        identifiers: Dict[str, Any] | None = None,
        status_code: int = 409,
    ) -> None:
        super().__init__(message)
        self.code = str(code)
        self.message = str(message)
        self.recovery = str(recovery or "")
        self.impacts = list(impacts or [])
        self.stale_artifacts = list(stale_artifacts or [])
        self.identifiers = dict(identifiers or {})
        self.status_code = int(status_code)

    def as_detail(self) -> Dict[str, Any]:
        return {
            "ok": False,
            "code": self.code,
            "message": self.message,
            "recovery": self.recovery,
            "impacts": list(self.impacts),
            "stale_artifacts": list(self.stale_artifacts),
            "identifiers": dict(self.identifiers),
        }


class AnalysisPartitionConfirmRequest(_AnalysisPartitionDecisionRequest):
    """Explicit user confirmation of one exact pre-EDA partition contract."""

    target_contract_id: str = Field(min_length=1)
    predictor_authorization_id: str = Field(min_length=1)
    # Transitional clients may omit this; the service always recalculates the
    # authoritative preview and validates the fingerprint whenever supplied.
    preview_fingerprint: str = ""
    selection_rationale: str = ""
    # Backward-compatible wire field. The single creation button is itself the
    # affirmative governed decision, so this value is deliberately ignored.
    confirmation_acknowledged: bool = False
    reset_existing: bool = False
    reset_reason: str = ""
    acknowledge_invalidation: bool = False
    expected_current_partition_id: str = ""
    expected_current_revision: int | None = Field(default=None, ge=1)

    @field_validator(
        "project_id",
        "dataset_id",
        "dataset_version_id",
        "target_contract_id",
        "target",
        "predictor_authorization_id",
        "preview_fingerprint",
        "selection_rationale",
        "reset_reason",
        "expected_current_partition_id",
        mode="before",
    )
    @classmethod
    def strip_required_text(cls, value: Any) -> str:
        return str(value or "").strip()

    @model_validator(mode="after")
    def validate_reset_concurrency_contract(self):
        if self.reset_existing and (
            not self.expected_current_partition_id
            or self.expected_current_revision is None
        ):
            raise ValueError(
                "Reset requires the exact current partition ID and revision."
            )
        return self


class AnalysisPartitionDocumentationRequest(BaseModel):
    """Retry only the documentation sidecars for one exact sealed partition."""

    model_config = ConfigDict(extra="forbid")

    project_id: str = Field(min_length=1)
    dataset_id: str = Field(min_length=1)
    dataset_version_id: str = Field(min_length=1)
    target: str = Field(min_length=1)
    target_contract_id: str = Field(min_length=1)
    predictor_authorization_id: str = Field(min_length=1)
    analysis_partition_id: str = Field(min_length=1)
    revision: int = Field(ge=1)

    @field_validator(
        "project_id",
        "dataset_id",
        "dataset_version_id",
        "target",
        "target_contract_id",
        "predictor_authorization_id",
        "analysis_partition_id",
        mode="before",
    )
    @classmethod
    def strip_documentation_text(cls, value: Any) -> str:
        return str(value or "").strip()


class AnalysisPartitionInvalidationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    project_id: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    expected_dataset_id: str = ""
    expected_dataset_version_id: str = ""
    expected_target: str = ""


class AnalysisPartitionStatusResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    ok: bool = True
    code: str
    readiness: Literal["current", "documentation_pending"] = "current"
    analysis_partition: Dict[str, Any]
    reused: bool = False
