import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const ROOT = new URL("../", import.meta.url);
const read = (path) =>
  readFileSync(new URL(path, ROOT), "utf8").replace(/\r\n/g, "\n");

const featurePage = read("src/steps/Step05_EncodingScaling.tsx");
const stepShell = read("src/components/StepShell.tsx");
const creditRiskStudio = read("src/steps/CreditRiskStudio.tsx");
const featureClient = read("src/lib/featureManifest.ts");
const featureService = read("server/features/feature_service.py");
const preparationDocumentation = read(
  "server/preprocessing/preparation_documentation_router.py",
);
const modelDevelopmentDocument = read(
  "src/lib/modelDevelopmentDocument.ts",
);

function count(source, pattern) {
  return [...source.matchAll(pattern)].length;
}

function functionBody(source, name, nextName) {
  const escapedName = name.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const startPattern = new RegExp(
    `(?:(?:async\\s+)?function\\s+${escapedName}\\s*\\(|const\\s+${escapedName}\\s*=\\s*async\\s*\\()`,
  );
  const match = startPattern.exec(source);
  assert.ok(match, `missing function ${name}`);
  const start = match.index;
  const end = nextName
    ? source.search(
        new RegExp(
          `(?:async\\s+)?function\\s+${nextName.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}\\s*\\(`,
        ),
      )
    : source.indexOf("\n  return (", start);
  assert.ok(end > start, `could not isolate function ${name}`);
  return source.slice(start, end);
}

function elementAroundTestId(source, testId, closingTag) {
  const marker = `data-testid="${testId}"`;
  const markerIndex = source.indexOf(marker);
  assert.notEqual(markerIndex, -1, `missing ${marker}`);
  const tagStart = source.lastIndexOf("<", markerIndex);
  const end = source.indexOf(closingTag, markerIndex);
  assert.ok(tagStart >= 0 && end > markerIndex, `could not isolate ${testId}`);
  return source.slice(tagStart, end + closingTag.length);
}

