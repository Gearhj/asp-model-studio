import assert from "node:assert/strict";
import { mkdir, readFile, rm, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import test from "node:test";
import ts from "typescript";

const ROOT = new URL("..", import.meta.url);
const TMP_DIR = fileURLToPath(new URL("../.tmp/decision-journal-tests", import.meta.url));

class QuotaStorage {
  constructor(limit = Infinity) {
    this.map = new Map();
    this.limit = limit;
  }
  get length() {
    return this.map.size;
  }
  clear() {
    this.map.clear();
  }
  getItem(key) {
    return this.map.has(key) ? this.map.get(key) : null;
  }
  key(index) {
    return Array.from(this.map.keys())[index] ?? null;
  }
  removeItem(key) {
    this.map.delete(key);
  }
  setItem(key, value) {
    const text = String(value);
    if (text.length > this.limit) {
      throw new DOMException("Setting the value exceeded the quota.", "QuotaExceededError");
    }
    this.map.set(String(key), text);
  }
}

const browserEvents = [];
globalThis.localStorage = new QuotaStorage();
globalThis.sessionStorage = new QuotaStorage();
globalThis.CustomEvent = class CustomEvent {
  constructor(type, init = {}) {
    this.type = type;
    this.detail = init.detail;
  }
};
globalThis.window = {
  dispatchEvent(event) {
    browserEvents.push(event);
    return true;
  },
};

async function transpileSource(sourcePath, outputPath) {
  const source = await readFile(new URL(sourcePath, ROOT), "utf8");
  let output = ts.transpileModule(source, {
    compilerOptions: {
      jsx: ts.JsxEmit.ReactJSX,
      module: ts.ModuleKind.ES2022,
      target: ts.ScriptTarget.ES2022,
    },
  }).outputText;
  output = output.replace(/from\s+["'](\.{1,2}\/[^"']+)["']/g, (match, specifier) => {
    if (specifier.endsWith(".js") || specifier.endsWith(".json") || specifier.endsWith(".css")) return match;
    return match.replace(specifier, `${specifier}.js`);
  });
  await mkdir(path.dirname(outputPath), { recursive: true });
  await writeFile(outputPath, output, "utf8");
}

async function compileModules() {
  await rm(TMP_DIR, { recursive: true, force: true });
  await mkdir(path.join(TMP_DIR, "src/config"), { recursive: true });
  await writeFile(
    path.join(TMP_DIR, "src/config/brand.js"),
    'export const BRAND = { productName: "ATLAS", productSubtitle: "Enterprise AI Model Development Platform" };\n',
    "utf8"
  );
  await mkdir(path.join(TMP_DIR, "src/lib"), { recursive: true });
  await mkdir(path.join(TMP_DIR, "src/state"), { recursive: true });
  await writeFile(
    path.join(TMP_DIR, "src/lib/serverPersistence.js"),
    "export async function saveDecisionToDatabase() { return null; }\n",
    "utf8"
  );
  await writeFile(
    path.join(TMP_DIR, "src/state/useWorkflowStore.js"),
    "export const useWorkflowStore = { getState: () => ({ projectId: null }) };\n",
    "utf8"
  );
  await transpileSource("src/lib/localDataset.ts", path.join(TMP_DIR, "src/lib/localDataset.js"));
  await transpileSource("src/lib/projectContext.ts", path.join(TMP_DIR, "src/lib/projectContext.js"));
  await transpileSource("src/lib/decisionJournal.ts", path.join(TMP_DIR, "src/lib/decisionJournal.js"));
  return {
    decisionJournal: await import(pathToFileURL(path.join(TMP_DIR, "src/lib/decisionJournal.js")).href),
  };
}

const modules = await compileModules();

function resetStorage(limit = Infinity) {
  globalThis.localStorage = new QuotaStorage(limit);
  globalThis.sessionStorage = new QuotaStorage(limit);
  browserEvents.length = 0;
}

test("logDecision compacts old entries instead of throwing on localStorage quota", () => {
  resetStorage(12_000);
  const oldEntries = Array.from({ length: 300 }, (_, index) => ({
    id: `old-${index}`,
    timestamp: "2026-07-03T00:00:00.000Z",
    workflowStep: "Data Acquisition",
    actionType: "workflow_setting_changed",
    subject: `entry-${index}`,
    previousValue: "x".repeat(2000),
    newValue: "y".repeat(2000),
    systemRecommendation: "z".repeat(2000),
    followStatus: "unknown",
    userReason: "",
  }));
  localStorage.map.set(modules.decisionJournal.DECISION_JOURNAL_KEY, JSON.stringify(oldEntries));

  assert.doesNotThrow(() => {
    modules.decisionJournal.logDecision({
      workflowStep: "Data Acquisition",
      actionType: "target_variable_selected",
      subject: "Target variable",
      previousValue: "",
      newValue: "Class",
    });
  });

  const saved = JSON.parse(localStorage.getItem(modules.decisionJournal.DECISION_JOURNAL_KEY));
  assert.ok(saved.length <= 10);
  assert.equal(saved[0].newValue, "Class");
  assert.equal(browserEvents.some((event) => event.type === "decision-journal-updated"), true);
});

test("saveDecisionJournal is fail-soft under severe quota pressure", () => {
  resetStorage(1500);
  assert.doesNotThrow(() => {
    modules.decisionJournal.saveDecisionJournal(
      Array.from({ length: 50 }, (_, index) => ({
        id: `entry-${index}`,
        timestamp: "2026-07-03T00:00:00.000Z",
        workflowStep: "Model Training",
        actionType: "workflow_setting_changed",
        subject: "large entry",
        previousValue: "a".repeat(2000),
        newValue: "b".repeat(2000),
        systemRecommendation: "c".repeat(2000),
        followStatus: "unknown",
        userReason: "",
      }))
    );
  });
});
