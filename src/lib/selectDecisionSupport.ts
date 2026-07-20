export type SelectionGuidance = {
  definition: string;
  useWhen: string;
  example: string;
  caution?: string;
  avoidWhen?: string;
  formulationEffect?: string;
  evidenceImplication?: string;
  downstreamImpact?: string;
};

export type SelectionGuidanceRequest = {
  label?: string;
  value: string;
  options?: string[];
};

function normalize(value: string) {
  return value.trim().toLowerCase().replace(/[\s/_-]+/g, " ");
}

const optionGuidance: Record<string, SelectionGuidance> = {};

function register(values: string[], guidance: SelectionGuidance) {
  values.forEach((value) => {
    optionGuidance[normalize(value)] = guidance;
  });
}

register(["Factorial experiment", "Factorial Experiment", "Full factorial"], {
  definition: "Tests combinations of two or more factors so ATLAS can estimate main effects and interactions in one design.",
  useWhen: "Use when the number of treatment combinations is manageable and combined factor effects matter.",
  example: "Test two pricing strategies across two contact channels to estimate pricing, channel, and pricing-by-channel effects.",
});
register(["Screening experiment", "Screening Experiment", "Fractional factorial"], {
  definition: "Uses an efficient design to identify the few influential factors from a larger candidate set.",
  useWhen: "Use early in development when many possible drivers exist and a full factorial would require too many runs.",
  example: "Screen eight offer, timing, and channel factors before carrying the strongest drivers into optimization.",
  caution: "Screening designs may alias interactions; document which effects cannot be separated.",
});
register(["Response surface", "Response Surface", "Response surface methodology"], {
  definition: "Fits curvature across continuous factor settings to locate a response optimum and characterize tradeoffs.",
  useWhen: "Use after important continuous factors are known and the objective is an optimal operating point rather than a simple comparison.",
  example: "Optimize discount percentage and contact frequency while keeping complaints below a guardrail.",
});
register(["Randomized block design", "Randomized block"], {
  definition: "Randomizes treatments within known blocks to remove a nuisance source of variation from the treatment comparison.",
  useWhen: "Use when branch, batch, risk tier, location, or time period affects the response but is not itself a treatment.",
  example: "Randomize all offer treatments separately within each credit-risk tier.",
});
register(["Taguchi design", "Taguchi Design", "Taguchi"], {
  definition: "A robust-design approach that chooses settings with strong average performance and low sensitivity to noise factors.",
  useWhen: "Use when consistency across hard-to-control operating conditions is as important as the average response.",
  example: "Choose a servicing process that remains effective across region, staffing level, and demand volatility.",
});

register(["Main Effects + Interaction Analysis"], {
  definition: "Estimates each factor's average effect and whether the effect of one factor changes at another factor's level.",
  useWhen: "Use for factorial designs when combinations may behave differently than individual factors.",
  example: "Determine whether personalized pricing performs differently for email versus SMS customers.",
});
register(["Main Effects Analysis"], {
  definition: "Estimates the average response change attributable to each factor while treating interactions as out of scope.",
  useWhen: "Use for additive designs, early screening, or when available sample cannot support reliable interaction estimates.",
  example: "Rank the independent effects of message, timing, and channel on activation.",
  caution: "Do not use when material interactions are plausible unless the limitation is documented.",
});
register(["Treatment Comparison"], {
  definition: "Compares prespecified treatment groups to determine which level or treatment produces the preferred response.",
  useWhen: "Use when the decision is a direct comparison among discrete alternatives rather than factor optimization.",
  example: "Compare three collections scripts against the current script using cure rate and complaint guardrails.",
});
register(["Process Optimization"], {
  definition: "Models factor-response relationships to identify settings that maximize or minimize a defined objective.",
  useWhen: "Use when controllable process settings are available and the desired output is a recommended operating point.",
  example: "Minimize handling time subject to quality and customer-experience constraints.",
});
register(["Robust Design (Taguchi)"], {
  definition: "Selects settings that deliver a strong response while reducing sensitivity to uncontrolled noise.",
  useWhen: "Use when operating conditions vary and the deployed treatment must remain stable.",
  example: "Optimize a fraud-review workflow across seasonal volume and analyst staffing scenarios.",
});
register(["Variance Reduction"], {
  definition: "Structures the design to explain or control nuisance variation and improve precision of treatment estimates.",
  useWhen: "Use when block, baseline, or repeated-measure information can materially reduce unexplained variance.",
  example: "Block by branch and include baseline conversion to improve precision of a process test.",
});
register(["Exploratory Screening"], {
  definition: "Prioritizes broad discovery of potentially important factors before confirmatory testing.",
  useWhen: "Use when the driver set is uncertain and the next decision is which factors deserve deeper study.",
  example: "Screen campaign attributes to select four factors for a confirmatory factorial experiment.",
});

