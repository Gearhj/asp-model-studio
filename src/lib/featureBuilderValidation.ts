import type { FeatureDraft, FeatureOrigin } from "./featureManifest";

const FEATURE_NAME_PATTERN = /^[A-Za-z_][A-Za-z0-9_]*$/;
const DEFAULT_RATIONALE =
  "Reviewer-defined deterministic feature created in the governed builder.";

export type FeatureBuilderSource = {
  name: string;
  dataType: string;
  eligible?: boolean;
  exclusionReason?: string;
  unit?: string;
  minimum?: number | null;
  maximum?: number | null;
  governedDate?: boolean;
};

export type BuilderMessageMetadata = Record<
  string,
  string | number | boolean | null
>;

export type BuilderValidationMessage = {
  code: string;
  severity: "error" | "warning";
  message: string;
  field?: string;
  metadata?: BuilderMessageMetadata;
};

export type BuilderValidationResult = {
  ok: boolean;
  definition: FeatureDraft | null;
  errors: BuilderValidationMessage[];
  warnings: BuilderValidationMessage[];
};

type CommonBuilderInput = {
  name: string;
  displayName?: string;
  rationale?: string;
  selected?: boolean;
  exclusionReason?: string;
  existingFeatureNames?: readonly string[];
  sourceCatalog: readonly FeatureBuilderSource[];
};

export type InteractionBuilderInput = CommonBuilderInput & {
  left: string;
  right: string;
};

export type NumericBinBuilderInput = CommonBuilderInput & {
  source: string;
  cutPoints: readonly number[];
  labels: readonly string[];
  specialValueLabel: string;
  missingValueLabel?: string;
};

export type RuleOperator =
  | "equals"
  | "contains"
  | "greater_than"
  | "greater_than_or_equal"
  | "less_than"
  | "less_than_or_equal"
  | "is_missing";

export type RuleCategoryBuilderInput = CommonBuilderInput & {
  source: string;
  operator: RuleOperator;
  value?: string | number;
  matchedLabel: string;
  elseLabel: string;
  specialValueLabel: string;
};

export type PolynomialBuilderInput = CommonBuilderInput & {
  source: string;
  degree: 2 | 3 | number;
};

export type ArithmeticOperation = "add" | "subtract" | "multiply" | "divide";

export type ArithmeticDomainEvidence = {
  leftGreaterThanOrEqualRight?: boolean;
  rightNonZero?: boolean;
  note?: string;
};

export type ArithmeticBuilderInput = CommonBuilderInput & {
  left: string;
  right: string;
  operation: ArithmeticOperation;
  requireNonnegativeResult?: boolean;
  domainEvidence?: ArithmeticDomainEvidence;
};

export type DateDerivedComponent = "year" | "month" | "quarter" | "day_of_week";

export type DateDerivedBuilderInput = CommonBuilderInput & {
  source: string;
  component: DateDerivedComponent;
};

export type DateDerivedAvailability = {
  available: boolean;
  dateSources: string[];
  reason: string;
};

type CommonValidation = {
  name: string;
  displayName: string;
  rationale: string;
  selected: boolean;
  exclusionReason: string;
  errors: BuilderValidationMessage[];
};

function error(
  code: string,
  message: string,
  field?: string,
  metadata?: BuilderMessageMetadata,
): BuilderValidationMessage {
  return { code, severity: "error", message, field, metadata };
}

function warning(
  code: string,
  message: string,
  field?: string,
  metadata?: BuilderMessageMetadata,
): BuilderValidationMessage {
  return { code, severity: "warning", message, field, metadata };
}

