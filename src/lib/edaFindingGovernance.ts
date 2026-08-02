import {
  generateEdaFindings,
  type EdaBulkDispositionAudit,
  type EdaCarryForwardDestination,
  type EdaFinding,
  type EdaFindingCategory,
  type EdaFindingDecision,
  type EdaFindingDisposition,
  type EdaFindingSections,
  type EdaFindingSeverity,
  type EdaFindingsReviewState,
} from "./edaFindings";

export type EdaParentFindingRequirement =
  | "blocker"
  | "required"
  | "informational";

export type EdaImmutableChildEvidence = Readonly<
  Omit<
    EdaFinding,
    "affectedVariables" | "suggestedTransformations" | "evidenceReferences"
  > & {
    affectedVariables: readonly string[];
    suggestedTransformations: readonly EdaFinding["suggestedTransformations"][number][];
    evidenceReferences: readonly string[];
  }
>;

export type EdaParentFinding = Readonly<{
  parentId: string;
  family: string;
  title: string;
  category: EdaFindingCategory;
  severity: EdaFindingSeverity;
  requirement: EdaParentFindingRequirement;
  affectedVariables: readonly string[];
  childIds: readonly string[];
  childEvidence: readonly EdaImmutableChildEvidence[];
  evidenceReferences: readonly string[];
  allowedDispositions: readonly EdaFindingDisposition[];
  defaultDestination: EdaCarryForwardDestination | "";
  systemDisposition?: Exclude<EdaFindingDisposition, "unresolved">;
  systemRationale?: string;
}>;

export type EdaFindingFamilySummary = {
  family: string;
  title: string;
  parent_ids: string[];
  child_count: number;
  requirement: EdaParentFindingRequirement;
};

export type EdaFindingsGovernanceSummary = {
  parent_findings: ReturnType<typeof documentedParentFindingRows>;
  finding_groups: EdaFindingFamilySummary[];
  required_parent_finding_count: number;
  unresolved_parent_finding_count: number;
  eligible_parent_finding_count: number;
  informational_parent_finding_count: number;
  child_evidence_count: number;
  unresolved_required_parent_ids: string[];
  rationale_required_parent_ids: string[];
};

const ALL_DECISIONS: readonly EdaFindingDisposition[] = [
  "unresolved",
  "accepted",
  "rejected",
  "deferred",
  "documented",
  "no_action_required",
  "not_applicable",
] as const;

const REQUIRED_DECISIONS: readonly EdaFindingDisposition[] = [
  "unresolved",
  "accepted",
  "rejected",
  "deferred",
  "documented",
  "no_action_required",
] as const;

type FamilyDefinition = {
  title: string;
  requirement: EdaParentFindingRequirement;
  defaultDestination: EdaCarryForwardDestination | "";
  systemDisposition?: Exclude<EdaFindingDisposition, "unresolved">;
  systemRationale?: string;
};

