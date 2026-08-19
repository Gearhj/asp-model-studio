// Phase 6E.5 — temporal-policy flexibility, Data Profile EDA, and feature-engineering examples.
import assert from "node:assert/strict";
import { mkdir, readFile, rm, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import test from "node:test";
import ts from "typescript";

const ROOT = new URL("..", import.meta.url);
const read = (p) => readFile(new URL(p, ROOT), "utf8");
const TMP = fileURLToPath(new URL("../.tmp/eda-temporal", import.meta.url));

globalThis.localStorage = {
  _s: new Map(),
  getItem(k) { return this._s.has(k) ? this._s.get(k) : null; },
  setItem(k, v) { this._s.set(k, String(v)); },
  removeItem(k) { this._s.delete(k); },
};
async function transpile(src, out) {
  let code = await readFile(new URL(src, ROOT), "utf8");
  code = ts.transpileModule(code, { compilerOptions: { module: ts.ModuleKind.ES2022, target: ts.ScriptTarget.ES2022 } }).outputText;
  code = code.replace(/from\s+["'](\.{1,2}\/[^"']+)["']/g, (m, s) => (s.endsWith(".js") || s.endsWith(".json") ? m : m.replace(s, `${s}.js`)));
  await mkdir(path.dirname(out), { recursive: true });
  await writeFile(out, code, "utf8");
}
await rm(TMP, { recursive: true, force: true });
await transpile("src/sports/workflow/workflowState.ts", path.join(TMP, "src/sports/workflow/workflowState.js"));
const wf = await import(pathToFileURL(path.join(TMP, "src/sports/workflow/workflowState.js")).href);

const [panel, steps1, ui] = await Promise.all([
  read("src/sports/workflow/ForecastContractPanel.tsx"),
  read("src/sports/cockpit/cockpitSteps1.tsx"),
  read("src/sports/cockpit/cockpitUi.tsx"),
]);
const profileStep = steps1.slice(steps1.indexOf("03 Data Profile"), steps1.indexOf("04 Outliers"));
const featStep = steps1.slice(steps1.indexOf("06 Feature Engineering"), steps1.indexOf("07 Player Segmentation"));

// ------------------------------------------------------------- temporal policy authority
test("source evidence spans 2021–2025; current Gen-2 policy stays 2023/2024/2025", () => {
  assert.deepEqual(wf.GOVERNED_TEMPORAL.sourceEvidenceSeasons, [2021, 2022, 2023, 2024, 2025]);
  assert.deepEqual(wf.GOVERNED_TEMPORAL.developmentSeasons, [2023]);
  assert.equal(wf.GOVERNED_TEMPORAL.validationSeason, 2024);
  assert.equal(wf.GOVERNED_TEMPORAL.frozenSeason, 2025);
});

test("only 2023 is an eligible development start; 2021/2022 carry reasons", () => {
  assert.equal(wf.isEligibleDevelopmentStart(2023), true);
  assert.equal(wf.isEligibleDevelopmentStart(2021), false);
  assert.equal(wf.isEligibleDevelopmentStart(2022), false);
  assert.equal(wf.isEligibleDevelopmentStart(2025), false); // frozen never a dev start
  assert.match(wf.SEASON_ROLE_POLICY[2021].reason, /no pre-2021|Y−1|history/i);
  assert.match(wf.SEASON_ROLE_POLICY[2022].reason, /PRIOR_ONLY_HISTORY|prior-history|reserved/i);
  assert.equal(wf.SEASON_ROLE_POLICY[2021].role, "PRIOR HISTORY");
  assert.equal(wf.SEASON_ROLE_POLICY[2023].role, "DEVELOPMENT");
});

test("a revised temporal experiment is a separate draft — it never overwrites the registered contract", () => {
  const pid = "proj-temporal";
  // seed a governed contract
  localStorage.setItem(`asp-sports-forecast-contract:${pid}`, JSON.stringify({ projectId: pid, developmentSeasons: [2023], validationSeason: 2024, frozenSeason: 2025 }));
  wf.saveTemporalDraft({ projectId: pid, developmentSeasons: [2021, 2022, 2023], validationSeason: 2024, frozenSeason: 2025, excludePriorFamilies: true, rationale: "explore", savedAt: "now" });
  // draft stored under a DISTINCT key; contract untouched
  const draft = wf.loadTemporalDraft(pid);
  assert.deepEqual(draft.developmentSeasons, [2021, 2022, 2023]);
  assert.equal(draft.excludePriorFamilies, true);
  const contract = JSON.parse(localStorage.getItem(`asp-sports-forecast-contract:${pid}`));
  assert.deepEqual(contract.developmentSeasons, [2023]); // governed contract unchanged
  // project isolation
  assert.equal(wf.loadTemporalDraft("other-project"), null);
});

test("ForecastContractPanel shows source-vs-policy, honest earlier seasons, and a revised-draft path", () => {
  assert.ok(panel.includes("Source evidence") && panel.includes("Current Gen-2 model policy"));
  assert.ok(panel.includes("DEV_START_CANDIDATES = [2021, 2022, 2023]"));
  assert.ok(panel.includes("Every registered season exists"));
  assert.ok(panel.includes("not eligible")); // ineligible seasons labelled in the dropdown
  assert.ok(panel.includes("Create revised temporal experiment") && panel.includes("saveTemporalDraft"));
  assert.ok(panel.includes("2021 feasibility") && panel.includes("NOT AVAILABLE"));
  assert.ok(panel.includes("SourceEvidenceTimeline") && panel.includes('"FROZEN"'));
  assert.ok(panel.includes("Exclude prior-history feature families")); // explicit alternative A
});

// ------------------------------------------------------------- Data Profile EDA
test("Data Profile is an independent EDA workspace with real analytical summary cards", () => {
  assert.ok(profileStep.includes("EDA workspace"));
  for (const card of ['label="Predictors"', 'label="High-IV"', 'label="High-MI"', 'label="High drift"', 'label="Strong corr pairs"', 'label="Missingness"', 'label="Outlier concern"']) {
    assert.ok(profileStep.includes(card), `missing summary card ${card}`);
  }
});

test("Feature Explorer selects a feature and drives distribution / box / target / temporal tabs", () => {
  assert.ok(profileStep.includes("function FeatureExplorer"));
  assert.ok(profileStep.includes('"Distribution"') && profileStep.includes('"Box plot"') && profileStep.includes('"Target relationship"') && profileStep.includes('"Temporal stability"'));
  assert.ok(profileStep.includes("<Histogram") && profileStep.includes("<BoxPlotSingle") && profileStep.includes("targetConditioned"));
  // charts update by selected feature via the feature-detail endpoint
  assert.ok(profileStep.includes("`/cockpit/profile/feature/${selected}`"));
  // selection persists (stored in notes, not component-local)
  assert.ok(profileStep.includes('notes["eda.feature"]') && profileStep.includes('setNote("eda.feature"'));
});

test("IV above threshold gets green highlight; low IV does not; temporal shows dev vs OOT descriptive", () => {
  assert.ok(profileStep.includes("ivTone") && profileStep.includes('iv >= thr ? "emerald"'));
  assert.ok(profileStep.includes("bg-emerald-100 text-emerald-800")); // green emphasis
  assert.ok(profileStep.includes("IV ≥") && profileStep.includes("notable"));
  assert.ok(profileStep.includes("out-of-time descriptive") || profileStep.includes("descriptive monitoring"));
  assert.ok(profileStep.includes("never used to fit"));
});

test("correlation heatmap is development-fold, with a real strong-pairs count and no auto-exclusion", () => {
  assert.ok(profileStep.includes("<CorrelationHeatmap") && profileStep.includes('"/cockpit/correlation"'));
  assert.ok(profileStep.includes("strongPairCount"));
  assert.ok(profileStep.includes("not automatic exclusion"));
  assert.ok(ui.includes("export function CorrelationHeatmap"));
});

test("predictor table syncs Include/Exclude with the experiment and loads the explorer", () => {
  assert.ok(profileStep.includes("toggleFeature(r.name)"));       // shared experiment selection
  assert.ok(profileStep.includes("onClick={() => setSelected(r.name)}")); // click loads explorer
  assert.ok(profileStep.includes("Strongest corr"));              // correlation column
});

// ------------------------------------------------------------- Feature Engineering examples + A/B
test("every supported builder kind has a worked example", () => {
  // KINDS ids present in the builder
  const kindIds = [...steps1.matchAll(/\{ id: "([a-z]+)", label:/g)].map((m) => m[1]);
  const expected = ["arithmetic", "ratio", "interaction", "log", "power", "bin", "indicator", "calendar"];
  for (const k of expected) assert.ok(kindIds.includes(k), `builder missing kind ${k}`);
  for (const k of expected) assert.ok(featStep.includes(`${k}: { title:`), `no example for kind ${k}`);
});

test("Load example fills the builder draft but does not add to the experiment", () => {
  assert.ok(featStep.includes("Load this example") && featStep.includes("loadExample"));
  assert.ok(featStep.includes("setDraft(example.draft)"));
  assert.ok(featStep.includes("it does not add the feature"));
  // examples never call addEngineered
  const exampleBlock = featStep.slice(featStep.indexOf("View example"), featStep.indexOf("Live formula"));
  assert.ok(!exampleBlock.includes("addEngineered"));
});

test("quantile-bin example stays fold-local; ratio example uses safe division", () => {
  assert.ok(featStep.includes("learned on the 2023 development fold only"));
  assert.ok(featStep.includes("Safe division") && featStep.includes("NaN, handled as ordinary missingness"));
});

test("A/B actions are explicit with tooltips, and Input B hides when the op needs one input", () => {
  assert.ok(featStep.includes(">Use as A<") && featStep.includes(">Use as B<"));
  assert.ok(featStep.includes("Set this feature as Input A") && featStep.includes("Set this feature as Input B"));
  assert.ok(featStep.includes("showInputB && ") && featStep.includes("TWO_INPUT_KINDS.includes(draft.kind)"));
});

test("the builder draft is persistent (lives in the store notes, not component-local state)", () => {
  assert.ok(featStep.includes('FE_DRAFT_KEY = "fe.draft"') && featStep.includes("function useFeatureDraft"));
  assert.ok(featStep.includes("const [draft, setDraft] = useFeatureDraft()"));
  // engineered features + D3 immutability preserved
  assert.ok(featStep.includes("store.addEngineered(spec(), profile.data"));
});
