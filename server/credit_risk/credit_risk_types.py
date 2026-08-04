from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class VariableMapping(BaseModel):
    variable: str
    role: str = "Unknown"
    source: str = ""
    include: bool = True
    notes: Optional[str] = None


class MonotonicConstraint(BaseModel):
    variable: str
    expectedDirection: str = ""
    constraint: str = "No constraint"
    rationale: str = ""
    reviewerNote: Optional[str] = None


class ChampionDecision(BaseModel):
    selectedModelId: Optional[str] = None
    selectedModelType: Optional[str] = None
    reason: Optional[str] = None
    reviewerNotes: Optional[str] = None
    decidedAt: Optional[str] = None


class ScorecardScaling(BaseModel):
    scorecardStyleModel: bool = False
    pdo: Optional[float] = None
    baseScore: Optional[float] = None
    baseOdds: Optional[str] = None
    factor: Optional[float] = None
    offset: Optional[float] = None
    scoreDirection: Optional[str] = None
    minScore: Optional[float] = None
    maxScore: Optional[float] = None
    oddsCalibrationApproach: Optional[str] = None
    referencePopulation: Optional[str] = None
    notes: Optional[str] = None


class CreditRiskProfile(BaseModel):
    profileId: Optional[str] = None
    projectId: str
    projectName: Optional[str] = None
    datasetId: Optional[str] = None
    datasetVersionId: Optional[str] = None
    productType: Optional[str] = None
    modelPurpose: Optional[str] = None
    targetEvent: Optional[str] = None
    targetColumn: Optional[str] = None
    eventValue: Optional[str] = None
    nonEventValue: Optional[str] = None
    originalTargetLabelColumn: Optional[str] = None
    splitColumn: Optional[str] = None
    validationDatasetId: Optional[str] = None
    ootDatasetId: Optional[str] = None
    ootType: Optional[str] = None
    targetSummary: Dict[str, Any] = Field(default_factory=dict)
    targetWindow: Optional[str] = None
    observationWindow: Optional[str] = None
    performanceWindow: Optional[str] = None
    modelType: Optional[str] = None
    ttcPitAssumption: Optional[str] = None
    regulatoryContext: List[str] = Field(default_factory=list)
    goodDefinition: Optional[str] = None
    badDefinition: Optional[str] = None
    indeterminateDefinition: Optional[str] = None
    performanceWindowStart: Optional[str] = None
    performanceWindowEnd: Optional[str] = None
    observationSnapshotDate: Optional[str] = None
    outcomeSourceTable: Optional[str] = None
    exclusionRules: Optional[str] = None
    censoringNotes: Optional[str] = None
    variableMappings: List[VariableMapping] = Field(default_factory=list)
    featureReview: Dict[str, Any] = Field(default_factory=dict)
    scorecardScaling: ScorecardScaling = Field(default_factory=ScorecardScaling)
    explainability: Dict[str, Any] = Field(default_factory=dict)
    decisionStrategy: Dict[str, Any] = Field(default_factory=dict)
    monitoring: Dict[str, Any] = Field(default_factory=dict)
    readiness: Dict[str, str] = Field(default_factory=dict)
    readinessScore: Optional[int] = None
    selectedModelingApproach: Optional[str] = None
    scorecardModelId: Optional[str] = None
    mlModelId: Optional[str] = None
    championModelId: Optional[str] = None
    championModelType: Optional[str] = None
    scorecardStatus: Optional[str] = None
    mlStatus: Optional[str] = None
    comparisonStatus: Optional[str] = None
    championDecisionStatus: Optional[str] = None
    monotonicConstraints: List[MonotonicConstraint] = Field(default_factory=list)
    championDecision: Optional[ChampionDecision] = None
    edaStatus: Optional[str] = None
    screeningStatus: Optional[str] = None
    woeIvStatus: Optional[str] = None
    scorecardModelStatus: Optional[str] = None
    pdoStatus: Optional[str] = None
    validationStatus: Optional[str] = None
    cutoffStrategyStatus: Optional[str] = None
    adverseActionStatus: Optional[str] = None
    monitoringStatus: Optional[str] = None
    evidenceStatus: Optional[str] = None
    createdAt: Optional[str] = None
    updatedAt: Optional[str] = None


class CreditRiskEvidenceRequest(BaseModel):
    profile: CreditRiskProfile
    technique: str
    label: str
    supportsSections: List[str] = Field(default_factory=list)