const FAMILY_DEFINITIONS: Record<string, FamilyDefinition> = {
  exact_duplicate_rows: {
    title: "Exact duplicate rows",
    requirement: "blocker",
    defaultDestination: "Feature Engineering",
  },
  bureau_special_value_policy: {
    title: "Bureau special-value policy",
    requirement: "required",
    defaultDestination: "Missing Values",
  },
  high_iv_strong_signal_review: {
    title: "High-IV and strong-signal review",
    requirement: "required",
    defaultDestination: "Validation",
  },
  valid_value_monotonicity_review: {
    title: "Valid-value monotonicity review",
    requirement: "required",
    defaultDestination: "Feature Engineering",
  },
  inquiry_multicollinearity_cluster: {
    title: "Inquiry-variable multicollinearity cluster",
    requirement: "required",
    defaultDestination: "Feature Engineering",
  },
  derogatory_public_record_multicollinearity_cluster: {
    title: "Derogatory-public-record multicollinearity cluster",
    requirement: "required",
    defaultDestination: "Feature Engineering",
  },
  delinquency_multicollinearity_cluster: {
    title: "Delinquency-related multicollinearity cluster",
    requirement: "required",
    defaultDestination: "Feature Engineering",
  },
  other_correlated_feature_groups: {
    title: "Other correlated feature groups",
    requirement: "required",
    defaultDestination: "Feature Engineering",
  },
  target_source_exclusion: {
    title: "Target-source exclusion",
    requirement: "informational",
    defaultDestination: "Documentation",
    systemDisposition: "documented",
    systemRationale:
      "The deterministic target source remains excluded by the governed predictor authorization contract.",
  },
  balanced_target: {
    title: "Balanced target",
    requirement: "informational",
    defaultDestination: "Balance and Split",
    systemDisposition: "no_action_required",
    systemRationale:
      "The observed class balance is documented for downstream validation design; no EDA treatment is required.",
  },
  stability_segments_unavailable: {
    title: "Stability and Segments unavailable",
    requirement: "informational",
    defaultDestination: "Documentation",
    systemDisposition: "not_applicable",
    systemRationale:
      "No governed time or segment field and no approved comparison population are available. Time stability, segment comparison, drift, and PSI are not assessed.",
  },
  target_quality_review: {
    title: "Target quality and leakage review",
    requirement: "blocker",
    defaultDestination: "Validation",
  },
  predictor_quality_review: {
    title: "Predictor quality review",
    requirement: "required",
    defaultDestination: "Feature Engineering",
  },
  data_quality_review: {
    title: "Other data-quality findings",
    requirement: "required",
    defaultDestination: "Missing Values",
  },
  documentation_review: {
    title: "Documentation findings",
    requirement: "informational",
    defaultDestination: "Documentation",
    systemDisposition: "documented",
    systemRationale:
      "The analytical record is retained as immutable informational evidence.",
  },
};

function normalize(value: unknown) {
  return String(value ?? "").trim().toLowerCase();
}

function featureHaystack(item: EdaFinding) {
  return normalize(
    [
      item.title,
      item.metricLabel,
      item.analyticalBasis,
      ...item.affectedVariables,
    ].join(" "),
  );
}

function classifyFinding(item: EdaFinding): string {
  const text = featureHaystack(item);
  if (text.includes("duplicate")) return "exact_duplicate_rows";
  if (text.includes("bureau special") || text.includes("special-value")) {
    return "bureau_special_value_policy";
  }
  if (item.iv !== null && item.iv !== undefined) {
    return "high_iv_strong_signal_review";
  }
  if (text.includes("monotonic")) return "valid_value_monotonicity_review";
  if (item.targetSourceStatus === "excluded") return "target_source_exclusion";
  if (item.category === "Stability") return "stability_segments_unavailable";
  if (
    item.category === "Target" &&
    (text.includes("class balance") || text.includes("balanced")) &&
    item.severity === "info"
  ) {
    return "balanced_target";
  }
  if (item.category === "Relationships") {
    if (text.includes("inq") || text.includes("inquiry")) {
      return "inquiry_multicollinearity_cluster";
    }
    if (text.includes("derog") || text.includes("publicrec")) {
      return "derogatory_public_record_multicollinearity_cluster";
    }
    if (text.includes("delq") || text.includes("delinquen")) {
      return "delinquency_multicollinearity_cluster";
    }
    return "other_correlated_feature_groups";
  }
  if (item.category === "Target") return "target_quality_review";
  if (item.category === "Predictors") return "predictor_quality_review";
  if (item.category === "Data quality") return "data_quality_review";
  return "documentation_review";
}

function stableParentId(family: string) {
  return `eda-parent-${family.replace(/_/g, "-")}`;
}

function severityOf(children: readonly EdaFinding[]): EdaFindingSeverity {
  if (children.some((item) => item.severity === "high")) return "high";
  if (children.some((item) => item.severity === "moderate")) return "moderate";
  return "info";
}

function freezeChild(item: EdaFinding): EdaImmutableChildEvidence {
  return Object.freeze({
    ...item,
    affectedVariables: Object.freeze([...item.affectedVariables]),
    suggestedTransformations: Object.freeze([...item.suggestedTransformations]),
    evidenceReferences: Object.freeze([...item.evidenceReferences]),
  });
}