register(["Controllable factors only"], {
  definition: "Includes only inputs that the business or process owner can deliberately set during the experiment and deployment.",
  useWhen: "Use when the goal is a clean operational prescription and nuisance variation is handled through randomization or blocking.",
  example: "Model offer amount, channel, and contact timing while blocking on region.",
});
register(["Factors plus covariates"], {
  definition: "Combines randomized or controlled factors with measured baseline variables that improve precision but are not manipulated.",
  useWhen: "Use when pre-treatment characteristics explain meaningful response variation.",
  example: "Estimate treatment effects while adjusting for prior balance, tenure, and baseline utilization.",
  caution: "Covariates must be measured before treatment to avoid post-treatment bias.",
});
register(["Screening design"], {
  definition: "Prioritizes a larger list of candidate factors using an economical run plan.",
  useWhen: "Use when the important drivers are not yet known and follow-up confirmation is planned.",
  example: "Screen ten underwriting workflow settings in a fractional factorial design.",
});
register(["Nested factors"], {
  definition: "Represents levels of one factor that occur only inside a level of another factor.",
  useWhen: "Use when organizational or process structure prevents all levels from crossing.",
  example: "Analysts are nested within review centers because each analyst works in only one center.",
});
register(["Mixture factors"], {
  definition: "Models component proportions whose values must sum to a fixed total.",
  useWhen: "Use for allocation, blend, portfolio, or budget-share experiments rather than independent factor settings.",
  example: "Optimize the share of spend across email, paid search, and direct mail subject to a 100% budget constraint.",
});

register(["Two-level coded design"], {
  definition: "Represents each factor at a low and high setting, commonly coded -1 and +1 for effect estimation.",
  useWhen: "Use for efficient screening and factorial designs where linear effects across the selected range are adequate.",
  example: "Code contact frequency as one versus three contacts per week.",
});
register(["Three-level design"], {
  definition: "Uses low, center, and high settings so curvature can be detected in addition to linear effects.",
  useWhen: "Use when a middle operating point is meaningful or a nonlinear response is plausible.",
  example: "Test discount levels of 0%, 5%, and 10%.",
});
register(["Ordinal levels"], {
  definition: "Represents ordered categories whose spacing is not assumed to be numerically equal.",
  useWhen: "Use when levels have a clear rank but differences between adjacent levels are not comparable.",
  example: "Code review intensity as low, standard, and enhanced.",
});
register(["Categorical levels"], {
  definition: "Treats named levels as distinct alternatives with no numeric ordering assumption.",
  useWhen: "Use for channels, vendors, scripts, or policies that are qualitatively different.",
  example: "Compare email, SMS, and outbound call as separate channel levels.",
});
register(["Continuous response-surface levels"], {
  definition: "Preserves numeric factor values for curvature, gradient, and optimum estimation.",
  useWhen: "Use with response-surface designs when settings can vary continuously inside approved bounds.",
  example: "Optimize APR discount between 0 and 250 basis points.",
});

