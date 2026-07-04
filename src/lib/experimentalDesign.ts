export type ExperimentalFactor = {
  factorName: string;
  levels: string[];
};

export type SuggestedFactor = ExperimentalFactor & {
  type: "Categorical" | "Numeric" | "Ordinal";
};

export function cleanFactorName(value: string) {
  return value
    .replace(/^[-*\u2022\d.)\s]+/, "")
    .replace(/\s+/g, " ")
    .trim();
}

export function inferFactorType(factor: string): SuggestedFactor["type"] {
  if (/amount|price|pricing|rate|threshold|limit|dose|duration|time|score|percent|%/i.test(factor)) return "Numeric";
  if (/low|medium|high|tier|band|level|rank|priority/i.test(factor)) return "Ordinal";
  return "Categorical";
}

export function suggestedLevelsForFactor(factor: string, type: SuggestedFactor["type"]) {
  if (/pricing|price|rate/i.test(factor)) return ["Current", "Personalized"];
  if (/contact|channel/i.test(factor)) return ["Email", "SMS"];
  if (/offer|incentive|discount/i.test(factor)) return ["Standard", "Enhanced"];
  if (/message|copy|creative|script/i.test(factor)) return ["Control", "Variant"];
  if (/timing|time|schedule/i.test(factor)) return ["Current timing", "Optimized timing"];
  if (/threshold|limit|cutoff|score/i.test(factor)) return ["Current threshold", "Proposed threshold"];
  if (type === "Numeric") return ["Low", "High"];
  if (type === "Ordinal") return ["Low", "Medium", "High"];
  return ["Control", "Treatment"];
}

export function deriveSuggestedFactors(rawFactors: string): SuggestedFactor[] {
  return rawFactors
    .split(/\n|;|,/)
    .map(cleanFactorName)
    .filter(Boolean)
    .slice(0, 8)
    .map((factor) => {
      const type = inferFactorType(factor);
      return { factorName: factor, type, levels: suggestedLevelsForFactor(factor, type) };
    });
}

function splitLevelText(rawLevelText: string) {
  return rawLevelText
    .split(/,|\|/)
    .map(cleanFactorName)
    .filter(Boolean);
}

function compactFactorLevelLine(line: string): ExperimentalFactor | null {
  const separator = line.includes(":") ? /:(.*)/ : /[-=](.*)/;
  const [rawFactor, rawLevelText] = line.split(separator).filter(Boolean);
  const factorName = cleanFactorName(rawFactor ?? "");
  const levels = splitLevelText(rawLevelText ?? "");
  return factorName && levels.length ? { factorName, levels } : null;
}

function isLevelLine(rawLine: string) {
  return /^\s+/.test(rawLine) || /^\s*[-*\u2022]/.test(rawLine);
}

function cleanLevelName(value: string) {
  return value
    .replace(/^\s*[-*\u2022]\s*/, "")
    .replace(/^levels?\s*:?\s*/i, "")
    .replace(/\s+/g, " ")
    .trim();
}

function uniqueFactors(factors: ExperimentalFactor[]) {
  const seen = new Set<string>();
  const cleaned: ExperimentalFactor[] = [];
  factors.forEach((factor) => {
    const factorName = cleanFactorName(factor.factorName);
    const key = factorName.toLowerCase();
    const levels = factor.levels.map(cleanFactorName).filter(Boolean);
    if (!factorName || !levels.length || seen.has(key)) return;
    seen.add(key);
    cleaned.push({ factorName, levels });
  });
  return cleaned;
}