function validateCommon(input: CommonBuilderInput): CommonValidation {
  const name = input.name.trim();
  const displayName = input.displayName?.trim() || name;
  const rationale = input.rationale?.trim() || DEFAULT_RATIONALE;
  const selected = input.selected !== false;
  const exclusionReason = input.exclusionReason?.trim() || "";
  const errors: BuilderValidationMessage[] = [];

  if (!name) {
    errors.push(error("feature_name_required", "Enter a feature name.", "name"));
  } else if (!FEATURE_NAME_PATTERN.test(name)) {
    errors.push(
      error(
        "feature_name_invalid",
        "Feature names must start with a letter or underscore and contain only letters, numbers, or underscores.",
        "name",
      ),
    );
  }

  if (
    name &&
    (input.existingFeatureNames ?? []).some(
      (existingName) => existingName.trim().toLocaleLowerCase() === name.toLocaleLowerCase(),
    )
  ) {
    errors.push(
      error(
        "feature_name_duplicate",
        `Feature name '${name}' already exists.`,
        "name",
      ),
    );
  }

  if (!selected && !exclusionReason) {
    errors.push(
      error(
        "exclusion_reason_required",
        "An excluded planned feature requires a reason.",
        "exclusionReason",
      ),
    );
  }

  return {
    name,
    displayName,
    rationale,
    selected,
    exclusionReason: selected ? "" : exclusionReason,
    errors,
  };
}

function findSource(
  sourceCatalog: readonly FeatureBuilderSource[],
  name: string,
): FeatureBuilderSource | undefined {
  const normalized = name.trim().toLocaleLowerCase();
  return sourceCatalog.find(
    (source) => source.name.trim().toLocaleLowerCase() === normalized,
  );
}

function isNumericDataType(dataType: string): boolean {
  return /(?:^|\b)(?:u?int\d*|float\d*|double|decimal|numeric|number)(?:\b|$)/i.test(
    dataType.trim(),
  );
}

function isDateDataType(dataType: string): boolean {
  return /date|datetime|timestamp/i.test(dataType.trim());
}

export function inferFeatureUnit(name: string): string {
  const normalized = name.trim().toLocaleLowerCase();
  if (normalized.startsWith("percent")) return "percentage";
  if (normalized.includes("fraction")) return "ratio";
  if (normalized.startsWith("num") || normalized.includes("trade_count")) {
    return "count";
  }
  if (
    normalized.startsWith("msince") ||
    normalized.includes("month") ||
    normalized === "averageminfile"
  ) {
    return "months";
  }
  if (normalized.startsWith("maxdelq")) return "ordinal_code";
  if (normalized.includes("estimate") || normalized.includes("score")) {
    return "score";
  }
  return "unknown";
}

function validateSource(
  sourceCatalog: readonly FeatureBuilderSource[],
  sourceName: string,
  field: string,
  expectedType: "numeric" | "date" | "any",
): { source?: FeatureBuilderSource; errors: BuilderValidationMessage[] } {
  const normalizedName = sourceName.trim();
  if (!normalizedName) {
    return {
      errors: [error("source_required", "Select a source predictor.", field)],
    };
  }

  const source = findSource(sourceCatalog, normalizedName);
  if (!source) {
    return {
      errors: [
        error(
          "source_unavailable",
          `Source '${normalizedName}' is not in the governed builder inventory.`,
          field,
          { source: normalizedName },
        ),
      ],
    };
  }

  if (source.eligible === false) {
    return {
      source,
      errors: [
        error(
          "source_excluded",
          source.exclusionReason?.trim() ||
            `Source '${source.name}' is excluded by predictor governance.`,
          field,
          { source: source.name },
        ),
      ],
    };
  }

  if (expectedType === "numeric" && !isNumericDataType(source.dataType)) {
    return {
      source,
      errors: [
        error(
          "numeric_source_required",
          `Source '${source.name}' must be numeric.`,
          field,
          { source: source.name, dataType: source.dataType },
        ),
      ],
    };
  }

  if (
    expectedType === "date" &&
    (!isDateDataType(source.dataType) || source.governedDate === false)
  ) {
    return {
      source,
      errors: [
        error(
          "governed_date_source_required",
          `Source '${source.name}' is not a governed calendar date predictor. Numeric durations cannot be used as dates.`,
          field,
          { source: source.name, dataType: source.dataType },
        ),
      ],
    };
  }

  return { source, errors: [] };
}