export function generateEdaParentFindings(
  sections: EdaFindingSections,
): EdaParentFinding[] {
  const grouped = new Map<string, EdaFinding[]>();
  for (const child of generateEdaFindings(sections)) {
    const family = classifyFinding(child);
    grouped.set(family, [...(grouped.get(family) ?? []), child]);
  }
  return [...grouped.entries()]
    .map(([family, children]) => {
      const definition =
        FAMILY_DEFINITIONS[family] ?? FAMILY_DEFINITIONS.documentation_review;
      const immutableChildren = Object.freeze(children.map(freezeChild));
      const category = children[0]?.category ?? "Documentation";
      return Object.freeze({
        parentId: stableParentId(family),
        family,
        title: definition.title,
        category,
        severity: severityOf(children),
        requirement: definition.requirement,
        affectedVariables: Object.freeze(
          [...new Set(children.flatMap((item) => item.affectedVariables))].sort(),
        ),
        childIds: Object.freeze(children.map((item) => item.id).sort()),
        childEvidence: immutableChildren,
        evidenceReferences: Object.freeze(
          [...new Set(children.flatMap((item) => item.evidenceReferences))].sort(),
        ),
        allowedDispositions:
          definition.requirement === "informational"
            ? ALL_DECISIONS
            : REQUIRED_DECISIONS,
        defaultDestination: definition.defaultDestination,
        systemDisposition: definition.systemDisposition,
        systemRationale: definition.systemRationale,
      }) as EdaParentFinding;
    })
    .sort(
      (left, right) =>
        ({ blocker: 3, required: 2, informational: 1 })[right.requirement] -
          ({ blocker: 3, required: 2, informational: 1 })[left.requirement] ||
        left.title.localeCompare(right.title),
    );
}

export function defaultParentFindingDecision(
  parent: EdaParentFinding,
): EdaFindingDecision {
  return {
    disposition: parent.systemDisposition ?? "unresolved",
    rationale: parent.systemRationale ?? "",
    destination: parent.defaultDestination,
    transformation: "No transformation",
  };
}

export function resolveParentFindingDecision(
  parent: EdaParentFinding,
  state: EdaFindingsReviewState,
): EdaFindingDecision {
  const explicit = state.parentDecisions?.[parent.parentId];
  if (explicit) return explicit;
  const legacy = parent.childIds
    .map((childId) => state.findingDecisions?.[childId])
    .filter((value): value is EdaFindingDecision => Boolean(value));
  if (
    legacy.length === parent.childIds.length &&
    legacy.length > 0 &&
    legacy.every(
      (decision) => decision.disposition === legacy[0].disposition,
    )
  ) {
    return legacy[0];
  }
  return defaultParentFindingDecision(parent);
}

export function decisionRequiresRationale(
  parent: EdaParentFinding,
  disposition: EdaFindingDisposition,
  options: { bulk?: boolean } = {},
) {
  if (disposition === "unresolved") return false;
  if (options.bulk) return true;
  if (disposition === "rejected" || disposition === "deferred") return true;
  if (parent.requirement === "blocker") return true;
  return disposition === "accepted" && parent.severity === "high";
}

export function isEligibleParentDisposition(
  parent: EdaParentFinding,
  decision: EdaFindingDecision,
) {
  if (!parent.allowedDispositions.includes(decision.disposition)) return false;
  if (parent.requirement === "informational") return true;
  if (decision.disposition === "unresolved") return false;
  if (decision.disposition === "not_applicable") return false;
  if (
    decisionRequiresRationale(parent, decision.disposition) &&
    !decision.rationale.trim()
  ) {
    return false;
  }
  return parent.requirement !== "blocker" || decision.disposition !== "deferred";
}