export function parseFactorHierarchy(rawLevels: string): ExperimentalFactor[] {
  const rawLines = rawLevels
    .split(/\r?\n|;/)
    .map((line) => line.replace(/\t/g, "  "))
    .filter((line) => line.trim());
  const parsed: ExperimentalFactor[] = [];

  for (let index = 0; index < rawLines.length; index += 1) {
    const rawLine = rawLines[index];
    const line = rawLine.trim();
    const factorMatch = line.match(/^factor\s*:?\s*(.*)$/i);

    if (factorMatch) {
      let factorName = cleanFactorName(factorMatch[1] ?? "");
      if (!factorName && index + 1 < rawLines.length) {
        index += 1;
        factorName = cleanFactorName(rawLines[index] ?? "");
      }

      const levels: string[] = [];
      for (let next = index + 1; next < rawLines.length; next += 1) {
        const nextRawLine = rawLines[next];
        const nextLine = nextRawLine.trim();
        if (/^factor\s*:?/i.test(nextLine)) break;

        const levelsMatch = nextLine.match(/^levels?\s*:?\s*(.*)$/i);
        if (levelsMatch) {
          const inlineLevels = splitLevelText(levelsMatch[1] ?? "");
          levels.push(...inlineLevels);
          index = next;
          continue;
        }

        if (!isLevelLine(nextRawLine)) break;
        levels.push(...splitLevelText(cleanLevelName(nextRawLine)));
        index = next;
      }

      parsed.push({ factorName, levels });
      continue;
    }

    const compact = compactFactorLevelLine(line);
    if (compact && !/^levels?\s*:?/i.test(line)) {
      parsed.push(compact);
      continue;
    }

    if (isLevelLine(rawLine) || /^levels?\s*:?/i.test(line)) continue;

    const factorName = cleanFactorName(line);
    const levels: string[] = [];
    for (let next = index + 1; next < rawLines.length; next += 1) {
      const nextRawLine = rawLines[next];
      const nextLine = nextRawLine.trim();
      if (/^factor\s*:?/i.test(nextLine)) break;

      const levelsMatch = nextLine.match(/^levels?\s*:?\s*(.*)$/i);
      if (levelsMatch) {
        levels.push(...splitLevelText(levelsMatch[1] ?? ""));
        index = next;
        continue;
      }

      if (!isLevelLine(nextRawLine)) break;
      levels.push(...splitLevelText(cleanLevelName(nextRawLine)));
      index = next;
    }

    parsed.push({ factorName, levels });
  }

  return uniqueFactors(parsed).slice(0, 6);
}

export const parseFactorLevels = parseFactorHierarchy;

export function cartesianProduct<T>(arrays: T[][]): T[][] {
  return arrays.reduce<T[][]>((acc, values) => acc.flatMap((row) => values.map((value) => [...row, value])), [[]]);
}

export function treatmentCellCount(factors: ExperimentalFactor[]) {
  return factors.reduce((result, factor) => result * Math.max(1, factor.levels.length), 1);
}

export function fullFactorialModelDf(factors: ExperimentalFactor[]) {
  return Math.max(0, treatmentCellCount(factors) - 1);
}

export function generateTreatmentMatrix(factors: ExperimentalFactor[]) {
  return cartesianProduct(factors.map((factor) => factor.levels)).map((combo, index) => {
    const row: Record<string, string> = { cell: `T${index + 1}` };
    factors.forEach((factor, factorIndex) => {
      row[factor.factorName] = combo[factorIndex];
    });
    return row;
  });
}

export function combinations<T>(values: T[], size: number): T[][] {
  if (size <= 0) return [[]];
  if (size > values.length) return [];
  if (size === 1) return values.map((value) => [value]);
  return values.flatMap((value, index) => combinations(values.slice(index + 1), size - 1).map((rest) => [value, ...rest]));
}

export function generateFullFactorialTerms(factors: ExperimentalFactor[]) {
  const factorNames = factors.map((factor) => factor.factorName);
  return Array.from({ length: factorNames.length }, (_, index) => index + 1).flatMap((order) =>
    combinations(factorNames, order).map((combo) => combo.join(" × "))
  );
}

export function levelPromotionWarnings(factors: ExperimentalFactor[]) {
  const factorNames = new Set(factors.map((factor) => factor.factorName.toLowerCase()));
  return factors
    .flatMap((factor) => factor.levels)
    .filter((level) => factorNames.has(level.toLowerCase()));
}

export type ExperimentalDesignNodeState = {
  objective?: string;
  inputs?: string;
  assumptions?: string;
  method?: string;
  metrics?: string[];
  validation?: string;
  risks?: string;
  decision?: string;
  rationale?: string;
  notes?: string;
  numeric?: Record<string, number>;
  simulationResults?: {
    meanPower?: number;
    wrongWinnerRate?: number;
    falseNegativeRate?: number;
    decisionStabilityScore?: number;
    recommendedAction?: string;
    inputs?: {
      treatmentCells?: number;
      samplePerCell?: number;
      totalSample?: number;
    };
  };
};