function result(
  common: CommonValidation,
  origin: FeatureOrigin,
  sourceFeatures: string[],
  formulaOrRule: string,
  outputDatatype: string,
  config: Record<string, unknown>,
  builderErrors: BuilderValidationMessage[] = [],
  warnings: BuilderValidationMessage[] = [],
): BuilderValidationResult {
  const errors = [...common.errors, ...builderErrors];
  if (errors.length) {
    return { ok: false, definition: null, errors, warnings };
  }

  return {
    ok: true,
    definition: {
      feature_name: common.name,
      display_name: common.displayName,
      origin,
      source_features: [...sourceFeatures],
      transformation_type: origin,
      formula_or_rule: formulaOrRule,
      output_datatype: outputDatatype,
      selected: common.selected,
      exclusion_reason: common.exclusionReason,
      user_rationale: common.rationale,
      config: { ...config },
    },
    errors: [],
    warnings,
  };
}

function cleanLabel(value: string): string {
  return value.trim();
}

function validateDistinctLabels(
  labels: readonly string[],
  field: string,
): BuilderValidationMessage[] {
  const cleaned = labels.map(cleanLabel);
  const errors: BuilderValidationMessage[] = [];
  if (cleaned.some((label) => !label)) {
    errors.push(error("label_required", "Labels cannot be blank.", field));
  }
  if (new Set(cleaned.map((label) => label.toLocaleLowerCase())).size !== cleaned.length) {
    errors.push(error("labels_must_be_unique", "Labels must be unique.", field));
  }
  return errors;
}

export function buildInteractionFeature(
  input: InteractionBuilderInput,
): BuilderValidationResult {
  const common = validateCommon(input);
  const left = validateSource(input.sourceCatalog, input.left, "left", "numeric");
  const right = validateSource(input.sourceCatalog, input.right, "right", "numeric");
  const errors = [...left.errors, ...right.errors];
  if (
    input.left.trim() &&
    input.right.trim() &&
    input.left.trim().toLocaleLowerCase() === input.right.trim().toLocaleLowerCase()
  ) {
    errors.push(
      error(
        "interaction_sources_must_differ",
        "Interaction features require two different numeric predictors.",
        "right",
      ),
    );
  }

  const leftName = left.source?.name ?? input.left.trim();
  const rightName = right.source?.name ?? input.right.trim();
  return result(
    common,
    "interaction",
    [leftName, rightName],
    `${leftName} * ${rightName}`,
    "numeric",
    {
      preserve_bureau_special_values: true,
      special_value_policy: "preserve_source_sentinel",
    },
    errors,
  );
}

export function buildNumericBinFeature(
  input: NumericBinBuilderInput,
): BuilderValidationResult {
  const common = validateCommon(input);
  const source = validateSource(input.sourceCatalog, input.source, "source", "numeric");
  const cutPoints = [...input.cutPoints];
  const labels = input.labels.map(cleanLabel);
  const specialValueLabel = cleanLabel(input.specialValueLabel);
  const missingValueLabel = cleanLabel(input.missingValueLabel || "Missing");
  const errors = [...source.errors, ...validateDistinctLabels(labels, "labels")];

  if (!cutPoints.length) {
    errors.push(
      error(
        "cut_points_required",
        "Numeric bins require at least one fixed cut point.",
        "cutPoints",
      ),
    );
  } else if (cutPoints.some((cutPoint) => !Number.isFinite(cutPoint))) {
    errors.push(
      error(
        "cut_points_must_be_finite",
        "Every numeric-bin cut point must be a finite number.",
        "cutPoints",
      ),
    );
  } else if (
    cutPoints.some(
      (cutPoint, index) => index > 0 && cutPoint <= cutPoints[index - 1],
    )
  ) {
    errors.push(
      error(
        "cut_points_must_increase",
        "Numeric-bin cut points must be unique and entered in strictly increasing order.",
        "cutPoints",
      ),
    );
  }

  if (labels.length !== cutPoints.length + 1) {
    errors.push(
      error(
        "bin_label_count_mismatch",
        "Numeric-bin labels must contain exactly one more value than cut points.",
        "labels",
        { cutPointCount: cutPoints.length, requiredLabelCount: cutPoints.length + 1 },
      ),
    );
  }

  if (!specialValueLabel) {
    errors.push(
      error(
        "special_value_label_required",
        "Provide a separate label for governed bureau special values.",
        "specialValueLabel",
      ),
    );
  } else if (
    labels.some(
      (label) => label.toLocaleLowerCase() === specialValueLabel.toLocaleLowerCase(),
    )
  ) {
    errors.push(
      error(
        "special_value_label_must_be_distinct",
        "The bureau-special label must differ from every ordinary bin label.",
        "specialValueLabel",
      ),
    );
  }

  const sourceName = source.source?.name ?? input.source.trim();
  return result(
    common,
    "numeric_bin",
    [sourceName],
    `cut(${sourceName}; ${cutPoints.join(", ")})`,
    "categorical",
    {
      binning_mode: "custom",
      cut_points: cutPoints,
      labels,
      missing_label: missingValueLabel,
      special_value_label: specialValueLabel,
      special_value_policy: "separate_category",
      preserve_bureau_special_values: true,
    },
    errors,
  );
}

