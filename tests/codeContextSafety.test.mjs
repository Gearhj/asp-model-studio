import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";
import { webcrypto } from "node:crypto";
import ts from "typescript";

const safetySource = fs.readFileSync("src/lib/codeContextSafety.ts", "utf8");
const panelSource = fs.readFileSync("src/components/StepPythonPanel.tsx", "utf8");
const workspaceSource = fs.readFileSync("src/components/code/CodeWorkspacePanel.tsx", "utf8");
const exportSource = fs.readFileSync("src/lib/notebookExport.ts", "utf8");

class MemoryStorage {
  #values = new Map();

  get length() {
    return this.#values.size;
  }

  key(index) {
    return [...this.#values.keys()][index] ?? null;
  }

  getItem(key) {
    return this.#values.has(key) ? this.#values.get(key) : null;
  }

  setItem(key, value) {
    this.#values.set(String(key), String(value));
  }

  removeItem(key) {
    this.#values.delete(String(key));
  }
}

const localStorage = new MemoryStorage();
const sessionStorage = new MemoryStorage();
let activeDataset = {
  headers: ["age", "income", "bad"],
  rows: [{ age: 41, income: 82_000, bad: 0 }],
  target: "bad",
  selected_columns: ["age", "income"],
  dataset_library: {
    datasetId: "ds_class",
    versionId: "v1",
    datasetName: "class_train.csv",
  },
};

const compiled = ts.transpileModule(safetySource, {
  compilerOptions: {
    target: ts.ScriptTarget.ES2021,
    module: ts.ModuleKind.CommonJS,
    esModuleInterop: true,
  },
  fileName: "codeContextSafety.ts",
}).outputText;
const moduleRecord = { exports: {} };
const sandbox = {
  module: moduleRecord,
  exports: moduleRecord.exports,
  require(specifier) {
    if (specifier === "./activeProjectContext") return { getCachedProjectId: () => "project-1" };
    if (specifier === "./authSession") return { getCachedUserId: () => "user-1" };
    if (specifier === "./localDataset") {
      return {
        loadLocalDataset: () => activeDataset,
        localDatasetVersion: (dataset) =>
          `${dataset?.target ?? ""}|${dataset?.rows?.length ?? 0}|${(dataset?.selected_columns ?? []).join(",")}`,
      };
    }
    throw new Error(`Unexpected test import: ${specifier}`);
  },
  localStorage,
  sessionStorage,
  window: { dispatchEvent() {} },
  CustomEvent: class CustomEvent {
    constructor(type) {
      this.type = type;
    }
  },
  crypto: webcrypto,
  console,
  Date,
  JSON,
  Math,
  encodeURIComponent,
};
vm.runInNewContext(compiled, sandbox, { filename: "codeContextSafety.js" });
const safety = moduleRecord.exports;

const scope = { userId: "user-1", projectId: "project-1", workflowPage: "/step02", language: "python" };
const contextA = safety.buildCurrentCodeContext({
  workflowPage: "/step02",
  language: "python",
  projectId: "project-1",
  dataset: activeDataset,
  generatedAt: "2026-07-27T10:00:00.000Z",
});
const contextALater = safety.buildCurrentCodeContext({
  workflowPage: "/step02",
  language: "python",
  projectId: "project-1",
  dataset: activeDataset,
  generatedAt: "2026-07-27T11:00:00.000Z",
});

assert.equal(
  safety.codeContextIdentity(contextA),
  safety.codeContextIdentity(contextALater),
  "generatedAt must be provenance, not context identity",
);
for (const field of [
  "datasetId",
  "datasetVersion",
  "datasetName",
  "target",
  "predictorManifestId",
  "workflowPage",
  "language",
  "generatedAt",
]) {
  assert.equal(typeof contextA[field], "string", `fingerprint must carry ${field}`);
}

const firstSave = safety.persistCodeDraft({
  scope,
  currentContext: contextA,
  code: "print('class')",
});
assert.equal(firstSave.ok, true);
assert.match(safety.buildCodeDraftStorageKey(scope), /user-1:project-1:%2Fstep02:python$/);

activeDataset = {
  ...activeDataset,
  target: "risk_flag",
  selected_columns: ["age"],
  dataset_library: {
    datasetId: "ds_heloc",
    versionId: "v2",
    datasetName: "heloc_train.csv",
  },
};
const contextB = safety.buildCurrentCodeContext({
  workflowPage: "/step02",
  language: "python",
  projectId: "project-1",
  dataset: activeDataset,
});
const historical = safety.loadCodeDraft({ scope }).draft;
const mismatch = safety.evaluateCodeDraftContext(historical, contextB, historical.code);
assert.equal(mismatch.warning, "This edited code was created for a different dataset or target.");
assert.equal(mismatch.canUseAsCurrent, false);
assert.ok(mismatch.details.some((detail) => detail.field === "datasetId"));
assert.ok(mismatch.details.some((detail) => detail.field === "target"));

const blockedSave = safety.persistCodeDraft({
  scope,
  currentContext: contextB,
  code: historical.code,
});
assert.equal(blockedSave.ok, false, "stale code must not save as current without acknowledgement");

const acknowledged = safety.acknowledgeCodeDraftContext({
  scope,
  currentContext: contextB,
  code: historical.code,
});
assert.ok(acknowledged?.acknowledgement);
assert.equal(
  safety.evaluateCodeDraftContext(acknowledged, contextB, acknowledged.code).canUseAsCurrent,
  true,
);
assert.equal(
  safety.evaluateCodeDraftContext(acknowledged, contextB, `${acknowledged.code}\n# edited`).canUseAsCurrent,
  false,
  "editing code must invalidate the exact-pair acknowledgement",
);

const reset = safety.resetCodeDraftForCurrentContext({
  scope,
  currentContext: contextB,
  generatedCode: "print('generated for HELOC')",
  historicalCode: "print('class')\n# retained edit",
});
assert.ok(reset.archivedDraft?.archivedAt, "reset must archive, not overwrite, the historical draft");
assert.equal(reset.archivedDraft?.code, "print('class')\n# retained edit");
assert.equal(reset.draft.context.datasetId, "ds_heloc");
const storedHistory = JSON.parse(localStorage.getItem(safety.buildCodeDraftStorageKey(scope)));
assert.equal(storedHistory.drafts.length, 2);
assert.ok(storedHistory.drafts.some((draft) => draft.archivedAt && draft.code.includes("retained edit")));

const sasScope = { ...scope, language: "sas" };
assert.notEqual(
  safety.buildCodeDraftStorageKey(scope),
  safety.buildCodeDraftStorageKey(sasScope),
  "Python and SAS drafts must remain independent",
);

const legacyKey = "modeling-tool-user-python-code-by-step";
localStorage.setItem(legacyKey, JSON.stringify({ legacy_eda: "print('legacy')" }));
const legacyScope = { ...scope, workflowPage: "/legacy-eda" };
const legacy = safety.loadCodeDraft({
  scope: legacyScope,
  legacyStorageKey: legacyKey,
  legacySectionKey: "legacy_eda",
});
assert.equal(legacy.source, "legacy_unverified");
assert.equal(legacy.draft.context, null, "legacy code must never be silently assigned the current context");
assert.equal(
  JSON.parse(localStorage.getItem(legacyKey)).legacy_eda,
  "print('legacy')",
  "reading legacy code must preserve the raw historical source",
);

safety.writeEdaCodeContextSeed("project-1", {
  datasetId: "ds_heloc",
  datasetVersion: "v2",
  datasetName: "heloc_train.csv",
  target: "risk_flag",
  predictorManifestId: "pm-authorized-v7",
  generatedAt: "2026-07-27T12:00:00.000Z",
});
const governedContext = safety.buildCurrentCodeContext({
  workflowPage: "/step02",
  language: "python",
  projectId: "project-1",
  dataset: activeDataset,
});
assert.equal(governedContext.predictorManifestId, "pm-authorized-v7");

// Boundary wiring: the shared evaluation gates save/run and notebook export.
assert.match(panelSource, /pythonContextEvaluation\.canUseAsCurrent/);
assert.match(panelSource, /sasContextEvaluation\.canUseAsCurrent/);
assert.match(panelSource, /if \(!persist\("python"\)\) return/);
assert.match(panelSource, /if \(!persist\("sas"\)\) return/);
assert.match(panelSource, /Historical Code Copy/);
assert.match(workspaceSource, /Keep historical draft/);
assert.match(workspaceSource, /Reset to current generated code/);
assert.match(workspaceSource, /View diff/);
assert.match(workspaceSource, /Save as separate notebook version \(copy\)/);
assert.match(workspaceSource, /Acknowledge exact context pair/);
assert.match(exportSource, /Historical User-Edited Python Code Omitted/);
assert.match(exportSource, /Historical User-Edited SAS Code Omitted/);
assert.match(exportSource, /Acknowledged Historical User-Edited Python Code/);
assert.match(exportSource, /evaluation\.canUseAsCurrent/);
assert.doesNotMatch(
  safetySource.slice(
    safetySource.indexOf("export function codeContextIdentity"),
    safetySource.indexOf("export function codeDraftIdentity"),
  ),
  /generatedAt: context\.generatedAt/,
);

console.log("codeContextSafety.test.mjs: all checks passed.");