test("Feature Engineering opts into one always-visible shared progression footer", () => {
  for (const prop of [
    "showEmbeddedNext",
    "nextAlwaysVisible",
    "nextFooterTestId",
    "nextStatusTestId",
    "nextButtonTestId",
  ]) {
    assert.match(stepShell, new RegExp(`\\b${prop}\\b`), `StepShell is missing ${prop}`);
    assert.match(featurePage, new RegExp(`\\b${prop}\\b`), `Feature Engineering does not opt into ${prop}`);
  }

  assert.match(
    featurePage,
    /nextFooterTestId="feature-engineering-sticky-footer"/,
  );
  assert.match(
    featurePage,
    /nextStatusTestId="feature-engineering-continue-status"/,
  );
  assert.match(
    featurePage,
    /nextButtonTestId="feature-confirm-continue"/,
  );
  assert.match(featurePage, /nextLabel="Confirm Feature Set & Continue"/);

  assert.match(
    stepShell,
    /location\.pathname === "\/credit-risk-studio"[\s\S]{0,180}!showEmbeddedNext/,
    "Credit Risk Studio must not suppress an explicitly requested Feature Engineering footer",
  );
  assert.match(
    stepShell,
    /nextAlwaysVisible[\s\S]{0,220}\bfixed\b[\s\S]{0,180}\bbottom-/,
    "persistent mode must use viewport-fixed positioning, not a sticky element reached only after long children",
  );
  assert.match(
    stepShell,
    /data-testid=\{nextFooterTestId \?\? "workflow-next-bar"\}/,
  );
  assert.match(stepShell, /data-testid=\{nextStatusTestId\}/);

  assert.equal(
    count(featurePage, /feature-confirm-continue"/g),
    1,
    "the page must expose exactly one progression CTA",
  );
});

test("the primary CTA is always rendered and orchestrates the governed contract", () => {
  const shellPropsStart = featurePage.indexOf("<StepShell");
  const shellPropsEnd = featurePage.indexOf("\n    >", shellPropsStart);
  assert.ok(shellPropsStart >= 0 && shellPropsEnd > shellPropsStart);
  const shellProps = featurePage.slice(shellPropsStart, shellPropsEnd);

  assert.doesNotMatch(
    shellProps,
    /nextDisabled=\{[^}]*\b(?:dirty|planReady)\b/,
    "draft or not-yet-materialized state should be handled by the CTA, not make it disappear or become unusable",
  );
  assert.match(shellProps, /onNext=\{finalizeFeatureSetAndContinue\}/);

  const orchestrator = functionBody(
    featurePage,
    "finalizeFeatureSetAndContinue",
    "completeStep",
  );
  const operations = [
    "saveFeatureManifest",
    "previewFeaturePlan",
    "materializeFeatureManifest",
    "confirmFeatureManifest",
  ];
  let priorIndex = -1;
  for (const operation of operations) {
    const operationIndex = orchestrator.indexOf(operation);
    assert.ok(operationIndex > priorIndex, `${operation} is missing or out of order`);
    priorIndex = operationIndex;
  }
  assert.match(orchestrator, /return\s+true/);
  assert.match(orchestrator, /catch\s*\(/);
  assert.match(orchestrator, /return\s+false/);
});

test("disabled progression explains exact blockers beside the CTA", () => {
  assert.match(featurePage, /const continueDisabledReason\s*=/);
  assert.match(
    featurePage,
    /feature-engineering-continue-status/,
  );
  assert.match(
    featurePage,
    /nextDisabledReason=\{continueDisabledReason\}/,
    "the visible status must render the same exact reason that controls the CTA",
  );

  for (const blocker of [
    /loading the governed feature manifest/i,
    /select at least one eligible source or engineered predictor before continuing to balance & split/i,
    /finish or cancel the open feature edit before continuing/i,
  ]) {
    assert.match(featurePage, blocker);
  }
  assert.match(
    featurePage,
    /selectedReviewFeatureCount === 0[\s\S]{0,220}Select at least one eligible source or engineered predictor/,
  );
  assert.match(
    functionBody(
      featurePage,
      "finalizeFeatureSetAndContinue",
      "completeStep",
    ),
    /selectedReviewFeatureCount === 0[\s\S]{0,220}return false/,
    "the one-click handler needs the same defensive zero-selection gate as the visible CTA",
  );

  const shellPropsStart = featurePage.indexOf("<StepShell");
  const shellPropsEnd = featurePage.indexOf("\n    >", shellPropsStart);
  const shellProps = featurePage.slice(shellPropsStart, shellPropsEnd);
  assert.match(shellProps, /nextDisabled=\{!!continueDisabledReason\}/);
  assert.match(
    stepShell,
    /data-testid=\{nextStatusTestId\}[\s\S]{0,500}nextDisabledReason/,
    "the blocker must be rendered inside the persistent progression footer",
  );
});

test("Feature Engineering leads with the builder, then inventory, and collapses secondary tools", () => {
  const builderIndex = featurePage.indexOf(
    'data-testid="feature-builder-launcher"',
  );
  const reviewIndex = featurePage.indexOf('data-testid="feature-set-review"');
  const secondaryIndex = featurePage.indexOf(
    'data-testid="feature-engineering-secondary-tools"',
  );
  assert.ok(builderIndex >= 0, "missing primary feature builder");
  assert.ok(reviewIndex >= 0, "missing feature inventory");
  assert.match(
    featurePage.slice(builderIndex - 80, builderIndex + 80),
    /order-\[10\]/,
    "feature builder must be the first rendered workflow surface",
  );
  assert.match(
    featurePage.slice(reviewIndex - 80, reviewIndex + 80),
    /order-\[20\]/,
    "feature inventory must render directly after the builder",
  );
  assert.ok(
    secondaryIndex > reviewIndex,
    "secondary tools must follow the primary feature-set review",
  );

  const secondary = elementAroundTestId(
    featurePage,
    "feature-engineering-secondary-tools",
    "</details>",
  );
  assert.match(secondary, /^<details\b/);
  assert.doesNotMatch(
    secondary.slice(0, secondary.indexOf(">") + 1),
    /\bopen\b/,
    "secondary tools should be collapsed by default",
  );

  for (const label of [
    "Included predictors",
    "Engineered features",
    "Training transforms",
    "Feature-set status",
  ]) {
    assert.match(featurePage, new RegExp(label, "i"), `review is missing ${label}`);
  }
});

test("the page has no competing save-preview-materialize-confirm progression buttons", () => {
  for (const oldAction of [
    /<button[^>]*>[\s\S]{0,220}Preview Feature Set[\s\S]{0,80}<\/button>/,
    /<button[^>]*>[\s\S]{0,220}Save Feature Manifest[\s\S]{0,80}<\/button>/,
    /<button[^>]*>[\s\S]{0,220}Materialize Governed Feature Set[\s\S]{0,80}<\/button>/,
    /<button[^>]*>[\s\S]{0,220}Confirm Feature Set Current[\s\S]{0,80}<\/button>/,
  ]) {
    assert.doesNotMatch(featurePage, oldAction);
  }
  assert.equal(
    count(featurePage, /nextLabel="Confirm Feature Set & Continue"/g),
    1,
    "there must be one plainly named progression action",
  );
});

test("navigation waits for safe completion and backend hash gates remain authoritative", () => {
  const handleNext = functionBody(stepShell, "handleNext", undefined);
  const onNextIndex = handleNext.indexOf("await onNext()");
  const markCompleteIndex = handleNext.indexOf("markComplete(");
  const navigateIndex = handleNext.indexOf("navigate(");
  assert.ok(onNextIndex >= 0, "StepShell must await the page completion contract");
  assert.match(handleNext, /if \(result === false\) return/);
  assert.ok(markCompleteIndex > onNextIndex);
  assert.ok(navigateIndex > markCompleteIndex);

  assert.match(featurePage, /nextPath=\{getNextStepPath\("step05"\)\}/);
  assert.match(featurePage, /workflowStepId="step05"/);
  assert.match(
    stepShell,
    /const currentStep = workflowStepId[\s\S]*?\?\? workflowStepIdFromPathname\(location\.pathname\)[\s\S]*?\?\? location\.pathname\.replace\(\/\^\\\/\+\//,
  );
  assert.match(
    featureClient,
    /confirmFeatureManifest[\s\S]*manifest_version:\s*manifestVersion[\s\S]*materialization_hash:\s*materializationHash/,
  );
  assert.match(
    featureService,
    /expected_version\s*!=\s*manifest\["manifest_hash"\]/,
  );
  assert.match(
    featureService,
    /materialization_status"\)\s*!=\s*"current"[\s\S]*materialized_manifest_hash"\)\s*!=\s*manifest\["manifest_hash"\]/,
  );
  assert.match(
    featureService,
    /manifest\["confirmed_manifest_hash"\]\s*=\s*manifest\["manifest_hash"\]/,
  );
});

test("Credit Risk Studio exposes the same completion CTA without a weaker competitor", () => {
  assert.doesNotMatch(
    creditRiskStudio,
    /data-step-next-button[^\n]{0,160}(?:hidden|display\s*:\s*none)/i,
  );
  assert.doesNotMatch(
    creditRiskStudio,
    /(?:hidden|display\s*:\s*none)[^\n]{0,160}data-step-next-button/i,
  );
  assert.doesNotMatch(
    creditRiskStudio,
    /Confirm Characteristic Screening and Continue/,
  );
  assert.match(
    creditRiskStudio,
    /activeWorkflowStep\.name === "Feature Engineering"[\s\S]*<Step05FeatureEngineering \/>/,
  );
  assert.match(stepShell, /showEmbeddedNext/);
});

test("target lineage and bureau special-value protections remain enforced", () => {
  assert.match(
    featureService,
    /if name == target or name in prior_materialized:\s*\n\s*continue/,
  );
  assert.match(
    featureService,
    /name\.casefold\(\) == target\.casefold\(\)[\s\S]*source\.casefold\(\) == target\.casefold\(\)/,
  );
  assert.match(
    featureService,
    /unsafe_sources[\s\S]*uses an excluded predictor/,
  );
  assert.match(
    featureService,
    /authorized_sources = set\(_base_columns\(\)\)[\s\S]*_normalize_engineered\(/,
    "materialization must re-authorize every engineered feature server-side",
  );
  assert.ok(
    count(featureService, /preserve_bureau_special_values", True/g) >= 5,
    "all applicable deterministic transformations must preserve bureau sentinels by default",
  );
  assert.match(featureService, /for special in \(-9\.0, -8\.0, -7\.0\)/);
  assert.match(featurePage, /preserve_bureau_special_values:\s*true/);
});

test("completion still records evidence and feeds MDD documentation", () => {
  const completeStep = functionBody(featurePage, "completeStep", undefined);
  assert.match(completeStep, /createEvidence\(/);
  assert.match(completeStep, /evidenceType:\s*"feature_engineering"/);
  assert.match(
    completeStep,
    /supportsSections:\s*\["Feature Engineering",\s*"Candidate Models"\]/,
  );
  assert.match(completeStep, /confirmedManifestHash/);
  assert.match(completeStep, /logDecision\(/);

  assert.match(preparationDocumentation, /def _feature_documentation\(/);
  assert.match(
    preparationDocumentation,
    /confirmation_status"\)\s*==\s*"confirmed"/,
  );
  assert.match(
    preparationDocumentation,
    /confirmed_manifest_hash"\)\s*==\s*manifest_hash/,
  );
  assert.match(modelDevelopmentDocument, /title:\s*"Feature Engineering"/);
});
