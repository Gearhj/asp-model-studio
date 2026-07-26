// ATLAS EDA Governed Analysis Scope and Evidence Integrity, Phase 1 -- frontend tests.
//
// The browser must never decide whether an analysis is governed. These tests
// assert the two halves of that: the client CONSUMES a server scope (and has no
// path to assert one), and the UI states the scope, the eligibility, and the
// reason a governed action is unavailable in visible text.
import assert from "node:assert/strict";
import { mkdir, readFile, rm, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import test from "node:test";
import ts from "typescript";

const ROOT = new URL("..", import.meta.url);
const TMP_DIR = fileURLToPath(new URL("../.tmp/analysis-scope-tests", import.meta.url));

async function transpile(sourcePath, outputName) {
  const source = await readFile(new URL(sourcePath, ROOT), "utf8");
  const patched = source.replace(/import\.meta\.env\?\.\w+ as string \| undefined/g, "undefined");
  const output = ts.transpileModule(patched, {
    compilerOptions: { module: ts.ModuleKind.ES2022, target: ts.ScriptTarget.ES2022 },
  }).outputText;
  const outPath = path.join(TMP_DIR, outputName);
  await mkdir(path.dirname(outPath), { recursive: true });
  await writeFile(outPath, output, "utf8");
  return import(pathToFileURL(outPath).href);
}

await rm(TMP_DIR, { recursive: true, force: true });
const lib = await transpile("src/lib/targetIntelligence.ts", "targetIntelligence.js");
const api = await transpile("src/lib/targetIntelligenceApi.ts", "targetIntelligenceApi.js");

const banner = await readFile(new URL("src/components/eda/AnalysisScopeBanner.tsx", ROOT), "utf8");
const workspace = await readFile(new URL("src/components/eda/TargetIntelligenceWorkspace.tsx", ROOT), "utf8");
const findingsPanel = await readFile(new URL("src/components/eda/TargetFindingsPanel.tsx", ROOT), "utf8");
const predictorPanel = await readFile(new URL("src/components/eda/TargetByPredictorPanel.tsx", ROOT), "utf8");
const hooks = await readFile(new URL("src/lib/useTargetIntelligence.ts", ROOT), "utf8");
const packageJson = JSON.parse(await readFile(new URL("package.json", ROOT), "utf8"));

const GOVERNED_SCOPE = {
  contractVersion: "analysis-scope/1",
  mode: "governed_version",
  label: "Governed Dataset Version",
  projectId: "proj-1",
  datasetId: "ds-class-train",
  datasetVersionId: "v_2026",
  workspaceDatasetId: null,
  datasetName: "CLASS_TRAIN",
  datasetFingerprint: null,
  artifactChecksum: "sha-abc",
  target: "Class",
  populationRows: 170884,
  exact: true,
  sampled: false,
  immutableVersion: true,
  analysisSource: "analytics.target_assessment",
  evidenceEligible: true,
  mddEligible: true,
  disclosure: "Governed Dataset Version.",
  resolvedAt: "2026-07-25T00:00:00Z",
};

const DRAFT_SCOPE = {
  ...GOVERNED_SCOPE,
  mode: "workspace_draft",
  label: "Workspace Draft Analysis",
  datasetId: null,
  datasetVersionId: null,
  workspaceDatasetId: "wsfp_abc",
  datasetFingerprint: "wsfp_abc",
  artifactChecksum: null,
  immutableVersion: false,
  evidenceEligible: false,
  mddEligible: false,
  disclosure: "Workspace Draft Analysis. Not tied to an immutable dataset version.",
};

// --- governed / draft scope rendering --------------------------------------

test("governed scope renders a positive, restrained governed state with exact identity", () => {
  assert.match(banner, /Governed Dataset Version/);
  assert.match(banner, /border-emerald-300 bg-emerald-50/, "Governed uses restrained green.");
  for (const testId of [
    "analysis-scope-banner",
    "analysis-scope-label",
    "analysis-scope-disclosure",
    "scope-dataset-name",
    "scope-dataset-id",
    "scope-version-id",
    "scope-immutable",
    "scope-population-rows",
    "scope-exact",
    "scope-eligibility",
  ]) {
    assert.ok(banner.includes(`"${testId}"`), `The scope banner must expose ${testId}.`);
  }
  assert.match(banner, /Immutable \/ version-pinned/);
  // No filesystem path is ever surfaced.
  assert.doesNotMatch(banner, /data_full|artifacts\/|fullDataPath/);
});

test("draft scope renders an amber, non-alarming governance state", () => {
  assert.match(banner, /Workspace Draft Analysis/);
  assert.match(banner, /border-amber-300 bg-amber-50/, "Draft uses restrained amber, not red.");
  assert.doesNotMatch(banner, /danger|breach|violation|forbidden/i, "A draft is a governance state, not a security error.");
  assert.match(banner, /Not version-pinned/);
  assert.match(banner, /Invalidated by/);
  assert.match(banner, /Changing or replacing the workspace dataset/);
  assert.ok(banner.includes('"scope-workspace-fingerprint"'));
  assert.ok(banner.includes('"scope-mdd"'));
});

test("the disclosure is visible text, never tooltip-only", () => {
  // Rendered as a paragraph, not a title/aria-label attribute.
  assert.match(banner, /<p[^>]*data-testid="analysis-scope-disclosure"/);
  assert.doesNotMatch(banner, /title=\{scope\?\.disclosure\}/);
  assert.match(banner, /aria-live="polite"/, "Scope changes are announced.");
  assert.match(banner, /role="status"/);
});

test("a registration CTA exists and is keyboard-accessible", () => {
  assert.ok(banner.includes('"analysis-scope-register-cta"'));
  assert.match(banner, /<button\s+type="button"[\s\S]{0,240}analysis-scope-register-cta/);
  assert.match(banner, /Register or Link a Dataset Version/);
  // EDA routes to the existing Data Acquisition flow rather than building a
  // second registration system.
  assert.match(workspace, /window\.location\.assign\("\/step01"\)/);
  assert.doesNotMatch(workspace, /createDataset|registerDataset|uploadDataset/);
});

// --- evidence eligibility ---------------------------------------------------

test("the evidence control is disabled in draft and the reason is visible", () => {
  assert.equal(lib.evidenceDisabledReason(GOVERNED_SCOPE, false), null, "Governed scope enables the action.");
  const draftReason = lib.evidenceDisabledReason(DRAFT_SCOPE, false);
  assert.match(draftReason, /Workspace Draft Analysis/);
  assert.match(draftReason, /Register or link/i);
  assert.match(lib.evidenceDisabledReason(GOVERNED_SCOPE, true), /Resolving the registered dataset version/);
  assert.match(lib.evidenceDisabledReason(null, false), /not been resolved/);

  assert.match(findingsPanel, /disabled=\{saving \|\| !!evidenceDisabledReason\}/);
  assert.ok(findingsPanel.includes('"target-evidence-disabled-reason"'));
  // Rendered as text, with an aria link from the control to the reason.
  assert.match(findingsPanel, /aria-describedby=\{evidenceDisabledReason \? "target-evidence-disabled-reason" : undefined\}/);
  assert.ok(findingsPanel.includes('"target-evidence-register-cta"'), "The dead end must have an exit.");
});

test("governed evidence is requested from the server and asserts nothing", async () => {
  let captured = null;
  globalThis.fetch = async (url, init) => {
    captured = { url: String(url), body: JSON.parse(init.body) };
    return {
      ok: true,
      status: 200,
      json: async () => ({
        ok: true, evidenceId: "ev-target-intel-abc", analysisScope: GOVERNED_SCOPE,
        mddEligible: true, createdAt: "2026-07-25T00:00:00Z",
      }),
    };
  };
  const result = await api.saveGovernedTargetEvidence({
    projectId: "proj-1", datasetId: "ds-class-train", versionId: "v_2026", target: "Class", eventValue: 1,
  });
  assert.equal(result.evidenceId, "ev-target-intel-abc");
  assert.match(captured.url, /\/analytics\/target-evidence$/, "A dedicated governed command, not generic evidence save.");

  // The request carries analytical SELECTION only -- no governance claim.
  for (const forbidden of [
    "analysisScope", "evidenceEligible", "mddEligible", "artifactChecksum", "scopeMode",
    "eventCount", "nonEventCount", "eventRate", "classBalance", "confidenceInterval", "populationRows",
  ]) {
    assert.ok(!(forbidden in captured.body), `The client must not send ${forbidden}.`);
  }
  assert.deepEqual(
    Object.keys(captured.body).sort(),
    [
      "chartSpecification", "datasetId", "eventValue", "nonEventValue", "notes", "predictor",
      "predictorAnalysisType", "predictorBands", "predictorIncludeMissing", "predictorTopCategories",
      "projectId", "segmentField", "target", "timeField", "title", "versionId",
    ]
  );

  // The workspace no longer writes evidence through the generic browser path.
  assert.doesNotMatch(workspace, /createEvidence\(\{/, "Client-asserted provenance must be gone.");
  assert.match(workspace, /saveGovernedTargetEvidence/);
});

// --- draft export disclosure ------------------------------------------------

test("a draft bounded export is prominently marked and cannot pass for governed", () => {
  assert.deepEqual(lib.DRAFT_EXPORT_MARKERS, [
    "Workspace Draft",
    "Not Governed Evidence",
    "Not Version-Pinned",
    "Not MDD Eligible",
  ]);

  const draftPayload = lib.buildTargetEvidencePayload({
    projectId: "p", datasetId: "", versionId: "", datasetName: "upload.csv", target: "Class",
    scope: DRAFT_SCOPE, assessment: null, governance: [], predictorAnalysis: null,
    timeField: "", segmentField: "", chartSpecification: {}, userId: "u", capturedAt: "2026-07-25T00:00:00Z",
  });
  assert.equal(draftPayload.scopeMode, "workspace_draft");
  assert.equal(draftPayload.governed, false);
  assert.equal(draftPayload.evidenceEligible, false);
  assert.equal(draftPayload.mddEligible, false);
  assert.deepEqual(draftPayload.markers, lib.DRAFT_EXPORT_MARKERS);
  assert.equal(draftPayload.datasetIdentity.versionId, null, "A draft export must not carry a version.");
  assert.equal(draftPayload.datasetIdentity.workspaceFingerprint, "wsfp_abc");

  const governedPayload = lib.buildTargetEvidencePayload({
    projectId: "p", datasetId: "ds-class-train", versionId: "v_2026", datasetName: "CLASS_TRAIN", target: "Class",
    scope: GOVERNED_SCOPE, assessment: null, governance: [], predictorAnalysis: null,
    timeField: "", segmentField: "", chartSpecification: {}, userId: "u", capturedAt: "2026-07-25T00:00:00Z",
  });
  assert.equal(governedPayload.governed, true);
  assert.deepEqual(governedPayload.markers, []);
  assert.equal(governedPayload.datasetIdentity.versionId, "v_2026");
  assert.equal(governedPayload.datasetIdentity.artifactChecksum, "sha-abc");

  // The downloaded filename itself declares the draft status.
  assert.match(workspace, /WORKSPACE-DRAFT-not-governed-evidence-target-/);
  assert.ok(findingsPanel.includes('"target-draft-export-warning"'));
});

// --- finding labels ---------------------------------------------------------

test("governed and draft findings are labeled distinctly and honestly", () => {
  assert.match(findingsPanel, /governed_version: "border-emerald-300/);
  assert.match(findingsPanel, /workspace_draft: "border-amber-300/);
  assert.match(findingsPanel, /legacy_unscoped: "border-slate-300/);
  assert.ok(findingsPanel.includes('"target-finding-scope-label"'));
  assert.ok(findingsPanel.includes('"target-finding-identity"'));
  // A draft finding must never be described as stored against a version.
  assert.match(findingsPanel, /workspace dataset, not version-pinned/);
  assert.match(findingsPanel, /scope unknown \(recorded before version pinning\)/);
  assert.match(findingsPanel, /Add Governed Finding/);
  assert.match(findingsPanel, /Add Draft Finding/);
  assert.match(
    findingsPanel,
    /A draft finding is NOT stored against an immutable dataset version/,
    "The draft copy must state the limitation plainly."
  );
  assert.ok(findingsPanel.includes('"target-legacy-findings"'), "Legacy rows stay visible but separate.");
  // Carry-forward is an explicit copy action, never automatic.
  assert.ok(findingsPanel.includes('"target-finding-promote"'));
  assert.match(findingsPanel, /Copy to governed version/);
  assert.doesNotMatch(workspace, /autoPromote|promoteAll|automaticallyPromote/);
});

test("the workspace sends draft findings without governed identity", () => {
  assert.match(
    workspace,
    /datasetId: governed \? governedScope\?\.datasetId \?\? "" : "",/,
    "A draft finding must not carry a dataset id."
  );
  assert.match(workspace, /workspaceFingerprint: governed \? null : draftScope\?\.datasetFingerprint \?\? null,/);
});

// --- scope-sensitive request identity ---------------------------------------

test("scope participates in request identity so a draft result cannot land in a governed panel", () => {
  const governedKey = api.buildTargetAssessmentKey({
    projectId: "p", datasetId: "ds", versionId: "v", target: "Class",
  });
  const draftKey = api.buildTargetAssessmentKey({
    projectId: "p", datasetId: "", versionId: "", target: "Class",
  });
  assert.match(governedKey, /^governed_version\|/);
  assert.match(draftKey, /^workspace_draft\|/);
  assert.notEqual(governedKey, draftKey);

  // Two different uploaded datasets are different draft identities.
  const first = api.buildTargetByPredictorKey({
    projectId: "p", datasetId: "", versionId: "", workspaceFingerprint: "wsfp_a",
    target: "Class", predictor: "V4", analysisType: "numeric_quantile",
  });
  const second = api.buildTargetByPredictorKey({
    projectId: "p", datasetId: "", versionId: "", workspaceFingerprint: "wsfp_b",
    target: "Class", predictor: "V4", analysisType: "numeric_quantile",
  });
  assert.notEqual(first, second);

  assert.equal(lib.scopeIdentity(GOVERNED_SCOPE) === lib.scopeIdentity(DRAFT_SCOPE), false);
  assert.match(lib.scopeIdentity(GOVERNED_SCOPE), /^scope\|governed_version\|/);
});

test("findings reload on scope change and never show the previous scope's rows", () => {
  // Scope mode and fingerprint are part of the hook's identity...
  assert.match(hooks, /scope\.scopeMode \?\? ""/);
  assert.match(hooks, /scope\.workspaceFingerprint \?\? ""/);
  // ...and the list is cleared immediately when it changes.
  assert.match(
    hooks,
    /\/\/ Clear immediately[\s\S]{0,200}setFindings\(\[\]\);\s*\n\s*setLegacyFindings\(\[\]\);/,
    "A scope change must clear the previous scope's findings before the new query lands."
  );
});

// --- event-majority semantics ------------------------------------------------

test("event-majority copy is present and no rare-event language is used for it", () => {
  assert.ok(workspace.includes('"target-event-is-majority"'));
  assert.match(workspace, /The configured event is the <strong>majority<\/strong> class/);
  assert.match(workspace, /the <strong>non-event<\/strong> class is the\s*\n?\s*minority class here/);
  assert.match(workspace, /This is not a rare-event condition for the configured positive value/);

  // Prevalence and imbalance are shown as two separate statements.
  assert.ok(workspace.includes('"target-prevalence-label"'));
  assert.ok(workspace.includes('"target-imbalance-label"'));
  assert.match(workspace, /Event prevalence: \{imbalance\.eventPrevalence\?\.label/);
  assert.match(workspace, /Class imbalance: \{imbalance\.classImbalance\?\.label/);

  // Ratios are explicitly oriented -- never a bare "imbalance ratio".
  assert.ok(workspace.includes('"ratio-non-events-per-event"'));
  assert.ok(workspace.includes('"ratio-majority-to-minority"'));
  assert.ok(workspace.includes('"target-ratio-orientation"'));
  assert.match(workspace, /Non-events per event/);
  assert.match(workspace, /Majority-to-minority ratio/);
  assert.match(workspace, /independent of which class is configured as the positive value/);

  // Both threshold tables are inspectable.
  assert.ok(workspace.includes('"target-prevalence-thresholds"'));
  assert.ok(workspace.includes('"target-imbalance-thresholds"'));
  assert.ok(workspace.includes('"target-single-class"'));
});

test("section tone follows event prevalence, not minority share", () => {
  assert.match(
    workspace,
    /IMBALANCE_TONES\[imbalance\?\.eventPrevalence\?\.severity \?\? imbalance\?\.severity \?\? "unknown"\]/,
    "A common event must not get an alarming treatment merely because classes are uneven."
  );
});

// --- transition, accessibility, hygiene -------------------------------------

test("no governed state is claimed before the server confirms it", () => {
  assert.match(workspace, /const governedScope: AnalysisScope \| null = isGovernedScope\(assessment\.result\?\.analysisScope\)/);
  assert.match(workspace, /scopeResolution: ScopeResolution = governedScope\s*\n?\s*\? "governed"/);
  // While resolving, the banner is not green and says the figures are still draft.
  assert.match(banner, /Resolving Governed Dataset Version/);
  assert.match(banner, /still the workspace draft result and are not governed until this completes/);
  // Governed figures are only read from the governed response.
  assert.match(workspace, /const balance = governed\s*\n?\s*\? assessment\.result\?\.classBalance \?\? null/);
  // A materially different registered result is reconciled, not silently swapped.
  assert.ok(banner.includes('"analysis-scope-reconciliation"'));
  assert.match(workspace, /The governed figures shown below come from the registered version|const reconciliation = useMemo/);
});

test("no decorative animation, fake progress, or console noise was added", () => {
  for (const source of [banner, workspace, findingsPanel, predictorPanel]) {
    assert.doesNotMatch(source, /confetti|fakeProgress|animate-bounce|animate-ping|marquee/i);
    assert.doesNotMatch(source, /console\.(log|warn|error|debug)\(/);
  }
  // The only spinner is a genuine in-flight indicator.
  assert.match(banner, /LoaderCircle size=\{17\} className="animate-spin"/);
  assert.equal(
    packageJson.scripts["test:analysis-scope"],
    "node tests/analysisScope.test.mjs && .\\.venv\\Scripts\\python.exe tests\\analysis_scope_test.py"
  );
});
