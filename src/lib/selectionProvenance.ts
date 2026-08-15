export const VERIFIED_SELECTION_SOURCES = [
  "cross_validation_mean",
  "out_of_fold",
  "training_validation_partition",
] as const;

export type VerifiedSelectionSource =
  (typeof VERIFIED_SELECTION_SOURCES)[number];

export type SelectionMetricEvidence = {
  name: string;
  value: number;
  source: VerifiedSelectionSource;
  partition_id: string;
  fold_definition_id: string;
  fold_count: number;
  fold_values: number[];
  mean: number;
  standard_deviation: number;
  out_of_fold_prediction_artifact_id: string;
  threshold_source: string;
  calibration_source: string;
  created_at: string;
};

export type SelectionCandidateEvidence = {
  candidate_id?: string;
  training_run_id?: string;
  key?: string;
  name?: string;
  algorithm_id?: string;
  champion_eligible?: boolean;
  selection_metric?: unknown;
  selection_integrity_status?: unknown;
  holdout_isolation_status?: unknown;
  candidate_contract?: unknown;
};

export type LockedSelectionDecision = {
  decision_id: string;
  status: "locked";
  selected_candidate_id: string;
  training_run_id: string;
  selection_metric: SelectionMetricEvidence;
  selection_ranking_snapshot_hash: string;
  selection_locked_at: string;
  actor: Record<string, unknown>;
};

export type GovernedEvaluationPackage = {
  evaluation_package_id?: unknown;
  status?: unknown;
  candidate_id?: unknown;
  training_run_id?: unknown;
  candidate_decision_id?: unknown;
  selection_integrity_status?: unknown;
  isolation_status?: unknown;
  holdout_isolation_status?: unknown;
  package_integrity_status?: unknown;
  final_holdout_status?: unknown;
  first_opened_at?: unknown;
  selection_evidence?: unknown;
  selection_evidence_json?: unknown;
  final_holdout_evidence?: unknown;
  final_holdout_evidence_json?: unknown;
  holdout_exposure?: unknown;
};

export type PromotionReadiness = {
  ready: boolean;
  reason: string;
  candidateDecisionId: string;
  evaluationPackageId: string;
  selectionMetric: SelectionMetricEvidence | null;
  holdoutFirstOpenedAt: string;
};

const text = (value: unknown) =>
  typeof value === "string" ? value.trim() : "";

const record = (value: unknown): Record<string, unknown> | null =>
  value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;

const finite = (value: unknown): number | null =>
  typeof value === "number" && Number.isFinite(value) ? value : null;

function actorIsPresent(actor: unknown): actor is Record<string, unknown> {
  const value = record(actor);
  return Boolean(
    value &&
      Object.values(value).some(
        (field) => typeof field === "string" && field.trim(),
      ),
  );
}

export function isVerifiedSelectionSource(
  value: unknown,
): value is VerifiedSelectionSource {
  return VERIFIED_SELECTION_SOURCES.includes(
    value as VerifiedSelectionSource,
  );
}

/**
 * Parse selection evidence fail closed. A generic metric value is never enough
 * to rank a candidate: its non-holdout population, fold contract, threshold,
 * calibration source, and creation time must all be explicit.
 */
export function parseSelectionMetric(
  input: unknown,
): SelectionMetricEvidence | null {
  const value = record(input);
  const source = value?.source ?? value?.selection_metric_source;
  if (!value || !isVerifiedSelectionSource(source)) return null;

  const metricName = text(value.name ?? value.selection_metric_name);
  const metricValue = finite(value.value ?? value.selection_metric_value);
  const mean = finite(value.mean);
  const standardDeviation = finite(value.standard_deviation);
  const foldCount = finite(value.fold_count);
  const foldValues = Array.isArray(value.fold_values)
    ? value.fold_values.map(finite)
    : [];
  if (
    !metricName ||
    metricValue === null ||
    mean === null ||
    standardDeviation === null ||
    foldCount === null ||
    foldCount < 1 ||
    !Number.isInteger(foldCount) ||
    !text(value.partition_id ?? value.selection_partition_id) ||
    !text(value.threshold_source) ||
    !text(value.calibration_source) ||
    !text(value.created_at) ||
    foldValues.some((item) => item === null)
  ) {
    return null;
  }

  const foldDefinitionId = text(value.fold_definition_id);
  const numericFoldValues = foldValues as number[];
  if (!foldDefinitionId || numericFoldValues.length !== foldCount) {
    return null;
  }
  const outOfFoldArtifactId = text(value.out_of_fold_prediction_artifact_id);
  if (source === "out_of_fold" && !outOfFoldArtifactId) return null;

  return {
    name: metricName,
    value: metricValue,
    source,
    partition_id: text(value.partition_id ?? value.selection_partition_id),
    fold_definition_id: foldDefinitionId,
    fold_count: foldCount,
    fold_values: numericFoldValues,
    mean,
    standard_deviation: standardDeviation,
    out_of_fold_prediction_artifact_id: outOfFoldArtifactId,
    threshold_source: text(value.threshold_source),
    calibration_source: text(value.calibration_source),
    created_at: text(value.created_at),
  };
}