export function documentedParentFindingRows(
  parents: EdaParentFinding[],
  state: EdaFindingsReviewState,
) {
  return parents.map((parent) => {
    const decision = resolveParentFindingDecision(parent, state);
    return {
      parent_id: parent.parentId,
      family: parent.family,
      title: parent.title,
      category: parent.category,
      severity: parent.severity,
      requirement: parent.requirement,
      child_ids: [...parent.childIds],
      child_evidence: parent.childEvidence.map((child) => ({ ...child })),
      affected_variables: [...parent.affectedVariables],
      evidence_references: [...parent.evidenceReferences],
      allowed_dispositions: [...parent.allowedDispositions],
      reviewer_disposition: decision.disposition,
      reviewer_rationale: decision.rationale,
      downstream_destination: decision.destination || null,
      suggested_transformation: decision.transformation,
      eligible_for_completion: isEligibleParentDisposition(parent, decision),
      rationale_required: decisionRequiresRationale(
        parent,
        decision.disposition,
      ),
      decision_origin: state.parentDecisions?.[parent.parentId]
        ? "reviewer"
        : parent.systemDisposition
          ? "system_informational_default"
          : "unresolved",
      mutation_applied: false,
    };
  });
}

export function summarizeFindingGovernance(
  parents: EdaParentFinding[],
  state: EdaFindingsReviewState,
): EdaFindingsGovernanceSummary {
  const rows = documentedParentFindingRows(parents, state);
  const required = rows.filter((row) => row.requirement !== "informational");
  const unresolved = required.filter((row) => !row.eligible_for_completion);
  const rationaleRequired = rows.filter(
    (row) => row.rationale_required && !row.reviewer_rationale.trim(),
  );
  const byFamily = new Map<string, typeof rows>();
  for (const row of rows) {
    byFamily.set(row.family, [...(byFamily.get(row.family) ?? []), row]);
  }
  return {
    parent_findings: rows,
    finding_groups: [...byFamily.entries()].map(([family, groupRows]) => ({
      family,
      title: groupRows[0].title,
      parent_ids: groupRows.map((row) => row.parent_id),
      child_count: groupRows.reduce(
        (total, row) => total + row.child_ids.length,
        0,
      ),
      requirement: groupRows[0].requirement,
    })),
    required_parent_finding_count: required.length,
    unresolved_parent_finding_count: unresolved.length,
    eligible_parent_finding_count: rows.length - unresolved.length,
    informational_parent_finding_count: rows.filter(
      (row) => row.requirement === "informational",
    ).length,
    child_evidence_count: rows.reduce(
      (total, row) => total + row.child_ids.length,
      0,
    ),
    unresolved_required_parent_ids: unresolved.map((row) => row.parent_id),
    rationale_required_parent_ids: rationaleRequired.map(
      (row) => row.parent_id,
    ),
  };
}

/**
 * Build the findings portion of an evidence record from governed parent
 * decisions. Child rows are retained only as immutable analytical evidence;
 * they never become independent carry-forward recommendations.
 */
export function buildGovernedFindingEvidencePayload(
  sections: EdaFindingSections,
  state: EdaFindingsReviewState,
) {
  const governance = summarizeFindingGovernance(
    generateEdaParentFindings(sections),
    state,
  );
  const parentFindings = governance.parent_findings;
  const childEvidence = parentFindings.flatMap((parent) =>
    parent.child_evidence.map((child) => ({
      ...child,
      parent_id: parent.parent_id,
      family: parent.family,
      immutable: true,
      mutation_applied: false,
    })),
  );
  const carryForward = parentFindings
    .filter(
      (parent) =>
        ["accepted", "deferred"].includes(parent.reviewer_disposition) &&
        Boolean(parent.downstream_destination),
    )
    .map((parent) => ({
      parent_id: parent.parent_id,
      child_ids: [...parent.child_ids],
      family: parent.family,
      title: parent.title,
      destination: parent.downstream_destination,
      disposition: parent.reviewer_disposition,
      recommendation:
        parent.reviewer_disposition === "deferred"
          ? "Retain as a governed deferred recommendation for downstream review."
          : "Retain as a governed draft recommendation for downstream review.",
      transformation: parent.suggested_transformation,
      reviewerRationale: parent.reviewer_rationale,
      status: "draft_recommendation" as const,
      mutationApplied: false as const,
    }));
  return {
    governance,
    parentFindings,
    childEvidence,
    carryForward,
    automaticTransformationsApplied: false as const,
  };
}

