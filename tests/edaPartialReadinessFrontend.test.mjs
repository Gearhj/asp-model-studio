import assert from "node:assert/strict";
import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { pathToFileURL } from "node:url";
import test, { after } from "node:test";
import ts from "typescript";

const ROOT = new URL("..", import.meta.url);
const TEMP = await mkdtemp(path.join(tmpdir(), "atlas-eda-readiness-"));

after(async () => {
  await rm(TEMP, { recursive: true, force: true });
});

const readinessSource = await readFile(
  new URL("src/lib/edaWorkspaceReadiness.ts", ROOT),
  "utf8",
);
const readinessTarget = path.join(TEMP, "edaWorkspaceReadiness.mjs");
await writeFile(
  readinessTarget,
  ts.transpileModule(readinessSource, {
    compilerOptions: {
      module: ts.ModuleKind.ES2022,
      target: ts.ScriptTarget.ES2022,
    },
  }).outputText,
  "utf8",
);
const { readBlockedEdaWorkspaceReadiness } = await import(
  pathToFileURL(readinessTarget).href
);

const step02 = (
  await readFile(new URL("src/steps/Step02_EDA.tsx", ROOT), "utf8")
).replace(/\r\n/g, "\n");

test("HTTP 200 partial readiness is classified as an Analysis Partition blocker", () => {
  const blocked = readBlockedEdaWorkspaceReadiness({
    ok: true,
    partial: true,
    governed_readiness: {
      status: "blocked",
      code: "analysis_partition_required",
      message: "Confirm the governed partition.",
      recovery: "Return to Data Acquisition.",
      stale_artifacts: ["eda", 42, "", "documentation"],
      target_directed_available: false,
      structural_overview_available: true,
      final_holdout_accessed: false,
    },
  });

  assert.deepEqual(blocked, {
    code: "analysis_partition_required",
    message: "Confirm the governed partition.",
    recovery: "Return to Data Acquisition.",
    staleArtifacts: ["eda", "documentation"],
    structuralOverviewAvailable: true,
    targetDirectedAvailable: false,
    finalHoldoutAccessed: false,
  });
});

test("blocked readiness fails closed even if a backend omits the partial flag", () => {
  const blocked = readBlockedEdaWorkspaceReadiness({
    ok: true,
    governed_readiness: {
      status: "blocked",
      target_directed_available: false,
    },
  });

  assert.equal(blocked?.code, "analysis_partition_required");
  assert.match(blocked?.message ?? "", /Analysis Partition/i);
  assert.match(blocked?.recovery ?? "", /Data Acquisition/i);
});

test("an ordinary complete Overview response is not classified as blocked", () => {
  assert.equal(
    readBlockedEdaWorkspaceReadiness({
      ok: true,
      partial: false,
      section: "overview",
      governed_readiness: {
        status: "current",
        target_directed_available: true,
      },
    }),
    null,
  );
});

test("Step 2 admits partial readiness to the blocker shell, not analytical state", () => {
  const responseStart = step02.indexOf("assertExactDatasetIdentity(");
  const analyticalAdmission = step02.indexOf(
    "writeEdaCodeContextSeed(projectId",
    responseStart,
  );
  const readinessCheck = step02.indexOf(
    "readBlockedEdaWorkspaceReadiness(payload)",
    responseStart,
  );
  const blockedBranch = step02.slice(readinessCheck, analyticalAdmission);

  assert.ok(responseStart >= 0, "exact response identity check is missing");
  assert.ok(
    readinessCheck > responseStart && readinessCheck < analyticalAdmission,
    "partial readiness must be checked before analytical state is admitted",
  );
  assert.match(blockedBranch, /setSections\(\{\}\)/);
  assert.match(blockedBranch, /setDocumentationState\(null\)/);
  assert.match(blockedBranch, /setDocumentationEvidence\(\[\]\)/);
  assert.match(blockedBranch, /return null/);
  assert.doesNotMatch(
    blockedBranch,
    /setSections\(\(current\)/,
    "the partial payload must not be stored as the Overview",
  );
});

test("the partial-readiness render path replaces ordinary Overview and documentation UI", () => {
  assert.match(
    step02,
    /analysisPartitionBlocker\s*\?\s*\(\s*<AnalysisPartitionRequiredShell[\s\S]*?\)\s*:\s*\(\s*<div className="eda-premium-page">/,
  );
  assert.match(step02, /data-testid="eda-analysis-partition-required-shell"/);
  assert.match(
    step02,
    /data-testid="eda-analysis-partition-data-acquisition-action"/,
  );
  assert.match(
    step02,
    /to=\{projectWorkflowRoute\(projectId, "\/step01#analysis-partition-readiness"\)\}/,
  );
  assert.match(
    step02,
    /has not started the ordinary EDA Overview or[\s\S]*documentation workflow/,
  );
});

test("documentation and secondary analytical requests wait for a complete Overview", () => {
  const documentationGate = step02.indexOf("if (!overview) {");
  const documentationRequest = step02.indexOf(
    "getEdaDocumentationState(projectId",
    documentationGate,
  );
  assert.ok(
    documentationGate >= 0 && documentationGate < documentationRequest,
    "documentation must be gated behind a complete Overview",
  );
  assert.match(
    step02,
    /activeTab !== "overview" && datasetIdentity && overview/,
    "secondary analytical sections must not start before Overview readiness is current",
  );
});