const NUMERIC_RULE_OPERATORS = new Set<RuleOperator>([
  "greater_than",
  "greater_than_or_equal",
  "less_than",
  "less_than_or_equal",
]);

const RULE_SYMBOLS: Record<RuleOperator, string> = {
  equals: "==",
  contains: "contains",
  greater_than: ">",
  greater_than_or_equal: ">=",
  less_than: "<",
  less_than_or_equal: "<=",
  is_missing: "is missing",
};

export function buildRuleCategoryFeature(
  input: RuleCategoryBuilderInput,
): BuilderValidationResult {
  const common = validateCommon(input);
  const expectedType = NUMERIC_RULE_OPERATORS.has(input.operator) ? "numeric" : "any";
  const source = validateSource(
    input.sourceCatalog,
    input.source,
    "source",
    expectedType,
  );
  const matchedLabel = cleanLabel(input.matchedLabel);
  const elseLabel = cleanLabel(input.elseLabel);
  const specialValueLabel = cleanLabel(input.specialValueLabel);
  const errors = [
    ...source.errors,
    ...validateDistinctLabels(
      [matchedLabel, elseLabel, specialValueLabel],
      "labels",
    ),
  ];

  const needsValue = input.operator !== "is_missing";
  const rawValue = input.value;
  if (needsValue && (rawValue === undefined || String(rawValue).trim() === "")) {
    errors.push(
      error("rule_value_required", "Provide a value for this rule.", "value"),
    );
  }

  let resolvedValue: string | number | null = rawValue ?? null;
  if (NUMERIC_RULE_OPERATORS.has(input.operator) && needsValue) {
    const numericValue = Number(rawValue);
    if (!Number.isFinite(numericValue)) {
      errors.push(
        error(
          "numeric_rule_value_required",
          "This comparison requires a finite numeric value.",
          "value",
        ),
      );
    } else {
      resolvedValue = numericValue;
    }
  }

  if (!specialValueLabel) {
    errors.push(
      error(
        "special_value_label_required",
        "Provide a separate label for governed bureau special values.",
        "specialValueLabel",
      ),
    );
  }

  const sourceName = source.source?.name ?? input.source.trim();
  const valueSuffix = input.operator === "is_missing" ? "" : ` ${String(resolvedValue)}`;
  return result(
    common,
    "categorical_rule",
    [sourceName],
    `${sourceName} ${RULE_SYMBOLS[input.operator]}${valueSuffix}`,
    "categorical",
    {
      rules: [
        {
          op: input.operator,
          value: resolvedValue,
          then_label: matchedLabel,
        },
      ],
      else_label: elseLabel,
      special_value_label: specialValueLabel,
      special_value_policy: "separate_category",
      preserve_bureau_special_values: true,
    },
    errors,
  );
}

