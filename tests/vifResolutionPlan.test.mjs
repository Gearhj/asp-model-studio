import assert from "node:assert/strict";
import fs from "node:fs";
import test from "node:test";


const read = (path) => fs.readFileSync(path, "utf8");
const explorer = read("src/components/eda/visual/VifExplorer.tsx");
const panel = read("src/components/eda/visual/VifResolutionPlanPanel.tsx");
const step = read("src/steps/Step02_EDA.tsx");
const featureEngineering = read("src/steps/Step05_EncodingScaling.tsx");
const client = read("src/lib/vifResolutionPlan.ts");
const router = read("server/eda/eda_router.py");
const service = read("server/eda/workspace_service.py");


test("temporary simulator renders an actionable current-versus-proposed comparison", () => {
  assert.match(explorer, /data-testid="vif-simulation-comparison"/);
  assert.match(explorer, /Current governed set/);
  assert.match(explorer, /Temporary proposed set/);
  assert.match(explorer, /Current<\/th>.*Proposed<\/th>.*Delta<\/th>/s);
});


test("resolution plan exposes every governed input", () => {
  for (const phrase of [
    "Intended model family",
    "Target VIF threshold",
    "Resolution objective",
    "Protected predictors",
    "Allowed actions",
    "Correlation threshold",
    "Preference weights",
    "Special-value burden",
    "Production availability",
  ]) {
    assert.match(panel, new RegExp(phrase));
  }
});


test("result presents complete comparisons, clusters, alternatives, ties, and scope", () => {
  for (const marker of [
    'data-testid="vif-before-after-chart"',
    'data-testid="vif-cluster-recommendations"',
    'data-testid="vif-tie-cases"',
    "Per-feature VIF delta table",
    "Alternative resolution plans",
    "Proposed exclusions",
    "Proposed combinations",
    "Unresolved clusters",
    "governed_feature_set_calculations",
    "simulated_complete_vif_recalculations",
    "sealed_final_holdout_rows_excluded",
  ]) {
    assert.match(panel, new RegExp(marker));
  }
});


test("all required plan dispositions are visible", () => {
  for (const phrase of [
    "Accept complete plan",
    "Accept selected clusters",
    "Modify plan",
    "Reject",
    "Defer",
    "Send accepted proposals to Feature Engineering",
  ]) {
    assert.match(panel, new RegExp(phrase));
  }
});


test("frontend calls only recommendation endpoints and enforces non-mutation", () => {
  assert.match(step, /\/eda\/vif-resolution-plan/);
  assert.match(step, /\/eda\/vif-resolution-plan\/decision/);
  assert.match(client, /governed_feature_set_changed !== false/);
  assert.match(client, /dataset_mutated !== false/);
  assert.doesNotMatch(panel, /features\/manifest|materialize|setRaw|setProcessed/);
  const nestedVif = step.slice(
    step.indexOf("const simulateVif = useCallback"),
    step.indexOf("const handleCorrelationVariable = useCallback"),
  );
  assert.equal(
    (nestedVif.match(/assertExactEdaResponseLineage\(props\.canonicalHandoff, payload\)/g) ?? []).length,
    3,
    "Simulation, plan generation, and plan disposition must each validate the full DA lineage.",
  );
  assert.equal(
    (nestedVif.match(/\.\.\.props\.canonicalRequest/g) ?? []).length,
    3,
    "Every VIF request must send the full canonical request envelope.",
  );
});


test("backend routes use the shared governed service", () => {
  assert.match(router, /@router\.post\("\/vif-resolution-plan"\)/);
  assert.match(router, /@router\.post\("\/vif-resolution-plan\/decision"\)/);
  assert.match(router, /@router\.get\("\/vif-resolution-recommendations"\)/);
  assert.match(service, /build_vif_resolution_plan/);
  assert.match(service, /development_population_only/);
  assert.match(service, /final_holdout_accessed["']:\s*False/);
});


test("accepted proposals remain visible draft recommendations in Feature Engineering", () => {
  assert.match(featureEngineering, /\/eda\/vif-resolution-recommendations/);
  assert.match(featureEngineering, /Draft VIF Resolution Recommendations/);
  assert.match(featureEngineering, /Review only — the governed feature set is unchanged\./);
  assert.doesNotMatch(featureEngineering, /vif-resolution-recommendations[\s\S]{0,500}(materialize|dropPredictor|removePredictor)/);
});
