import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const root = new URL("../", import.meta.url);
const read = (path) => readFile(new URL(path, root), "utf8");

const [acquisition, featureEngineering, modelDocument] = await Promise.all([
  read("src/components/BureauReviewPanel.tsx"),
  read("src/steps/Step05_EncodingScaling.tsx"),
  read("src/lib/modelDevelopmentDocument.ts"),
]);

test("special-value actions use plain modeling outcomes without changing stored identifiers", () => {
  for (const label of [
    "Create special-value indicator (dummy variable)",
    "Impute with a valid governed value",
    "Exclude feature from modeling",
    "Leave value unchanged",
  ]) {
    assert.ok(acquisition.includes(label), `missing treatment label: ${label}`);
    assert.ok(modelDocument.includes(label), `missing documented label: ${label}`);
  }

  for (const identifier of [
    "preserve_informative",
    "convert_to_missing",
    "convert_to_category",
    "documented_domain_mapping",
    "exclude_variable",
    "leave_unchanged",
    "custom",
  ]) {
    assert.ok(acquisition.includes(identifier), `missing stored action: ${identifier}`);
  }

  assert.doesNotMatch(acquisition, /Preserve as numeric sentinel/);
  assert.doesNotMatch(acquisition, /Convert to labeled category/);
  assert.doesNotMatch(acquisition, /Map to governed replacement/);
  assert.match(acquisition, /data-testid="special-value-treatment-help"/);
  assert.match(acquisition, /data-testid="selected-special-value-treatment-help"/);
  assert.match(acquisition, /Missing Values step/);
});

test("feature inventory is visibly tabular with checkbox-only inclusion controls", () => {
  assert.match(
    featureEngineering,
    /data-testid="feature-transformation-plan"[\s\S]*aria-label="Modeling dataset feature inventory and summary statistics"/,
  );
  assert.match(featureEngineering, /<caption className="sr-only">/);
  assert.match(featureEngineering, /<th scope="col" className="w-20 border-b border-slate-300 px-3 py-3 text-center">Include<\/th>/);
  assert.match(featureEngineering, /aria-describedby="feature-inventory-selection-help"/);
  assert.match(featureEngineering, /className="h-4 w-4 rounded border-slate-300/);
  assert.match(featureEngineering, /sticky top-0[\s\S]*bg-slate-100 shadow-sm/);
  assert.match(featureEngineering, /border-b border-slate-100 px-3 py-3/);
  assert.doesNotMatch(featureEngineering, /\{included \? "Yes" : "No"\}/);
  assert.match(featureEngineering, /use the checkboxes to\s+change the modeling set/);
});