export function buildPolynomialFeature(
  input: PolynomialBuilderInput,
): BuilderValidationResult {
  const common = validateCommon(input);
  const source = validateSource(input.sourceCatalog, input.source, "source", "numeric");
  const errors = [...source.errors];
  if (input.degree !== 2 && input.degree !== 3) {
    errors.push(
      error(
        "polynomial_degree_invalid",
        "Polynomial degree must be 2 or 3.",
        "degree",
        { degree: input.degree },
      ),
    );
  }

  const warnings = [
    warning(
      "polynomial_scale_review",
      `Degree ${input.degree} can expand the feature scale; review scaling before model fitting.`,
      "degree",
      { degree: input.degree, review: "scale" },
    ),
    warning(
      "polynomial_multicollinearity_review",
      `Degree ${input.degree} can be highly correlated with its source; review VIF and model stability.`,
      "degree",
      { degree: input.degree, review: "multicollinearity" },
    ),
  ];
  const sourceName = source.source?.name ?? input.source.trim();
  return result(
    common,
    "polynomial",
    [sourceName],
    `${sourceName} ^ ${input.degree}`,
    "numeric",
    {
      degree: input.degree,
      preserve_bureau_special_values: true,
      special_value_policy: "preserve_source_sentinel",
      review_warnings: warnings.map(({ code, message, metadata }) => ({
        code,
        message,
        metadata: metadata ? { ...metadata } : undefined,
      })),
    },
    errors,
    warnings,
  );
}

function normalizedUnit(unit: string | undefined): string {
  return unit?.trim().toLocaleLowerCase() || "";
}

function proveNonnegativeResult(
  input: ArithmeticBuilderInput,
  left: FeatureBuilderSource,
  right: FeatureBuilderSource,
): boolean {
  const leftMinimum = left.minimum;
  const leftMaximum = left.maximum;
  const rightMinimum = right.minimum;
  const rightMaximum = right.maximum;

  if (input.operation === "add") {
    return (
      leftMinimum !== null &&
      leftMinimum !== undefined &&
      rightMinimum !== null &&
      rightMinimum !== undefined &&
      leftMinimum >= 0 &&
      rightMinimum >= 0
    );
  }
  if (input.operation === "subtract") {
    return (
      input.domainEvidence?.leftGreaterThanOrEqualRight === true ||
      (leftMinimum !== null &&
        leftMinimum !== undefined &&
        rightMaximum !== null &&
        rightMaximum !== undefined &&
        leftMinimum >= rightMaximum)
    );
  }
  if (input.operation === "multiply") {
    const bothNonnegative =
      leftMinimum !== null &&
      leftMinimum !== undefined &&
      rightMinimum !== null &&
      rightMinimum !== undefined &&
      leftMinimum >= 0 &&
      rightMinimum >= 0;
    const bothNonpositive =
      leftMaximum !== null &&
      leftMaximum !== undefined &&
      rightMaximum !== null &&
      rightMaximum !== undefined &&
      leftMaximum <= 0 &&
      rightMaximum <= 0;
    return bothNonnegative || bothNonpositive;
  }

  const numeratorNonnegative =
    leftMinimum !== null && leftMinimum !== undefined && leftMinimum >= 0;
  const denominatorPositive =
    rightMinimum !== null && rightMinimum !== undefined && rightMinimum > 0;
  const numeratorNonpositive =
    leftMaximum !== null && leftMaximum !== undefined && leftMaximum <= 0;
  const denominatorNegative =
    rightMaximum !== null && rightMaximum !== undefined && rightMaximum < 0;
  return (
    (numeratorNonnegative && denominatorPositive) ||
    (numeratorNonpositive && denominatorNegative)
  );
}

function arithmeticUnit(
  operation: ArithmeticOperation,
  leftUnit: string,
  rightUnit: string,
): string {
  if (operation === "add" || operation === "subtract") return leftUnit;
  if (operation === "multiply") return `${leftUnit}*${rightUnit}`;
  return `${leftUnit}/${rightUnit}`;
}

const ARITHMETIC_SYMBOLS: Record<ArithmeticOperation, string> = {
  add: "+",
  subtract: "-",
  multiply: "*",
  divide: "/",
};

