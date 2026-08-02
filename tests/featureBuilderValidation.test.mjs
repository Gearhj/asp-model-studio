import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";
import ts from "typescript";

const testDirectory = dirname(fileURLToPath(import.meta.url));
const modulePath = resolve(
  testDirectory,
  "../src/lib/featureBuilderValidation.ts",
);
const source = readFileSync(modulePath, "utf8");
const transpiled = ts.transpileModule(source, {
  fileName: modulePath,
  compilerOptions: {
    module: ts.ModuleKind.ESNext,
    target: ts.ScriptTarget.ES2022,
  },
}).outputText;
const builder = await import(
  `data:text/javascript;base64,${Buffer.from(transpiled).toString("base64")}`
);

const sourceCatalog = Object.freeze([
  Object.freeze({
    name: "ExternalRiskEstimate",
    dataType: "int64",
    eligible: true,
    unit: "score",
    minimum: 0,
    maximum: 100,
  }),
  Object.freeze({
    name: "PercentTradesNeverDelq",
    dataType: "float64",
    eligible: true,
    unit: "percent",
    minimum: 0,
    maximum: 100,
  }),
  Object.freeze({
    name: "NetFractionRevolvingBurden",
    dataType: "float64",
    eligible: true,
    unit: "percent",
    minimum: 0,
    maximum: 200,
  }),
  Object.freeze({
    name: "AverageMInFile",
    dataType: "int64",
    eligible: true,
    unit: "months",
    minimum: 0,
    maximum: 500,
  }),
  Object.freeze({
    name: "NumTotalTrades",
    dataType: "int64",
    eligible: true,
    unit: "count",
    minimum: 0,
    maximum: 150,
  }),
  Object.freeze({
    name: "NumSatisfactoryTrades",
    dataType: "int64",
    eligible: true,
    unit: "count",
    minimum: 0,
    maximum: 150,
  }),
  Object.freeze({
    name: "bad_flag",
    dataType: "int64",
    eligible: false,
    exclusionReason: "The configured target cannot be used as a predictor.",
    unit: "class",
  }),
  Object.freeze({
    name: "RiskPerformance",
    dataType: "int64",
    eligible: false,
    exclusionReason:
      "The deterministic target source cannot be used as a predictor.",
    unit: "class",
  }),
]);

function codes(messages) {
  return messages.map((message) => message.code);
}

test("interaction creates the representative governed definition without mutating inputs", () => {
  const input = {
    name: "ExternalRisk_x_NeverDelq",
    displayName: "External risk × never delinquent",
    rationale: "Review the joint effect for transparent challenger models.",
    left: "ExternalRiskEstimate",
    right: "PercentTradesNeverDelq",
    sourceCatalog,
  };
  const before = JSON.stringify(input);

  const result = builder.buildInteractionFeature(input);

  assert.equal(result.ok, true);
  assert.deepEqual(result.errors, []);
  assert.equal(result.definition.origin, "interaction");
  assert.equal(result.definition.transformation_type, "interaction");
  assert.deepEqual(result.definition.source_features, [
    "ExternalRiskEstimate",
    "PercentTradesNeverDelq",
  ]);
  assert.equal(
    result.definition.formula_or_rule,
    "ExternalRiskEstimate * PercentTradesNeverDelq",
  );
  assert.equal(result.definition.output_datatype, "numeric");
  assert.equal(
    result.definition.user_rationale,
    "Review the joint effect for transparent challenger models.",
  );
  assert.deepEqual(result.definition.config, {
    preserve_bureau_special_values: true,
    special_value_policy: "preserve_source_sentinel",
  });
  assert.equal(JSON.stringify(input), before);
});

test("excluded target and deterministic target-source predictors cannot enter a builder", () => {
  for (const sourceName of ["bad_flag", "RiskPerformance"]) {
    const result = builder.buildPolynomialFeature({
      name: `${sourceName}_squared`,
      source: sourceName,
      degree: 2,
      sourceCatalog,
    });
    assert.equal(result.ok, false);
    assert.equal(result.definition, null);
    assert.ok(codes(result.errors).includes("source_excluded"));
  }
});