export function normalizeSelectionMetricName(value: unknown): string {
  const name = text(value).toLowerCase();
  const aliases: Record<string, string> = {
    auc: "roc_auc",
    roc_auc: "roc_auc",
    average_precision: "pr_auc",
    pr_auc: "pr_auc",
  };
  return aliases[name] ?? name;
}

export function selectionMetricNamesMatch(left: unknown, right: unknown): boolean {
  return normalizeSelectionMetricName(left) === normalizeSelectionMetricName(right);
}

export function normalizeSelectionCandidateEvidence<
  T extends SelectionCandidateEvidence,
>(candidate: T): T {
  const contract = record(candidate.candidate_contract);
  if (!contract) return candidate;

  const normalized: Record<string, unknown> = { ...candidate };
  const fillTextField = (field: keyof SelectionCandidateEvidence) => {
    if (!text(normalized[field])) normalized[field] = contract[field];
  };
  fillTextField("candidate_id");
  fillTextField("training_run_id");
  fillTextField("key");
  fillTextField("algorithm_id");
  if (!text(normalized.key)) normalized.key = contract.algorithm_id;
  if (!text(normalized.name)) normalized.name = contract.name ?? contract.algorithm_id;
  if (normalized.selection_metric == null) {
    normalized.selection_metric = contract.selection_metric;
  }
  if (normalized.selection_integrity_status == null) {
    normalized.selection_integrity_status = contract.selection_integrity_status;
  }
  if (normalized.holdout_isolation_status == null) {
    normalized.holdout_isolation_status = contract.holdout_isolation_status;
  }
  if (normalized.champion_eligible == null) {
    normalized.champion_eligible = contract.champion_eligible;
  }
  return normalized as T;
}

export function verifiedSelectionMetric(
  candidate: SelectionCandidateEvidence,
  expectedName?: string,
): SelectionMetricEvidence | null {
  const normalized = normalizeSelectionCandidateEvidence(candidate);
  if (
    normalized.selection_integrity_status !== "verified" ||
    normalized.holdout_isolation_status !== "verified"
  ) {
    return null;
  }
  const metric = parseSelectionMetric(normalized.selection_metric);
  if (!metric) return null;
  if (
    expectedName &&
    !selectionMetricNamesMatch(metric.name, expectedName)
  ) {
    return null;
  }
  return metric;
}

export function isVerifiedSelectionCandidate(
  candidate: SelectionCandidateEvidence,
  expectedName?: string,
): boolean {
  const normalized = normalizeSelectionCandidateEvidence(candidate);
  return Boolean(
    text(normalized.candidate_id) &&
      text(normalized.training_run_id) &&
      verifiedSelectionMetric(normalized, expectedName),
  );
}

export function rankVerifiedSelectionCandidates<
  T extends SelectionCandidateEvidence,
>(rows: T[], metricName: string, lowerIsBetter: boolean): T[] {
  return rows
    .map((row) => normalizeSelectionCandidateEvidence(row))
    .filter((row) => isVerifiedSelectionCandidate(row, metricName))
    .slice()
    .sort((left, right) => {
      const a = verifiedSelectionMetric(left, metricName)!.value;
      const b = verifiedSelectionMetric(right, metricName)!.value;
      const difference = lowerIsBetter ? a - b : b - a;
      if (difference) return difference;
      return (
        text(left.candidate_id) ||
        text(left.key) ||
        text(left.name)
      ).localeCompare(
        text(right.candidate_id) || text(right.key) || text(right.name),
      );
    });
}

