import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const ROOT = new URL("../", import.meta.url);
const read = (path) =>
  readFileSync(new URL(path, ROOT), "utf8").replace(/\r\n/g, "\n");

const pages = {
  outliers: read("src/steps/Step04_Outliers.tsx"),
  missing: read("src/steps/Step04_MissingValues.tsx"),
  features: read("src/steps/Step05_EncodingScaling.tsx"),
  split: read("src/steps/Step06_BalancingSplit.tsx"),
};
const chrome = read(
  "src/components/preparation/PreparationPageChrome.tsx",
);
const styles = read(
  "src/components/preparation/preparation-premium.css",
);

test("the four preparation pages share the compact reference chrome", () => {
  for (const [name, source] of Object.entries(pages)) {
    assert.match(source, /className="prep-premium-page/);
    assert.match(source, /<PreparationPageIdentity/);
    assert.match(
      source,
      /\bshowEmbeddedNext\b/,
      `${name} must keep its continuation action in Credit Risk Studio`,
    );
    assert.match(
      source,
      /\bnextAlwaysVisible\b/,
      `${name} must keep its continuation action in the viewport`,
    );
  }

  assert.match(chrome, /appearance\?: "dark" \| "light"/);
  assert.match(chrome, /PreparationGovernanceDisclosure/);
  assert.match(styles, /\.prep-identity--light/);
  assert.match(styles, /\.prep-governance-disclosure/);
  assert.match(styles, /min-height: 82px/);
});

test("Outliers and Missing Values remain table-first with compact evidence below", () => {
  assert.match(
    pages.outliers,
    /All-Feature Outlier Summary and Treatment Table/,
  );
  assert.match(pages.outliers, /max-h-\[430px\]/);
  assert.match(pages.outliers, /outlier-global-treatment/);
  assert.match(pages.outliers, /outlier-cutoff-histogram-gallery/);
  assert.match(pages.outliers, /nextFooterTestId="outliers-sticky-footer"/);

  assert.match(
    pages.missing,
    /All-Feature Missing-Value Summary and Treatment/,
  );
  assert.match(pages.missing, /max-h-\[430px\]/);
  assert.match(pages.missing, /missing-global-strategy/);
  assert.match(pages.missing, /Missingness and Imputation Map/);
  assert.match(
    pages.missing,
    /nextFooterTestId="missing-values-sticky-footer"/,
  );
});

test("Feature Engineering follows builder, inventory, optional-tools composition", () => {
  const review = pages.features.indexOf('data-testid="feature-set-review"');
  const launcher = pages.features.indexOf(
    'data-testid="feature-builder-launcher"',
  );
  const tools = pages.features.indexOf(
    'data-testid="feature-engineering-secondary-tools"',
  );
  const recommendations = pages.features.indexOf(
    'data-testid="feature-engineering-recommendation-details"',
  );

  assert.ok(launcher >= 0);
  assert.ok(review >= 0);
  assert.ok(tools > launcher);
  assert.match(
    pages.features.slice(launcher - 80, launcher + 80),
    /order-\[10\]/,
  );
  assert.match(
    pages.features.slice(review - 80, review + 80),
    /order-\[20\]/,
  );
  assert.ok(recommendations >= 0);
  assert.match(pages.features, /Search features, rules, or types/);
  assert.match(pages.features, /Filter feature set/);
  assert.match(pages.features, />IV</);
  assert.match(pages.features, />Mean</);
  assert.match(pages.features, />Missing</);
  assert.match(pages.features, />Distinct</);
  assert.match(styles, /\.prep-feature-builder-launcher/);
  assert.match(styles, /\.prep-feature-builder-tile/);
});

test("Balance and Split uses the reference validation-design sequence", () => {
  for (const label of [
    "1. Review Inherited Analysis Partition",
    "Data Acquisition Analysis Partition",
    "Inherited Development / Final Holdout",
    "Cross-Validation Inside Training",
    "2. Configure Cross-Validation",
    "3. Preview of resulting split",
    "4. Class Preservation Summary",
    "Advanced Balancing Settings",
    "Advanced External Validation Data",
    "Final Predictor Review",
  ]) {
    assert.ok(pages.split.includes(label), `missing split layout label: ${label}`);
  }

  assert.match(pages.split, /appearance="light"/);
  assert.match(
    pages.split,
    /<PreparationPageIdentity[\s\S]{0,140}title="Training and Validation Design"/,
  );
  assert.match(
    pages.split,
    /<AtlasWorkflowSection[\s\S]{0,140}title="1\. Review Inherited Analysis Partition"/,
  );
  assert.match(pages.split, /prep-split-preview__bar/);
  for (const testId of [
    "advanced-balancing-settings",
    "advanced-external-validation",
    "compact-final-predictor-review",
  ]) {
    assert.match(pages.split, new RegExp(`<section data-testid="${testId}">`));
    assert.doesNotMatch(
      pages.split,
      new RegExp(`<details[^>]*data-testid="${testId}"`),
    );
  }
  assert.match(
    pages.split,
    /nextFooterTestId="balance-split-sticky-footer"/,
  );
  assert.match(styles, /\.prep-split-preview/);
  assert.match(styles, /\.prep-split-preview__train/);
  assert.match(styles, /\.prep-split-preview__holdout/);
});