test("numeric bins require cut-points plus one labels and persist a separate bureau-special policy", () => {
  const result = builder.buildNumericBinFeature({
    name: "ExternalRiskBand",
    rationale: "Use reviewer-approved fixed score bands.",
    source: "ExternalRiskEstimate",
    cutPoints: [60, 70, 80],
    labels: ["Below 60", "60 to 69", "70 to 79", "80 or above"],
    specialValueLabel: "Bureau special",
    missingValueLabel: "Missing",
    sourceCatalog,
  });

  assert.equal(result.ok, true);
  assert.equal(result.definition.formula_or_rule, "cut(ExternalRiskEstimate; 60, 70, 80)");
  assert.deepEqual(result.definition.config.cut_points, [60, 70, 80]);
  assert.deepEqual(result.definition.config.labels, [
    "Below 60",
    "60 to 69",
    "70 to 79",
    "80 or above",
  ]);
  assert.equal(result.definition.config.special_value_label, "Bureau special");
  assert.equal(result.definition.config.special_value_policy, "separate_category");
  assert.equal(result.definition.config.preserve_bureau_special_values, true);

  const invalid = builder.buildNumericBinFeature({
    name: "InvalidExternalRiskBand",
    source: "ExternalRiskEstimate",
    cutPoints: [60, 70, 80],
    labels: ["Low", "Middle", "High"],
    specialValueLabel: "Bureau special",
    sourceCatalog,
  });
  assert.equal(invalid.ok, false);
  assert.ok(codes(invalid.errors).includes("bin_label_count_mismatch"));
});

test("numeric bins reject unordered cut points instead of silently changing the reviewer definition", () => {
  const result = builder.buildNumericBinFeature({
    name: "UnorderedExternalRiskBand",
    source: "ExternalRiskEstimate",
    cutPoints: [70, 60, 80],
    labels: ["A", "B", "C", "D"],
    specialValueLabel: "Bureau special",
    sourceCatalog,
  });

  assert.equal(result.ok, false);
  assert.ok(codes(result.errors).includes("cut_points_must_increase"));
});

test("rule category supports greater-than-or-equal and handles bureau special values explicitly", () => {
  const result = builder.buildRuleCategoryFeature({
    name: "HighRevolvingBurden",
    rationale: "Flag the governed 75 percent review threshold.",
    source: "NetFractionRevolvingBurden",
    operator: "greater_than_or_equal",
    value: 75,
    matchedLabel: "75 or above",
    elseLabel: "Below 75",
    specialValueLabel: "Bureau special",
    sourceCatalog,
  });

  assert.equal(result.ok, true);
  assert.equal(
    result.definition.formula_or_rule,
    "NetFractionRevolvingBurden >= 75",
  );
  assert.deepEqual(result.definition.config.rules, [
    {
      op: "greater_than_or_equal",
      value: 75,
      then_label: "75 or above",
    },
  ]);
  assert.equal(result.definition.config.else_label, "Below 75");
  assert.equal(result.definition.config.special_value_label, "Bureau special");
  assert.equal(result.definition.config.special_value_policy, "separate_category");
  assert.equal(result.definition.config.preserve_bureau_special_values, true);
});

test("polynomial definition carries degree-specific scale and multicollinearity warnings", () => {
  const result = builder.buildPolynomialFeature({
    name: "AverageMInFileSquared",
    source: "AverageMInFile",
    degree: 2,
    sourceCatalog,
  });

  assert.equal(result.ok, true);
  assert.equal(result.definition.formula_or_rule, "AverageMInFile ^ 2");
  assert.equal(result.definition.config.degree, 2);
  assert.deepEqual(codes(result.warnings), [
    "polynomial_scale_review",
    "polynomial_multicollinearity_review",
  ]);
  assert.deepEqual(
    result.definition.config.review_warnings.map((item) => item.code),
    ["polynomial_scale_review", "polynomial_multicollinearity_review"],
  );
  assert.equal(
    result.definition.config.review_warnings[0].metadata.degree,
    2,
  );

  const invalid = builder.buildPolynomialFeature({
    name: "AverageMInFileFourth",
    source: "AverageMInFile",
    degree: 4,
    sourceCatalog,
  });
  assert.equal(invalid.ok, false);
  assert.ok(codes(invalid.errors).includes("polynomial_degree_invalid"));
});

