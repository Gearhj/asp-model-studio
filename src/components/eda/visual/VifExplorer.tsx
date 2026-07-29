import {
  CheckCircle2,
  Download,
  FlaskConical,
  Link2,
  RotateCcw,
  ShieldCheck,
  TableProperties,
  X,
} from "lucide-react";
import {
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
} from "react";
import { ATLAS_MOTION_TOKENS } from "../../../visual-intelligence/motion";
import { useReducedMotion } from "../../../visual-intelligence/useReducedMotion";

export type VifRow = {
  feature?: string;
  variable?: string;
  vif?: number | string | null;
  status?: string | null;
  [key: string]: unknown;
};

export type VifDecisionAction = "retain" | "drop" | "combine";

export type VifDecision = {
  action: VifDecisionAction;
  combineWith?: string;
  rationale: string;
  updatedAt: string;
};

export type VifSimulationRequest = {
  datasetVersion: string;
  mode: "temporary-exclusion";
  temporarilyExcludedVariables: string[];
};

export type VifSimulationResult = {
  summary?: string;
  maximumVif?: number | null;
  materialReviewCount?: number | null;
  rows?: VifRow[];
};

export type VifScope = {
  scope?: string;
  population_rows?: number;
  complete_case_rows?: number;
  rows_used?: number;
  sampled?: boolean;
  maximum_rows?: number;
  source_predictors?: number;
  predictors_used?: string[];
  predictor_cap?: number;
};

export type VifExplorerProps = {
  rows: VifRow[];
  correlationColumns: string[];
  correlationMatrix: Array<Array<number | null>>;
  selectedVariable?: string | null;
  onSelectVariable: (variable: string | null) => void;
  datasetVersion: string;
  scope?: VifScope;
  /**
   * Enables an analytical preview only. The explorer never mutates the
   * governed predictor manifest or dataset.
   */
  onSimulate?: (
    request: VifSimulationRequest,
  ) => VifSimulationResult | void | Promise<VifSimulationResult | void>;
};

type PreparedVifRow = VifRow & {
  featureName: string;
  numericVif: number | null;
  isInfinite: boolean;
  zone: "acceptable" | "review" | "material" | "unavailable";
};

type CorrelationPartner = {
  variable: string;
  correlation: number;
  magnitude: number;
};

type DecisionState = {
  datasetVersion: string;
  decisions: Record<string, VifDecision>;
};

type SimulationState =
  | { status: "idle" }
  | { status: "running"; variable: string }
  | { status: "success"; variable: string; result?: VifSimulationResult }
  | { status: "error"; variable: string; message: string };

const DECISION_STORAGE_PREFIX = "atlas.eda.vif-decisions";

const ZONE_META = {
  acceptable: {
    label: "Acceptable",
    shortLabel: "< 5",
    barClass: "bg-emerald-600",
    textClass: "text-emerald-800",
    badgeClass: "border-emerald-200 bg-emerald-50 text-emerald-800",
  },
  review: {
    label: "Review",
    shortLabel: "5–<10",
    barClass: "bg-amber-500",
    textClass: "text-amber-800",
    badgeClass: "border-amber-200 bg-amber-50 text-amber-900",
  },
  material: {
    label: "Material review",
    shortLabel: "≥ 10",
    barClass: "bg-rose-600",
    textClass: "text-rose-800",
    badgeClass: "border-rose-200 bg-rose-50 text-rose-900",
  },
  unavailable: {
    label: "Unavailable",
    shortLabel: "—",
    barClass: "bg-slate-400",
    textClass: "text-slate-600",
    badgeClass: "border-slate-200 bg-slate-50 text-slate-700",
  },
} as const;

function featureName(row: VifRow): string {
  return String(row.feature ?? row.variable ?? "").trim();
}

function prepareVifRow(row: VifRow): PreparedVifRow | null {
  const name = featureName(row);
  if (!name) return null;
  const raw = row.vif;
  const normalized = typeof raw === "string" ? raw.trim().toLowerCase() : raw;
  const hasValue =
    raw !== null &&
    raw !== undefined &&
    !(typeof raw === "string" && raw.trim() === "");
  const parsed = hasValue ? Number(raw) : Number.NaN;
  const isInfinite =
    row.is_infinite === true ||
    parsed === Number.POSITIVE_INFINITY ||
    normalized === "inf" ||
    normalized === "+inf" ||
    normalized === "infinity" ||
    normalized === "+infinity";
  const numericVif = Number.isFinite(parsed) && parsed >= 0 ? parsed : null;
  const zone = isInfinite || (numericVif !== null && numericVif >= 10)
    ? "material"
    : numericVif !== null && numericVif >= 5
      ? "review"
      : numericVif !== null
        ? "acceptable"
        : "unavailable";
  return { ...row, featureName: name, numericVif, isInfinite, zone };
}

function comparePreparedRows(left: PreparedVifRow, right: PreparedVifRow): number {
  if (left.isInfinite !== right.isInfinite) return left.isInfinite ? -1 : 1;
  if (left.numericVif === null && right.numericVif !== null) return 1;
  if (right.numericVif === null && left.numericVif !== null) return -1;
  if (left.numericVif !== right.numericVif) {
    return (right.numericVif ?? -1) - (left.numericVif ?? -1);
  }
  return left.featureName.localeCompare(right.featureName);
}