export function buildArithmeticFeature(
  input: ArithmeticBuilderInput,
): BuilderValidationResult {
  const common = validateCommon(input);
  const left = validateSource(input.sourceCatalog, input.left, "left", "numeric");
  const right = validateSource(input.sourceCatalog, input.right, "right", "numeric");
  const errors = [...left.errors, ...right.errors];
  const leftUnit = normalizedUnit(left.source?.unit);
  const rightUnit = normalizedUnit(right.source?.unit);

  if (left.source && !leftUnit) {
    errors.push(
      error(
        "arithmetic_unit_required",
        `Source '${left.source.name}' needs a governed unit before arithmetic can be approved.`,
        "left",
      ),
    );
  }
  if (right.source && !rightUnit) {
    errors.push(
      error(
        "arithmetic_unit_required",
        `Source '${right.source.name}' needs a governed unit before arithmetic can be approved.`,
        "right",
      ),
    );
  }
  if (
    (input.operation === "add" || input.operation === "subtract") &&
    leftUnit &&
    rightUnit &&
    leftUnit !== rightUnit
  ) {
    errors.push(
      error(
        "arithmetic_units_incompatible",
        `Operation '${input.operation}' requires compatible units; received '${leftUnit}' and '${rightUnit}'.`,
        "operation",
        { operation: input.operation, leftUnit, rightUnit },
      ),
    );
  }

  if (input.operation === "divide" && right.source) {
    const minimum = right.source.minimum;
    const maximum = right.source.maximum;
    const boundsExcludeZero =
      (minimum !== null && minimum !== undefined && minimum > 0) ||
      (maximum !== null && maximum !== undefined && maximum < 0);
    if (!boundsExcludeZero && input.domainEvidence?.rightNonZero !== true) {
      errors.push(
        error(
          "division_by_zero_not_ruled_out",
          "Division requires governed evidence that the denominator cannot be zero.",
          "right",
        ),
      );
    }
  }

  if (
    input.requireNonnegativeResult &&
    left.source &&
    right.source &&
    !proveNonnegativeResult(input, left.source, right.source)
  ) {
    errors.push(
      error(
        "nonnegative_domain_unproven",
        "The supplied bounds or domain evidence do not prove that this arithmetic result is nonnegative.",
        "domainEvidence",
        { operation: input.operation },
      ),
    );
  }

  const leftName = left.source?.name ?? input.left.trim();
  const rightName = right.source?.name ?? input.right.trim();
  const resultUnit =
    leftUnit && rightUnit
      ? arithmeticUnit(input.operation, leftUnit, rightUnit)
      : "unresolved";
  return result(
    common,
    "arithmetic",
    [leftName, rightName],
    `${leftName} ${ARITHMETIC_SYMBOLS[input.operation]} ${rightName}`,
    "numeric",
    {
      operation: input.operation,
      left_unit: leftUnit,
      right_unit: rightUnit,
      result_unit: resultUnit,
      result_domain: input.requireNonnegativeResult ? "nonnegative" : "unrestricted",
      domain_evidence: {
        left_greater_than_or_equal_right:
          input.domainEvidence?.leftGreaterThanOrEqualRight === true,
        right_nonzero: input.domainEvidence?.rightNonZero === true,
        note: input.domainEvidence?.note?.trim() || "",
      },
      preserve_bureau_special_values: true,
      special_value_policy: "preserve_source_sentinel",
    },
    errors,
  );
}

export function resolveDateDerivedAvailability(
  sourceCatalog: readonly FeatureBuilderSource[],
): DateDerivedAvailability {
  const dateSources = sourceCatalog
    .filter(
      (source) =>
        source.eligible !== false &&
        source.governedDate !== false &&
        isDateDataType(source.dataType),
    )
    .map((source) => source.name);
  return {
    available: dateSources.length > 0,
    dateSources,
    reason: dateSources.length
      ? "Governed calendar-date predictors are available."
      : "Date Derived is unavailable because no governed calendar-date predictor exists. Numeric duration fields are not calendar dates.",
  };
}

export function buildDateDerivedFeature(
  input: DateDerivedBuilderInput,
): BuilderValidationResult {
  const common = validateCommon(input);
  const source = validateSource(input.sourceCatalog, input.source, "source", "date");
  const availability = resolveDateDerivedAvailability(input.sourceCatalog);
  const errors = [...source.errors];
  if (!availability.available) {
    errors.push(
      error(
        "date_derived_unavailable",
        availability.reason,
        "source",
      ),
    );
  }
  const sourceName = source.source?.name ?? input.source.trim();
  return result(
    common,
    "date-derived",
    [sourceName],
    `${input.component}(${sourceName})`,
    "numeric",
    {
      component: input.component,
      invalid_date_policy: "missing",
    },
    errors,
  );
}