test("arithmetic persists compatible units and explicit nonnegative-domain evidence", () => {
  const result = builder.buildArithmeticFeature({
    name: "UnsatisfactoryTrades",
    rationale: "Derive the count not classified as satisfactory.",
    left: "NumTotalTrades",
    right: "NumSatisfactoryTrades",
    operation: "subtract",
    requireNonnegativeResult: true,
    domainEvidence: {
      leftGreaterThanOrEqualRight: true,
      note: "Satisfactory trades are a governed subset of total trades.",
    },
    sourceCatalog,
  });

  assert.equal(result.ok, true);
  assert.equal(
    result.definition.formula_or_rule,
    "NumTotalTrades - NumSatisfactoryTrades",
  );
  assert.equal(result.definition.config.left_unit, "count");
  assert.equal(result.definition.config.right_unit, "count");
  assert.equal(result.definition.config.result_unit, "count");
  assert.equal(result.definition.config.result_domain, "nonnegative");
  assert.equal(
    result.definition.config.domain_evidence.left_greater_than_or_equal_right,
    true,
  );
  assert.equal(result.definition.config.preserve_bureau_special_values, true);
});

test("arithmetic blocks incompatible units and an unproven nonnegative domain", () => {
  const incompatibleCatalog = [
    ...sourceCatalog,
    {
      name: "DollarBalance",
      dataType: "float64",
      eligible: true,
      unit: "currency",
      minimum: 0,
      maximum: 100_000,
    },
  ];
  const incompatible = builder.buildArithmeticFeature({
    name: "InvalidMixedUnitDifference",
    left: "NumTotalTrades",
    right: "DollarBalance",
    operation: "subtract",
    sourceCatalog: incompatibleCatalog,
  });
  assert.equal(incompatible.ok, false);
  assert.ok(codes(incompatible.errors).includes("arithmetic_units_incompatible"));

  const unproven = builder.buildArithmeticFeature({
    name: "UnprovenTradeDifference",
    left: "NumTotalTrades",
    right: "NumSatisfactoryTrades",
    operation: "subtract",
    requireNonnegativeResult: true,
    sourceCatalog,
  });
  assert.equal(unproven.ok, false);
  assert.ok(codes(unproven.errors).includes("nonnegative_domain_unproven"));
});

test("date-derived remains unavailable for numeric duration fields", () => {
  const availability = builder.resolveDateDerivedAvailability(sourceCatalog);
  assert.deepEqual(availability.dateSources, []);
  assert.equal(availability.available, false);
  assert.match(availability.reason, /Numeric duration fields are not calendar dates/);

  const result = builder.buildDateDerivedFeature({
    name: "AverageMInFileYear",
    source: "AverageMInFile",
    component: "year",
    sourceCatalog,
  });
  assert.equal(result.ok, false);
  assert.ok(codes(result.errors).includes("governed_date_source_required"));
  assert.ok(codes(result.errors).includes("date_derived_unavailable"));
});

test("date-derived becomes available only for an eligible governed date datatype", () => {
  const catalogWithDate = [
    ...sourceCatalog,
    {
      name: "ApplicationDate",
      dataType: "datetime64[ns]",
      eligible: true,
      governedDate: true,
    },
  ];
  const availability = builder.resolveDateDerivedAvailability(catalogWithDate);
  assert.deepEqual(availability.dateSources, ["ApplicationDate"]);
  assert.equal(availability.available, true);

  const result = builder.buildDateDerivedFeature({
    name: "ApplicationQuarter",
    source: "ApplicationDate",
    component: "quarter",
    sourceCatalog: catalogWithDate,
  });
  assert.equal(result.ok, true);
  assert.equal(result.definition.formula_or_rule, "quarter(ApplicationDate)");
  assert.deepEqual(result.definition.config, {
    component: "quarter",
    invalid_date_policy: "missing",
  });
});