export function formatSelectionSource(source: unknown): string {
  const labels: Record<VerifiedSelectionSource, string> = {
    cross_validation_mean: "cross-validation mean",
    out_of_fold: "out-of-fold",
    training_validation_partition: "governed validation partition",
  };
  return isVerifiedSelectionSource(source)
    ? labels[source]
    : "unverified selection source";
}

export function selectionMetricLabel(metric: SelectionMetricEvidence): string {
  const labels: Record<string, string> = {
    auc: "ROC-AUC",
    roc_auc: "ROC-AUC",
    pr_auc: "PR-AUC",
    rmse: "RMSE",
    mae: "MAE",
    r2: "R-squared",
  };
  return `${labels[metric.name.toLowerCase()] ?? metric.name.replace(/_/g, " ").toUpperCase()} - ${formatSelectionSource(metric.source)}`;
}

export function parseLockedSelectionDecision(
  input: unknown,
): LockedSelectionDecision | null {
  const value = record(input);
  if (
    !value ||
    value.status !== "locked" ||
    !text(value.decision_id ?? value.candidate_decision_id) ||
    !text(value.selected_candidate_id) ||
    !text(value.training_run_id) ||
    !text(value.selection_ranking_snapshot_hash) ||
    !text(value.selection_locked_at) ||
    !actorIsPresent(value.actor)
  ) {
    return null;
  }
  const metric = parseSelectionMetric(value.selection_metric ?? value);
  if (!metric) return null;
  return {
    decision_id: text(value.decision_id ?? value.candidate_decision_id),
    status: "locked",
    selected_candidate_id: text(value.selected_candidate_id),
    training_run_id: text(value.training_run_id),
    selection_metric: metric,
    selection_ranking_snapshot_hash: text(
      value.selection_ranking_snapshot_hash,
    ),
    selection_locked_at: text(value.selection_locked_at),
    actor: value.actor as Record<string, unknown>,
  };
}

export function lockedDecisionMatchesCandidate(
  decision: LockedSelectionDecision | null,
  candidate: SelectionCandidateEvidence | null,
): boolean {
  return Boolean(
    decision &&
      candidate &&
      decision.selected_candidate_id === text(candidate.candidate_id) &&
      decision.training_run_id === text(candidate.training_run_id) &&
      verifiedSelectionMetric(candidate, decision.selection_metric.name),
  );
}

function evidenceMetric(input: unknown): SelectionMetricEvidence | null {
  const value = record(input);
  return parseSelectionMetric(value?.selection_metric ?? value?.metric ?? value);
}

/**
 * Normalize the command-center response and its nested durable package without
 * inventing any missing evidence. Either surface may carry the canonical
 * fields while an in-progress response is being persisted.
 */
export function normalizeGovernedEvaluationPackage(
  input: unknown,
): GovernedEvaluationPackage | null {
  const outer = record(input);
  if (!outer) return null;
  const nested = record(outer.evaluation_package) ?? {};
  const packageValue = (key: string) => nested[key] ?? outer[key];
  const finalEvidence = packageValue("final_holdout_evidence") ??
    packageValue("final_holdout_evidence_json");
  const exposure = packageValue("holdout_exposure") ?? {
    status: packageValue("final_holdout_status"),
    first_opened_at: packageValue("first_opened_at"),
    candidate_decision_id: packageValue("candidate_decision_id"),
    evaluation_package_id: packageValue("evaluation_package_id"),
  };
  return {
    evaluation_package_id: packageValue("evaluation_package_id"),
    status: packageValue("status"),
    candidate_id: packageValue("candidate_id"),
    training_run_id: packageValue("training_run_id"),
    candidate_decision_id: packageValue("candidate_decision_id"),
    selection_integrity_status: packageValue("selection_integrity_status"),
    isolation_status: packageValue("isolation_status"),
    holdout_isolation_status: packageValue("holdout_isolation_status"),
    package_integrity_status:
      packageValue("package_integrity_status") ??
      packageValue("evaluation_package_integrity_status"),
    final_holdout_status: packageValue("final_holdout_status"),
    first_opened_at: packageValue("first_opened_at"),
    selection_evidence:
      packageValue("selection_evidence") ?? packageValue("selection_evidence_json"),
    final_holdout_evidence: finalEvidence,
    holdout_exposure: exposure,
  };
}