register(["Linear programming", "Linear programming (LP)"], {
  definition: "Optimizes a linear objective subject to linear constraints with continuous decision variables.",
  useWhen: "Use for transparent allocation, capacity, funding, pricing, or scheduling decisions without indivisible choices.",
  example: "Allocate a marketing budget across channels to maximize expected contribution subject to spend and risk limits.",
  avoidWhen: "Avoid when decisions must be whole numbers, include activation choices, or contain nonlinear economics.",
  formulationEffect: "Creates a continuous linear objective and linear equality or inequality matrices for the LP solver.",
  evidenceImplication: "Retain objective coefficients, bounds, constraint matrices, solver tolerance, status, slack, and dual values.",
  downstreamImpact: "Enables deterministic scenario, sensitivity, allocation, and implementation outputs when the formulation is valid.",
});
register(["Mixed integer programming", "Mixed-integer programming", "Mixed-integer programming (MILP)"], {
  definition: "Optimizes linear decisions while enforcing integer or yes/no choices.",
  useWhen: "Use when branches, campaigns, facilities, contracts, or other decisions cannot be fractional.",
  example: "Select which campaigns to launch and how much budget to assign to each selected campaign.",
  avoidWhen: "Avoid when every quantity can remain continuous because integer search adds runtime and complexity.",
  formulationEffect: "Adds integer or binary domains and requires an integer-capable solver with optimality-gap controls.",
  evidenceImplication: "Retain variable domains, branch-and-bound status, gap, incumbent, runtime, and stopping criteria.",
  downstreamImpact: "Supports implementable yes/no and whole-unit decisions, but may increase solve time and sensitivity complexity.",
});
register(["Risk-adjusted nonlinear", "Nonlinear optimization"], {
  definition: "Optimizes an objective containing curvature, nonlinear penalties, or nonlinear constraints.",
  useWhen: "Use when marginal benefit, risk, or cost changes as the decision level increases.",
  example: "Maximize expected return while applying an increasing concentration-risk penalty.",
  avoidWhen: "Avoid when the business problem is fully linear or when no supported nonlinear runtime is configured.",
  formulationEffect: "Introduces nonlinear objective or constraint terms and changes solver, convergence, and local-optimum assumptions.",
  evidenceImplication: "Retain starting values, gradients where available, convergence criteria, solver status, and local-optimum limitations.",
  downstreamImpact: "Can represent richer economics but requires stronger validation, stress testing, and implementation controls.",
});
register(["Heuristic search"], {
  definition: "Searches a large or irregular solution space without guaranteeing a mathematically proven optimum.",
  useWhen: "Use when exact formulations are impractical and a reproducible high-quality solution is acceptable.",
  example: "Construct a complex workforce schedule with many conditional business rules.",
  caution: "Record seed, stopping rule, benchmark, and optimality limitations.",
});
register(["Simulation optimization"], {
  definition: "Evaluates candidate decisions through stochastic simulation and searches for the strongest expected outcome.",
  useWhen: "Use when uncertainty and system dynamics cannot be represented adequately by a closed-form objective.",
  example: "Optimize call-center staffing under simulated arrival and service-time distributions.",
});

register(["Dataset Library"], {
  definition: "Links a governed, versioned ATLAS dataset with schema, ownership, lineage, and full-artifact metadata.",
  useWhen: "Use when the source data already exists in ATLAS and reproducibility matters.",
  example: "Select the approved demand forecast input table and lock its current version for optimization.",
});
register(["File upload", "Upload file"], {
  definition: "Registers a local delimited file as a governed ATLAS dataset version before analysis.",
  useWhen: "Use when the source is available locally but is not yet in the Dataset Library.",
  example: "Upload a candidate-allocation table containing benefit, cost, lower bound, and upper bound columns.",
});
register(["SQL / warehouse", "SQL database"], {
  definition: "Uses a reproducible query or governed warehouse table as the analytical source.",
  useWhen: "Use when the system of record is a database and refreshable lineage is required.",
  example: "Load current account demand and capacity from an approved warehouse view.",
});