function displayVif(row: PreparedVifRow): string {
  if (row.isInfinite) return "∞";
  if (row.numericVif === null) return "Not available";
  return row.numericVif.toLocaleString(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
}

function formatCorrelation(value: number): string {
  return value.toLocaleString(undefined, {
    minimumFractionDigits: 3,
    maximumFractionDigits: 3,
  });
}

function normalizedName(value: string): string {
  return value.trim().toLocaleLowerCase();
}

function decisionStorageKey(datasetVersion: string): string {
  return `${DECISION_STORAGE_PREFIX}:${encodeURIComponent(datasetVersion || "unknown")}`;
}

function validDecision(value: unknown): value is VifDecision {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  const candidate = value as Partial<VifDecision>;
  return (
    (candidate.action === "retain" ||
      candidate.action === "drop" ||
      candidate.action === "combine") &&
    typeof candidate.rationale === "string" &&
    typeof candidate.updatedAt === "string" &&
    (candidate.combineWith === undefined || typeof candidate.combineWith === "string")
  );
}

function readDecisions(datasetVersion: string): Record<string, VifDecision> {
  if (typeof window === "undefined") return {};
  try {
    const raw = window.localStorage.getItem(decisionStorageKey(datasetVersion));
    if (!raw) return {};
    const parsed = JSON.parse(raw) as unknown;
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) return {};
    const decisions: Record<string, VifDecision> = {};
    Object.entries(parsed as Record<string, unknown>).forEach(
      ([variable, decision]) => {
        if (variable.trim() && validDecision(decision)) {
          decisions[variable] = decision;
        }
      },
    );
    return decisions;
  } catch {
    return {};
  }
}

function hardenCsvCell(value: unknown): string {
  let text = String(value ?? "");
  if (/^[\t\r ]*[=+\-@]/.test(text)) text = `'${text}`;
  return `"${text.replace(/"/g, '""')}"`;
}

function safeFilenameSegment(value: string): string {
  return value.trim().replace(/[^a-zA-Z0-9._-]+/g, "-").replace(/^-+|-+$/g, "") || "dataset";
}

function strongestPartners(
  variable: string | null,
  columns: string[],
  matrix: Array<Array<number | null>>,
): CorrelationPartner[] {
  if (!variable) return [];
  const exactIndex = columns.indexOf(variable);
  const normalizedVariable = normalizedName(variable);
  const selectedIndex = exactIndex >= 0
    ? exactIndex
    : columns.findIndex((column) => normalizedName(column) === normalizedVariable);
  if (selectedIndex < 0) return [];
  return columns
    .map((column, columnIndex) => {
      if (columnIndex === selectedIndex) return null;
      const rawValue =
        matrix[selectedIndex]?.[columnIndex] ??
        matrix[columnIndex]?.[selectedIndex];
      if (rawValue === null || rawValue === undefined) return null;
      const value = Number(rawValue);
      if (!Number.isFinite(value)) return null;
      return {
        variable: column,
        correlation: value,
        magnitude: Math.abs(value),
      };
    })
    .filter((partner): partner is CorrelationPartner => partner !== null)
    .sort(
      (left, right) =>
        right.magnitude - left.magnitude ||
        left.variable.localeCompare(right.variable),
    );
}

function makeExportRows(
  rows: PreparedVifRow[],
  columns: string[],
  matrix: Array<Array<number | null>>,
  decisions: Record<string, VifDecision>,
): string {
  const header = [
    "Variable",
    "VIF",
    "Review zone",
    "Strongest correlated partner",
    "Correlation",
    "Decision",
    "Combine with",
    "Rationale",
  ];
  const body = rows.map((row) => {
    const strongest = strongestPartners(row.featureName, columns, matrix)[0];
    const decision = decisions[row.featureName];
    return [
      row.featureName,
      row.isInfinite ? "Infinity" : row.numericVif ?? "",
      ZONE_META[row.zone].label,
      strongest?.variable ?? "",
      strongest ? formatCorrelation(strongest.correlation) : "",
      decision?.action ?? "",
      decision?.combineWith ?? "",
      decision?.rationale ?? "",
    ];
  });
  return [header, ...body].map((values) => values.map(hardenCsvCell).join(",")).join("\r\n");
}

function downloadCsv(filename: string, csv: string): void {
  const url = URL.createObjectURL(
    new Blob([`\uFEFF${csv}`], { type: "text/csv;charset=utf-8" }),
  );
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  window.setTimeout(() => URL.revokeObjectURL(url), 0);
}

