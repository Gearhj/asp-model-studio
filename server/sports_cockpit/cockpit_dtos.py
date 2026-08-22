"""Phase 7D.4 (B9 / Gate 9) — strict, versioned, backend-authoritative response DTOs for the four scientific
cockpit reads (Active Candidate / Evaluation / Calibration / Registry-Evidence) and the V2-only feature-family
comparison.

Every model is ``extra="forbid"`` and every critical identity / immutable SHA / scalar metric is a REQUIRED
field, so a renamed, missing, misnested, or unexpected field fails construction (surfaced as a fail-closed
server error, never a silently-truncated "successful" payload). The service layer (``gen3_authority``)
resolves all of these ONLY through ``verify_canonical_model_run_chain`` — these DTOs merely bind the exact
wire shape the TypeScript client compiles against. 2025 never appears in any of them.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


# --------------------------------------------------------------------------- shared metric sub-objects
class AggregateMetricsV2(_Strict):
    """The 5 governed scalar metrics persisted in the immutable ``aggregate-metrics.json`` bundle child."""
    logLoss: float
    brierScore: float
    topLabelEce: float
    top1Accuracy: float
    macroF1: float


class PerClassBlockV2(_Strict):
    perClass: dict[str, Any]
    classwiseBrier: dict[str, float]
    classwiseEce: dict[str, float]


class ConfusionBlockV2(_Strict):
    confusionMatrix: list[list[float]]
    axes: dict[str, str]
    classOrder: list[str]


class ReliabilityBlockV2(_Strict):
    topLabelReliability: list[dict[str, Any]]
    classwiseReliability: dict[str, Any]
    probabilityHistograms: Any = None


# --------------------------------------------------------------------------- ACTIVE_CANDIDATE_RESPONSE_V2
class ActiveCandidateResponseV2(_Strict):
    """The project's active candidate — immutable identities only, reconstructed from the verified V2 chain
    (never mutable run JSON, never a browser result)."""
    schemaVersion: str = Field(default="ACTIVE_CANDIDATE_RESPONSE_V2")
    status: str
    runId: str
    runAuthorityId: str
    datasetVersionId: str
    generation: str
    modelFamily: str
    developmentSeasons: list[int]
    developmentRows: int
    validationSeason: int
    validationRows: int
    runReceiptSha256: str
    bundleManifestSha256: str
    bindingId: str
    bindingRevision: int
    activationRevision: int
    activatedAt: str
    preprocessingContractId: str


# --------------------------------------------------------------------------- MODEL_EVALUATION_RESPONSE_V2
class ModelEvaluationResponseV2(_Strict):
    """The active candidate's immutable 2024-validation evidence: verified aggregate + per-class + confusion +
    reliability, plus the INDEPENDENT log-loss recompute (which fails closed on mismatch upstream)."""
    schemaVersion: str = Field(default="MODEL_EVALUATION_RESPONSE_V2")
    runId: str
    runAuthorityId: str
    runReceiptSha256: str
    bundleManifestSha256: str
    datasetVersionId: str
    datasetContentSha256: str
    generation: str
    modelFamily: str
    developmentSeasons: list[int]
    developmentRows: int
    validationSeason: int
    validationRows: int
    featureCount: int
    preprocessingContractId: str
    classOrder: list[str]
    metrics: AggregateMetricsV2
    perClass: PerClassBlockV2
    confusion: ConfusionBlockV2
    diagnostics: ReliabilityBlockV2
    independentRecomputedLogLoss: float
    recomputationMatchesStored: bool
    calibrationStatus: str
    calibratorConfigured: bool
    validationLabel: str


# --------------------------------------------------------------------------- MODEL_CALIBRATION_RESPONSE_V2
class ModelCalibrationResponseV2(_Strict):
    """The active candidate's RAW 2024-validation calibration state. It states the current condition honestly
    (no calibrator is fit in this phase); the reliability curves are the candidate's raw probabilities."""
    schemaVersion: str = Field(default="MODEL_CALIBRATION_RESPONSE_V2")
    runId: str
    runReceiptSha256: str
    bundleManifestSha256: str
    generation: str
    modelFamily: str
    validationSeason: int
    calibrationStatus: str
    calibratorConfigured: bool
    topLabelEce: float
    brierScore: float
    classOrder: list[str]
    topLabelReliability: list[dict[str, Any]]
    classwiseReliability: dict[str, Any]
    validationLabel: str


# --------------------------------------------------------------------------- MODEL_REGISTRY_EVIDENCE_RESPONSE_V2
class ModelRegistryEvidenceResponseV2(_Strict):
    """The active candidate's immutable registry record + model card: content-addressed identities and digests
    resolved from the verified V2 bundle/receipt (never inferred, never decorative)."""
    schemaVersion: str = Field(default="MODEL_REGISTRY_EVIDENCE_RESPONSE_V2")
    runId: str
    runAuthorityId: str
    runReceiptSha256: str
    bundleManifestSha256: str
    datasetVersionId: str
    datasetContentSha256: str
    generation: str
    modelFamily: str
    preprocessorSha256: str
    modelSha256: str
    predictionSha256: str
    aggregateMetricsSha256: str
    codeRevision: str
    worktreeContentSha256: str
    environmentSha256: str
    developmentSeasons: list[int]
    developmentRows: int
    validationSeason: int
    validationRows: int
    featureCount: int
    logLoss: float
    independentRecomputedLogLoss: float
    recomputationMatchesStored: bool
    calibrationStatus: str
    validationLabel: str


# --------------------------------------------------------------------------- FEATURE_FAMILY_COMPARISON_RESPONSE_V2
class ComparisonArmV2(_Strict):
    runId: str
    runReceiptSha256: str
    bundleManifestSha256: str
    featureSetName: str
    featureSetSha256: str
    metrics: AggregateMetricsV2


class ComparisonUncertaintyV2(_Strict):
    method: str
    iterations: int
    games: int
    logLossDeltaMean: float
    logLossDelta95CI: list[float]
    challengerImproves: bool


class FeatureFamilyComparisonResponseV2(_Strict):
    """The V2-only feature-family comparison: both arms resolved through the canonical chain, an immutable
    content-addressed comparison receipt, the added family + its contract SHA, the paired delta + game-cluster
    bootstrap uncertainty. 2025 never enters."""
    schemaVersion: str = Field(default="MODEL_FEATURE_FAMILY_COMPARISON_RECEIPT_V1")
    comparisonReceiptSha256: str
    projectId: str
    bindingId: str
    bindingRevision: int
    generation: str
    datasetVersionId: str
    datasetContentSha256: str
    modelFamily: str
    seed: int
    controlFeatureSet: str
    challengerFeatureSet: str
    featureFamilyAdded: list[str]
    featureFamilyId: str
    featureFamilySha256: str
    control: ComparisonArmV2
    challenger: ComparisonArmV2
    validationSeason: int
    validationRows: int
    metricDelta: dict[str, float]
    classConditionalLogLossDelta: dict[str, float]
    uncertainty: ComparisonUncertaintyV2
    createdAt: str