register(["Maximize"], {
  definition: "Chooses feasible decision values that make the objective as large as possible.",
  useWhen: "Use for profit, response, coverage, yield, recovery, or utility objectives.",
  example: "Maximize expected recoveries subject to contact capacity and complaint limits.",
  avoidWhen: "Avoid when the natural decision objective is cost, loss, delay, burden, or risk reduction.",
  formulationEffect: "The solver searches for the highest feasible objective value under the encoded bounds and constraints.",
  evidenceImplication: "Document the value unit, coefficient provenance, baseline, and any omitted harms or penalties.",
  downstreamImpact: "Higher coefficients receive more allocation unless capacity, policy, risk, or fairness rules constrain them.",
});
register(["Minimize"], {
  definition: "Chooses feasible decision values that make the objective as small as possible.",
  useWhen: "Use for cost, risk, loss, wait time, error, or resource consumption objectives.",
  example: "Minimize expected loss subject to approval-rate and fair-lending constraints.",
  avoidWhen: "Avoid when the objective represents benefit, recovery, coverage, yield, or contribution that should increase.",
  formulationEffect: "The solver searches for the lowest feasible objective value; minimum-action constraints are essential when zero is operationally useless.",
  evidenceImplication: "Document cost or risk units, coefficient provenance, baseline, and proof that service or demand requirements prevent a trivial zero solution.",
  downstreamImpact: "Allocation moves toward lower-cost decisions while all hard service, capacity, policy, and governance constraints remain enforced.",
});