export type ExperimentalDesignKpi = {
  label: string;
  value: string;
  status: "good" | "warning" | "risk" | "neutral";
  confidence: number;
};

export type ExperimentalDesignAnalysis = {
  stepLabel: string;
  executiveInsight: string;
  kpis: ExperimentalDesignKpi[];
  visualizations: Array<{
    title: string;
    type: "matrix" | "bar" | "line" | "table" | "flow" | "scorecard";
    description: string;
  }>;
  interpretation: string;
  recommendedNextSteps: string[];
  warnings: string[];
  evidenceTables: Array<{
    title: string;
    headers: string[];
    rows: string[][];
  }>;
};

function numberValue(state: ExperimentalDesignNodeState | undefined, key: string, fallback: number) {
  const value = Number(state?.numeric?.[key]);
  return Number.isFinite(value) ? value : fallback;
}

function percent(value: number, digits = 1) {
  return `${(value * 100).toFixed(digits)}%`;
}

function normalCdf(value: number) {
  const sign = value < 0 ? -1 : 1;
  const x = Math.abs(value) / Math.sqrt(2);
  const t = 1 / (1 + 0.3275911 * x);
  const a1 = 0.254829592;
  const a2 = -0.284496736;
  const a3 = 1.421413741;
  const a4 = -1.453152027;
  const a5 = 1.061405429;
  const erf = 1 - (((((a5 * t + a4) * t) + a3) * t + a2) * t + a1) * t * Math.exp(-x * x);
  return 0.5 * (1 + sign * erf);
}

