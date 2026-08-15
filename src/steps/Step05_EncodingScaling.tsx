import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import {
  AlertTriangle,
  Braces,
  Calculator,
  CalendarDays,
  Check,
  CheckCircle2,
  ChevronDown,
  Clock3,
  Columns3,
  Eye,
  FileCheck2,
  GitCompareArrows,
  GitBranch,
  LoaderCircle,
  Pause,
  Pencil,
  Plus,
  Save,
  Search,
  Settings2,
  ShieldCheck,
  Sparkles,
  X,
} from "lucide-react";
import StepShell from "../components/StepShell";
import {
  CarryForwardPanel,
  PreparationPageIdentity,
  PreparationQuickSummary,
} from "../components/preparation/PreparationPageChrome";
import {
  AtlasAttentionPanel,
  AtlasDataScopeBadge,
  AtlasExecutionStatus,
  AtlasWorkflowSection,
} from "../components/ui/AtlasWorkflow";
import {
  confirmFeatureManifest,
  getFeatureManifest,
  materializeFeatureManifest,
  previewFeaturePlan,
  removeFeature,
  saveFeatureManifest,
  type FeatureDraft,
  type FeatureManifest,
  type FeatureManifestRow,
  type FeatureOrigin,
  type FeaturePreview,
  type PipelineStep,
} from "../lib/featureManifest";
import { createEvidence, type EvidenceItem } from "../lib/evidenceGraph";
import { syncFeatureEngineeringMdd } from "../lib/featureEngineeringCompletion";
import {
  assertExactDatasetIdentity,
  buildCanonicalEvidenceEnvelope,
  canonicalDatasetStorageKey,
  requireLocalDatasetCanonicalIdentity,
  type CanonicalDatasetIdentity,
} from "../lib/datasetIdentity";
import { logDecision } from "../lib/decisionJournal";
import {
  buildFeatureRecommendations,
  recommendationToFeatureDraft,
  type FeatureRecommendation,
} from "../lib/featureRecommendations";
import {
  buildArithmeticFeature,
  buildDateDerivedFeature,
  buildInteractionFeature,
  buildNumericBinFeature,
  buildPolynomialFeature,
  buildRuleCategoryFeature,
  inferFeatureUnit,
  resolveDateDerivedAvailability,
  type BuilderValidationResult,
  type FeatureBuilderSource,
  type RuleOperator,
} from "../lib/featureBuilderValidation";
import { loadLocalDataset } from "../lib/localDataset";
import {
  getEdaCarryForward,
  getPreparationDocumentation,
  saveCarryForwardDisposition,
  type CarryForwardDisposition,
  type PreparationCarryForwardItem,
  type PreparationDocumentationState,
} from "../lib/preparationGovernance";
import { useWorkflowStore } from "../state/useWorkflowStore";
import BureauSemanticContextPanel from "../components/BureauSemanticContextPanel";

const API_BASE =
  (import.meta.env.VITE_API_BASE as string | undefined)?.replace(/\/$/, "") ||
  "http://127.0.0.1:8001/api";

type BuilderType = "interaction" | "numeric_bin" | "categorical_rule" | "polynomial" | "arithmetic" | "date-derived";

type VifRow = {
  feature: string;
  vif: number | null;
  status: string;
};

type RecommendationDisposition =
  | "suggested"
  | "accepted_to_plan"
  | "rejected"
  | "deferred";

type VifCarryForwardRecommendation = {
  recommendation_id: string;
  source_plan_id: string;
  cluster_id: string;
  action: "retain" | "exclude" | "combine" | "defer";
  features: string[];
  proposed_exclusions: string[];
  protected_features: string[];
  status: "draft_recommendation";
  rationale: string;
};

const PREVIEW_ROW_LIMITS = [10, 25, 50, 100] as const;
const VIF_AUTO_EXCLUDE_THRESHOLD = 10;

const builderOptions: Array<{ id: BuilderType; label: string; icon: typeof Plus; description: string }> = [
  { id: "interaction", label: "Interaction", icon: GitCompareArrows, description: "Multiply two governed numeric predictors." },
  { id: "numeric_bin", label: "Numeric Bin", icon: Columns3, description: "Create fixed reviewer-defined cut points." },
  { id: "categorical_rule", label: "Rule Category", icon: Braces, description: "Create a deterministic category from explicit rules." },
  { id: "polynomial", label: "Polynomial", icon: Calculator, description: "Create one named squared or cubed term." },
  { id: "arithmetic", label: "Arithmetic", icon: Calculator, description: "Add, subtract, multiply, or divide two predictors." },
  { id: "date-derived", label: "Date Derived", icon: CalendarDays, description: "Extract a governed date component." },
];

function toDraft(row: Partial<FeatureManifestRow>): FeatureDraft {
  const featureName = row.feature_name?.trim() || row.feature_id || "unnamed_feature";
  const origin = row.origin ?? "other";
  return {
    feature_id: row.feature_id,
    feature_name: featureName,
    display_name: row.display_name?.trim() || featureName,
    origin,
    source_features: Array.isArray(row.source_features) ? row.source_features.filter(Boolean) : [],
    transformation_type: row.transformation_type || origin,
    formula_or_rule: row.formula_or_rule || "Metadata requires review",
    output_datatype: row.output_datatype || "unknown",
    selected: row.selected !== false,
    exclusion_reason: row.exclusion_reason || "",
    user_rationale: row.user_rationale || "",
    config: row.config ?? {},
  };
}

function parseList(value: string) {
  return value.split(",").map((item) => item.trim()).filter(Boolean);
}

function parseNumbers(value: string) {
  return Array.from(new Set(parseList(value).map(Number).filter(Number.isFinite))).sort((left, right) => left - right);
}