export default function VifExplorer({
  rows,
  correlationColumns,
  correlationMatrix,
  selectedVariable = null,
  onSelectVariable,
  datasetVersion,
  scope,
  onSimulate,
}: VifExplorerProps) {
  const titleId = useId();
  const summaryId = useId();
  const reducedMotion = useReducedMotion();
  const [motionPhase, setMotionPhase] = useState<"initial" | "entering" | "settled">(
    reducedMotion ? "settled" : "initial",
  );
  const [decisionState, setDecisionState] = useState<DecisionState>(() => ({
    datasetVersion,
    decisions: readDecisions(datasetVersion),
  }));
  const [storageMessage, setStorageMessage] = useState("");
  const [simulationState, setSimulationState] = useState<SimulationState>({ status: "idle" });
  const simulationRevision = useRef(0);

  const preparedRows = useMemo(
    () =>
      rows
        .map(prepareVifRow)
        .filter((row): row is PreparedVifRow => row !== null)
        .sort(comparePreparedRows),
    [rows],
  );
  const chartRows = preparedRows.slice(0, 20);
  const finiteMaximum = Math.max(
    0,
    ...preparedRows.map((row) => row.numericVif ?? 0),
  );
  const scaleMaximum = Math.min(50, Math.max(12, Math.ceil(finiteMaximum * 1.08)));
  const selectedPrepared = preparedRows.find(
    (row) => normalizedName(row.featureName) === normalizedName(selectedVariable ?? ""),
  );
  const activeVariable = selectedPrepared?.featureName ?? null;
  const motionSignature = preparedRows
    .map((row) => `${row.featureName}:${row.isInfinite ? "inf" : row.numericVif ?? "na"}`)
    .join("|");
  const partners = useMemo(
    () =>
      strongestPartners(activeVariable, correlationColumns, correlationMatrix),
    [activeVariable, correlationColumns, correlationMatrix],
  );
  const topPartners = partners.slice(0, 5);
  const partnerRank = new Map(
    topPartners.map((partner, index) => [normalizedName(partner.variable), index + 1]),
  );
  const currentDecisions =
    decisionState.datasetVersion === datasetVersion ? decisionState.decisions : {};
  const activeDecision = activeVariable ? currentDecisions[activeVariable] : undefined;
  const acceptableCount = preparedRows.filter((row) => row.zone === "acceptable").length;
  const reviewCount = preparedRows.filter((row) => row.zone === "review").length;
  const materialCount = preparedRows.filter((row) => row.zone === "material").length;
  const decidedCount = Object.keys(currentDecisions).filter((variable) =>
    preparedRows.some((row) => row.featureName === variable),
  ).length;

  useEffect(() => {
    if (reducedMotion) {
      setMotionPhase("settled");
      return;
    }
    setMotionPhase("initial");
    const frame = window.requestAnimationFrame(() => setMotionPhase("entering"));
    const timer = window.setTimeout(
      () => setMotionPhase("settled"),
      ATLAS_MOTION_TOKENS.durationMs.enter +
        ATLAS_MOTION_TOKENS.stagger.maxTotalMs +
        32,
    );
    return () => {
      window.cancelAnimationFrame(frame);
      window.clearTimeout(timer);
    };
  }, [datasetVersion, motionSignature, reducedMotion]);

  useEffect(() => {
    if (decisionState.datasetVersion === datasetVersion) return;
    setDecisionState({
      datasetVersion,
      decisions: readDecisions(datasetVersion),
    });
    setStorageMessage("");
  }, [datasetVersion, decisionState.datasetVersion]);

  useEffect(() => {
    if (
      typeof window === "undefined" ||
      decisionState.datasetVersion !== datasetVersion
    ) {
      return;
    }
    try {
      window.localStorage.setItem(
        decisionStorageKey(datasetVersion),
        JSON.stringify(decisionState.decisions),
      );
      setStorageMessage("");
    } catch {
      setStorageMessage(
        "Decision changes are available for this session, but the browser could not persist them.",
      );
    }
  }, [datasetVersion, decisionState]);

  useEffect(
    () => () => {
      simulationRevision.current += 1;
    },
    [],
  );

  useEffect(() => {
    simulationRevision.current += 1;
    setSimulationState({ status: "idle" });
  }, [activeVariable, datasetVersion]);

  const updateDecision = (
    variable: string,
    patch: Partial<VifDecision> & Pick<VifDecision, "action">,
  ) => {
    setDecisionState((current) => {
      const decisions =
        current.datasetVersion === datasetVersion
          ? current.decisions
          : readDecisions(datasetVersion);
      const existing = decisions[variable];
      const strongest = strongestPartners(
        variable,
        correlationColumns,
        correlationMatrix,
      )[0]?.variable;
      const next: VifDecision = {
        action: patch.action,
        combineWith:
          patch.action === "combine"
            ? patch.combineWith ?? existing?.combineWith ?? strongest
            : undefined,
        rationale: patch.rationale ?? existing?.rationale ?? "",
        updatedAt: new Date().toISOString(),
      };
      return {
        datasetVersion,
        decisions: { ...decisions, [variable]: next },
      };
    });
  };

  const clearDecision = (variable: string) => {
    setDecisionState((current) => {
      const decisions =
        current.datasetVersion === datasetVersion
          ? current.decisions
          : readDecisions(datasetVersion);
      const next = { ...decisions };
      delete next[variable];
      return { datasetVersion, decisions: next };
    });
  };

  const runSimulation = async () => {
    if (!onSimulate || !activeVariable) return;
    const revision = simulationRevision.current + 1;
    simulationRevision.current = revision;
    setSimulationState({ status: "running", variable: activeVariable });
    try {
      const result = await onSimulate({
        datasetVersion,
        mode: "temporary-exclusion",
        temporarilyExcludedVariables: [activeVariable],
      });
      if (revision !== simulationRevision.current) return;
      const normalizedResult =
        result && typeof result === "object" ? result : undefined;
      setSimulationState({
        status: "success",
        variable: activeVariable,
        result: normalizedResult,
      });
    } catch (error) {
      if (revision !== simulationRevision.current) return;
      setSimulationState({
        status: "error",
        variable: activeVariable,
        message: error instanceof Error ? error.message : "The temporary simulation failed.",
      });
    }
  };

  const exportCurrentTable = () => {
    downloadCsv(
      `atlas-vif-${safeFilenameSegment(datasetVersion)}.csv`,
      makeExportRows(
        preparedRows,
        correlationColumns,
        correlationMatrix,
        currentDecisions,
      ),
    );
  };

  if (!preparedRows.length) {
    return (
      <section
        className="overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm"
        data-testid="vif-explorer"
        aria-labelledby={titleId}
      >
        <div className="border-b border-slate-200 bg-slate-50 px-5 py-4">
          <div className="flex items-center gap-2 text-[11px] font-semibold uppercase tracking-[0.14em] text-blue-700">
            <ShieldCheck size={14} aria-hidden="true" />
            Multicollinearity review
          </div>
          <h3 id={titleId} className="mt-1 text-base font-semibold text-slate-950">
            Variance Inflation Explorer
          </h3>
        </div>
        <div className="flex min-h-56 flex-col items-center justify-center px-6 py-10 text-center">
          <div className="rounded-full border border-slate-200 bg-slate-50 p-3 text-slate-500">
            <TableProperties size={22} aria-hidden="true" />
          </div>
          <p className="mt-4 text-sm font-semibold text-slate-800">
            VIF requires at least two eligible numeric predictors.
          </p>
          <p className="mt-1 max-w-xl text-xs leading-5 text-slate-500">
            No automated removal is performed. The explorer will become available when
            the governed backend returns a valid VIF inventory.
          </p>
        </div>
      </section>
    );
  }

  const acceptableEnd = (5 / scaleMaximum) * 100;
  const reviewEnd = (10 / scaleMaximum) * 100;
  const transitionDuration =
    reducedMotion
      ? 0
      : motionPhase === "entering"
        ? ATLAS_MOTION_TOKENS.durationMs.enter
        : ATLAS_MOTION_TOKENS.durationMs.update;

  return (
    <section
      className="overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm"
      data-testid="vif-explorer"
      data-motion-phase={motionPhase}
      data-reduced-motion={reducedMotion ? "true" : "false"}
      aria-labelledby={titleId}
      aria-describedby={summaryId}
    >
      <header className="border-b border-slate-200 bg-slate-50 px-4 py-4 sm:px-5">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
          <div>
            <div className="flex items-center gap-2 text-[11px] font-semibold uppercase tracking-[0.14em] text-blue-700">
              <ShieldCheck size={14} aria-hidden="true" />
              Multicollinearity review
            </div>
            <h3 id={titleId} className="mt-1 text-base font-semibold text-slate-950">
              Variance Inflation Explorer
            </h3>
            <p id={summaryId} className="mt-1 max-w-3xl text-xs leading-5 text-slate-600">
              VIF 5–&lt;10 and VIF ≥10 are review thresholds, not automatic removal
              rules. Select a variable to inspect its strongest correlated partners,
              then record a non-binding analyst decision.
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <span
              className="inline-flex items-center rounded-full border border-slate-300 bg-white px-2.5 py-1 text-[10px] font-semibold text-slate-700"
              data-testid="vif-scope-badge"
              title={
                scope
                  ? `${Number(scope.complete_case_rows ?? 0).toLocaleString()} complete rows before the deterministic ${Number(scope.maximum_rows ?? 0).toLocaleString()}-row cap`
                  : "Backend-bounded VIF computation"
              }
            >
              {scope
                ? `${Number(scope.rows_used ?? 0).toLocaleString()} backend rows${
                    scope.sampled ? " · sampled" : " · complete cases"
                  }`
                : "Bounded backend computation"}
            </span>
            {selectedVariable ? (
              <button
                type="button"
                onClick={() => onSelectVariable(null)}
                className="inline-flex items-center gap-1.5 rounded-lg border border-slate-300 bg-white px-3 py-2 text-xs font-semibold text-slate-700 shadow-sm hover:border-slate-400 hover:bg-slate-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500"
              >
                <X size={14} aria-hidden="true" />
                Clear selection
              </button>
            ) : null}
            <button
              type="button"
              onClick={exportCurrentTable}
              data-testid="vif-export"
              className="inline-flex items-center gap-1.5 rounded-lg border border-blue-200 bg-blue-50 px-3 py-2 text-xs font-semibold text-blue-800 shadow-sm hover:border-blue-300 hover:bg-blue-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500"
            >
              <Download size={14} aria-hidden="true" />
              Export current table
            </button>
          </div>
        </div>
      </header>

      <div className="grid gap-0 xl:grid-cols-[minmax(0,1.55fr)_minmax(330px,0.75fr)]">
        <div className="min-w-0 border-b border-slate-200 p-4 sm:p-5 xl:border-b-0 xl:border-r">
          <div className="mb-4 grid grid-cols-2 gap-2 sm:grid-cols-4">
            {[
              ["Analyzed", preparedRows.length, "border-slate-200 bg-slate-50 text-slate-800"],
              ["Acceptable", acceptableCount, "border-emerald-200 bg-emerald-50 text-emerald-800"],
              ["Review", reviewCount, "border-amber-200 bg-amber-50 text-amber-900"],
              ["Material review", materialCount, "border-rose-200 bg-rose-50 text-rose-900"],
            ].map(([label, value, className]) => (
              <div key={String(label)} className={`rounded-xl border px-3 py-2.5 ${className}`}>
                <div className="text-[10px] font-semibold uppercase tracking-wide">{label}</div>
                <div className="mt-0.5 text-lg font-semibold tabular-nums">{value}</div>
              </div>
            ))}
          </div>

          <div className="mb-4 flex flex-wrap gap-x-4 gap-y-2 text-[11px] font-semibold">
            <span className="inline-flex items-center gap-1.5 text-emerald-800">
              <span className="h-2.5 w-2.5 rounded-sm bg-emerald-600" aria-hidden="true" />
              Acceptable &lt; 5
            </span>
            <span className="inline-flex items-center gap-1.5 text-amber-800">
              <span className="h-2.5 w-2.5 rounded-sm bg-amber-500" aria-hidden="true" />
              Review 5–&lt;10
            </span>
            <span className="inline-flex items-center gap-1.5 text-rose-800">
              <span className="h-2.5 w-2.5 rounded-sm bg-rose-600" aria-hidden="true" />
              Material review ≥10
            </span>
          </div>

          <div className="hidden grid-cols-[minmax(150px,220px)_minmax(220px,1fr)_84px_112px] gap-3 px-3 pb-2 text-[10px] font-semibold uppercase tracking-wide text-slate-500 sm:grid">
            <span>Variable</span>
            <span className="relative h-5" aria-hidden="true">
              <span className="absolute left-0">0</span>
              <span
                className="absolute -translate-x-1/2"
                style={{ left: `${acceptableEnd}%` }}
              >
                5
              </span>
              <span
                className="absolute -translate-x-1/2"
                style={{ left: `${reviewEnd}%` }}
              >
                10
              </span>
              <span className="absolute right-0">{scaleMaximum}</span>
            </span>
            <span className="text-right">VIF</span>
            <span>Zone</span>
          </div>

          <div
            className="space-y-2"
            aria-label={`VIF bars for ${chartRows.length} variables`}
            data-default-vertical-scroll="false"
          >
            {chartRows.map((row, index) => {
              const selected =
                normalizedName(activeVariable ?? "") === normalizedName(row.featureName);
              const relatedRank = partnerRank.get(normalizedName(row.featureName));
              const plottedValue = row.isInfinite
                ? scaleMaximum
                : Math.min(scaleMaximum, row.numericVif ?? 0);
              const targetWidth =
                row.numericVif === null && !row.isInfinite
                  ? 0
                  : Math.max(1.5, (plottedValue / scaleMaximum) * 100);
              const width = motionPhase === "initial" && !reducedMotion ? 0 : targetWidth;
              const delay = reducedMotion
                ? 0
                : motionPhase === "entering"
                  ? Math.min(
                      index * ATLAS_MOTION_TOKENS.stagger.stepMs,
                      ATLAS_MOTION_TOKENS.stagger.maxTotalMs,
                    )
                  : 0;
              const meta = ZONE_META[row.zone];
              return (
                <button
                  type="button"
                  key={row.featureName}
                  data-variable={row.featureName}
                  data-vif-zone={row.zone}
                  aria-pressed={selected}
                  aria-label={`${row.featureName}, VIF ${displayVif(row)}, ${meta.label}${
                    relatedRank ? `, correlated partner rank ${relatedRank}` : ""
                  }`}
                  onClick={() =>
                    onSelectVariable(selected ? null : row.featureName)
                  }
                  className={`group flex w-full flex-col gap-2 rounded-xl border px-3 py-3 text-left transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 sm:grid sm:grid-cols-[minmax(150px,220px)_minmax(220px,1fr)_84px_112px] sm:items-center sm:gap-3 ${
                    selected
                      ? "border-blue-400 bg-blue-50 shadow-sm"
                      : relatedRank
                        ? "border-violet-300 bg-violet-50/70"
                        : "border-transparent hover:border-slate-200 hover:bg-slate-50"
                  }`}
                >
                  <span className="min-w-0">
                    <span
                      className="block truncate text-xs font-semibold text-slate-900"
                      title={row.featureName}
                    >
                      {row.featureName}
                    </span>
                    <span className="mt-0.5 block text-[10px] text-slate-500 sm:hidden">
                      VIF {displayVif(row)} · {meta.label}
                    </span>
                    {relatedRank ? (
                      <span className="mt-1 inline-flex items-center gap-1 text-[10px] font-semibold text-violet-800">
                        <Link2 size={11} aria-hidden="true" />
                        Partner #{relatedRank}
                      </span>
                    ) : null}
                  </span>
                  <span className="relative block h-5 overflow-hidden rounded-md border border-slate-200 bg-white">
                    <span
                      className="absolute inset-y-0 left-0 bg-emerald-50"
                      style={{ width: `${acceptableEnd}%` }}
                      aria-hidden="true"
                    />
                    <span
                      className="absolute inset-y-0 bg-amber-50"
                      style={{
                        left: `${acceptableEnd}%`,
                        width: `${Math.max(0, reviewEnd - acceptableEnd)}%`,
                      }}
                      aria-hidden="true"
                    />
                    <span
                      className="absolute inset-y-0 right-0 bg-rose-50"
                      style={{ left: `${reviewEnd}%` }}
                      aria-hidden="true"
                    />
                    <span
                      className="absolute inset-y-0 z-10 border-l border-dashed border-amber-500"
                      style={{ left: `${acceptableEnd}%` }}
                      aria-hidden="true"
                    />
                    <span
                      className="absolute inset-y-0 z-10 border-l border-dashed border-rose-500"
                      style={{ left: `${reviewEnd}%` }}
                      aria-hidden="true"
                    />
                    <span
                      className={`relative z-20 block h-full rounded-sm ${meta.barClass}`}
                      style={
                        {
                          width: `${width}%`,
                          opacity: motionPhase === "initial" && !reducedMotion ? 0.4 : 1,
                          transitionProperty: "width, opacity",
                          transitionDuration: `${transitionDuration}ms`,
                          transitionDelay: `${delay}ms`,
                          transitionTimingFunction: "cubic-bezier(0.22, 1, 0.36, 1)",
                        } satisfies CSSProperties
                      }
                      aria-hidden="true"
                    />
                  </span>
                  <span className={`text-right text-xs font-semibold tabular-nums ${meta.textClass}`}>
                    {displayVif(row)}
                    {row.numericVif !== null && row.numericVif > scaleMaximum ? (
                      <span className="ml-1 text-[9px] font-medium text-slate-500">
                        capped
                      </span>
                    ) : null}
                  </span>
                  <span
                    className={`w-fit rounded-full border px-2 py-1 text-[10px] font-semibold ${meta.badgeClass}`}
                  >
                    {meta.label}
                  </span>
                </button>
              );
            })}
          </div>
          {preparedRows.length > chartRows.length ? (
            <p className="mt-3 text-[11px] text-slate-500">
              Chart shows the 20 highest VIF values. The complete table and export
              include all {preparedRows.length.toLocaleString()} variables.
            </p>
          ) : null}
        </div>

        <aside className="min-w-0 bg-slate-50/70 p-4 sm:p-5">
          <section aria-labelledby={`${titleId}-relationships`}>
            <div className="flex items-center justify-between gap-3">
              <div>
                <div className="text-[10px] font-semibold uppercase tracking-[0.13em] text-slate-500">
                  Linked evidence
                </div>
                <h4
                  id={`${titleId}-relationships`}
                  className="mt-1 text-sm font-semibold text-slate-950"
                >
                  Strongest relationships
                </h4>
              </div>
              {activeVariable ? (
                <span
                  className="max-w-40 truncate rounded-full border border-blue-200 bg-blue-50 px-2.5 py-1 text-[10px] font-semibold text-blue-800"
                  title={activeVariable}
                >
                  {activeVariable}
                </span>
              ) : null}
            </div>

            {!activeVariable ? (
              <div className="mt-3 rounded-xl border border-dashed border-slate-300 bg-white px-4 py-5 text-xs leading-5 text-slate-600">
                Select a VIF bar to highlight its strongest correlated partners and
                capture a review decision.
              </div>
            ) : !topPartners.length ? (
              <div className="mt-3 rounded-xl border border-dashed border-slate-300 bg-white px-4 py-5 text-xs leading-5 text-slate-600">
                No valid correlation row is available for {activeVariable}. VIF remains
                visible, but relationship attribution cannot be inferred.
              </div>
            ) : (
              <ol
                className="mt-3 space-y-2"
                data-testid="vif-partner-list"
                aria-label={`Strongest correlated partners for ${activeVariable}`}
              >
                {topPartners.map((partner, index) => (
                  <li key={partner.variable}>
                    <button
                      type="button"
                      onClick={() => onSelectVariable(partner.variable)}
                      className="grid w-full grid-cols-[24px_minmax(0,1fr)_auto] items-center gap-2 rounded-xl border border-slate-200 bg-white px-3 py-2.5 text-left shadow-sm hover:border-violet-300 hover:bg-violet-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-violet-500"
                      aria-label={`Select ${partner.variable}, correlation ${formatCorrelation(
                        partner.correlation,
                      )}`}
                    >
                      <span className="flex h-6 w-6 items-center justify-center rounded-full bg-violet-50 text-[10px] font-semibold text-violet-800">
                        {index + 1}
                      </span>
                      <span className="min-w-0">
                        <span
                          className="block truncate text-xs font-semibold text-slate-900"
                          title={partner.variable}
                        >
                          {partner.variable}
                        </span>
                        <span className="text-[10px] text-slate-500">
                          |r| {formatCorrelation(partner.magnitude)}
                        </span>
                      </span>
                      <span
                        className={`text-xs font-semibold tabular-nums ${
                          partner.correlation < 0 ? "text-rose-700" : "text-blue-700"
                        }`}
                      >
                        r {partner.correlation > 0 ? "+" : ""}
                        {formatCorrelation(partner.correlation)}
                      </span>
                    </button>
                  </li>
                ))}
              </ol>
            )}
            <p className="mt-3 text-[10px] leading-4 text-slate-500">
              Relationship ranking uses absolute Pearson correlation from the governed
              matrix. Direction and the exact coefficient remain visible.
            </p>
          </section>

          <div className="my-5 border-t border-slate-200" />

          <section
            aria-labelledby={`${titleId}-decision`}
            data-testid="vif-decision-capture"
          >
            <div className="flex items-center justify-between gap-3">
              <div>
                <div className="text-[10px] font-semibold uppercase tracking-[0.13em] text-slate-500">
                  Analyst record
                </div>
                <h4
                  id={`${titleId}-decision`}
                  className="mt-1 text-sm font-semibold text-slate-950"
                >
                  Retain / drop / combine
                </h4>
              </div>
              <span className="text-[10px] font-semibold text-slate-500">
                {decidedCount}/{preparedRows.length} reviewed
              </span>
            </div>
            {!activeVariable ? (
              <p className="mt-3 rounded-xl border border-dashed border-slate-300 bg-white px-4 py-4 text-xs leading-5 text-slate-600">
                Select a variable before recording a decision.
              </p>
            ) : (
              <div className="mt-3 rounded-xl border border-slate-200 bg-white p-3 shadow-sm">
                <p className="text-xs leading-5 text-slate-600">
                  Decision for <strong className="font-semibold text-slate-950">{activeVariable}</strong>.
                  This record does not alter data or predictor eligibility.
                </p>
                <div
                  className="mt-3 grid grid-cols-3 gap-1 rounded-lg bg-slate-100 p-1"
                  role="group"
                  aria-label={`Decision for ${activeVariable}`}
                >
                  {(["retain", "drop", "combine"] as const).map((action) => {
                    const pressed = activeDecision?.action === action;
                    return (
                      <button
                        type="button"
                        key={action}
                        aria-pressed={pressed}
                        onClick={() => updateDecision(activeVariable, { action })}
                        className={`rounded-md px-2 py-2 text-[11px] font-semibold capitalize focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 ${
                          pressed
                            ? "bg-slate-950 text-white shadow-sm"
                            : "text-slate-700 hover:bg-white"
                        }`}
                      >
                        {action}
                      </button>
                    );
                  })}
                </div>

                {activeDecision?.action === "combine" ? (
                  <label className="mt-3 block text-[11px] font-semibold text-slate-700">
                    Combine with
                    <select
                      value={activeDecision.combineWith ?? ""}
                      onChange={(event) =>
                        updateDecision(activeVariable, {
                          action: "combine",
                          combineWith: event.target.value || undefined,
                        })
                      }
                      className="mt-1.5 block w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-xs text-slate-800 focus:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-200"
                    >
                      <option value="">Choose a reviewed partner</option>
                      {partners.map((partner) => (
                        <option key={partner.variable} value={partner.variable}>
                          {partner.variable} (r {formatCorrelation(partner.correlation)})
                        </option>
                      ))}
                    </select>
                  </label>
                ) : null}

                {activeDecision ? (
                  <>
                    <label className="mt-3 block text-[11px] font-semibold text-slate-700">
                      Rationale
                      <textarea
                        value={activeDecision.rationale}
                        onChange={(event) =>
                          updateDecision(activeVariable, {
                            action: activeDecision.action,
                            combineWith: activeDecision.combineWith,
                            rationale: event.target.value,
                          })
                        }
                        rows={3}
                        placeholder="Record business context, redundancy evidence, or why the variable should remain."
                        className="mt-1.5 block w-full resize-y rounded-lg border border-slate-300 bg-white px-3 py-2 text-xs leading-5 text-slate-800 placeholder:text-slate-400 focus:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-200"
                      />
                    </label>
                    <div className="mt-2 flex items-center justify-between gap-3">
                      <span className="inline-flex items-center gap-1 text-[10px] font-medium text-emerald-700">
                        <CheckCircle2 size={12} aria-hidden="true" />
                        Saved for this dataset version
                      </span>
                      <button
                        type="button"
                        onClick={() => clearDecision(activeVariable)}
                        className="inline-flex items-center gap-1 text-[10px] font-semibold text-slate-600 underline decoration-slate-300 underline-offset-2 hover:text-slate-950 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500"
                      >
                        <RotateCcw size={11} aria-hidden="true" />
                        Clear record
                      </button>
                    </div>
                  </>
                ) : null}
              </div>
            )}
            <p className="mt-2 min-h-4 text-[10px] leading-4 text-rose-700" role="status">
              {storageMessage}
            </p>
          </section>

          {onSimulate ? (
            <>
              <div className="my-5 border-t border-slate-200" />
              <section
                aria-labelledby={`${titleId}-simulation`}
                data-testid="vif-simulator"
              >
                <div className="flex items-center gap-2">
                  <FlaskConical size={15} className="text-blue-700" aria-hidden="true" />
                  <h4
                    id={`${titleId}-simulation`}
                    className="text-sm font-semibold text-slate-950"
                  >
                    Temporary reduction simulator
                  </h4>
                </div>
                <p className="mt-1 text-[10px] leading-4 text-slate-500">
                  Runs an analytical preview without changing the dataset, approved
                  predictor manifest, or recorded decision.
                </p>
                <button
                  type="button"
                  onClick={runSimulation}
                  disabled={
                    !activeVariable || simulationState.status === "running"
                  }
                  className="mt-3 inline-flex w-full items-center justify-center gap-2 rounded-lg bg-blue-700 px-3 py-2.5 text-xs font-semibold text-white shadow-sm hover:bg-blue-800 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:bg-slate-300"
                >
                  <FlaskConical size={14} aria-hidden="true" />
                  {simulationState.status === "running"
                    ? `Simulating without ${simulationState.variable}…`
                    : activeVariable
                      ? `Simulate without ${activeVariable}`
                      : "Select a variable to simulate"}
                </button>
                <div className="mt-2 min-h-5 text-[10px] leading-4 text-slate-600" aria-live="polite">
                  {simulationState.status === "success" ? (
                    <span>
                      {simulationState.result?.summary ??
                        `Temporary simulation completed for ${simulationState.variable}.`}
                      {Number.isFinite(simulationState.result?.maximumVif) ? (
                        <> Maximum simulated VIF: {Number(simulationState.result?.maximumVif).toFixed(2)}.</>
                      ) : null}
                      {Number.isFinite(simulationState.result?.materialReviewCount) ? (
                        <> Material-review variables: {Number(simulationState.result?.materialReviewCount)}.</>
                      ) : null}
                    </span>
                  ) : simulationState.status === "error" ? (
                    <span className="text-rose-700">{simulationState.message}</span>
                  ) : null}
                </div>
              </section>
            </>
          ) : null}
        </aside>
      </div>

      <details className="group border-t border-slate-200" data-testid="vif-data-table">
        <summary className="flex cursor-pointer list-none items-center justify-between gap-3 px-4 py-3 text-xs font-semibold text-slate-800 hover:bg-slate-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-blue-500 sm:px-5">
          <span className="inline-flex items-center gap-2">
            <TableProperties size={15} className="text-blue-700" aria-hidden="true" />
            VIF analysis data table
          </span>
          <span className="font-normal text-slate-500">
            {preparedRows.length.toLocaleString()} variables · export includes decisions
          </span>
        </summary>
        <div className="max-h-[460px] overflow-auto border-t border-slate-200">
          <table className="w-full min-w-[860px] border-separate border-spacing-0 text-xs">
            <caption className="sr-only">
              VIF values from the disclosed bounded backend cohort, strongest correlation relationships, review zones, and
              locally captured analyst decisions
            </caption>
            <thead className="sticky top-0 z-10 bg-slate-950 text-white">
              <tr>
                {[
                  "Variable",
                  "VIF",
                  "Review zone",
                  "Strongest partner",
                  "Correlation",
                  "Decision",
                ].map((heading) => (
                  <th
                    key={heading}
                    scope="col"
                    className="whitespace-nowrap border-b border-slate-800 px-4 py-3 text-left text-[10px] font-semibold uppercase tracking-wide text-slate-200"
                  >
                    {heading}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {preparedRows.map((row) => {
                const strongest = strongestPartners(
                  row.featureName,
                  correlationColumns,
                  correlationMatrix,
                )[0];
                const decision = currentDecisions[row.featureName];
                return (
                  <tr
                    key={row.featureName}
                    className="even:bg-slate-50 hover:bg-blue-50"
                    data-selected={
                      normalizedName(activeVariable ?? "") ===
                      normalizedName(row.featureName)
                        ? "true"
                        : undefined
                    }
                  >
                    <th
                      scope="row"
                      className="border-b border-slate-100 px-4 py-3 text-left font-semibold text-slate-950"
                    >
                      <button
                        type="button"
                        onClick={() => onSelectVariable(row.featureName)}
                        className="max-w-64 truncate text-left hover:text-blue-700 hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500"
                        title={row.featureName}
                      >
                        {row.featureName}
                      </button>
                    </th>
                    <td className="border-b border-slate-100 px-4 py-3 font-semibold tabular-nums text-slate-800">
                      {displayVif(row)}
                    </td>
                    <td className="border-b border-slate-100 px-4 py-3">
                      <span
                        className={`inline-flex rounded-full border px-2 py-1 text-[10px] font-semibold ${ZONE_META[row.zone].badgeClass}`}
                      >
                        {ZONE_META[row.zone].label}
                      </span>
                    </td>
                    <td className="border-b border-slate-100 px-4 py-3 text-slate-700">
                      {strongest?.variable ?? "Not available"}
                    </td>
                    <td className="border-b border-slate-100 px-4 py-3 tabular-nums text-slate-700">
                      {strongest ? formatCorrelation(strongest.correlation) : "—"}
                    </td>
                    <td className="border-b border-slate-100 px-4 py-3 capitalize text-slate-700">
                      {decision?.action ?? "Not reviewed"}
                      {decision?.action === "combine" && decision.combineWith
                        ? ` with ${decision.combineWith}`
                        : ""}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </details>
    </section>
  );
}