function dynamicGuidance(labelText: string, value: string, optionCount: number): SelectionGuidance {
  const label = normalize(labelText);
  const selected = value.trim();
  const choiceCount = Math.max(0, optionCount - 1);
  if (/dataset|data source|source data/.test(label)) {
    return {
      definition: `"${selected}" is the data asset used for this step's calculations and evidence record.`,
      useWhen: "Use it only when the population, grain, time period, owner, and version match the decision you need to defend.",
      example: "For model development, use the governed training population rather than a dashboard extract or browser preview.",
      caution: "If the asset is only a preview or sample, downstream metrics should be labeled preview-only.",
    };
  }
  if (/version|snapshot/.test(label)) {
    return {
      definition: `"${selected}" fixes the analysis to one reproducible data or model version.`,
      useWhen: "Use the version tied to the approved analysis cutoff, source lineage, and decision record.",
      example: "Lock the version that was used for validation so a reviewer can reproduce the same results later.",
    };
  }
  if (/column|feature|field|variable|target|response|outcome|factor|segment/.test(label)) {
    return {
      definition: `"${selected}" is mapped to the ${labelText || "selected analytical role"}.`,
      useWhen: "Use the field whose business meaning, data type, timing, and grain match this role.",
      example: `Before choosing "${selected}", confirm it is measured before the decision point and is not target leakage.`,
      caution: "For regulated models, document why this field is appropriate and whether it may proxy for sensitive information.",
    };
  }
  if (/metric|measure|score|statistic/.test(label)) {
    return {
      definition: `"${selected}" is the measure used to rank, compare, or approve results on this page.`,
      useWhen: "Use the metric that matches the decision economics, class balance, error costs, and reviewer expectations.",
      example: "For rare-event classification, prefer PR-AUC, recall, lift, KS, and calibration over accuracy.",
      caution: "A single metric is rarely enough; pair it with stability, fairness, and operational guardrails.",
    };
  }
  if (/confidence|alpha|significance/.test(label)) {
    return {
      definition: `"${selected}" sets the statistical error tolerance for the decision.`,
      useWhen: "Choose it before looking at results and align it with materiality, customer impact, and multiple-testing policy.",
      example: "Use a stricter threshold when a false positive could trigger an unfair, costly, or customer-facing action.",
    };
  }
  if (/strategy|method|approach|policy|design|algorithm|model|solver/.test(label)) {
    return {
      definition: `"${selected}" controls how this step will transform, test, or model the data.`,
      useWhen: "Use it when the method's assumptions, runtime, interpretability, and governance burden fit the project.",
      example: `Compare "${selected}" with ${choiceCount} alternative${choiceCount === 1 ? "" : "s"} before locking the workflow evidence.`,
      caution: "If the method changes the modeling population, validation design, or interpretability, record the reason.",
    };
  }
  if (/frequency|window|period|date|time|horizon/.test(label)) {
    return {
      definition: `"${selected}" sets the time basis for this analysis.`,
      useWhen: "Use the time grain that matches how the decision is made and how outcomes mature.",
      example: "For credit outcomes, align the performance window to the policy definition, such as default within 90 days.",
      caution: "Changing the window can change target rates, leakage risk, and validation conclusions.",
    };
  }
  return {
    definition: `"${selected}" is the selected value for ${labelText || "this workflow control"}.`,
    useWhen: "Use it when it matches the project objective, data evidence, and the downstream decision being documented.",
    example: `Confirm "${selected}" only after checking nearby fields and page warnings for conflicts.`,
  };
  if (/dataset|data source|source data/.test(label)) {
    return {
      definition: `Selects “${value}” as the governed analytical data source for this control.`,
      useWhen: "Use the artifact whose population, grain, time window, ownership, and refresh policy match the decision being made.",
      example: "Choose the approved production-like dataset version, then verify row count and lineage before analysis.",
    };
  }
  if (/version|snapshot/.test(label)) {
    return {
      definition: `Locks the workflow to the “${value}” immutable data or model version.`,
      useWhen: "Use the version that corresponds to the documented analysis cutoff and approved source lineage.",
      example: "Select the version used for the review so results can be reproduced later.",
    };
  }
  if (/column|feature|field|variable|target|response|outcome|factor|segment/.test(label)) {
    return {
      definition: `Maps “${value}” to the ${labelText || "selected analytical role"}.`,
      useWhen: "Use the field whose business meaning, data type, timing, and grain match this role; confirm that it is not leakage or post-outcome data.",
      example: `Review the schema and lineage for “${value}” before confirming the mapping.`,
    };
  }
  if (/metric|measure|score|statistic/.test(label)) {
    return {
      definition: `Uses “${value}” as the selected ${labelText || "analytical measure"}.`,
      useWhen: "Use the measure that aligns with the business decision, model task, class balance, and cost of errors.",
      example: "Pair the primary decision metric with at least one stability, fairness, or operational guardrail.",
    };
  }
  if (/confidence|alpha|significance/.test(label)) {
    return {
      definition: `Applies “${value}” as the statistical confidence or error-control setting.`,
      useWhen: "Choose the threshold before reviewing results and align it with decision risk and multiple-testing policy.",
      example: "Use a stricter threshold when a false positive would create material customer or regulatory harm.",
    };
  }
  if (/strategy|method|approach|policy|design|algorithm|model|solver/.test(label)) {
    return {
      definition: `Configures ${labelText || "the analytical method"} as “${value}”.`,
      useWhen: "Select it only when its assumptions, data requirements, interpretability, and operational constraints match the project.",
      example: `Compare “${value}” with the other ${Math.max(0, optionCount - 1)} available choice${optionCount === 2 ? "" : "s"} and document why it fits.`,
    };
  }
  return {
    definition: `Sets ${labelText || "this workflow control"} to “${value}”.`,
    useWhen: "Use this choice when it matches the documented project objective, available evidence, and downstream decision requirements.",
    example: `Confirm “${value}” after reviewing the neighboring fields and any page-specific validation messages.`,
  };
}

export function getSelectionGuidance({ label = "Selection", value, options = [] }: SelectionGuidanceRequest): SelectionGuidance | null {
  if (!value.trim()) return null;
  return optionGuidance[normalize(value)] ?? dynamicGuidance(label, value, options.length);
}

export function hasCuratedSelectionGuidance(value: string) {
  return Boolean(optionGuidance[normalize(value)]);
}

export const experimentalDesignGuidanceValues = [
  "Factorial experiment",
  "Screening experiment",
  "Response surface",
  "Randomized block design",
  "Taguchi design",
  "Main Effects + Interaction Analysis",
  "Main Effects Analysis",
  "Treatment Comparison",
  "Process Optimization",
  "Robust Design (Taguchi)",
  "Variance Reduction",
  "Exploratory Screening",
  "Controllable factors only",
  "Factors plus covariates",
  "Screening design",
  "Nested factors",
  "Mixture factors",
  "Two-level coded design",
  "Three-level design",
  "Ordinal levels",
  "Categorical levels",
  "Continuous response-surface levels",
] as const;
