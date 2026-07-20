export type OptimizationTemplateId =
  | "generic_single_table"
  | "transportation_logistics"
  | "manual_formulation";

export type OptimizationInputRoleId =
  | "candidate_decision_table"
  | "constraint_table"
  | "baseline_table"
  | "scenario_table"
  | "route_costs"
  | "demand"
  | "supply_maximum"
  | "transport_capacity"
  | "inventory_or_handling_cost"
  | "approved_coefficients"
  | "approved_constraints";

export type OptimizationBundleKey =
  | "transportationCost"
  | "demand"
  | "supplyMax"
  | "transportCapacity"
  | "inventoryCost";

export type OptimizationInputRoleDefinition = {
  role_id: OptimizationInputRoleId;
  display_name: string;
  purpose: string;
  accepted_shapes: string[];
  detected_key_hints: string[];
  evidence_role: string;
  bundle_key?: OptimizationBundleKey;
};

export type OptimizationTemplateDefinition = {
  template_id: OptimizationTemplateId;
  display_name: string;
  short_description: string;
  applicable_use_cases: string[];
  required_input_roles: OptimizationInputRoleId[];
  optional_input_roles: OptimizationInputRoleId[];
  expected_decision_grain: string;
  default_objective_direction: "Maximize" | "Minimize";
  default_solver: string;
  generated_variable_type: string;
  generated_constraint_groups: string[];
  scenario_controls: string[];
  chart_outputs: string[];
  evidence_types: string[];
  guide_context: {
    task: string;
    target: string;
    objective: string;
    solver: string;
  };
};

export const OPTIMIZATION_INPUT_ROLE_REGISTRY: Record<OptimizationInputRoleId, OptimizationInputRoleDefinition> = {
  candidate_decision_table: {
    role_id: "candidate_decision_table",
    display_name: "Candidate decision table",
    purpose: "Defines one candidate decision per row with objective coefficients, bounds, costs, risk measures, and optional grouping fields.",
    accepted_shapes: ["One row per decision candidate", "Unique decision key plus numeric coefficient columns"],
    detected_key_hints: ["item_id", "decision_id", "candidate_id", "name"],
    evidence_role: "Candidate decision population and coefficient lineage",
  },
  constraint_table: {
    role_id: "constraint_table",
    display_name: "Constraint table",
    purpose: "Supplies approved limits, senses, right-hand sides, and coefficient references for executable business rules.",
    accepted_shapes: ["One row per constraint", "Long coefficient table keyed by constraint and decision"],
    detected_key_hints: ["constraint_id", "constraint_name", "sense", "rhs"],
    evidence_role: "Constraint source and policy lineage",
  },
  baseline_table: {
    role_id: "baseline_table",
    display_name: "Baseline table",
    purpose: "Provides the current or approved allocation used to measure improvement and implementation change.",
    accepted_shapes: ["One row per decision candidate", "Decision key plus current allocation or status"],
    detected_key_hints: ["decision_id", "baseline_value", "current_allocation"],
    evidence_role: "Current-state benchmark",
  },
  scenario_table: {
    role_id: "scenario_table",
    display_name: "Scenario table",
    purpose: "Provides governed stress assumptions and scenario-specific coefficient or capacity changes.",
    accepted_shapes: ["One row per scenario", "Long scenario-by-driver table"],
    detected_key_hints: ["scenario_id", "driver", "multiplier", "value"],
    evidence_role: "Scenario assumption lineage",
  },
  route_costs: {
    role_id: "route_costs",
    display_name: "Route cost matrix",
    purpose: "Defines the transportation cost for every valid supplier-to-customer route.",
    accepted_shapes: [
      "Wide matrix: customers as rows, suppliers as columns",
      "Long route table: supplier, customer, route_cost",
    ],
    detected_key_hints: ["supplier", "customer", "route_cost"],
    evidence_role: "Route transportation cost coefficient source",
    bundle_key: "transportationCost",
  },
  demand: {
    role_id: "demand",
    display_name: "Demand table",
    purpose: "Defines required quantity for each customer and generates demand-fulfillment constraints.",
    accepted_shapes: ["One row per customer", "Customer key plus nonnegative demand quantity"],
    detected_key_hints: ["customer", "destination", "demand", "quantity"],
    evidence_role: "Demand fulfillment constraint source",
    bundle_key: "demand",
  },
  supply_maximum: {
    role_id: "supply_maximum",
    display_name: "Supply maximum table",
    purpose: "Defines the maximum quantity available from each supplier and generates supplier limits.",
    accepted_shapes: ["One row per supplier", "Supplier key plus nonnegative supply maximum"],
    detected_key_hints: ["supplier", "source", "supply_maximum", "available"],
    evidence_role: "Supplier availability constraint source",
    bundle_key: "supplyMax",
  },
  transport_capacity: {
    role_id: "transport_capacity",
    display_name: "Transport capacity table",
    purpose: "Defines supplier-level shipping or throughput limits and generates transport-capacity constraints.",
    accepted_shapes: ["One row per supplier", "Supplier key plus nonnegative transport capacity"],
    detected_key_hints: ["supplier", "transport_capacity", "shipping_capacity", "throughput"],
    evidence_role: "Transportation capacity constraint source",
    bundle_key: "transportCapacity",
  },
  inventory_or_handling_cost: {
    role_id: "inventory_or_handling_cost",
    display_name: "Inventory or handling cost table",
    purpose: "Optionally adds a supplier-level inventory or handling coefficient to each route objective coefficient.",
    accepted_shapes: ["One row per supplier", "Supplier key plus inventory, handling, or holding cost"],
    detected_key_hints: ["supplier", "inventory_cost", "handling_cost", "holding_cost"],
    evidence_role: "Optional objective coefficient source",
    bundle_key: "inventoryCost",
  },
  approved_coefficients: {
    role_id: "approved_coefficients",
    display_name: "Approved coefficients",
    purpose: "Optionally imports reviewer-approved objective coefficients and variable bounds for a manual formulation.",
    accepted_shapes: ["One row per decision variable", "Variable name, coefficient, lower bound, and upper bound"],
    detected_key_hints: ["variable", "coefficient", "lower_bound", "upper_bound"],
    evidence_role: "Manual coefficient approval evidence",
  },
  approved_constraints: {
    role_id: "approved_constraints",
    display_name: "Approved constraints",
    purpose: "Optionally imports approved constraint coefficients, senses, and right-hand sides for a manual formulation.",
    accepted_shapes: ["One row per constraint", "Long constraint-by-variable coefficient table"],
    detected_key_hints: ["constraint", "variable", "coefficient", "sense", "rhs"],
    evidence_role: "Manual constraint approval evidence",
  },
};