function normalQuantile(p: number) {
  const clamped = Math.max(0.000001, Math.min(0.999999, p));
  const a = [-39.6968302866538, 220.946098424521, -275.928510446969, 138.357751867269, -30.6647980661472, 2.50662827745924];
  const b = [-54.4760987982241, 161.585836858041, -155.698979859887, 66.8013118877197, -13.2806815528857];
  const c = [-0.00778489400243029, -0.322396458041136, -2.40075827716184, -2.54973253934373, 4.37466414146497, 2.93816398269878];
  const d = [0.00778469570904146, 0.32246712907004, 2.445134137143, 3.75440866190742];
  const plow = 0.02425;
  const phigh = 1 - plow;
  if (clamped < plow) {
    const q = Math.sqrt(-2 * Math.log(clamped));
    return (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1);
  }
  if (clamped > phigh) {
    const q = Math.sqrt(-2 * Math.log(1 - clamped));
    return -(((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1);
  }
  const q = clamped - 0.5;
  const r = q * q;
  return (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5]) * q / (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1);
}

function powerForPerCell(perCell: number, baseline: number, treatmentRate: number, alpha: number) {
  const n = Math.max(1, perCell);
  const pbar = (baseline + treatmentRate) / 2;
  const diff = Math.abs(treatmentRate - baseline);
  const zAlpha = normalQuantile(1 - alpha / 2);
  const pooledSe = Math.sqrt((2 * pbar * (1 - pbar)) / n);
  const alternativeSe = Math.sqrt((baseline * (1 - baseline) + treatmentRate * (1 - treatmentRate)) / n);
  return normalCdf((diff - zAlpha * pooledSe) / Math.max(1e-9, alternativeSe));
}

export function experimentalSampleSizePlan(state: ExperimentalDesignNodeState | undefined, fallbackCells = 1) {
  const factorCount = Math.max(1, Math.round(numberValue(state, "factorCount", 2)));
  const averageLevels = Math.max(2, numberValue(state, "averageLevels", 2));
  const treatmentCells = Math.max(1, Math.round(fallbackCells || averageLevels ** factorCount));
  const alpha = Math.max(0.001, Math.min(0.5, numberValue(state, "alpha", 5) / 100));
  const desiredPower = Math.max(0.5, Math.min(0.99, numberValue(state, "power", 80) / 100));
  const baseline = Math.max(0.0001, Math.min(0.9999, numberValue(state, "baselineRate", 10) / 100));
  const minimumDetectableLift = Math.max(0.0001, numberValue(state, "expectedLift", 5) / 100);
  const treatmentRate = Math.max(0.0001, Math.min(0.9999, baseline * (1 + minimumDetectableLift)));
  const absoluteEffect = Math.max(0.0001, Math.abs(treatmentRate - baseline));
  const zAlpha = normalQuantile(1 - alpha / 2);
  const zPower = normalQuantile(desiredPower);
  const pooled = (baseline + treatmentRate) / 2;
  const numerator =
    zAlpha * Math.sqrt(2 * pooled * (1 - pooled)) +
    zPower * Math.sqrt(baseline * (1 - baseline) + treatmentRate * (1 - treatmentRate));
  const perCell = Math.ceil((numerator * numerator) / (absoluteEffect * absoluteEffect));
  const total = perCell * treatmentCells;
  const available = Math.max(0, numberValue(state, "sampleSize", 0));
  const plannedTotal = available > 0 ? available : total;
  const plannedPerCell = Math.floor(plannedTotal / treatmentCells);
  const expectedPower = powerForPerCell(perCell, baseline, treatmentRate, alpha);
  return {
    factorCount,
    averageLevels,
    treatmentCells,
    alpha,
    desiredPower,
    baseline,
    treatmentRate,
    minimumDetectableLift,
    absoluteEffect,
    perCell,
    total,
    plannedPerCell,
    plannedTotal,
    available,
    expectedPower,
    adequatelyPowered: available >= total,
  };
}

function analysisFactors(nodeStates: Record<string, ExperimentalDesignNodeState>) {
  const levels = parseFactorHierarchy(nodeStates.Levels?.objective ?? "");
  if (levels.length) return levels;
  const suggested = deriveSuggestedFactors(nodeStates.Factors?.objective ?? "");
  if (suggested.length) return suggested.map(({ factorName, levels }) => ({ factorName, levels }));
  return [];
}

function designLabel(factors: ExperimentalFactor[]) {
  if (!factors.length) return "Design not specified";
  const balanced = new Set(factors.map((factor) => factor.levels.length)).size === 1;
  if (factors.length === 1) return `${factors[0].levels.length}-level single-factor design`;
  return `${balanced ? "Balanced" : "Unbalanced"} ${factors.map((factor) => factor.levels.length).join(" x ")} factorial`;
}

function defaultVisuals(stepLabel: string): ExperimentalDesignAnalysis["visualizations"] {
  const lookup: Record<string, ExperimentalDesignAnalysis["visualizations"]> = {
    "Project Context": [
      { title: "Project readiness gauge", type: "scorecard", description: "Summarizes context completeness, governance requirements, and deployment readiness." },
      { title: "Business objective hierarchy", type: "flow", description: "Connects business objective, target definition, population, and decision use." },
    ],
    "Research Question": [
      { title: "Hypothesis diagram", type: "flow", description: "Maps independent variables, dependent variable, assumptions, and possible confounders." },
    ],
    Factors: [
      { title: "Factor relationship diagram", type: "table", description: "Classifies controllable factors, covariates, and expected influence." },
      { title: "Treatment count preview", type: "scorecard", description: "Shows expected treatment-cell count and design complexity." },
    ],
    Levels: [
      { title: "Treatment matrix", type: "matrix", description: "Displays the factorial treatment combinations generated from parent factors and nested levels." },
    ],
    Blocking: [
      { title: "Variance reduction chart", type: "bar", description: "Shows expected benefit of blocking versus added operational complexity." },
    ],
    Randomization: [
      { title: "Assignment flow diagram", type: "flow", description: "Documents randomization sequence, assignment QA, and audit file creation." },
    ],
    "Sample Size": [
      { title: "Power curve", type: "line", description: "Shows expected power as per-cell sample size changes." },
      { title: "Cost vs power", type: "bar", description: "Compares sample investment against detectable lift and target confidence." },
    ],
    "Monte Carlo Simulation": [
      { title: "Power distribution", type: "bar", description: "Shows simulated power across stressed experiment assumptions." },
      { title: "Risk tornado chart", type: "bar", description: "Ranks assumptions that most influence launch readiness." },
    ],
    ANOVA: [
      { title: "ANOVA table", type: "table", description: "Shows generated model terms, degrees of freedom, and interpretation sequence." },
      { title: "Main effects and interactions", type: "bar", description: "Ranks expected factor and interaction contributions." },
    ],
    "Interaction Effects": [
      { title: "Interaction heatmap", type: "matrix", description: "Highlights treatment combinations with practical or statistical interaction signal." },
    ],
    Optimization: [
      { title: "Response surface", type: "matrix", description: "Shows the predicted optimum and nearby sensitivity." },
    ],
    Documentation: [
      { title: "Governance artifact center", type: "scorecard", description: "Summarizes report readiness, evidence completeness, and downloadable artifacts." },
    ],
  };
  return lookup[stepLabel] ?? [{ title: "Evidence scorecard", type: "scorecard", description: "Summarizes readiness, risks, decisions, and required governance evidence." }];
}

export function buildExperimentalDesignAnalysis(input: {
  stepLabel: string;
  currentState?: ExperimentalDesignNodeState;
  nodeStates?: Record<string, ExperimentalDesignNodeState>;
}): ExperimentalDesignAnalysis {
  const nodeStates = { ...(input.nodeStates ?? {}), [input.stepLabel]: input.currentState ?? input.nodeStates?.[input.stepLabel] ?? {} };
  const current = input.currentState ?? nodeStates[input.stepLabel] ?? {};
  const factors = analysisFactors(nodeStates);
  const cells = factors.length ? treatmentCellCount(factors) : Math.max(1, Math.round(numberValue(current, "averageLevels", 2) ** numberValue(current, "factorCount", 2)));
  const samplePlan = experimentalSampleSizePlan(nodeStates["Sample Size"] ?? current, cells);
  const simulation = nodeStates["Monte Carlo Simulation"]?.simulationResults ?? current.simulationResults;
  const anovaTerms = factors.length ? generateFullFactorialTerms(factors) : [];
  const evidenceFields = [current.objective, current.inputs, current.assumptions, current.validation, current.decision, current.rationale].filter((value) => String(value ?? "").trim()).length;
  const warnings: string[] = [];

  if (!factors.length && ["Factors", "Levels", "Sample Size", "ANOVA", "Monte Carlo Simulation"].includes(input.stepLabel)) {
    warnings.push("Factors and levels are not fully defined, so treatment cells and ANOVA terms are using fallback assumptions.");
  }
  if (input.stepLabel === "Sample Size" && !samplePlan.adequatelyPowered && samplePlan.available > 0) {
    warnings.push("Available population is below the estimated total sample required for target power.");
  }
  if (simulation?.recommendedAction && /Weak|Redesign/i.test(simulation.recommendedAction)) {
    warnings.push("Monte Carlo validation does not yet support launch readiness under current assumptions.");
  }

  const kpis: ExperimentalDesignKpi[] = [
    { label: "Factors", value: factors.length ? String(factors.length) : "-", status: factors.length ? "good" : "warning", confidence: factors.length ? 0.9 : 0.45 },
    { label: "Treatment Cells", value: cells.toLocaleString(), status: cells <= 16 ? "good" : cells <= 64 ? "warning" : "risk", confidence: factors.length ? 0.88 : 0.5 },
    { label: "Sample Per Cell", value: samplePlan.plannedPerCell.toLocaleString(), status: samplePlan.plannedPerCell >= samplePlan.perCell ? "good" : "risk", confidence: samplePlan.available ? 0.86 : 0.62 },
    { label: "Total Sample", value: samplePlan.plannedTotal.toLocaleString(), status: samplePlan.adequatelyPowered ? "good" : samplePlan.available ? "risk" : "warning", confidence: samplePlan.available ? 0.82 : 0.62 },
    { label: "Power", value: percent(samplePlan.expectedPower), status: samplePlan.expectedPower >= 0.8 ? "good" : "warning", confidence: 0.75 },
    { label: "Evidence", value: `${evidenceFields}/6`, status: evidenceFields >= 4 ? "good" : "warning", confidence: 0.7 },
  ];

  if (simulation) {
    kpis.push(
      { label: "MC Readiness", value: simulation.recommendedAction ?? "Not run", status: /Strong|Adequate/i.test(simulation.recommendedAction ?? "") ? "good" : "risk", confidence: 0.86 },
      { label: "Wrong Winner", value: percent(Number(simulation.wrongWinnerRate ?? 0)), status: Number(simulation.wrongWinnerRate ?? 1) <= 0.1 ? "good" : "risk", confidence: 0.84 }
    );
  }

  const defaultInsight = factors.length
    ? `${factors.map((factor) => factor.factorName).join(" and ")} define ${cells.toLocaleString()} treatment combination${cells === 1 ? "" : "s"}. The current sample-size plan requires ${samplePlan.perCell.toLocaleString()} observations per cell and ${samplePlan.total.toLocaleString()} total observations. ${samplePlan.adequatelyPowered ? "The available population appears sufficient for the target power." : "The available population should be reviewed before launch approval."}`
    : `${input.stepLabel} is ready for structured experimental evidence. Define factors, levels, sample assumptions, and decision criteria so ATLAS can generate synchronized analysis and documentation.`;
  const insightByStep: Record<string, string> = {
    "Project Context": `The project context defines the business purpose, target population, intended use, and governance expectations. ${current.decision ? "A decision has been drafted for this stage." : "Approval language should be documented before research design begins."}`,
    "Research Question": `The research question should translate the business objective into a measurable hypothesis with response variable, success metric, guardrails, and practical decision threshold. ${current.method ? `Current analysis objective: ${current.method}.` : "Select the analysis objective before factor planning."}`,
    Factors: factors.length
      ? `${factors.length} controllable factor${factors.length === 1 ? "" : "s"} are defined. ATLAS estimates ${cells.toLocaleString()} treatment cell${cells === 1 ? "" : "s"} and recommends confirming which variables are randomized factors versus measured covariates.`
      : "No controllable factors have been parsed yet. Enter candidate factors so ATLAS can classify them and estimate design complexity.",
    Levels: factors.length
      ? `The entered factor hierarchy produces ${cells.toLocaleString()} treatment cell${cells === 1 ? "" : "s"} using only parent factor names as treatment-matrix columns.`
      : "Factor levels are not yet structured. Enter nested levels under each parent factor to generate the treatment matrix.",
    Blocking: current.objective
      ? `Potential nuisance variables have been documented for blocking review. ATLAS recommends using blocking only when the expected variance reduction is worth the operational complexity.`
      : "No nuisance variables are entered. Simple randomization remains appropriate unless a known response driver should be controlled.",
    Randomization: `Randomization should preserve treatment balance across ${cells.toLocaleString()} treatment cell${cells === 1 ? "" : "s"} and produce an auditable assignment file before launch.`,
    "Sample Size": `The current design allocates ${samplePlan.plannedPerCell.toLocaleString()} observations per treatment cell from ${samplePlan.plannedTotal.toLocaleString()} total observations. The estimated minimum requirement is ${samplePlan.perCell.toLocaleString()} per cell and ${samplePlan.total.toLocaleString()} total. ${samplePlan.adequatelyPowered ? "The available population appears sufficient." : "The available population or minimum detectable effect should be reviewed."}`,
    "Monte Carlo Simulation": simulation
      ? `Monte Carlo validation is ${simulation.recommendedAction ?? "not classified"} with mean power ${percent(Number(simulation.meanPower ?? 0))} and wrong-winner risk ${percent(Number(simulation.wrongWinnerRate ?? 0))}.`
      : "Monte Carlo simulation has not been run from the current assumptions. Run the simulation to quantify power distribution, wrong-winner risk, and launch readiness.",
    "Experiment Run Plan": simulation
      ? `The launch plan is anchored to Monte Carlo evidence: readiness ${simulation.recommendedAction ?? "not classified"}, mean power ${percent(Number(simulation.meanPower ?? 0))}, and wrong-winner risk ${percent(Number(simulation.wrongWinnerRate ?? 0))}. Execution controls should address any remaining simulation risk before launch.`
      : "Run Monte Carlo before finalizing the execution plan. The run plan should convert simulation evidence into operational sequence, QA checks, assignment controls, monitoring cadence, and stopping rules.",
    ANOVA: anovaTerms.length
      ? `ATLAS generated ${anovaTerms.length} ANOVA term${anovaTerms.length === 1 ? "" : "s"} from the factor hierarchy. Model degrees of freedom equal ${fullFactorialModelDf(factors)} for the full factorial design.`
      : "ANOVA terms are waiting for factor hierarchy inputs. Define factors and levels before interpreting model effects.",
    "Interaction Effects": factors.length > 1
      ? `The design supports interaction review across ${factors.length} factors. Interactions should be interpreted only when statistically reliable and practically meaningful.`
      : "Interaction review requires at least two experimental factors.",
    Optimization: "Optimization should recommend the best feasible treatment combination while respecting performance, customer impact, operational, and compliance guardrails.",
    Documentation: "The documentation page should package completed analysis evidence into executive, notebook, JSON, governance, and validation artifacts.",
  };
  const insight = insightByStep[input.stepLabel] ?? defaultInsight;

  const interpretation =
    input.stepLabel === "ANOVA" && anovaTerms.length
      ? `ATLAS generated ${anovaTerms.length} model term${anovaTerms.length === 1 ? "" : "s"} from the factor hierarchy. Interpret main effects first, then interaction terms that are both statistically and operationally meaningful.`
      : ["Monte Carlo Simulation", "Experiment Run Plan"].includes(input.stepLabel) && simulation
        ? `Monte Carlo validation is ${simulation.recommendedAction ?? "not classified"} with mean power ${percent(Number(simulation.meanPower ?? 0))} and wrong-winner risk ${percent(Number(simulation.wrongWinnerRate ?? 0))}.`
        : `ATLAS is using the current experimental design inputs to produce the live workflow view and report-ready evidence from the same analysis object.`;

  const evidenceTables: ExperimentalDesignAnalysis["evidenceTables"] = [];
  if (factors.length) {
    evidenceTables.push({
      title: "Factor Hierarchy",
      headers: ["Factor", "Levels"],
      rows: factors.map((factor) => [factor.factorName, factor.levels.join(", ")]),
    });
  }
  if (input.stepLabel === "Levels" && factors.length) {
    const matrix = generateTreatmentMatrix(factors).slice(0, 64);
    evidenceTables.push({
      title: "Treatment Matrix",
      headers: ["Cell", ...factors.map((factor) => factor.factorName)],
      rows: matrix.map((row) => ["cell", ...factors.map((factor) => factor.factorName)].map((key) => row[key] ?? "-")),
    });
  }
  if (input.stepLabel === "Sample Size") {
    evidenceTables.push({
      title: "Power Planning Summary",
      headers: ["Measure", "Value"],
      rows: [
        ["Treatment cells", String(samplePlan.treatmentCells)],
        ["Planned sample per cell", samplePlan.plannedPerCell.toLocaleString()],
        ["Planned total sample", samplePlan.plannedTotal.toLocaleString()],
        ["Required per cell", samplePlan.perCell.toLocaleString()],
        ["Required total sample", samplePlan.total.toLocaleString()],
        ["Available population", samplePlan.available ? samplePlan.available.toLocaleString() : "Not entered"],
        ["Expected power", percent(samplePlan.expectedPower)],
        ["Status", samplePlan.adequatelyPowered ? "Adequately powered" : "Population shortfall"],
      ],
    });
  }
  if (input.stepLabel === "ANOVA" && anovaTerms.length) {
    evidenceTables.push({
      title: "Generated ANOVA Terms",
      headers: ["Term", "Interpretation"],
      rows: anovaTerms.map((term) => [term, term.includes("Ã—") ? "Interaction effect" : "Main effect"]),
    });
  }

  return {
    stepLabel: input.stepLabel,
    executiveInsight: insight,
    kpis,
    visualizations: defaultVisuals(input.stepLabel),
    interpretation,
    recommendedNextSteps: warnings.length
      ? ["Resolve warnings before final approval.", "Save rationale for any accepted limitations.", "Regenerate governance artifacts after changes."]
      : ["Review generated visuals and supporting evidence.", "Confirm decision and rationale.", "Save the node evidence for governance documentation."],
    warnings,
    evidenceTables,
  };
}