export function applyBulkParentDisposition(input: {
  parents: EdaParentFinding[];
  state: EdaFindingsReviewState;
  family: string;
  disposition: EdaFindingDisposition;
  rationale: string;
  destination: EdaCarryForwardDestination | "";
  actor: string;
  timestamp?: string;
}): EdaFindingsReviewState {
  const selected = input.parents.filter(
    (parent) => parent.family === input.family,
  );
  if (!selected.length) throw new Error("No parent findings match this family.");
  if (!input.rationale.trim()) {
    throw new Error("Bulk disposition requires a reviewer rationale.");
  }
  const timestamp = input.timestamp ?? new Date().toISOString();
  const priorStatuses = Object.fromEntries(
    selected.map((parent) => [
      parent.parentId,
      resolveParentFindingDecision(parent, input.state).disposition,
    ]),
  );
  const decisions = { ...(input.state.parentDecisions ?? {}) };
  for (const parent of selected) {
    if (!parent.allowedDispositions.includes(input.disposition)) {
      throw new Error(
        `${input.disposition} is not permitted for ${parent.title}.`,
      );
    }
    decisions[parent.parentId] = {
      disposition: input.disposition,
      rationale: input.rationale.trim(),
      destination: input.destination || parent.defaultDestination,
      transformation: "No transformation",
      updatedAt: timestamp,
    };
  }
  const audit: EdaBulkDispositionAudit = {
    actionId: `eda-bulk-${timestamp}-${input.family}`,
    family: input.family,
    parentIds: selected.map((parent) => parent.parentId),
    childIds: selected.flatMap((parent) => [...parent.childIds]),
    priorStatuses,
    newStatus: input.disposition,
    rationale: input.rationale.trim(),
    destination: input.destination,
    actor: input.actor || "Authenticated reviewer",
    timestamp,
  };
  return {
    ...input.state,
    parentDecisions: decisions,
    bulkDispositionAudit: [...(input.state.bulkDispositionAudit ?? []), audit],
  };
}

export function buildOptionalReviewerDraft(
  parents: EdaParentFinding[],
  state: EdaFindingsReviewState,
  now = new Date().toISOString(),
) {
  const summary = summarizeFindingGovernance(parents, state);
  const notApplicable = parents.filter(
    (parent) =>
      resolveParentFindingDecision(parent, state).disposition ===
      "not_applicable",
  );
  return {
    overallConclusion:
      `${summary.child_evidence_count} immutable analytical records were consolidated into ${parents.length} decision-oriented parent findings. ` +
      `${summary.unresolved_parent_finding_count} required parent findings remain unresolved.`,
    commentary:
      "Generated from governed EDA evidence for reviewer editing. This draft does not approve EDA or change any disposition." +
      (notApplicable.length
        ? ` ${notApplicable.map((item) => item.title).join(", ")} is documented as not applicable.`
        : ""),
    generatedAt: now,
    nonApproving: true as const,
  };
}

export function evaluateFindingsCompletionEligibility(
  parents: EdaParentFinding[],
  state: EdaFindingsReviewState,
) {
  const governance = summarizeFindingGovernance(parents, state);
  const blockers: string[] = [];
  if (governance.unresolved_parent_finding_count) {
    blockers.push(
      `${governance.unresolved_parent_finding_count} required parent finding(s) need an eligible governed disposition and required rationale.`,
    );
  }
  if (!String(state.overallConclusion ?? "").trim()) {
    blockers.push("Reviewer conclusion is required.");
  }
  if (!String(state.commentary ?? "").trim()) {
    blockers.push("Reviewer commentary is required.");
  }
  if (!["accepted", "accepted_with_conditions"].includes(state.status)) {
    blockers.push(
      "Overall EDA status must be Accepted or Accepted with Conditions.",
    );
  }
  if (
    state.status === "accepted_with_conditions" &&
    !(state.requiredConditions ?? []).some((value) => value.trim())
  ) {
    blockers.push(
      "Accepted with Conditions requires at least one documented condition.",
    );
  }
  return {
    eligible: blockers.length === 0,
    blockers,
    governance,
    stability_not_applicable: parents.some(
      (parent) =>
        parent.family === "stability_segments_unavailable" &&
        resolveParentFindingDecision(parent, state).disposition ===
          "not_applicable",
    ),
  };
}