export default function Step05FeatureEngineering() {
  const localDataset = loadLocalDataset();
  const projectId = useWorkflowStore((state) => state.projectId);
  const projectName = useWorkflowStore((state) => state.projectName);
  const getNextStepPath = useWorkflowStore((state) => state.getNextStepPath);
  let datasetIdentity: CanonicalDatasetIdentity | null = null;
  let datasetIdentityError = "";
  try {
    datasetIdentity = requireLocalDatasetCanonicalIdentity(
      projectId,
      localDataset,
      "Feature Engineering dataset identity",
    );
  } catch (cause) {
    datasetIdentityError =
      cause instanceof Error
        ? cause.message
        : "Feature Engineering requires an exact registered Dataset Library version.";
  }
  const [manifest, setManifest] = useState<FeatureManifest | null>(null);
  const [drafts, setDrafts] = useState<FeatureDraft[]>([]);
  const [pipelineSteps, setPipelineSteps] = useState<PipelineStep[]>([]);
  const [builderType, setBuilderType] = useState<BuilderType>("interaction");
  const [form, setForm] = useState<Record<string, string>>({});
  const [dirty, setDirty] = useState(false);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [materializing, setMaterializing] = useState(false);
  const [previewing, setPreviewing] = useState(false);
  const [previewRowLimit, setPreviewRowLimit] = useState(10);
  const [preview, setPreview] = useState<FeaturePreview | null>(null);
  const [featureSearch, setFeatureSearch] = useState("");
  const [featureKindFilter, setFeatureKindFilter] = useState<
    "all" | "source" | "engineered" | "included"
  >("all");
  const [selectedFeatureKey, setSelectedFeatureKey] = useState("");
  const [editingFeatureKey, setEditingFeatureKey] = useState("");
  const [editingDraft, setEditingDraft] = useState<FeatureDraft | null>(null);
  const [confirming, setConfirming] = useState(false);
  const [advancing, setAdvancing] = useState(false);
  const [advancingStage, setAdvancingStage] = useState("");
  const [vifRows, setVifRows] = useState<VifRow[] | null>(null);
  const [vifLoading, setVifLoading] = useState(false);
  const [vifSaving, setVifSaving] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [recommendationDispositions, setRecommendationDispositions] =
    useState<Record<string, RecommendationDisposition>>({});
  const [recommendationFilter, setRecommendationFilter] = useState<
    "all" | "eligible" | "accepted" | "deferred"
  >("all");
  const [recommendationPreviewId, setRecommendationPreviewId] = useState("");
  const [carryForward, setCarryForward] = useState<
    PreparationCarryForwardItem[]
  >([]);
  const [edaDocumentStatus, setEdaDocumentStatus] = useState("unavailable");
  const [edaManifest, setEdaManifest] = useState("");
  const [predictorEvidence, setPredictorEvidence] = useState<
    Record<
      string,
      {
        iv?: number | null;
        outlierRate?: number | null;
        monotonicity?: string | null;
      }
    >
  >({});
  const [highCorrelationPairs, setHighCorrelationPairs] = useState<
    Array<Record<string, unknown>>
  >([]);
  const [vifCarryForwardRecommendations, setVifCarryForwardRecommendations] =
    useState<VifCarryForwardRecommendation[]>([]);
  const [preparationDocs, setPreparationDocs] =
    useState<PreparationDocumentationState | null>(null);
  const previewController = useRef<AbortController | null>(null);
  const advancingRef = useRef(false);

  async function loadManifest() {
    setLoading(true);
    setError(datasetIdentityError);
    if (!datasetIdentity) {
      setLoading(false);
      return;
    }
    try {
      const payload = await getFeatureManifest(datasetIdentity);
      setManifest(payload);
      setDrafts(payload.features.filter((feature) => feature.origin !== "original").map(toDraft));
      setPipelineSteps(payload.pipeline_steps ?? []);
      setDirty(false);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Feature manifest is unavailable.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void loadManifest();
    if (datasetIdentity) {
      try {
        setRecommendationDispositions(
          JSON.parse(
            localStorage.getItem(
              canonicalDatasetStorageKey(
                "atlas:feature-recommendation-dispositions",
                datasetIdentity,
              ),
            ) || "{}",
          ),
        );
      } catch {
        setRecommendationDispositions({});
      }
    } else {
      setRecommendationDispositions({});
    }
    const controller = new AbortController();
    if (datasetIdentity) {
      getEdaCarryForward(
        datasetIdentity,
        "feature_engineering",
        controller.signal,
      )
        .then((context) => {
          setCarryForward(context.items);
          setEdaDocumentStatus(context.documentationStatus);
          setEdaManifest(context.predictorManifestId);
          setPredictorEvidence(context.predictorEvidence);
          setHighCorrelationPairs(context.highCorrelationPairs);
        })
        .catch(() => undefined);
      getPreparationDocumentation(datasetIdentity, controller.signal)
        .then(setPreparationDocs)
        .catch(() => undefined);
      const vifRecommendationQuery = new URLSearchParams({
        project_id: datasetIdentity.project_id,
        expected_dataset_id: datasetIdentity.dataset_id,
        expected_dataset_version_id: datasetIdentity.dataset_version_id,
      });
      fetch(
        `${API_BASE}/eda/vif-resolution-recommendations?${vifRecommendationQuery}`,
        { credentials: "include", signal: controller.signal },
      )
        .then(async (response) => {
          const payload = await response.json().catch(() => null);
          if (!response.ok || !payload?.ok) return [];
          assertExactDatasetIdentity(
            datasetIdentity,
            payload,
            "Feature Engineering VIF recommendation carry-forward",
          );
          if (
            payload.governed_feature_set_changed !== false ||
            payload.dataset_mutated !== false
          ) {
            throw new Error(
              "VIF carry-forward violated the draft-recommendation contract.",
            );
          }
          return Array.isArray(payload.recommendations)
            ? payload.recommendations
            : [];
        })
        .then(setVifCarryForwardRecommendations)
        .catch(() => undefined);
    } else {
      setVifCarryForwardRecommendations([]);
    }
    return () => controller.abort();
  }, [
    projectId,
    datasetIdentity?.dataset_id,
    datasetIdentity?.dataset_version_id,
  ]);

  const originals = manifest?.features.filter((feature) => feature.origin === "original") ?? [];
  const forbiddenBuilderSources = useMemo(
    () =>
      new Set(
        [
          ...(manifest?.predictor_authorization?.target_source_excluded ?? []),
          ...Object.keys(
            manifest?.predictor_authorization?.excluded_predictors ?? {},
          ),
        ].map((name) => name.toLocaleLowerCase()),
      ),
    [manifest?.predictor_authorization],
  );
  const eligibleOriginals = originals.filter(
    (feature) =>
      feature.eligibility_status === "eligible" &&
      !forbiddenBuilderSources.has(feature.feature_name.toLocaleLowerCase()),
  );
  const numericOriginals = eligibleOriginals.filter((feature) => /int|float|double|numeric|number/i.test(feature.output_datatype));
  const categoricalOriginals = eligibleOriginals.filter((feature) => !numericOriginals.includes(feature));
  const builderSourceCatalog = useMemo<FeatureBuilderSource[]>(
    () =>
      [
        ...eligibleOriginals.map((feature) => ({
          name: feature.feature_name,
          dataType: feature.output_datatype,
          eligible: true,
          unit: inferFeatureUnit(feature.feature_name),
          minimum:
            typeof feature.summary_statistics?.minimum === "number"
              ? feature.summary_statistics.minimum
              : null,
          maximum:
            typeof feature.summary_statistics?.maximum === "number"
              ? feature.summary_statistics.maximum
              : null,
          governedDate: /date|datetime|timestamp/i.test(feature.output_datatype),
        })),
        ...drafts.map((draft) => ({
          name: draft.feature_name,
          dataType: draft.output_datatype,
          eligible: draft.selected,
          exclusionReason: draft.exclusion_reason,
          unit: String(draft.config?.result_unit || inferFeatureUnit(draft.feature_name)),
          minimum: null,
          maximum: null,
          governedDate: draft.origin === "date-derived",
        })),
      ],
    [drafts, eligibleOriginals],
  );
  const availableNames = useMemo(() => [...eligibleOriginals.map((feature) => feature.feature_name), ...drafts.map((feature) => feature.feature_name)], [drafts, eligibleOriginals]);
  const numericNames = useMemo(() => [...numericOriginals.map((feature) => feature.feature_name), ...drafts.filter((feature) => feature.output_datatype === "numeric").map((feature) => feature.feature_name)], [drafts, numericOriginals]);
  const vifCandidateNames = useMemo(() => (manifest?.features ?? [])
    .filter((feature) => feature.selected
      && feature.eligibility_status === "eligible"
      && /int|float|double|numeric|number/i.test(feature.output_datatype)
      && (feature.origin === "original" || feature.materialization_status === "materialized"))
    .map((feature) => feature.feature_name), [manifest]);
  const selectedByFeature = useMemo(() => new Map((manifest?.features ?? []).map((feature) => [feature.feature_name, feature.selected])), [manifest]);
  const materializedCount = manifest?.features.filter((feature) => feature.origin !== "original" && feature.materialization_status === "materialized").length ?? 0;
  const exactMaterialization =
    !!manifest &&
    manifest.validation_status === "passed" &&
    manifest.materialization_status === "current" &&
    manifest.materialized_manifest_hash === manifest.manifest_hash;
  const planReady =
    !dirty &&
    exactMaterialization &&
    manifest?.confirmation_status === "confirmed" &&
    manifest.confirmed_manifest_hash === manifest.manifest_hash &&
    drafts.filter((draft) => draft.selected).every((draft) =>
      manifest.features.some(
        (feature) =>
          (feature.feature_id === draft.feature_id ||
            feature.feature_name === draft.feature_name) &&
          feature.materialization_status === "materialized",
      ),
    );
  const dateAvailability = useMemo(
    () => resolveDateDerivedAvailability(builderSourceCatalog),
    [builderSourceCatalog],
  );
  const dateNames = dateAvailability.dateSources;
  const excludedFeatures = useMemo(
    () =>
      Object.fromEntries(
        originals
          .filter((feature) => feature.eligibility_status === "excluded")
          .map((feature) => [
            feature.feature_name,
            feature.exclusion_reason || "Excluded by predictor governance",
          ]),
      ),
    [originals],
  );
  const recommendations = useMemo(
    () =>
      buildFeatureRecommendations({
        availableFeatures: eligibleOriginals.map(
          (feature) => feature.feature_name,
        ),
        excludedFeatures,
        existingFeatureNames: [
          ...originals.map((feature) => feature.feature_name),
          ...drafts.map((feature) => feature.feature_name),
        ],
        evidenceByFeature: predictorEvidence,
      }),
    [drafts, eligibleOriginals, excludedFeatures, originals, predictorEvidence],
  );
  const visibleRecommendations = recommendations.filter((recommendation) => {
    const disposition =
      recommendationDispositions[recommendation.id] ?? "suggested";
    if (recommendationFilter === "eligible") return recommendation.eligible;
    if (recommendationFilter === "accepted") {
      return disposition === "accepted_to_plan";
    }
    if (recommendationFilter === "deferred") return disposition === "deferred";
    return true;
  });
  const acceptedRecommendationCount = Object.values(
    recommendationDispositions,
  ).filter((value) => value === "accepted_to_plan").length;

  function field(name: string) {
    return form[name] ?? "";
  }

  function updateField(name: string, value: string) {
    setForm((current) => ({ ...current, [name]: value }));
  }

  function addFeature() {
    setError("");
    const name = field("name").trim();
    const common = {
      name,
      rationale: field("rationale"),
      existingFeatureNames: availableNames,
      sourceCatalog: builderSourceCatalog,
    };
    let validation: BuilderValidationResult;
    if (builderType === "interaction") {
      validation = buildInteractionFeature({
        ...common,
        left: field("left"),
        right: field("right"),
      });
    } else if (builderType === "numeric_bin") {
      const source = field("source");
      const binningMode = field("binningMode") || "custom";
      const cutPoints =
        binningMode === "custom" ? parseNumbers(field("cutPoints")) : [];
      const labels = parseList(field("labels"));
      const specialValueLabel = field("specialValueLabel") || "Bureau special";
      const missingValueLabel = field("missingLabel") || "Missing";
      if (binningMode === "quantile") {
        const quantiles = [0.2, 0.4, 0.6, 0.8];
        const resolvedLabels = labels.length
          ? labels
          : ["Very low", "Low", "Mid", "High", "Very high"];
        validation =
          !source || resolvedLabels.length !== quantiles.length + 1
            ? {
                ok: false,
                definition: null,
                errors: [
                  {
                    code: "quantile_definition_invalid",
                    severity: "error",
                    message:
                      "Quantile bins require one numeric source and exactly five ordinary labels.",
                  },
                ],
                warnings: [],
              }
            : {
                ok: true,
                definition: makeDraft(
                  name,
                  builderType,
                  [source],
                  `quantile_band(${source}; 20%, 40%, 60%, 80%)`,
                  "categorical",
                  {
                    binning_mode: "quantile",
                    quantiles,
                    labels: resolvedLabels,
                    missing_label: missingValueLabel,
                    special_value_label: specialValueLabel,
                    special_value_policy: "separate_category",
                    preserve_bureau_special_values: true,
                  },
                ),
                errors: [],
                warnings: [],
              };
      } else {
        validation = buildNumericBinFeature({
          ...common,
          source,
          cutPoints,
          labels,
          specialValueLabel,
          missingValueLabel,
        });
      }
    } else if (builderType === "categorical_rule") {
      validation = buildRuleCategoryFeature({
        ...common,
        source: field("source"),
        operator: (field("operator") || "equals") as RuleOperator,
        value: field("value"),
        matchedLabel: field("thenLabel") || "Matched",
        elseLabel: field("elseLabel") || "Other",
        specialValueLabel: field("specialValueLabel") || "Bureau special",
      });
    } else if (builderType === "polynomial") {
      validation = buildPolynomialFeature({
        ...common,
        source: field("source"),
        degree: Number(field("degree") || 2),
      });
    } else if (builderType === "arithmetic") {
      const operation = (field("operation") || "add") as
        | "add"
        | "subtract"
        | "multiply"
        | "divide";
      validation = buildArithmeticFeature({
        ...common,
        left: field("left"),
        right: field("right"),
        operation,
        requireNonnegativeResult: field("resultDomain") === "nonnegative",
        domainEvidence: {
          leftGreaterThanOrEqualRight:
            field("domainEvidence") === "left_gte_right",
          rightNonZero: field("domainEvidence") === "right_nonzero",
          note: field("domainNote"),
        },
      });
    } else {
      validation = buildDateDerivedFeature({
        ...common,
        source: field("source"),
        component: (field("component") || "year") as
          | "year"
          | "month"
          | "quarter"
          | "day_of_week",
      });
    }
    if (!validation.ok || !validation.definition) {
      setError(
        validation.errors.map((item) => item.message).join(" ") ||
          "The feature definition is not valid.",
      );
      return;
    }
    const draft = validation.definition;
    setDrafts((current) => [...current, draft]);
    setDirty(true);
    setPreview(null);
    setForm({});
    setMessage(
      validation.warnings.length
        ? `${name} was added to the draft feature set. ${validation.warnings.map((item) => item.message).join(" ")}`
        : `${name} was added to the draft feature set. Review it in the table, then use Confirm Feature Set & Continue.`,
    );
  }

  function persistRecommendationDisposition(
    recommendationId: string,
    disposition: RecommendationDisposition,
  ) {
    setRecommendationDispositions((current) => {
      const next = { ...current, [recommendationId]: disposition };
      try {
        if (!datasetIdentity) {
          throw new Error(
            "Recommendation decisions require an exact registered Dataset Library version.",
          );
        }
        localStorage.setItem(
          canonicalDatasetStorageKey(
            "atlas:feature-recommendation-dispositions",
            datasetIdentity,
          ),
          JSON.stringify(next),
        );
      } catch {
        setMessage(
          "Recommendation decisions are retained for this session, but browser persistence is unavailable.",
        );
      }
      return next;
    });
  }

  function acceptRecommendation(recommendation: FeatureRecommendation) {
    setError("");
    if (!recommendation.eligible) {
      setError(recommendation.blockedReason);
      return;
    }
    if (
      drafts.some(
        (draft) =>
          draft.feature_name.toLowerCase() ===
          recommendation.featureName.toLowerCase(),
      )
    ) {
      persistRecommendationDisposition(
        recommendation.id,
        "accepted_to_plan",
      );
      setMessage(
        `${recommendation.featureName} is already present in the governed plan.`,
      );
      return;
    }
    try {
      const draft = recommendationToFeatureDraft(recommendation);
      setDrafts((current) => [...current, draft]);
      setDirty(true);
      setPreview(null);
      setRecommendationPreviewId("");
      persistRecommendationDisposition(
        recommendation.id,
        "accepted_to_plan",
      );
      logDecision({
        workflowStep: "Feature Engineering",
        actionType: "feature_inclusion_changed",
        subject: recommendation.featureName,
        previousValue: "suggested",
        newValue: "accepted_to_plan",
        systemRecommendation: recommendation.expectedBenefit,
        followStatus: "followed",
        userReason: recommendation.rationale,
      });
      setMessage(
        `${recommendation.featureName} was accepted to the draft plan. It has not been saved or materialized.`,
      );
    } catch (cause) {
      setError(
        cause instanceof Error
          ? cause.message
          : "The recommendation could not be accepted.",
      );
    }
  }

  function decideRecommendation(
    recommendation: FeatureRecommendation,
    disposition: "rejected" | "deferred",
  ) {
    persistRecommendationDisposition(recommendation.id, disposition);
    logDecision({
      workflowStep: "Feature Engineering",
      actionType: "feature_inclusion_changed",
      subject: recommendation.featureName,
      previousValue:
        recommendationDispositions[recommendation.id] ?? "suggested",
      newValue: disposition,
      systemRecommendation: recommendation.expectedBenefit,
      followStatus:
        disposition === "rejected" ? "overrode" : "not_applicable",
    });
    setMessage(
      `${recommendation.featureName} was ${disposition}. No feature was added or materialized.`,
    );
  }

  async function previewRecommendation(
    recommendation: FeatureRecommendation,
  ) {
    if (!datasetIdentity) {
      setError(datasetIdentityError);
      return;
    }
    const existing = drafts.find(
      (draft) =>
        draft.feature_name.toLowerCase() ===
        recommendation.featureName.toLowerCase(),
    );
    if (!existing && !recommendation.eligible) {
      setError(recommendation.blockedReason);
      return;
    }
    let candidate: FeatureDraft;
    try {
      candidate = existing ?? recommendationToFeatureDraft(recommendation);
    } catch (cause) {
      setError(
        cause instanceof Error
          ? cause.message
          : "The recommendation preview is unavailable.",
      );
      return;
    }
    previewController.current?.abort();
    const controller = new AbortController();
    previewController.current = controller;
    setPreviewing(true);
    setError("");
    try {
      const plan = [
        ...drafts.filter(
          (draft) =>
            draft.feature_name.toLowerCase() !==
            candidate.feature_name.toLowerCase(),
        ),
        candidate,
      ];
      const payload = await previewFeaturePlan(
        datasetIdentity,
        plan,
        previewRowLimit,
        controller.signal,
      );
      setPreview(payload);
      setRecommendationPreviewId(recommendation.id);
      setMessage(
        `${recommendation.featureName} previewed on ${payload.preview_row_count} bounded rows. The plan and backend frame were not changed.`,
      );
    } catch (cause) {
      if (cause instanceof DOMException && cause.name === "AbortError") return;
      setError(
        cause instanceof Error
          ? cause.message
          : "Recommendation preview failed.",
      );
    } finally {
      if (!controller.signal.aborted) setPreviewing(false);
    }
  }

  function handleCarryForward(
    item: PreparationCarryForwardItem,
    disposition: CarryForwardDisposition,
  ) {
    if (!datasetIdentity) {
      setError(
        datasetIdentityError ||
          "Feature-planning evidence decisions require an exact registered Dataset Library version.",
      );
      return;
    }
    saveCarryForwardDisposition(
      datasetIdentity,
      "feature_engineering",
      item.findingId,
      disposition,
    );
    setCarryForward((current) =>
      current.map((row) =>
        row.findingId === item.findingId ? { ...row, disposition } : row,
      ),
    );
    setMessage(
      disposition === "accepted"
        ? `${item.title} is accepted as feature-planning evidence. It did not add or remove a predictor.`
        : `${item.title} remains ${disposition} at the Feature Engineering destination.`,
    );
  }

  async function savePlan() {
    if (!datasetIdentity) {
      setError(datasetIdentityError);
      return;
    }
    setSaving(true);
    setError("");
    try {
      const payload = await saveFeatureManifest(
        datasetIdentity,
        drafts,
        pipelineSteps,
      );
      setManifest(payload);
      setDrafts(payload.features.filter((feature) => feature.origin !== "original").map(toDraft));
      setPipelineSteps(payload.pipeline_steps ?? []);
      setDirty(false);
      setPreview(null);
      setMessage(`Feature manifest ${payload.manifest_version} saved. Deterministic features are ready to materialize.`);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "The feature plan could not be saved.");
    } finally {
      setSaving(false);
    }
  }

  async function runPreview() {
    if (!datasetIdentity) {
      setError(datasetIdentityError);
      return;
    }
    if (dirty || !manifest) {
      setError("Validate and save the current transformation plan before previewing it.");
      return;
    }
    previewController.current?.abort();
    const controller = new AbortController();
    previewController.current = controller;
    setPreviewing(true);
    setError("");
    try {
      const payload = await previewFeaturePlan(
        datasetIdentity,
        drafts,
        previewRowLimit,
        controller.signal,
        manifest.manifest_hash,
      );
      setPreview(payload);
      const refreshed = await getFeatureManifest(datasetIdentity);
      setManifest(refreshed);
      setMessage(`Preview ${payload.preview_hash} generated from ${payload.preview_row_count} bounded rows. No full-data materialization occurred.`);
    } catch (cause) {
      if (cause instanceof DOMException && cause.name === "AbortError") return;
      setError(cause instanceof Error ? cause.message : "Feature preview failed.");
    } finally {
      if (!controller.signal.aborted) setPreviewing(false);
    }
  }

  async function materialize() {
    if (!datasetIdentity) {
      setError(datasetIdentityError);
      return;
    }
    if (dirty) {
      setError("Save the current transformation plan before materializing features.");
      return;
    }
    if (!manifest) return;
    setMaterializing(true);
    setError("");
    try {
      const previewHash =
        preview?.manifest_hash === manifest.manifest_hash
          ? preview.preview_hash
          : manifest.preview_hash;
      if (!previewHash) {
        setError("Preview the saved feature contract before full-data materialization.");
        return;
      }
      const payload = await materializeFeatureManifest(
        datasetIdentity,
        manifest.manifest_hash,
        previewHash,
      );
      await loadManifest();
      setMessage(`${payload.engineered_feature_count} engineered features materialized across ${payload.row_count.toLocaleString()} backend rows in ${payload.duration_ms.toLocaleString()} ms. Materialization ${payload.materialization_hash} now matches ${payload.manifest_hash}.`);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Feature materialization failed.");
    } finally {
      setMaterializing(false);
    }
  }

  async function confirmCurrentSet() {
    if (!datasetIdentity) {
      setError(datasetIdentityError);
      return;
    }
    if (!manifest || !exactMaterialization) {
      setError("Materialize the exact saved feature contract before confirming the set current.");
      return;
    }
    setConfirming(true);
    setError("");
    try {
      const payload = await confirmFeatureManifest(
        datasetIdentity,
        manifest.manifest_hash,
        manifest.materialization_hash,
      );
      setManifest(payload);
      setMessage(`Feature set confirmed current against ${payload.manifest_hash}. Balance & Split may now consume this exact contract.`);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "The current feature set could not be confirmed.");
    } finally {
      setConfirming(false);
    }
  }

  async function deleteDraft(draft: FeatureDraft) {
    if (!datasetIdentity) {
      setError(datasetIdentityError);
      return;
    }
    if (draft.feature_id && manifest?.features.some((feature) => feature.feature_id === draft.feature_id)) {
      try {
        const payload = await removeFeature(datasetIdentity, draft.feature_id);
        setManifest(payload);
        setDrafts(payload.features.filter((feature) => feature.origin !== "original").map(toDraft));
        setDirty(false);
        setMessage(
          `${draft.feature_name} was removed. Confirm Feature Set & Continue will refresh the governed backend contract.`,
        );
      } catch (cause) {
        setError(cause instanceof Error ? cause.message : "The feature could not be removed.");
      }
    } else {
      setDrafts((current) => current.filter((item) => item !== draft));
      setDirty(true);
      setPreview(null);
    }
    if ((draft.feature_id ?? draft.feature_name) === selectedFeatureKey) {
      setSelectedFeatureKey("");
      setEditingFeatureKey("");
      setEditingDraft(null);
    }
  }

  function beginEdit(draft: FeatureDraft) {
    const key = draft.feature_id ?? draft.feature_name;
    setSelectedFeatureKey(key);
    setEditingFeatureKey(key);
    setEditingDraft({
      ...draft,
      source_features: [...draft.source_features],
      config: { ...draft.config },
    });
  }

  function saveFeatureEdit() {
    if (!editingDraft) return;
    const name = editingDraft.feature_name.trim();
    if (!name) {
      setError("Feature name is required.");
      return;
    }
    const duplicate = drafts.some(
      (draft) =>
        (draft.feature_id ?? draft.feature_name) !== editingFeatureKey &&
        draft.feature_name.toLowerCase() === name.toLowerCase(),
    );
    if (duplicate || originals.some((row) => row.feature_name.toLowerCase() === name.toLowerCase())) {
      setError(`Feature name '${name}' already exists.`);
      return;
    }
    const next = {
      ...editingDraft,
      feature_name: name,
      display_name: editingDraft.display_name?.trim() || name,
    };
    setDrafts((current) =>
      current.map((draft) =>
        (draft.feature_id ?? draft.feature_name) === editingFeatureKey
          ? next
          : draft,
      ),
    );
    setDirty(true);
    setPreview(null);
    setSelectedFeatureKey(next.feature_id ?? next.feature_name);
    setEditingFeatureKey("");
    setEditingDraft(null);
    setMessage(
      `${name} was updated in the draft contract. Review it, then use Confirm Feature Set & Continue.`,
    );
  }

  function duplicateFeature(draft: FeatureDraft) {
    const existing = new Set(
      [...originals.map((row) => row.feature_name), ...drafts.map((row) => row.feature_name)]
        .map((name) => name.toLowerCase()),
    );
    const base = `${draft.feature_name}_copy`;
    let name = base;
    let suffix = 2;
    while (existing.has(name.toLowerCase())) {
      name = `${base}_${suffix}`;
      suffix += 1;
    }
    const copy: FeatureDraft = {
      ...draft,
      feature_id: undefined,
      feature_name: name,
      display_name: name,
      source_features: [...draft.source_features],
      config: { ...draft.config },
      user_rationale: `Duplicate of ${draft.feature_name}. ${draft.user_rationale}`.trim(),
    };
    setDrafts((current) => [...current, copy]);
    setDirty(true);
    setPreview(null);
    setSelectedFeatureKey(name);
    setMessage(
      `${name} was duplicated into the draft feature set. Review its definition before continuing.`,
    );
  }

  function focusFeatureDetail(draft: FeatureDraft, mode: "detail" | "lineage" | "evidence") {
    setSelectedFeatureKey(draft.feature_id ?? draft.feature_name);
    setEditingFeatureKey("");
    setEditingDraft(null);
    if (mode === "lineage") {
      document.getElementById("feature-lineage-graph")?.scrollIntoView({
        behavior: "smooth",
        block: "start",
      });
    } else if (mode === "evidence") {
      setMessage(`Evidence context opened for ${draft.feature_name}. The detail panel shows its rationale, source contract, profile summary, and evidence reference.`);
    }
  }

  async function previewFeatureRow(draft: FeatureDraft) {
    if (!datasetIdentity) {
      setError(datasetIdentityError);
      return;
    }
    previewController.current?.abort();
    const controller = new AbortController();
    previewController.current = controller;
    setPreviewing(true);
    setError("");
    focusFeatureDetail(draft, "detail");
    try {
      const payload = await previewFeaturePlan(
        datasetIdentity,
        drafts,
        previewRowLimit,
        controller.signal,
        !dirty ? manifest?.manifest_hash ?? "" : "",
      );
      setPreview(payload);
      if (!dirty && payload.preview_hash) {
        const refreshed = await getFeatureManifest(datasetIdentity);
        setManifest(refreshed);
      }
      setMessage(
        `${draft.feature_name} is visible in a ${payload.preview_row_count}-row bounded preview. ${
          dirty
            ? "This draft preview does not satisfy the saved-contract preview gate."
            : `Preview ${payload.preview_hash} satisfies the current contract gate.`
        }`,
      );
    } catch (cause) {
      if (cause instanceof DOMException && cause.name === "AbortError") return;
      setError(cause instanceof Error ? cause.message : "Feature preview failed.");
    } finally {
      if (!controller.signal.aborted) setPreviewing(false);
    }
  }

  async function runVif() {
    if (!datasetIdentity) {
      setError(datasetIdentityError);
      return;
    }
    if (dirty) {
      setError("Save and materialize the current feature plan before running VIF diagnostics.");
      return;
    }
    if (vifCandidateNames.length < 2) {
      setError("At least two selected numeric predictors are required for VIF diagnostics.");
      return;
    }
    setVifLoading(true);
    setError("");
    try {
      const response = await fetch(`${API_BASE}/eda/workspace/relationships`, {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          project_id: projectId,
          expected_dataset_id: datasetIdentity.dataset_id,
          expected_dataset_version_id: datasetIdentity.dataset_version_id,
          dataset_version: datasetIdentity.dataset_version_id,
          selected_features: vifCandidateNames,
        }),
      });
      const payload = await response.json().catch(() => null);
      if (!response.ok || !payload?.ok) throw new Error(payload?.detail ?? "VIF analysis failed.");
      assertExactDatasetIdentity(
        datasetIdentity,
        { ...payload, project_id: payload.project_id ?? projectId },
        "Feature VIF response",
      );
      setVifRows(payload.vif ?? []);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "VIF analysis failed.");
    } finally {
      setVifLoading(false);
    }
  }

  async function persistVifSelection(updates: Record<string, boolean>) {
    if (!datasetIdentity) {
      setError(datasetIdentityError);
      return;
    }
    if (!manifest) return;
    setVifSaving(true);
    setError("");
    try {
      const draftByName = new Map(drafts.map((draft) => [draft.feature_name, draft]));
      const featureUpdates = manifest.features.map((feature) => {
        const draft = draftByName.get(feature.feature_name) ?? toDraft(feature);
        const selected = updates[feature.feature_name];
        if (selected === undefined || feature.eligibility_status !== "eligible") return draft;
        return {
          ...draft,
          selected,
          exclusion_reason: selected ? "" : "Excluded after VIF review",
        };
      });
      const payload = await saveFeatureManifest(
        datasetIdentity,
        featureUpdates,
        pipelineSteps,
      );
      setManifest(payload);
      setDrafts(payload.features.filter((feature) => feature.origin !== "original").map(toDraft));
      setPipelineSteps(payload.pipeline_steps ?? []);
      setDirty(false);
      setPreview(null);
      const excludedCount = Object.values(updates).filter((selected) => !selected).length;
      setMessage(excludedCount
        ? `${excludedCount.toLocaleString()} predictor${excludedCount === 1 ? "" : "s"} excluded after VIF review. Any existing split is now stale.`
        : "Predictor restored to the governed Feature Manifest. Any existing split is now stale.");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "The VIF selection could not be saved.");
    } finally {
      setVifSaving(false);
    }
  }

  async function excludeHighVifFeatures() {
    const updates = Object.fromEntries((vifRows ?? [])
      .filter((row) => typeof row.vif === "number" && Number.isFinite(row.vif) && row.vif >= VIF_AUTO_EXCLUDE_THRESHOLD)
      .map((row) => [row.feature, false]));
    if (!Object.keys(updates).length) {
      setMessage(`No predictors have VIF greater than or equal to ${VIF_AUTO_EXCLUDE_THRESHOLD}.`);
      return;
    }
    await persistVifSelection(updates);
  }

  function updatePipeline(type: "scaler" | "encoding", value: string) {
    setPipelineSteps((current) => {
      const remaining = current.filter((step) => step.transformation_type !== type);
      return value === "None" ? remaining : [...remaining, { transformation_type: type, selected_features: [], config: { method: value }, enabled: true }];
    });
    setDirty(true);
    setPreview(null);
  }

  function pipelineValue(type: "scaler" | "encoding") {
    const step = pipelineSteps.find((item) => item.transformation_type === type && item.enabled);
    return String(step?.config?.method ?? "None");
  }

  async function finalizeFeatureSetAndContinue() {
    if (advancingRef.current) return false;
    if (!datasetIdentity) {
      setError(datasetIdentityError);
      return false;
    }
    if (!manifest) {
      setError("The governed Feature Manifest is not available yet.");
      return false;
    }
    if (selectedReviewFeatureCount === 0) {
      setError(
        "Select at least one eligible source or engineered predictor before continuing to Balance & Split.",
      );
      return false;
    }
    if (vifSaving || previewing || saving || materializing || confirming) {
      setError(
        "Finish the feature-table update already in progress before confirming the governed feature set.",
      );
      return false;
    }
    if (editingFeatureKey) {
      setError("Finish or cancel the open feature edit before continuing.");
      return false;
    }

    advancingRef.current = true;
    setAdvancing(true);
    setError("");
    setMessage("");
    let currentManifest = manifest;
    let currentDrafts = drafts;
    let failedStage = "validating the canonical feature contract";
    const runStage = async <T,>(label: string, operation: () => Promise<T>) => {
      failedStage = label;
      setAdvancingStage(label);
      return operation();
    };

    try {
      let mddSyncWarning = "";
      if (
        dirty ||
        currentManifest.validation_status !== "passed" ||
        currentManifest.persistence_status !== "persisted"
      ) {
        currentManifest = await runStage(
          "Validating and saving the versioned Feature Manifest",
          () =>
            saveFeatureManifest(
              datasetIdentity,
              currentDrafts,
              pipelineSteps,
            ),
        );
        currentDrafts = currentManifest.features
          .filter((feature) => feature.origin !== "original")
          .map(toDraft);
        setManifest(currentManifest);
        setDrafts(currentDrafts);
        setPipelineSteps(currentManifest.pipeline_steps ?? []);
        setDirty(false);
        setPreview(null);
      }

      if (currentManifest.validation_status !== "passed") {
        throw new Error(
          "Feature definitions did not pass source, target-leakage, and type validation. Review the highlighted definition and try again.",
        );
      }

      const materializationIsCurrent =
        currentManifest.materialization_status === "current" &&
        currentManifest.materialized_manifest_hash ===
          currentManifest.manifest_hash;

      if (!materializationIsCurrent) {
        let previewHash = currentManifest.preview_hash;
        if (!previewHash) {
          const previewPayload = await runStage(
            "Previewing included deterministic features",
            () =>
              previewFeaturePlan(
                datasetIdentity,
                currentDrafts.filter((draft) => draft.selected),
                previewRowLimit,
                undefined,
                currentManifest.manifest_hash,
              ),
          );
          previewHash = previewPayload.preview_hash;
          setPreview(previewPayload);
          currentManifest = await getFeatureManifest(datasetIdentity);
        }

        await runStage(
          "Materializing included deterministic features",
          () =>
            materializeFeatureManifest(
              datasetIdentity,
              currentManifest.manifest_hash,
              previewHash,
            ),
        );
        currentManifest = await getFeatureManifest(datasetIdentity);
      }

      const exactCurrentMaterialization =
        currentManifest.materialization_status === "current" &&
        currentManifest.materialized_manifest_hash ===
          currentManifest.manifest_hash &&
        !!currentManifest.materialization_hash;
      if (!exactCurrentMaterialization) {
        throw new Error(
          "The saved and materialized feature contracts do not match. Re-run confirmation after the backend materialization finishes.",
        );
      }

      if (
        currentManifest.confirmation_status !== "confirmed" ||
        currentManifest.confirmed_manifest_hash !==
          currentManifest.manifest_hash
      ) {
        currentManifest = await runStage(
          "Confirming the exact saved and materialized feature contract",
          () =>
            confirmFeatureManifest(
              datasetIdentity,
              currentManifest.manifest_hash,
              currentManifest.materialization_hash,
            ),
        );
      }

      setManifest(currentManifest);
      setDrafts(
        currentManifest.features
          .filter((feature) => feature.origin !== "original")
          .map(toDraft),
      );
      setPipelineSteps(currentManifest.pipeline_steps ?? []);
      setDirty(false);
      const evidence = await runStage(
        "Recording durable Feature Engineering evidence",
        () => completeStep(currentManifest),
      );
      try {
        await runStage(
          "Updating the exact Model Development Document draft",
          () =>
            syncFeatureEngineeringMdd(
              datasetIdentity,
              evidence,
              currentManifest,
            ),
        );
      } catch (cause) {
        mddSyncWarning =
          cause instanceof Error
            ? cause.message
            : "ATLAS could not attach the Feature Engineering evidence to the MDD draft.";
      }
      const documentation = await runStage(
        "Verifying the live preparation and MDD contract",
        () => getPreparationDocumentation(datasetIdentity),
      );
      const documented = documentation.feature_engineering;
      if (
        documented.status !== "confirmed" ||
        documented.manifest_hash !== currentManifest.manifest_hash ||
        documented.materialization_hash !== currentManifest.materialization_hash
      ) {
        throw new Error(
          "The live preparation documentation did not confirm the exact Feature Manifest and materialization hashes.",
        );
      }
      setPreparationDocs(documentation);
      setMessage(
        mddSyncWarning
          ? `Feature set confirmed. Opening Balance & Split with the exact saved and materialized contract. MDD draft attachment was deferred: ${mddSyncWarning}`
          : "Feature set confirmed. Opening Balance & Split with the exact saved and materialized contract.",
      );
      return true;
    } catch (cause) {
      setError(
        `Feature Engineering failed during ${failedStage}: ${
          cause instanceof Error
            ? cause.message
            : "ATLAS could not confirm the governed feature set."
        }`,
      );
      return false;
    } finally {
      advancingRef.current = false;
      setAdvancing(false);
      setAdvancingStage("");
    }
  }

  async function completeStep(
    confirmedManifest: FeatureManifest | null = manifest,
  ): Promise<EvidenceItem> {
    if (!datasetIdentity) {
      throw new Error(datasetIdentityError);
    }
    if (!confirmedManifest) {
      throw new Error("The exact confirmed Feature Manifest is unavailable for evidence persistence.");
    }
    const confirmedDrafts = confirmedManifest.features.filter(
      (feature) => feature.origin !== "original",
    );
    const includedDrafts = confirmedDrafts.filter(
      (feature) => feature.selected && feature.eligibility_status === "eligible",
    );
    const excludedDrafts = confirmedDrafts.filter(
      (feature) => !feature.selected || feature.eligibility_status !== "eligible",
    );
    const confirmedPipelineSteps = confirmedManifest.pipeline_steps ?? [];
    const evidence = await createEvidence({
      ...buildCanonicalEvidenceEnvelope(datasetIdentity, {
        manifestVersion: confirmedManifest.manifest_hash,
        materializationHash: confirmedManifest.materialization_hash,
      }),
      projectName,
      evidenceType: "feature_engineering",
      title: "Governed Feature Manifest",
      summary: `${includedDrafts.length} included deterministic engineered features, ${excludedDrafts.length} excluded planned definitions, and ${confirmedPipelineSteps.length} training-only pipeline steps were recorded in manifest ${confirmedManifest.manifest_version}.`,
      sourcePage: "Feature Engineering",
      sourceRoute: "/step05",
      modelIds: [],
      documentIds: [],
      notebookIds: [],
      supportsSections: ["Feature Engineering", "Candidate Models"],
      tags: ["predictive_modeling", "feature_manifest", "lineage"],
      status: "ready",
      importance: "high",
      payload: {
        features: confirmedManifest.features,
        includedEngineeredFeatures: includedDrafts.map((feature) => feature.feature_name),
        excludedEngineeredFeatures: excludedDrafts.map((feature) => feature.feature_name),
        pipelineSteps: confirmedPipelineSteps,
        executionStages: confirmedManifest.execution_history,
        manifestHash: confirmedManifest.manifest_hash,
        materializationHash: confirmedManifest.materialization_hash,
        confirmedManifestHash: confirmedManifest.confirmed_manifest_hash,
      },
    }, { requireDatabaseMirror: true });
    logDecision({
      workflowStep: "Feature Engineering",
      actionType: "workflow_setting_changed",
      subject: confirmedManifest.manifest_hash,
      previousValue: "materialized",
      newValue: "confirmed_current",
      systemRecommendation: "Continue only when the saved and materialized contracts match exactly.",
      followStatus: "followed",
      userReason: `Materialization ${confirmedManifest.materialization_hash} confirmed against ${confirmedManifest.manifest_hash}.`,
    });
    return evidence;
  }

  const documentationStatus = planReady && !dirty
    ? "confirmed"
    : materializedCount || preparationDocs?.feature_engineering.status === "confirmed"
      ? "stale"
      : (preparationDocs?.feature_engineering.status ?? "draft");
  const planState = advancing
    ? advancingStage || "Confirming"
    : materializing
      ? "Materializing"
      : saving
        ? "Saving"
        : dirty
          ? "Draft changed"
          : planReady
            ? "Current"
            : "Ready to confirm";
  const datasetName =
    localDataset?.dataset_library?.datasetName ||
    projectName ||
    "Registered dataset";
  const targetName =
    localDataset?.target ||
    manifest?.predictor_authorization?.target ||
    preparationDocs?.target ||
    "";
  const targetSourceExclusions = Array.from(
    new Set([
      ...(manifest?.predictor_authorization?.target_source_excluded ?? []),
      ...(preparationDocs?.governance.target_source_excluded ?? []),
    ]),
  );
  const eligibleRecommendationCount = recommendations.filter(
    (recommendation) => recommendation.eligible,
  ).length;
  const selectedDraft =
    drafts.find(
      (draft) =>
        (draft.feature_id ?? draft.feature_name) === selectedFeatureKey,
    ) ?? null;
  const selectedSavedFeature = selectedDraft
    ? manifest?.features.find(
        (feature) =>
          feature.feature_id === selectedDraft.feature_id ||
          feature.feature_name === selectedDraft.feature_name,
      ) ?? null
    : null;
  const savedReviewFeatures =
    manifest?.features.filter(
      (feature) => feature.eligibility_status === "eligible",
    ) ?? [];
  const unsavedReviewFeatures = drafts
    .filter(
      (draft) =>
        !savedReviewFeatures.some(
          (feature) =>
            feature.feature_id === draft.feature_id ||
            feature.feature_name === draft.feature_name,
        ),
    )
    .map((draft) => ({
      ...draft,
      feature_id: draft.feature_id ?? `draft:${draft.feature_name}`,
      eligibility_status: "eligible" as const,
      materialization_status: "not_materialized" as const,
    }));
  const reviewFeatures = [...savedReviewFeatures, ...unsavedReviewFeatures];
  const visibleReviewFeatures = reviewFeatures.filter((feature) => {
    const normalizedSearch = featureSearch.trim().toLowerCase();
    const draft =
      feature.origin === "original"
        ? null
        : drafts.find(
            (row) =>
              row.feature_id === feature.feature_id ||
              row.feature_name === feature.feature_name,
          );
    const included = draft?.selected ?? feature.selected;
    const matchesKind =
      featureKindFilter === "all" ||
      (featureKindFilter === "source" && feature.origin === "original") ||
      (featureKindFilter === "engineered" && feature.origin !== "original") ||
      (featureKindFilter === "included" && included);
    const searchable = `${feature.feature_name} ${feature.origin} ${feature.output_datatype} ${feature.formula_or_rule}`.toLowerCase();
    return matchesKind && (!normalizedSearch || searchable.includes(normalizedSearch));
  });
  const selectedReviewFeatureCount = reviewFeatures.filter((feature) => {
    const draft =
      feature.origin === "original"
        ? null
        : drafts.find(
            (row) =>
              row.feature_id === feature.feature_id ||
              row.feature_name === feature.feature_name,
          );
    return draft?.selected ?? feature.selected;
  }).length;
  const previewIsCurrent =
    !dirty &&
    !!manifest &&
    ((preview?.manifest_hash === manifest.manifest_hash &&
      !!preview.preview_hash) ||
      !!manifest.preview_hash);
  const executionStages = [
    {
      label: "Build plan",
      detail: `${drafts.length} reviewer-controlled definition${drafts.length === 1 ? "" : "s"}`,
      state: "Complete",
      complete: true,
    },
    {
      label: "Validate definitions",
      detail: "Names, lineage, target safety",
      state: dirty ? "Ready" : manifest?.validation_status === "passed" ? "Complete" : "Not started",
      complete: !dirty && manifest?.validation_status === "passed",
    },
    {
      label: "Save manifest",
      detail: "Immutable contract hash",
      state: saving ? "In progress" : dirty ? (manifest?.materialization_hash ? "Stale" : "Ready") : "Complete",
      complete: !dirty && !!manifest?.manifest_hash,
    },
    {
      label: "Preview features",
      detail: "Bounded non-mutating sample",
      state: previewing ? "In progress" : previewIsCurrent ? "Complete" : dirty ? "Not started" : "Ready",
      complete: previewIsCurrent,
    },
    {
      label: "Materialize full dataset",
      detail: "Execute deterministic features",
      state: materializing
        ? "In progress"
        : exactMaterialization
          ? "Complete"
          : manifest?.materialization_status === "failed"
            ? "Failed"
            : manifest?.materialization_status === "stale"
              ? "Stale"
              : previewIsCurrent
                ? "Ready"
                : "Not started",
      complete: exactMaterialization,
    },
    {
      label: "Confirm set current",
      detail: "Hash equality attestation",
      state: confirming
        ? "In progress"
        : manifest?.confirmation_status === "confirmed"
          ? "Complete"
          : exactMaterialization
            ? "Ready"
            : "Not started",
      complete: planReady,
    },
    {
      label: "Continue",
      detail: "Unlock Validation Design",
      state: planReady ? "Ready" : "Not started",
      complete: planReady,
    },
  ];
  const continueDisabledReason = loading
    ? "Loading the governed Feature Manifest."
    : !datasetIdentity
      ? datasetIdentityError
    : !manifest
      ? "The governed Feature Manifest is unavailable. Reload the page or restore the registered dataset."
      : selectedReviewFeatureCount === 0
        ? "Select at least one eligible source or engineered predictor before continuing to Balance & Split."
        : editingFeatureKey
          ? "Finish or cancel the open feature edit before continuing."
          : vifSaving || previewing || saving || materializing || confirming
            ? "Finish the feature-table update already in progress before confirming the governed feature set."
          : advancing
            ? advancingStage || "Confirming the governed feature set."
            : undefined;
  const continueStatus = advancing
    ? advancingStage
    : error
      ? error
      : planReady
        ? "The feature contract is current. Continue to Balance & Split."
        : "One click validates, saves, previews, materializes, confirms, and records this governed feature set before continuing.";

  return (
    <StepShell
      title=""
      hideHeader
      nextPath={getNextStepPath("step05")}
      nextDisabled={!!continueDisabledReason}
      nextDisabledReason={continueDisabledReason}
      onNext={finalizeFeatureSetAndContinue}
      nextLabel="Confirm Feature Set & Continue"
      nextButtonTestId="feature-confirm-continue"
      nextFooterTestId="feature-engineering-sticky-footer"
      nextStatusTestId="feature-engineering-continue-status"
      workflowStepId="step05"
      showEmbeddedNext
      nextAlwaysVisible
      nextRequireDurableWorkflowSave
      nextStatusLine={continueStatus}
    >
      <div className="prep-premium-page flex flex-col gap-4">
        <PreparationPageIdentity
          step="Step 5 of 13"
          title="Feature Engineering"
          description="Review the predictors that will move forward. Add an engineered feature only when it is needed, then use the single confirmation action to continue."
          datasetName={datasetName}
          datasetVersion={
            datasetIdentity?.dataset_version_id || ""
          }
          target={targetName}
          predictorCount={eligibleOriginals.length}
          predictorManifest={
            manifest?.manifest_version || edaManifest || "Loading"
          }
          documentationStatus={documentationStatus}
          decisionState={planState}
        />

        <PreparationQuickSummary
          metrics={[
            {
              label: "Included predictors",
              value: manifest
                ? manifest.features
                    .filter(
                      (feature) =>
                        feature.eligibility_status === "eligible" &&
                        feature.selected,
                    )
                    .length.toLocaleString()
                : "—",
              tone: "info",
            },
            {
              label: "Planned features",
              value: drafts.length.toLocaleString(),
              tone: drafts.length ? "info" : "neutral",
            },
            {
              label: "Materialized features",
              value: materializedCount.toLocaleString(),
              tone: materializedCount ? "success" : "neutral",
            },
            {
              label: "Source features",
              value: eligibleOriginals.length.toLocaleString(),
              detail: `${pipelineSteps.length} training transforms`,
            },
            {
              label: "Feature-set status",
              value: planState,
              tone: planReady ? "success" : "warning",
            },
          ]}
        />

        {datasetIdentity ? (
          <BureauSemanticContextPanel
            datasetIdentity={datasetIdentity}
            datasetFields={eligibleOriginals.map((feature) => feature.feature_name)}
            pageName="Feature Engineering"
          />
        ) : null}

        {loading ? (
          <div className="atlas-workflow-section flex min-h-52 items-center justify-center">
            <LoaderCircle size={28} className="animate-spin text-blue-600" />
          </div>
        ) : null}
        {error ? <AtlasAttentionPanel title="Feature plan requires attention" tone="danger">{error}</AtlasAttentionPanel> : null}
        {message ? <div className="rounded-lg border border-blue-200 bg-blue-50 px-4 py-3 text-sm text-blue-900">{message}</div> : null}

        {!loading && manifest ? (
          <>
        <div className="flex flex-wrap items-center gap-2 rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-2 text-xs text-emerald-900">
          <ShieldCheck size={15} />
          <strong>Predictor authorization enforced:</strong>
          target {targetName || "not set"}
          {targetSourceExclusions.length
            ? ` and deterministic source ${targetSourceExclusions.join(", ")} are excluded from every recommendation, builder, preview, and materialization.`
            : " is excluded from every recommendation, builder, preview, and materialization."}
        </div>

        {vifCarryForwardRecommendations.length ? (
          <AtlasWorkflowSection
            eyebrow="EDA carry-forward"
            title="Draft VIF Resolution Recommendations"
            description="Accepted EDA proposals arrive here for governed review. They do not uncheck predictors, create features, materialize data, or change the feature manifest."
            tone="warning"
            id="vif-resolution-carry-forward"
          >
            <div className="grid gap-2 md:grid-cols-2">
              {vifCarryForwardRecommendations.map((recommendation) => (
                <article
                  key={recommendation.recommendation_id}
                  className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-xs text-amber-950"
                  data-testid="vif-feature-recommendation"
                >
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <strong>{recommendation.features.join(" · ")}</strong>
                    <span className="rounded-full border border-amber-300 bg-white px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide">
                      Draft · {recommendation.action}
                    </span>
                  </div>
                  <p className="mt-2 leading-5">{recommendation.rationale}</p>
                  {recommendation.proposed_exclusions.length ? (
                    <p className="mt-2"><strong>Proposed exclusion:</strong> {recommendation.proposed_exclusions.join(", ")}</p>
                  ) : null}
                  {recommendation.protected_features.length ? (
                    <p className="mt-1"><strong>Protected:</strong> {recommendation.protected_features.join(", ")}</p>
                  ) : null}
                  <p className="mt-2 font-semibold text-amber-800">
                    Review only — the governed feature set is unchanged.
                  </p>
                </article>
              ))}
            </div>
          </AtlasWorkflowSection>
        ) : null}

        <details
          className="order-[40] rounded-xl border border-slate-200 bg-white p-4"
          data-testid="feature-engineering-recommendation-details"
        >
          <summary className="flex cursor-pointer list-none items-center justify-between gap-4">
            <span>
              <span className="block text-sm font-semibold text-slate-950">
                Optional recommendations and contract details
              </span>
              <span className="mt-1 block text-xs text-slate-600">
                Open only when you want EDA carry-forward, suggested features,
                or technical contract hashes.
              </span>
            </span>
            <ChevronDown size={18} className="shrink-0 text-slate-500" />
          </summary>
          <div className="mt-4 space-y-4 border-t border-slate-200 pt-4">
            <CarryForwardPanel
              items={carryForward}
              sourceStatus={edaDocumentStatus}
              onDisposition={handleCarryForward}
            />

        <AtlasWorkflowSection
          eyebrow="Recommendation architecture"
          title="Automated Feature Recommendations"
          description="Deterministic rules identify plausible candidates from governed predictor names and evidence. Statistical evidence informs rationale. Explanations are descriptive only; no LLM output can accept, save, or materialize a feature."
          tone="info"
          id="feature-recommendations"
        >
          <div className="mb-3 grid gap-2 md:grid-cols-3">
            <ArchitectureCard
              icon={Sparkles}
              title="Deterministic rules"
              detail="Source availability, formulas, names, type contracts, and exclusions are reproducible."
            />
            <ArchitectureCard
              icon={GitCompareArrows}
              title="Statistical evidence"
              detail="EDA signal, outliers, monotonicity, correlation, and upstream treatment inform review."
            />
            <ArchitectureCard
              icon={FileCheck2}
              title="Explanation layer"
              detail="Rationale contains no expected lift claim and never performs an action."
            />
          </div>
          <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
            <div className="flex flex-wrap gap-1">
              {(["all", "eligible", "accepted", "deferred"] as const).map(
                (filter) => (
                  <button
                    key={filter}
                    type="button"
                    className={
                      recommendationFilter === filter
                        ? "prep-choice-button is-active"
                        : "prep-choice-button"
                    }
                    onClick={() => setRecommendationFilter(filter)}
                  >
                    {filter === "all"
                      ? "All recommendations"
                      : filter.charAt(0).toUpperCase() + filter.slice(1)}
                  </button>
                ),
              )}
            </div>
            <span className="text-xs font-semibold text-slate-500">
              Recommendation only · never auto-accepted
            </span>
          </div>
          <RecommendationLandscape
            recommendations={visibleRecommendations}
            dispositions={recommendationDispositions}
            previewing={previewing}
            onAccept={acceptRecommendation}
            onReject={(recommendation) =>
              decideRecommendation(recommendation, "rejected")
            }
            onDefer={(recommendation) =>
              decideRecommendation(recommendation, "deferred")
            }
            onPreview={(recommendation) =>
              void previewRecommendation(recommendation)
            }
          />
          {recommendationPreviewId && preview ? (
            <div className="mt-4 rounded-lg border border-blue-200 bg-blue-50/40 p-3">
              <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
                <div>
                  <div className="text-sm font-semibold text-slate-950">
                    Recommendation Before / After Preview
                  </div>
                  <div className="text-xs text-slate-600">
                    Bounded rows only. No manifest or backend mutation occurred.
                  </div>
                </div>
                <AtlasDataScopeBadge
                  scope="rendered_sample"
                  rows={preview.preview_row_count}
                />
              </div>
              <FeaturePreviewTable preview={preview} />
            </div>
          ) : null}
        </AtlasWorkflowSection>

        <AtlasWorkflowSection
          eyebrow="Decision sequence"
          title="Feature Engineering Execution Pipeline"
          description="A governed seven-stage contract prevents unsaved, unvalidated, unpreviewed, stale, or unconfirmed feature definitions from reaching Validation Design."
          tone="neutral"
          id="feature-plan-pipeline"
        >
          <div
            className="grid gap-2 md:grid-cols-2 xl:grid-cols-7"
            data-testid="feature-execution-pipeline"
            aria-label="Plan Pipeline"
          >
            {executionStages.map((stage, index) => (
              <div
                key={stage.label}
                className={`relative rounded-xl border p-3 ${
                  stage.complete
                    ? "border-emerald-200 bg-emerald-50"
                    : index === executionStages.findIndex((row) => !row.complete)
                      ? "border-blue-300 bg-blue-50"
                      : "border-slate-200 bg-slate-50"
                }`}
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="text-[10px] font-bold uppercase tracking-[0.12em] text-slate-500">
                    Stage {index + 1}
                  </span>
                  {stage.complete ? (
                    <CheckCircle2 size={15} className="text-emerald-600" />
                  ) : (
                    <span className="h-2 w-2 rounded-full bg-slate-300" />
                  )}
                </div>
                <div className="mt-2 text-xs font-bold text-slate-950">
                  {stage.label}
                </div>
                <div className="mt-1 text-[11px] leading-4 text-slate-600">
                  {stage.detail}
                </div>
                <div
                  className={`mt-2 truncate text-[10px] font-bold ${
                    stage.complete ? "text-emerald-700" : "text-slate-500"
                  }`}
                  title={stage.state}
                >
                  {stage.state}
                </div>
              </div>
            ))}
          </div>
          <div className="mt-4 grid gap-3 lg:grid-cols-[1fr_auto]">
            <div className="grid gap-2 sm:grid-cols-3">
              <HashReadout
                label="Manifest hash"
                value={manifest.manifest_hash}
                status={!dirty ? "current" : "draft changed"}
              />
              <HashReadout
                label="Materialization hash"
                value={manifest.materialization_hash || "Not materialized"}
                status={manifest.materialization_status.replace(/_/g, " ")}
              />
              <HashReadout
                label="Confirmed manifest"
                value={manifest.confirmed_manifest_hash || "Not confirmed"}
                status={manifest.confirmation_status}
              />
            </div>
          </div>
          <div className="mt-3 rounded-lg border border-cyan-200 bg-cyan-50 p-3 text-xs leading-5 text-cyan-950">
            <strong>Deterministic before split:</strong> accepted engineered
            predictors are materialized on the governed full dataset. Scaling
            and encoding are intentionally separate: they are learned after the
            split, fit on training data only, and applied unchanged to
            validation, test, and scoring populations.
          </div>
        </AtlasWorkflowSection>
          </div>
        </details>

        <div className="order-[20]" data-testid="feature-set-review">
        <AtlasWorkflowSection eyebrow="Dataset table" title="Feature Inventory and Summary Statistics" description="Review the complete modeling dataset in one table. Every authorized source and newly created feature appears here; full summary statistics populate when materialization completes." tone="info" action={manifest ? <span className="text-xs font-semibold text-slate-600">{manifest.manifest_version}</span> : null}>
          <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-4">
            <StatusMetric label="Original features" value={eligibleOriginals.length} />
            <StatusMetric label="Planned features" value={drafts.length} />
            <StatusMetric label="Materialized features" value={materializedCount} />
            <StatusMetric label="Split status" value={manifest?.split_status?.replace(/_/g, " ") ?? "not created"} warning={manifest?.split_status === "stale"} />
          </div>
          <div className="mt-3 flex flex-wrap items-center gap-2">
            <label className="relative min-w-56 flex-1">
              <Search
                size={15}
                className="pointer-events-none absolute left-3 top-2.5 text-slate-400"
              />
              <input
                className="atlas-input pl-9"
                value={featureSearch}
                onChange={(event) => setFeatureSearch(event.target.value)}
                placeholder="Search features, rules, or types"
                aria-label="Search feature set"
              />
            </label>
            <select
              className="atlas-input min-w-44"
              value={featureKindFilter}
              onChange={(event) =>
                setFeatureKindFilter(
                  event.target.value as typeof featureKindFilter,
                )
              }
              aria-label="Filter feature set"
            >
              <option value="all">All features</option>
              <option value="included">Included only</option>
              <option value="source">Source features</option>
              <option value="engineered">Engineered features</option>
            </select>
            <span className="text-xs font-semibold text-slate-500">
              {visibleReviewFeatures.length} of {reviewFeatures.length}
            </span>
            <span
              className="rounded-full border border-blue-200 bg-blue-50 px-2.5 py-1 text-xs font-semibold text-blue-800"
              id="feature-inventory-selection-help"
            >
              {selectedReviewFeatureCount} included · use the checkboxes to
              change the modeling set
            </span>
          </div>
          <div className="mt-3 max-h-[32rem] overflow-auto rounded-xl border border-slate-300 bg-white shadow-sm">
            <table
              className="atlas-table w-full min-w-[1560px] border-separate border-spacing-0 text-sm"
              data-testid="feature-transformation-plan"
              aria-label="Modeling dataset feature inventory and summary statistics"
              aria-describedby="feature-inventory-selection-help"
            >
              <caption className="sr-only">
                Modeling dataset features, inclusion controls, source rules,
                summary statistics, and review status
              </caption>
              <thead className="sticky top-0 z-[1] bg-slate-100 shadow-sm">
                <tr>
                  <th scope="col" className="w-20 border-b border-slate-300 px-3 py-3 text-center">Include</th>
                  <th scope="col" className="min-w-64 border-b border-slate-300 px-3 py-3">Feature</th>
                  <th scope="col" className="min-w-32 border-b border-slate-300 px-3 py-3">Kind</th>
                  <th scope="col" className="min-w-64 border-b border-slate-300 px-3 py-3">Source or rule</th>
                  <th scope="col" className="min-w-20 border-b border-slate-300 px-3 py-3 text-right">IV</th>
                  <th scope="col" className="min-w-20 border-b border-slate-300 px-3 py-3 text-right">Mean</th>
                  <th scope="col" className="min-w-20 border-b border-slate-300 px-3 py-3 text-right">Std dev</th>
                  <th scope="col" className="min-w-20 border-b border-slate-300 px-3 py-3 text-right">Min</th>
                  <th scope="col" className="min-w-20 border-b border-slate-300 px-3 py-3 text-right">Max</th>
                  <th scope="col" className="min-w-24 border-b border-slate-300 px-3 py-3 text-right">Missing</th>
                  <th scope="col" className="min-w-20 border-b border-slate-300 px-3 py-3 text-right">Distinct</th>
                  <th scope="col" className="min-w-36 border-b border-slate-300 px-3 py-3">Status</th>
                  <th scope="col" className="min-w-36 border-b border-slate-300 px-3 py-3">Review</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-200">
                {visibleReviewFeatures.map((feature) => {
                  const draft =
                    feature.origin === "original"
                      ? null
                      : drafts.find(
                          (row) =>
                            row.feature_id === feature.feature_id ||
                            row.feature_name === feature.feature_name,
                        ) ?? toDraft(feature);
                  const key =
                    draft?.feature_id ??
                    draft?.feature_name ??
                    feature.feature_id ??
                    feature.feature_name;
                  const included = draft?.selected ?? feature.selected;
                  const status =
                    feature.origin === "original"
                      ? included
                        ? "Authorized source"
                        : "Excluded"
                      : feature.materialization_status.replace(/_/g, " ");
                  const summaryStatistics =
                    "summary_statistics" in feature
                      ? feature.summary_statistics ?? {}
                      : {};
                  const iv = predictorEvidence[feature.feature_name]?.iv;
                  return (
                    <tr
                      key={key}
                      data-feature-origin={feature.origin}
                      className={`transition-colors hover:bg-slate-50 ${
                        selectedFeatureKey === key
                          ? "bg-blue-50/80"
                          : feature.origin !== "original"
                            ? "bg-cyan-50/40"
                            : "bg-white"
                      }`}
                    >
                      <td className="border-b border-slate-100 px-3 py-2 text-center">
                        <label className="inline-flex min-h-9 cursor-pointer items-center justify-center rounded-md p-2 hover:bg-blue-50">
                          <input
                            type="checkbox"
                            className="h-4 w-4 rounded border-slate-300 text-blue-600 focus:ring-blue-500"
                            checked={included}
                            aria-label={`Include ${feature.feature_name}`}
                            disabled={vifSaving || advancing}
                            onChange={(event) => {
                              const selected = event.target.checked;
                              if (feature.origin === "original") {
                                void persistVifSelection({
                                  [feature.feature_name]: selected,
                                });
                                return;
                              }
                              setDrafts((current) =>
                                current.map((row) =>
                                  (row.feature_id ?? row.feature_name) === key
                                    ? {
                                        ...row,
                                        selected,
                                        exclusion_reason: selected
                                          ? ""
                                          : "Excluded in Feature Engineering review",
                                      }
                                    : row,
                                ),
                              );
                              setDirty(true);
                              setPreview(null);
                            }}
                          />
                          <span className="sr-only">
                            {included
                              ? `${feature.feature_name} is included`
                              : `${feature.feature_name} is excluded`}
                          </span>
                        </label>
                      </td>
                      <td className="max-w-80 whitespace-normal break-words border-b border-slate-100 px-3 py-3 font-semibold leading-5 text-slate-950">
                        {feature.feature_name}
                      </td>
                      <td className="border-b border-slate-100 px-3 py-3">
                        <ContractBadge
                          label={
                            feature.origin === "original"
                              ? "Source"
                              : "Engineered"
                          }
                          tone={
                            feature.origin === "original" ? "slate" : "blue"
                          }
                        />
                        <span className="ml-1 text-[10px] text-slate-500">
                          {feature.output_datatype}
                        </span>
                      </td>
                      <td className="max-w-md whitespace-normal border-b border-slate-100 px-3 py-3 text-xs leading-5 text-slate-600">
                        {feature.origin === "original"
                          ? "Registered predictor"
                          : draft?.formula_or_rule ?? feature.formula_or_rule}
                      </td>
                      <td className="border-b border-slate-100 px-3 py-3 text-right font-semibold tabular-nums text-blue-800">
                        {formatFeatureSummary(iv, 4)}
                      </td>
                      <td className="border-b border-slate-100 px-3 py-3 text-right tabular-nums">
                        {formatFeatureSummary(
                          summaryStatistic(summaryStatistics, "mean"),
                        )}
                      </td>
                      <td className="border-b border-slate-100 px-3 py-3 text-right tabular-nums">
                        {formatFeatureSummary(
                          summaryStatistic(
                            summaryStatistics,
                            "standard_deviation",
                            "std_dev",
                          ),
                        )}
                      </td>
                      <td className="border-b border-slate-100 px-3 py-3 text-right tabular-nums">
                        {formatFeatureSummary(
                          summaryStatistic(summaryStatistics, "minimum", "min"),
                        )}
                      </td>
                      <td className="border-b border-slate-100 px-3 py-3 text-right tabular-nums">
                        {formatFeatureSummary(
                          summaryStatistic(summaryStatistics, "maximum", "max"),
                        )}
                      </td>
                      <td className="border-b border-slate-100 px-3 py-3 text-right tabular-nums">
                        {formatFeatureMissingRate(summaryStatistics)}
                      </td>
                      <td className="border-b border-slate-100 px-3 py-3 text-right tabular-nums">
                        {formatFeatureSummary(
                          summaryStatistic(
                            summaryStatistics,
                            "distinct_count",
                            "distinct",
                          ),
                          0,
                        )}
                      </td>
                      <td className="border-b border-slate-100 px-3 py-3">
                        <ContractBadge
                          label={status}
                          tone={
                            status === "materialized" ||
                            status === "Authorized source"
                              ? "emerald"
                              : status === "failed"
                                ? "rose"
                                : status === "stale"
                                  ? "amber"
                                  : "slate"
                          }
                        />
                      </td>
                      <td className="border-b border-slate-100 px-3 py-3">
                        {draft ? (
                          <button
                            type="button"
                            className="atlas-secondary-button min-h-8 px-2 py-1 text-xs"
                            onClick={() => focusFeatureDetail(draft, "detail")}
                          >
                            Review details
                          </button>
                        ) : (
                          <span className="text-xs text-slate-500">
                            Governed upstream
                          </span>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          {selectedDraft ? (
            <FeatureContractDetail
              draft={selectedDraft}
              saved={selectedSavedFeature}
              preview={preview}
              evidence={predictorEvidence}
              correlationPairs={highCorrelationPairs}
              history={manifest.execution_history}
              editing={editingFeatureKey === (selectedDraft.feature_id ?? selectedDraft.feature_name)}
              editingDraft={editingDraft}
              onEditingChange={setEditingDraft}
              onEdit={() => beginEdit(selectedDraft)}
              onCancelEdit={() => {
                setEditingFeatureKey("");
                setEditingDraft(null);
              }}
              onSaveEdit={saveFeatureEdit}
              onClose={() => {
                setSelectedFeatureKey("");
                setEditingFeatureKey("");
                setEditingDraft(null);
              }}
            />
          ) : null}
        </AtlasWorkflowSection>
        </div>

        <section
          className="prep-feature-builder-launcher order-[10]"
          data-testid="feature-builder-launcher"
        >
          <div className="prep-feature-builder-launcher__header">
            <div>
              <div className="prep-quick-summary__label !bg-transparent !p-0">
                Feature builder
              </div>
              <h2 className="mt-1 text-sm font-semibold text-slate-950">
                Create an engineered predictor
              </h2>
              <p className="mt-0.5 text-[11px] text-slate-500">
                Choose an operation, define its governed inputs, and add it to
                the feature inventory directly below.
              </p>
            </div>
            <span className="prep-state-pill prep-state-pill--info">
              {drafts.length} planned
            </span>
          </div>
          <div className="prep-feature-builder-launcher__body">
            <div className="prep-feature-builder-launcher__tiles">
              {builderOptions.map((option) => {
                const Icon = option.icon;
                const unavailable =
                  option.id === "date-derived" && !dateNames.length;
                return (
                  <button
                    key={option.id}
                    type="button"
                    className={`prep-feature-builder-tile ${
                      builderType === option.id ? "is-active" : ""
                    }`}
                    disabled={unavailable}
                    onClick={() => {
                      setBuilderType(option.id);
                      setForm({});
                    }}
                  >
                    <Icon size={16} />
                    <strong>{option.label}</strong>
                    <small>
                      {unavailable
                        ? "No governed date predictor"
                        : option.description}
                    </small>
                  </button>
                );
              })}
            </div>
            <div className="prep-feature-builder-launcher__recent">
              <div className="flex items-center justify-between gap-2">
                <strong className="text-[10px] uppercase tracking-wide text-blue-700">
                  Recently created
                </strong>
                <span className="text-[10px] text-slate-500">
                  {materializedCount} materialized
                </span>
              </div>
              {drafts.length ? (
                <ul className="mt-1">
                  {[...drafts].reverse().slice(0, 5).map((draft) => {
                    const saved = manifest.features.find(
                      (feature) =>
                        feature.feature_id === draft.feature_id ||
                        feature.feature_name === draft.feature_name,
                    );
                    return (
                      <li key={draft.feature_id ?? draft.feature_name}>
                        <strong title={draft.feature_name}>
                          {draft.feature_name}
                        </strong>
                        <span>
                          {saved?.materialization_status.replace(/_/g, " ") ??
                            "planned"}
                        </span>
                      </li>
                    );
                  })}
                </ul>
              ) : (
                <p className="mt-2 text-[11px] leading-4 text-slate-500">
                  No engineered features have been added. The authorized source
                  feature set can continue unchanged.
                </p>
              )}
            </div>
          </div>
          <div
            className="border-t border-blue-100 bg-white/90 p-4"
            data-testid="feature-builder-configuration"
          >
            <BuilderForm
              type={builderType}
              form={form}
              update={updateField}
              allNames={availableNames}
              numericNames={numericNames}
              categoricalNames={categoricalOriginals.map(
                (feature) => feature.feature_name,
              )}
              dateNames={dateNames}
            />
            <BuilderSafetyNotice type={builderType} form={form} />
            <div className="mt-4 flex flex-wrap items-center justify-between gap-3 border-t border-slate-200 pt-4">
              <p className="text-xs text-slate-600">
                Adding a definition updates the inventory immediately. Save and
                materialize when the feature set is ready.
              </p>
              <button
                type="button"
                className="atlas-primary-button"
                onClick={addFeature}
                data-testid="feature-builder-add"
              >
                <Plus size={15} /> Add to feature inventory
              </button>
            </div>
          </div>
        </section>

        <details
          className="order-[30] rounded-xl border border-slate-200 bg-white p-4"
          data-testid="feature-engineering-secondary-tools"
        >
          <summary className="flex cursor-pointer list-none items-center justify-between gap-4">
            <span>
              <span className="block text-sm font-semibold text-slate-950">
                Optional feature creation and diagnostics
              </span>
              <span className="mt-1 block text-xs text-slate-600">
                Configure training-only transforms, inspect lineage, or run VIF
                only when your review requires it.
              </span>
            </span>
            <ChevronDown size={18} className="shrink-0 text-slate-500" />
          </summary>
          <div className="mt-4 space-y-4 border-t border-slate-200 pt-4">
        <AtlasWorkflowSection eyebrow="Training-only preprocessing" title="Pipeline Transformations" description="Learned transformations are fit on training data only after splitting. They do not appear as deterministic created predictor rows." tone="neutral">
          <div className="grid gap-4 lg:grid-cols-2">
            <SelectField label="Numeric scaling" value={pipelineValue("scaler")} onChange={(value) => updatePipeline("scaler", value)} options={["None", "StandardScaler", "MinMaxScaler"]} helper="Use None for tree-only modeling. Scaling is fitted after the validation split." />
            <SelectField label="Categorical encoding" value={pipelineValue("encoding")} onChange={(value) => updatePipeline("encoding", value)} options={["None", "OneHotEncoder"]} helper="Encoding is fitted on training categories with unknown-level handling." />
          </div>
        </AtlasWorkflowSection>

        <AtlasWorkflowSection eyebrow="Execution evidence" title="Preview and Materialization" description="Preview returns bounded before/after rows without mutation. Materialization executes the exact saved contract across the backend working dataset and records lineage, hash bindings, and stage history." tone="info" id="feature-execution">
          <div className="flex flex-wrap items-center gap-2">
            <label className="flex items-center gap-2 text-xs font-semibold text-slate-700">
              Preview rows
              <select className="atlas-input w-24" value={previewRowLimit} onChange={(event) => setPreviewRowLimit(Number(event.target.value))} disabled={previewing}>
                {PREVIEW_ROW_LIMITS.map((limit) => <option key={limit} value={limit}>{limit}</option>)}
              </select>
            </label>
            {materializing ? <AtlasExecutionStatus state="running" label="Materializing features" detail="Backend execution is in progress." /> : planReady ? <AtlasExecutionStatus state="complete" label="Feature set current" detail="Saved manifest, materialization, and reviewer confirmation match exactly." /> : exactMaterialization ? <AtlasExecutionStatus state="idle" label="Confirmation required" detail="Confirm that the exact materialized feature set is current." /> : manifest.materialization_status === "stale" ? <AtlasExecutionStatus state="idle" label="Materialization stale" detail="Re-preview and re-materialize after the latest plan change." /> : <AtlasExecutionStatus state="idle" label="Materialization required" detail="Validate, save, preview, and execute the current plan." />}
          </div>
          {preview && !recommendationPreviewId ? <FeaturePreviewTable preview={preview} /> : null}
        </AtlasWorkflowSection>

        <AtlasWorkflowSection
          eyebrow="Governed lineage"
          title="Feature Lineage Graph"
          description="Every engineered output traces to authorized sources, its deterministic rule, materialization state, and the downstream manifest."
          id="feature-lineage-graph"
        >
          <FeatureLineageGraph drafts={drafts} manifest={manifest} />
        </AtlasWorkflowSection>

        <details className="atlas-workflow-section">
          <summary className="flex cursor-pointer list-none items-center justify-between"><span><span className="block text-sm font-semibold text-slate-950">Predictor Redundancy Check</span><span className="mt-1 block text-xs text-slate-600">VIF is intentionally lazy and never runs during page render.</span></span><ChevronDown size={17} /></summary>
          <div className="mt-4 border-t border-slate-200 pt-4">
            <div className="flex flex-wrap items-center gap-2">
              <button type="button" className="atlas-secondary-button" onClick={() => void runVif()} disabled={vifLoading || vifSaving || dirty}>{vifLoading ? <LoaderCircle size={15} className="animate-spin" /> : <GitCompareArrows size={15} />} Run VIF diagnostics</button>
              {vifRows ? <button type="button" className="atlas-secondary-button" onClick={() => void excludeHighVifFeatures()} disabled={vifLoading || vifSaving}>{vifSaving ? <LoaderCircle size={15} className="animate-spin" /> : <Settings2 size={15} />} Uncheck VIF &gt;= {VIF_AUTO_EXCLUDE_THRESHOLD}</button> : null}
            </div>
            <p className="mt-2 text-xs leading-5 text-slate-600">VIF values at or above {VIF_AUTO_EXCLUDE_THRESHOLD} indicate severe multicollinearity. Exclusions are saved to the Feature Manifest and flow into Final Predictor Review and Model Training.</p>
            {vifRows ? <div className="mt-3 overflow-auto rounded-lg border border-slate-200"><table className="atlas-table"><thead><tr><th>Use in model</th><th>Feature</th><th>VIF</th><th>Status</th></tr></thead><tbody>{vifRows.map((row) => <tr key={row.feature}><td><label className="inline-flex items-center gap-2 text-xs font-semibold text-slate-700"><input type="checkbox" checked={selectedByFeature.get(row.feature) ?? true} onChange={(event) => void persistVifSelection({ [row.feature]: event.target.checked })} disabled={vifSaving} /> Use</label></td><td>{row.feature}</td><td>{typeof row.vif === "number" && Number.isFinite(row.vif) ? row.vif.toFixed(3) : "Not available"}</td><td>{row.status}</td></tr>)}</tbody></table></div> : null}
          </div>
        </details>
          </div>
        </details>
          </>
        ) : null}
      </div>
    </StepShell>
  );
}

function summaryStatistic(
  summary: Record<string, unknown>,
  ...keys: string[]
) {
  for (const key of keys) {
    const value = summary[key];
    if (typeof value === "number" && Number.isFinite(value)) return value;
  }
  return null;
}

function formatFeatureSummary(
  value: number | null | undefined,
  digits = 2,
) {
  if (typeof value !== "number" || !Number.isFinite(value)) return "—";
  return value.toLocaleString(undefined, {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

function formatFeatureMissingRate(summary: Record<string, unknown>) {
  const rows = summaryStatistic(summary, "row_count", "rows");
  const missing = summaryStatistic(summary, "missing_count", "missing");
  if (rows === null || missing === null || rows <= 0) return "—";
  return `${((missing / rows) * 100).toFixed(2)}%`;
}

function ContractBadge({
  label,
  tone,
}: {
  label: string;
  tone: "slate" | "blue" | "emerald" | "amber" | "rose";
}) {
  const classes = {
    slate: "bg-slate-100 text-slate-700",
    blue: "bg-blue-100 text-blue-700",
    emerald: "bg-emerald-100 text-emerald-700",
    amber: "bg-amber-100 text-amber-800",
    rose: "bg-rose-100 text-rose-700",
  };
  return (
    <span
      className={`inline-flex max-w-full items-center rounded-full px-2 py-0.5 text-[10px] font-bold capitalize ${classes[tone]}`}
    >
      {label}
    </span>
  );
}

function RowAction({
  icon: Icon,
  label,
  onClick,
  disabled = false,
}: {
  icon: typeof Eye;
  label: string;
  onClick: () => void;
  disabled?: boolean;
}) {
  return (
    <button
      type="button"
      className="inline-flex min-h-7 items-center gap-1 rounded-md border border-slate-200 bg-white px-1.5 py-1 text-left text-[10px] font-semibold text-slate-700 hover:border-blue-300 hover:text-blue-800 disabled:cursor-not-allowed disabled:opacity-50"
      onClick={onClick}
      disabled={disabled}
      title={label}
    >
      <Icon size={12} />
      <span>{label}</span>
    </button>
  );
}

function HashReadout({
  label,
  value,
  status,
}: {
  label: string;
  value: string;
  status: string;
}) {
  return (
    <div className="min-w-0 rounded-lg border border-slate-200 bg-white px-3 py-2">
      <div className="text-[10px] font-bold uppercase tracking-[0.1em] text-slate-500">
        {label}
      </div>
      <code className="mt-1 block truncate text-[11px] font-semibold text-slate-900" title={value}>
        {value}
      </code>
      <div className="mt-1 text-[10px] font-semibold capitalize text-slate-500">
        {status}
      </div>
    </div>
  );
}

function FeatureContractDetail({
  draft,
  saved,
  preview,
  evidence,
  correlationPairs,
  history,
  editing,
  editingDraft,
  onEditingChange,
  onEdit,
  onCancelEdit,
  onSaveEdit,
  onClose,
}: {
  draft: FeatureDraft;
  saved: FeatureManifestRow | null;
  preview: FeaturePreview | null;
  evidence: Record<
    string,
    { iv?: number | null; outlierRate?: number | null; monotonicity?: string | null }
  >;
  correlationPairs: Array<Record<string, unknown>>;
  history: FeatureManifest["execution_history"];
  editing: boolean;
  editingDraft: FeatureDraft | null;
  onEditingChange: (draft: FeatureDraft | null) => void;
  onEdit: () => void;
  onCancelEdit: () => void;
  onSaveEdit: () => void;
  onClose: () => void;
}) {
  const associationRows = draft.source_features.map((source) => ({
    source,
    ...evidence[source],
  }));
  const relatedCorrelations = correlationPairs.filter((pair) => {
    const values = Object.values(pair).map(String);
    return draft.source_features.some((source) => values.includes(source));
  });
  const materializationHistory = history.filter((event) =>
    ["materialize_full_dataset", "confirm_feature_set"].includes(event.stage),
  );

  return (
    <aside
      className="mt-4 rounded-xl border border-blue-200 bg-gradient-to-br from-white to-blue-50/60 p-4"
      aria-label={`Feature detail: ${draft.feature_name}`}
      data-testid="feature-contract-detail"
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="text-[10px] font-bold uppercase tracking-[0.14em] text-blue-700">
            Feature contract detail
          </div>
          <h3 className="mt-1 break-all text-base font-semibold text-slate-950">
            {draft.feature_name}
          </h3>
          <p className="mt-1 text-xs text-slate-600">
            {originLabel(draft.origin)} · {draft.output_datatype} ·{" "}
            {saved?.transformation_version
              ? `definition v${saved.transformation_version}`
              : "unsaved draft"}
          </p>
        </div>
        <div className="flex gap-2">
          {!editing ? (
            <button type="button" className="atlas-secondary-button" onClick={onEdit}>
              <Pencil size={14} /> Edit definition
            </button>
          ) : null}
          <button type="button" className="atlas-icon-button" onClick={onClose} title="Close feature detail">
            <X size={15} />
          </button>
        </div>
      </div>

      {editing && editingDraft ? (
        <div className="mt-4 rounded-lg border border-blue-200 bg-white p-3">
          <div className="grid gap-3 md:grid-cols-2">
            <label className="text-xs font-semibold text-slate-700">
              Feature name
              <input
                className="atlas-input mt-1 w-full"
                value={editingDraft.feature_name}
                onChange={(event) =>
                  onEditingChange({ ...editingDraft, feature_name: event.target.value })
                }
              />
            </label>
            <label className="text-xs font-semibold text-slate-700">
              Display name
              <input
                className="atlas-input mt-1 w-full"
                value={editingDraft.display_name ?? ""}
                onChange={(event) =>
                  onEditingChange({ ...editingDraft, display_name: event.target.value })
                }
              />
            </label>
            <label className="text-xs font-semibold text-slate-700 md:col-span-2">
              Formula or rule
              <textarea
                className="atlas-input mt-1 min-h-20 w-full"
                value={editingDraft.formula_or_rule}
                onChange={(event) =>
                  onEditingChange({ ...editingDraft, formula_or_rule: event.target.value })
                }
              />
            </label>
            <label className="text-xs font-semibold text-slate-700 md:col-span-2">
              Evidence / rationale
              <textarea
                className="atlas-input mt-1 min-h-24 w-full"
                value={editingDraft.user_rationale}
                onChange={(event) =>
                  onEditingChange({ ...editingDraft, user_rationale: event.target.value })
                }
              />
            </label>
          </div>
          <div className="mt-3 flex justify-end gap-2">
            <button type="button" className="atlas-secondary-button" onClick={onCancelEdit}>
              Cancel
            </button>
            <button type="button" className="atlas-primary-button" onClick={onSaveEdit}>
              <Save size={14} /> Apply draft edit
            </button>
          </div>
        </div>
      ) : (
        <div className="mt-4 grid gap-3 lg:grid-cols-2 xl:grid-cols-3">
          <DetailBlock title="Full formula">
            <code className="whitespace-pre-wrap break-words text-[11px] leading-5 text-slate-800">
              {draft.formula_or_rule}
            </code>
          </DetailBlock>
          <DetailBlock title="Source variables">
            <div className="flex flex-wrap gap-1">
              {draft.source_features.map((source) => (
                <ContractBadge key={source} label={source} tone="blue" />
              ))}
            </div>
          </DetailBlock>
          <DetailBlock title="Transformation parameters">
            <pre className="max-h-32 overflow-auto whitespace-pre-wrap break-words text-[10px] leading-5 text-slate-700">
              {JSON.stringify(draft.config, null, 2)}
            </pre>
          </DetailBlock>
          <DetailBlock title="Preview statistics">
            <div className="text-xs leading-5 text-slate-700">
              <div>Bounded preview: {preview?.preview_row_count ?? "Not run"} rows</div>
              <pre className="mt-1 max-h-28 overflow-auto whitespace-pre-wrap text-[10px]">
                {JSON.stringify(saved?.summary_statistics ?? {}, null, 2)}
              </pre>
            </div>
          </DetailBlock>
          <DetailBlock title="Target association result">
            {associationRows.length ? (
              <div className="space-y-1 text-[11px] leading-5 text-slate-700">
                {associationRows.map((row) => (
                  <div key={row.source}>
                    <strong>{row.source}</strong>: IV{" "}
                    {typeof row.iv === "number" ? row.iv.toFixed(4) : "not available"}
                    {" · "}shape {row.monotonicity ?? "not available"}
                  </div>
                ))}
              </div>
            ) : (
              <span className="text-xs text-slate-500">No source evidence recorded.</span>
            )}
          </DetailBlock>
          <DetailBlock title="Source correlation">
            <div className="text-[11px] leading-5 text-slate-700">
              {relatedCorrelations.length
                ? `${relatedCorrelations.length} governed high-correlation relationship${relatedCorrelations.length === 1 ? "" : "s"} linked.`
                : "No governed high-correlation pair is linked to these sources."}
            </div>
          </DetailBlock>
          <DetailBlock title="Leakage review">
            <div className="flex flex-wrap gap-1">
              <ContractBadge label="Target excluded" tone="emerald" />
              <ContractBadge label="Target source excluded" tone="emerald" />
              <ContractBadge label="Split metadata blocked" tone="emerald" />
              <ContractBadge label="Review passed" tone="emerald" />
            </div>
          </DetailBlock>
          <DetailBlock title="Rationale">
            <p className="text-xs leading-5 text-slate-700">
              {draft.user_rationale || "Review required before confirmation."}
            </p>
          </DetailBlock>
          <DetailBlock title="Creation history">
            <div className="text-[11px] leading-5 text-slate-700">
              <div>Created: {saved?.created_at ? new Date(saved.created_at).toLocaleString() : "Draft"}</div>
              <div>Actor: {saved?.created_by ?? "Current reviewer"}</div>
              <div>Status: {saved?.creation_status ?? "Draft"}</div>
            </div>
          </DetailBlock>
          <DetailBlock title="Materialization history" span>
            {materializationHistory.length ? (
              <ol className="space-y-1 text-[11px] leading-5 text-slate-700">
                {materializationHistory.map((event, index) => (
                  <li key={`${event.recorded_at}-${index}`}>
                    <strong>{event.stage.replace(/_/g, " ")}</strong> · {event.status} ·{" "}
                    {new Date(event.recorded_at).toLocaleString()} — {event.detail}
                  </li>
                ))}
              </ol>
            ) : (
              <span className="text-xs text-slate-500">No materialization has been recorded.</span>
            )}
          </DetailBlock>
        </div>
      )}
    </aside>
  );
}

function DetailBlock({
  title,
  children,
  span = false,
}: {
  title: string;
  children: ReactNode;
  span?: boolean;
}) {
  return (
    <section className={`rounded-lg border border-slate-200 bg-white p-3 ${span ? "lg:col-span-2 xl:col-span-3" : ""}`}>
      <h4 className="mb-2 text-[10px] font-bold uppercase tracking-[0.1em] text-slate-500">
        {title}
      </h4>
      {children}
    </section>
  );
}

function ArchitectureCard({
  icon: Icon,
  title,
  detail,
}: {
  icon: typeof Sparkles;
  title: string;
  detail: string;
}) {
  return (
    <div className="rounded-lg border border-blue-100 bg-white p-3">
      <div className="flex items-center gap-2 text-blue-800">
        <Icon size={15} />
        <span className="text-xs font-semibold">{title}</span>
      </div>
      <p className="mt-1.5 text-xs leading-5 text-slate-600">{detail}</p>
    </div>
  );
}

function RecommendationLandscape({
  recommendations,
  dispositions,
  previewing,
  onAccept,
  onReject,
  onDefer,
  onPreview,
}: {
  recommendations: FeatureRecommendation[];
  dispositions: Record<string, RecommendationDisposition>;
  previewing: boolean;
  onAccept: (recommendation: FeatureRecommendation) => void;
  onReject: (recommendation: FeatureRecommendation) => void;
  onDefer: (recommendation: FeatureRecommendation) => void;
  onPreview: (recommendation: FeatureRecommendation) => void;
}) {
  return (
    <div
      className="grid gap-3 lg:grid-cols-2"
      data-testid="feature-recommendation-landscape"
      aria-label="Recommendation Landscape"
    >
      {recommendations.map((recommendation) => {
        const disposition =
          dispositions[recommendation.id] ?? "suggested";
        const accepted = disposition === "accepted_to_plan";
        const StatusIcon =
          disposition === "accepted_to_plan"
            ? Check
            : disposition === "rejected"
              ? X
              : disposition === "deferred"
                ? Pause
                : Clock3;
        return (
          <article
            key={recommendation.id}
            className={`rounded-xl border p-4 ${
              accepted
                ? "border-emerald-300 bg-emerald-50/50"
                : recommendation.eligible
                  ? "border-slate-200 bg-white"
                  : "border-slate-200 bg-slate-50"
            }`}
            data-recommendation-id={recommendation.id}
          >
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-1.5">
                  <span
                    className={`rounded-full px-2 py-0.5 text-[10px] font-bold uppercase ${
                      recommendation.recommendationClass === "deterministic"
                        ? "bg-blue-100 text-blue-700"
                        : recommendation.recommendationClass === "statistical"
                          ? "bg-violet-100 text-violet-700"
                          : "bg-amber-100 text-amber-700"
                    }`}
                  >
                    {recommendation.recommendationClass}
                  </span>
                  <span className="rounded-full bg-slate-100 px-2 py-0.5 text-[10px] font-bold uppercase text-slate-600">
                    {originLabel(recommendation.transformationType)}
                  </span>
                </div>
                <h3 className="mt-2 break-all text-sm font-semibold text-slate-950">
                  {recommendation.featureName}
                </h3>
              </div>
              <span
                className={`inline-flex shrink-0 items-center gap-1 rounded-full px-2 py-1 text-[10px] font-bold ${
                  accepted
                    ? "bg-emerald-100 text-emerald-700"
                    : disposition === "rejected"
                      ? "bg-rose-100 text-rose-700"
                      : disposition === "deferred"
                        ? "bg-amber-100 text-amber-700"
                        : "bg-blue-100 text-blue-700"
                }`}
              >
                <StatusIcon size={11} />
                {disposition.replace(/_/g, " ")}
              </span>
            </div>
            <code className="mt-2 block overflow-x-auto rounded-md bg-slate-950 px-2.5 py-2 text-[11px] text-cyan-100">
              {recommendation.formula}
            </code>
            <div className="mt-2 flex flex-wrap gap-1">
              {recommendation.sourceFeatures.map((source) => (
                <span
                  key={source}
                  className="rounded-full border border-slate-200 bg-white px-2 py-0.5 text-[10px] font-semibold text-slate-600"
                >
                  {source}
                </span>
              ))}
            </div>
            <p className="mt-2 text-xs leading-5 text-slate-700">
              {recommendation.rationale}
            </p>
            <details className="mt-2 rounded-lg border border-slate-200 bg-white/80 p-2.5">
              <summary className="cursor-pointer text-xs font-semibold text-slate-800">
                Evidence, benefit, risk, and validation
              </summary>
              <dl className="mt-2 grid gap-2 text-[11px] leading-5 text-slate-600">
                <div>
                  <dt className="font-bold text-slate-800">Evidence metrics</dt>
                  <dd>{recommendation.evidenceMetrics.join(" · ")}</dd>
                </div>
                <div>
                  <dt className="font-bold text-slate-800">
                    Potential analytical benefit
                  </dt>
                  <dd>{recommendation.expectedBenefit}</dd>
                </div>
                <div>
                  <dt className="font-bold text-slate-800">Risks</dt>
                  <dd>{recommendation.risks.join(" ")}</dd>
                </div>
                <div>
                  <dt className="font-bold text-slate-800">
                    Leakage assessment
                  </dt>
                  <dd>{recommendation.leakageAssessment}</dd>
                </div>
                <div className="grid grid-cols-2 gap-2">
                  <span>
                    <strong className="text-slate-800">Interpretability:</strong>{" "}
                    {recommendation.interpretability}
                  </span>
                  <span>
                    <strong className="text-slate-800">Complexity:</strong>{" "}
                    {recommendation.complexity}
                  </span>
                </div>
                <div>
                  <dt className="font-bold text-slate-800">
                    Validation requirement
                  </dt>
                  <dd>{recommendation.validationRequirement}</dd>
                </div>
              </dl>
            </details>
            {!recommendation.eligible && !accepted ? (
              <div className="mt-2 flex items-start gap-1.5 rounded-md border border-amber-200 bg-amber-50 px-2 py-1.5 text-[11px] text-amber-900">
                <AlertTriangle size={13} className="mt-0.5 shrink-0" />
                {recommendation.blockedReason}
              </div>
            ) : null}
            <div className="mt-3 flex flex-wrap gap-1.5">
              <button
                type="button"
                className="atlas-primary-button"
                disabled={!recommendation.eligible || accepted}
                onClick={() => onAccept(recommendation)}
              >
                <Check size={14} />{" "}
                {accepted ? "Accepted to Plan" : "Accept to Plan"}
              </button>
              <button
                type="button"
                className="atlas-secondary-button"
                disabled={previewing || (!recommendation.eligible && !accepted)}
                onClick={() => onPreview(recommendation)}
              >
                {previewing ? (
                  <LoaderCircle size={14} className="animate-spin" />
                ) : (
                  <Eye size={14} />
                )}{" "}
                Preview
              </button>
              <button
                type="button"
                className="atlas-secondary-button"
                disabled={accepted}
                onClick={() => onReject(recommendation)}
              >
                <X size={14} /> Reject
              </button>
              <button
                type="button"
                className="atlas-secondary-button"
                disabled={accepted}
                onClick={() => onDefer(recommendation)}
              >
                <Pause size={14} /> Defer
              </button>
            </div>
          </article>
        );
      })}
      {!recommendations.length ? (
        <div className="rounded-lg border border-slate-200 bg-slate-50 p-6 text-center text-sm text-slate-500 lg:col-span-2">
          No recommendations match this filter.
        </div>
      ) : null}
    </div>
  );
}

function BuilderSafetyNotice({
  type,
  form,
}: {
  type: BuilderType;
  form: Record<string, string>;
}) {
  const operation = form.operation || "add";
  const notices: Record<BuilderType, string> = {
    interaction:
      "Interactions remain exploratory until a main-effects comparison, VIF review, and holdout validation are complete.",
    numeric_bin:
      (form.binningMode || "custom") === "quantile"
        ? "Quantile-derived cut points are statistical and dataset-version specific. Bureau special values must remain separately labeled."
        : "Custom bins require ordered cut points, one more label than cut points, and explicit treatment of special values.",
    categorical_rule:
      "Numeric threshold rules require a numeric source and a defensible measurement scale. is_missing is reserved for true nulls, not bureau special values.",
    polynomial:
      "Polynomial terms can magnify scale and multicollinearity. AverageMInFile is a numeric duration; squaring it does not make it a date feature.",
    arithmetic:
      operation === "divide"
        ? "Division requires compatible units and a zero-denominator policy. Backend division returns null when the denominator is zero."
        : "Confirm both sources have compatible units and that the resulting domain is valid (for example, count differences should not be negative).",
    "date-derived":
      "Calendar components are allowed only for governed date/datetime predictors. Numeric durations are not dates.",
  };
  return (
    <div className="mt-3 flex items-start gap-2 rounded-lg border border-amber-200 bg-amber-50 p-3 text-xs leading-5 text-amber-900">
      <AlertTriangle size={15} className="mt-0.5 shrink-0" />
      {notices[type]}
    </div>
  );
}

function FeatureLineageGraph({
  drafts,
  manifest,
}: {
  drafts: FeatureDraft[];
  manifest: FeatureManifest;
}) {
  const visible = drafts.slice(0, 10);
  return (
    <div data-testid="feature-lineage-graph">
      <div className="space-y-2">
        {visible.map((draft) => {
          const saved = manifest.features.find(
            (feature) =>
              feature.feature_id === draft.feature_id ||
              feature.feature_name === draft.feature_name,
          );
          return (
            <div
              key={draft.feature_id ?? draft.feature_name}
              className="grid items-center gap-2 rounded-lg border border-slate-200 bg-slate-50 p-2.5 md:grid-cols-[minmax(180px,1fr)_auto_minmax(180px,1fr)_auto_minmax(180px,1fr)]"
            >
              <div className="flex flex-wrap gap-1">
                {draft.source_features.map((source) => (
                  <span
                    key={source}
                    className="rounded-md border border-blue-200 bg-blue-50 px-2 py-1 text-[10px] font-semibold text-blue-800"
                  >
                    {source}
                  </span>
                ))}
              </div>
              <GitBranch size={15} className="mx-auto text-slate-400" />
              <div className="rounded-md border border-violet-200 bg-violet-50 px-2 py-1.5 text-center">
                <div className="text-[10px] font-bold uppercase text-violet-700">
                  {originLabel(draft.origin)}
                </div>
                <code className="mt-0.5 block truncate text-[10px] text-violet-950">
                  {draft.formula_or_rule}
                </code>
              </div>
              <GitBranch size={15} className="mx-auto text-slate-400" />
              <div className="rounded-md border border-emerald-200 bg-emerald-50 px-2 py-1.5">
                <div className="truncate text-xs font-semibold text-emerald-950">
                  {draft.feature_name}
                </div>
                <div className="mt-0.5 text-[10px] text-emerald-700">
                  {saved?.materialization_status?.replace(/_/g, " ") ??
                    "draft"}{" "}
                  · manifest {manifest.manifest_version}
                </div>
              </div>
            </div>
          );
        })}
      </div>
      {!visible.length ? (
        <div className="rounded-lg border border-dashed border-slate-300 p-6 text-center text-sm text-slate-500">
          No engineered lineage exists until a recommendation or manual
          feature is accepted to the plan.
        </div>
      ) : null}
      {drafts.length > visible.length ? (
        <p className="mt-2 text-xs text-slate-500">
          Showing {visible.length} of {drafts.length} lineage paths. The
          Transformation Plan remains the complete manifest inventory.
        </p>
      ) : null}
    </div>
  );
}

function makeDraft(name: string, origin: FeatureOrigin, sources: string[], formula: string, output: string, config: Record<string, any>): FeatureDraft {
  return {
    feature_name: name,
    display_name: name,
    origin,
    source_features: sources,
    transformation_type: origin,
    formula_or_rule: formula,
    output_datatype: output,
    config: { preserve_bureau_special_values: true, ...config },
    selected: true,
    exclusion_reason: "",
    user_rationale: "",
  };
}

function BuilderForm({
  type,
  form,
  update,
  allNames,
  numericNames,
  categoricalNames,
  dateNames,
}: {
  type: BuilderType;
  form: Record<string, string>;
  update: (name: string, value: string) => void;
  allNames: string[];
  numericNames: string[];
  categoricalNames: string[];
  dateNames: string[];
}) {
  const field = (name: string) => form[name] ?? "";
  const sources =
    type === "date-derived"
      ? dateNames
      : type === "categorical_rule"
        ? allNames
        : numericNames;
  return (
    <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
      <TextField label="New feature name" value={field("name")} onChange={(value) => update("name", value)} placeholder="e.g. amount_x_velocity" />
      {type === "interaction" || type === "arithmetic" ? <><SelectField label="Left source" value={field("left")} onChange={(value) => update("left", value)} options={numericNames} placeholder="Select predictor" /><SelectField label="Right source" value={field("right")} onChange={(value) => update("right", value)} options={numericNames} placeholder="Select predictor" /></> : <SelectField label="Source predictor" value={field("source")} onChange={(value) => update("source", value)} options={sources} placeholder="Select predictor" />}
      {type === "numeric_bin" ? <><SelectField label="Binning mode" value={field("binningMode") || "custom"} onChange={(value) => update("binningMode", value)} options={["custom", "quantile"]} helper={field("binningMode") === "quantile" ? "Quantile cut points are dataset-version specific and require stability review." : "Custom cut points are reviewer-defined and versioned in the manifest."} />{(field("binningMode") || "custom") === "custom" ? <TextField label="Cut points" value={field("cutPoints")} onChange={(value) => update("cutPoints", value)} placeholder="60, 70, 80" /> : null}<TextField label="Ordinary labels" value={field("labels")} onChange={(value) => update("labels", value)} placeholder={(field("binningMode") || "custom") === "quantile" ? "Optional; five labels expected" : "Below 60, 60 to 69, 70 to 79, 80 or above"} /><TextField label="Bureau-special label" value={field("specialValueLabel")} onChange={(value) => update("specialValueLabel", value)} placeholder="Bureau special" /><TextField label="True-missing label" value={field("missingLabel")} onChange={(value) => update("missingLabel", value)} placeholder="Missing" /></> : null}
      {type === "categorical_rule" ? <><SelectField label="Operator" value={field("operator") || "equals"} onChange={(value) => update("operator", value)} options={["equals", "contains", "greater_than", "greater_than_or_equal", "less_than", "less_than_or_equal", "is_missing"]} />{(field("operator") || "equals") === "is_missing" ? <div className="rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs text-slate-500">Rule value is not required for is_missing.</div> : <TextField label="Rule value" value={field("value")} onChange={(value) => update("value", value)} />}<TextField label="Matched label" value={field("thenLabel")} onChange={(value) => update("thenLabel", value)} placeholder="Matched" /><TextField label="Else label" value={field("elseLabel")} onChange={(value) => update("elseLabel", value)} placeholder="Other" /><TextField label="Bureau-special label" value={field("specialValueLabel")} onChange={(value) => update("specialValueLabel", value)} placeholder="Bureau special" /></> : null}
      {type === "polynomial" ? <SelectField label="Degree" value={field("degree") || "2"} onChange={(value) => update("degree", value)} options={["2", "3"]} /> : null}
      {type === "arithmetic" ? <><SelectField label="Operation" value={field("operation") || "add"} onChange={(value) => update("operation", value)} options={["add", "subtract", "multiply", "divide"]} /><SelectField label="Result domain" value={field("resultDomain") || "unrestricted"} onChange={(value) => update("resultDomain", value)} options={["unrestricted", "nonnegative"]} helper="Choose nonnegative only when the governed data and business definition support it." />{field("resultDomain") === "nonnegative" || field("operation") === "divide" ? <SelectField label="Domain evidence" value={field("domainEvidence") || "not_established"} onChange={(value) => update("domainEvidence", value)} options={["not_established", "left_gte_right", "right_nonzero"]} helper="ATLAS also validates the resulting full-data domain during manifest save." /> : null}<TextField label="Domain evidence note" value={field("domainNote")} onChange={(value) => update("domainNote", value)} placeholder="Why are the units and resulting domain valid?" /></> : null}
      {type === "date-derived" ? <SelectField label="Date component" value={field("component") || "year"} onChange={(value) => update("component", value)} options={["year", "month", "quarter", "day_of_week"]} /> : null}
      {type === "categorical_rule" && !categoricalNames.length ? <div className="text-xs text-amber-800">No categorical source was inferred. Numeric fields remain available for threshold rules.</div> : null}
      {type === "date-derived" && !dateNames.length ? <div className="text-xs font-semibold text-amber-800">Unavailable: no governed date predictor is present. Duration fields such as months-in-file are numeric durations, not calendar dates.</div> : null}
      <TextField label="Reviewer rationale" value={field("rationale")} onChange={(value) => update("rationale", value)} placeholder="Why is this feature defensible and useful to validate?" />
    </div>
  );
}

function FeaturePreviewTable({ preview }: { preview: FeaturePreview }) {
  return (
    <div className="mt-4">
      <div className="mb-2 flex items-center justify-between"><div className="text-sm font-semibold text-slate-950">Bounded feature preview</div><AtlasDataScopeBadge scope="rendered_sample" rows={preview.preview_row_count} /></div>
      <div className="max-h-80 overflow-auto rounded-lg border border-slate-200"><table className="atlas-table min-w-[760px]"><thead><tr>{preview.columns.map((column) => <th key={column}>{column}</th>)}</tr></thead><tbody>{preview.rows.map((row, index) => <tr key={index}>{preview.columns.map((column) => <td key={column}>{String(row[column] ?? "")}</td>)}</tr>)}</tbody></table></div>
      <p className="mt-2 text-xs text-slate-600">The preview renders {preview.preview_row_count.toLocaleString()} rows. Full-data execution occurs only through Materialize full dataset.</p>
    </div>
  );
}

function StatusMetric({ label, value, warning = false }: { label: string; value: string | number; warning?: boolean }) {
  return <div className={`rounded-lg border px-3 py-2.5 ${warning ? "border-amber-300 bg-amber-50" : "border-slate-200 bg-white"}`}><div className="text-[10px] font-semibold uppercase text-slate-500">{label}</div><div className="mt-1 text-sm font-semibold capitalize text-slate-950">{value}</div></div>;
}

function TextField({ label, value, onChange, placeholder = "" }: { label: string; value: string; onChange: (value: string) => void; placeholder?: string }) {
  return <label><span className="atlas-label">{label}</span><input className="atlas-input mt-1" value={value} onChange={(event) => onChange(event.target.value)} placeholder={placeholder} /></label>;
}

function SelectField({ label, value, onChange, options, helper, placeholder }: { label: string; value: string; onChange: (value: string) => void; options: string[]; helper?: string; placeholder?: string }) {
  return <label><span className="atlas-label">{label}</span><select className="atlas-input mt-1" value={value} onChange={(event) => onChange(event.target.value)}>{placeholder ? <option value="">{placeholder}</option> : null}{options.map((option) => <option key={option} value={option}>{option}</option>)}</select>{helper ? <span className="mt-1 block text-xs text-slate-500">{helper}</span> : null}</label>;
}

function originLabel(origin: FeatureOrigin) {
  return origin.split(/[-_]/).map((part) => `${part.charAt(0).toUpperCase()}${part.slice(1)}`).join(" ");
}