export function resolvePromotionReadiness(
  candidate: SelectionCandidateEvidence | null,
  decisionInput: unknown,
  packageInput: GovernedEvaluationPackage | null | undefined,
): PromotionReadiness {
  const blocked = (reason: string): PromotionReadiness => ({
    ready: false,
    reason,
    candidateDecisionId: "",
    evaluationPackageId: "",
    selectionMetric: null,
    holdoutFirstOpenedAt: "",
  });
  const decision = parseLockedSelectionDecision(decisionInput);
  if (!decision || !lockedDecisionMatchesCandidate(decision, candidate)) {
    return blocked(
      "Promotion requires the exact locked candidate decision and verified non-holdout selection evidence.",
    );
  }
  const evaluationPackage = normalizeGovernedEvaluationPackage(packageInput);
  if (!evaluationPackage || evaluationPackage.status !== "complete") {
    return blocked("A complete governed Evaluation package is required.");
  }
  const evaluationPackageId = text(
    evaluationPackage.evaluation_package_id,
  );
  if (!evaluationPackageId) {
    return blocked("The Evaluation package is missing its durable identity.");
  }
  if (
    evaluationPackage.selection_integrity_status !== "verified" ||
    (evaluationPackage.isolation_status ?? evaluationPackage.holdout_isolation_status) !== "verified" ||
    (evaluationPackage.package_integrity_status != null &&
      evaluationPackage.package_integrity_status !== "verified")
  ) {
    return blocked(
      "Promotion is blocked because selection integrity or holdout isolation is not verified.",
    );
  }
  if (
    text(evaluationPackage.candidate_id) !== text(candidate?.candidate_id) ||
    text(evaluationPackage.training_run_id) !== text(candidate?.training_run_id) ||
    text(evaluationPackage.candidate_decision_id) !== decision.decision_id
  ) {
    return blocked(
      "The Evaluation package does not match the exact locked candidate decision.",
    );
  }

  const selectionEvidence = record(
    evaluationPackage.selection_evidence ??
      evaluationPackage.selection_evidence_json,
  );
  const selectionMetric = evidenceMetric(selectionEvidence);
  if (
    !selectionEvidence ||
    !selectionMetric ||
    selectionMetric.name !== decision.selection_metric.name ||
    selectionMetric.source !== decision.selection_metric.source ||
    selectionMetric.partition_id !== decision.selection_metric.partition_id ||
    selectionMetric.value !== decision.selection_metric.value
  ) {
    return blocked(
      "The Evaluation package does not preserve verified selection-metric provenance.",
    );
  }

  const holdout = record(
    evaluationPackage.final_holdout_evidence ??
      evaluationPackage.final_holdout_evidence_json,
  );
  const holdoutSource = text(holdout?.metric_source ?? holdout?.metric_class);
  const holdoutRole = text(holdout?.role ?? holdout?.final_holdout_role);
  if (
    !holdout ||
    holdoutSource !== "final_holdout" ||
    (holdoutRole && holdoutRole !== "reporting_only")
  ) {
    return blocked(
      "The Evaluation package is missing distinct reporting-only final-holdout evidence.",
    );
  }

  const exposure = record(evaluationPackage.holdout_exposure) ?? {
    status: evaluationPackage.final_holdout_status,
    first_opened_at: evaluationPackage.first_opened_at,
    candidate_decision_id: evaluationPackage.candidate_decision_id,
    evaluation_package_id: evaluationPackage.evaluation_package_id,
  };
  if (
    !exposure ||
    exposure.status !== "evaluated" ||
    !text(exposure.first_opened_at) ||
    (text(exposure.candidate_decision_id) &&
      text(exposure.candidate_decision_id) !== decision.decision_id) ||
    (text(exposure.evaluation_package_id) &&
      text(exposure.evaluation_package_id) !== evaluationPackageId)
  ) {
    return blocked(
      "Final-holdout exposure is not durably bound to the locked decision and Evaluation package.",
    );
  }

  return {
    ready: true,
    reason: "Selection integrity and final-holdout isolation are verified.",
    candidateDecisionId: decision.decision_id,
    evaluationPackageId,
    selectionMetric,
    holdoutFirstOpenedAt: text(exposure.first_opened_at),
  };
}