class WoeIvRunRequest(BaseModel):
    projectId: str
    datasetId: str
    datasetVersionId: str
    analysisPartitionId: Optional[str] = None
    analysisPartitionRevision: Optional[int] = None
    targetColumn: str
    eventValue: Any
    predictorColumns: List[str] = Field(default_factory=list)
    binningMethod: str = "quantile"
    maxBins: int = 5
    minBinPct: float = 0.05
    smoothing: float = 0.5
    excludeMissingFromBins: bool = False


class WoeIvManualBin(BaseModel):
    binId: Optional[str] = None
    label: str
    lowerBound: Optional[float] = None
    upperBound: Optional[float] = None
    categoryValues: List[str] = Field(default_factory=list)
    isMissingBin: bool = False
    manualOverride: bool = True
    reviewerNote: Optional[str] = None


class WoeIvManualBinsRequest(BaseModel):
    analysisId: str
    variable: str
    bins: List[WoeIvManualBin] = Field(default_factory=list)
    allowNumericGaps: bool = False


class WoeIvSaveRequest(BaseModel):
    analysis: Dict[str, Any]


class WoeIvAnalysisIdRequest(BaseModel):
    analysisId: str


class WoeIvEvidenceRequest(BaseModel):
    analysisId: str
    technique: str = "woe_iv"
    label: str = "WOE / IV analysis"


class ScorecardTrainRequest(BaseModel):
    projectId: str
    datasetId: str
    datasetVersionId: str
    analysisPartitionId: Optional[str] = None
    analysisPartitionRevision: Optional[int] = None
    targetColumn: str
    eventValue: Any = 1
    woeAnalysisId: Optional[str] = None
    selectedVariables: List[str] = Field(default_factory=list)
    trainValidationSplit: float = 0.7
    crossValidationFolds: int = 5
    modelType: str = "Logistic Scorecard"
    regularization: str = "l2"
    regularizationC: float = 1.0
    classWeight: Optional[str] = None
    trainRawBaseline: bool = False
    pdo: float = 20
    baseScore: float = 600
    baseOdds: str = "50:1"
    scoreDirection: str = "Higher score = lower risk"
    minScore: Optional[float] = None
    maxScore: Optional[float] = None
    averageBalance: Optional[float] = None
    lossGivenDefault: Optional[float] = None
    revenuePerBookedAccount: Optional[float] = None
    operationalApprovalTarget: Optional[float] = None
    maximumBadRate: Optional[float] = None


class ScorecardModelIdRequest(BaseModel):
    modelId: str


class ScorecardEvidenceRequest(BaseModel):
    modelId: str
    technique: str = "scorecard_modeling"
    label: str = "Scorecard Model Evidence"


class ScorecardRegisterRequest(BaseModel):
    modelId: str
    champion: bool = True


class CreditRiskMlTrainRequest(BaseModel):
    projectId: str
    datasetId: str
    datasetVersionId: str
    analysisPartitionId: Optional[str] = None
    analysisPartitionRevision: Optional[int] = None
    targetColumn: str
    eventValue: Any = 1
    selectedVariables: List[str] = Field(default_factory=list)
    modelType: str = "Random Forest"
    trainValidationSplit: float = 0.7
    classWeight: Optional[str] = None
    calibrationMethod: Optional[str] = None
    monotonicConstraints: List[MonotonicConstraint] = Field(default_factory=list)
    evaluationMetric: str = "AUC"


class CreditRiskMlEvidenceRequest(BaseModel):
    modelId: str
    technique: str = "ml_underwriting"
    label: str = "AI/ML Underwriting Evidence"


class CreditRiskDatasetSummaryRequest(BaseModel):
    projectId: str
    datasetId: str
    datasetVersionId: str
    analysisPartitionId: Optional[str] = None
    analysisPartitionRevision: Optional[int] = None
    targetColumn: Optional[str] = None
    eventValue: Optional[str] = None
    nonEventValue: Optional[str] = None


class ChampionComparisonRunRequest(BaseModel):
    profile: CreditRiskProfile
    scorecardModel: Optional[Dict[str, Any]] = None
    mlModel: Optional[Dict[str, Any]] = None


class ChampionDecisionRequest(BaseModel):
    profile: CreditRiskProfile
    decision: ChampionDecision


class ChampionEvidenceRequest(BaseModel):
    profile: CreditRiskProfile
    label: str = "Champion / Challenger Evidence"