export const OPTIMIZATION_TEMPLATE_REGISTRY: Record<OptimizationTemplateId, OptimizationTemplateDefinition> = {
  generic_single_table: {
    template_id: "generic_single_table",
    display_name: "Generic single-table optimizer",
    short_description: "Build a governed optimization from one candidate-decision table with optional constraint, baseline, and scenario inputs.",
    applicable_use_cases: ["Resource allocation", "Portfolio allocation", "Offer selection", "Capacity planning"],
    required_input_roles: ["candidate_decision_table"],
    optional_input_roles: ["constraint_table", "baseline_table", "scenario_table"],
    expected_decision_grain: "One row per candidate decision",
    default_objective_direction: "Maximize",
    default_solver: "Linear programming (LP)",
    generated_variable_type: "Continuous or integer candidate-level decision variable",
    generated_constraint_groups: ["Bounds", "Budget", "Capacity", "Service", "Policy"],
    scenario_controls: ["Objective coefficient", "Capacity", "Cost", "Risk"],
    chart_outputs: ["Objective contribution", "Allocation", "Constraint utilization", "Scenario comparison", "Sensitivity"],
    evidence_types: ["Input lineage", "Formulation", "Solver result", "Scenario analysis", "Validation", "Recommendation"],
    guide_context: {
      task: "Mathematical optimization",
      target: "Not applicable",
      objective: "User-defined objective",
      solver: "Linear or mixed-integer programming",
    },
  },
  transportation_logistics: {
    template_id: "transportation_logistics",
    display_name: "Transportation / Logistics Template",
    short_description: "Creates supplier-to-customer route variables, fulfillment constraints, supplier limits, transport-capacity limits, and logistics-specific diagnostics.",
    applicable_use_cases: ["Transportation planning", "Distribution allocation", "Supplier routing", "Logistics cost minimization"],
    required_input_roles: ["route_costs", "demand", "supply_maximum", "transport_capacity"],
    optional_input_roles: ["inventory_or_handling_cost"],
    expected_decision_grain: "One continuous shipment quantity per valid supplier-customer route",
    default_objective_direction: "Minimize",
    default_solver: "Linear programming (LP)",
    generated_variable_type: "Continuous nonnegative supplier-to-customer route quantity",
    generated_constraint_groups: ["Demand fulfillment", "Supplier supply maximum", "Transportation capacity", "Nonnegativity"],
    scenario_controls: ["Demand", "Supply", "Transport capacity", "Route cost", "Inventory or handling cost"],
    chart_outputs: ["Route cost matrix", "Allocation heatmap", "Demand versus capacity", "Supplier utilization", "Customer fulfillment", "Sensitivity tornado"],
    evidence_types: ["Input bundle", "Route formulation", "Solver allocation", "Scenario analysis", "Sensitivity", "Validation", "Decision package"],
    guide_context: {
      task: "Transportation / logistics optimization",
      target: "Not applicable",
      objective: "Minimize total logistics cost",
      solver: "Linear programming",
    },
  },
  manual_formulation: {
    template_id: "manual_formulation",
    display_name: "Manual formulation",
    short_description: "Enter approved variables, coefficients, and executable constraints when no analytical dataset is required.",
    applicable_use_cases: ["Policy-approved planning", "Small transparent models", "Reproduction of approved formulations"],
    required_input_roles: [],
    optional_input_roles: ["approved_coefficients", "approved_constraints"],
    expected_decision_grain: "Reviewer-defined decision variable",
    default_objective_direction: "Maximize",
    default_solver: "Linear programming (LP)",
    generated_variable_type: "Reviewer-defined continuous or integer decision variable",
    generated_constraint_groups: ["Reviewer-defined executable rules"],
    scenario_controls: ["Coefficient", "Bound", "Constraint right-hand side"],
    chart_outputs: ["Decision allocation", "Constraint utilization", "Scenario comparison", "Sensitivity"],
    evidence_types: ["Coefficient approval", "Constraint approval", "Solver result", "Validation", "Recommendation"],
    guide_context: {
      task: "Manual mathematical optimization",
      target: "Not applicable",
      objective: "User-defined objective",
      solver: "User-selected supported solver",
    },
  },
};

export const OPTIMIZATION_TEMPLATE_STORAGE_PREFIX = "atlas-optimization-template";
export const LEGACY_OPTIMIZATION_TEMPLATE_STORAGE_PREFIX = "atlas-optimization-input-strategy";

const LEGACY_TEMPLATE_IDS: Record<string, OptimizationTemplateId> = {
  generic: "generic_single_table",
  transportation: "transportation_logistics",
  manual: "manual_formulation",
};

export function normalizeOptimizationTemplateId(value: unknown): OptimizationTemplateId {
  const candidate = String(value ?? "").trim();
  if (candidate in OPTIMIZATION_TEMPLATE_REGISTRY) return candidate as OptimizationTemplateId;
  return LEGACY_TEMPLATE_IDS[candidate] ?? "generic_single_table";
}

export function getOptimizationTemplate(templateId: unknown): OptimizationTemplateDefinition {
  return OPTIMIZATION_TEMPLATE_REGISTRY[normalizeOptimizationTemplateId(templateId)];
}

export function getOptimizationTemplateInputRoles(templateId: unknown) {
  const template = getOptimizationTemplate(templateId);
  return [
    ...template.required_input_roles.map((roleId) => ({ ...OPTIMIZATION_INPUT_ROLE_REGISTRY[roleId], requirement: "required" as const })),
    ...template.optional_input_roles.map((roleId) => ({ ...OPTIMIZATION_INPUT_ROLE_REGISTRY[roleId], requirement: "optional" as const })),
  ];
}

export function readStoredOptimizationTemplateId(projectId: string): OptimizationTemplateId {
  if (typeof localStorage === "undefined") return "generic_single_table";
  const canonical = localStorage.getItem(`${OPTIMIZATION_TEMPLATE_STORAGE_PREFIX}:${projectId}`);
  const legacy = localStorage.getItem(`${LEGACY_OPTIMIZATION_TEMPLATE_STORAGE_PREFIX}:${projectId}`);
  const templateId = normalizeOptimizationTemplateId(canonical ?? legacy);
  if (canonical !== templateId) localStorage.setItem(`${OPTIMIZATION_TEMPLATE_STORAGE_PREFIX}:${projectId}`, templateId);
  return templateId;
}

export function storeOptimizationTemplateId(projectId: string, templateId: OptimizationTemplateId) {
  localStorage.setItem(`${OPTIMIZATION_TEMPLATE_STORAGE_PREFIX}:${projectId}`, templateId);
  localStorage.removeItem(`${LEGACY_OPTIMIZATION_TEMPLATE_STORAGE_PREFIX}:${projectId}`);
}
