// Durable Project Context autosave and restoration.
//
// Root cause under test: Step00_ProjectContext only persisted from "Continue"
// and "Mark Page Complete", and hydrated from a single unscoped localStorage
// key -- so leaving by any other route lost every keystroke, and stored backend
// content was never restored on reopen.
import assert from "node:assert/strict";
import { mkdir, readFile, rm, writeFile } from "node:fs/promises";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import test from "node:test";
import ts from "typescript";

const ROOT = new URL("..", import.meta.url);
const TMP_DIR = fileURLToPath(new URL("../.tmp/project-context-persistence-tests", import.meta.url));

async function compile(relativePath, outputName) {
  const source = await readFile(new URL(relativePath, ROOT), "utf8");
  const patched = source
    .replace(/import\.meta\.env\?\.\w+ as string \| undefined/g, "undefined")
    .replace(/from "\.\/projectContext"/g, 'from "./projectContext.js"');
  const output = ts.transpileModule(patched, {
    compilerOptions: { module: ts.ModuleKind.ES2022, target: ts.ScriptTarget.ES2022 },
  }).outputText;
  const outPath = path.join(TMP_DIR, outputName);
  await mkdir(path.dirname(outPath), { recursive: true });
  await writeFile(outPath, output, "utf8");
  return outPath;
}

await rm(TMP_DIR, { recursive: true, force: true });
await compile("src/lib/projectContext.ts", "projectContext.js");
const persistencePath = await compile("src/lib/projectContextPersistence.ts", "projectContextPersistence.js");

// Minimal localStorage shim for the convenience-cache functions.
globalThis.localStorage = {
  _data: new Map(),
  getItem(key) { return this._data.has(key) ? this._data.get(key) : null; },
  setItem(key, value) { this._data.set(key, String(value)); },
  removeItem(key) { this._data.delete(key); },
};

const lib = await import(pathToFileURL(persistencePath).href);

const NARRATIVE = {
  businessObjective: "Reduce authorization fraud losses.",
  intendedModelUse: "Analyst review queue prioritization.",
  targetDefinition: "Confirmed fraudulent authorization.",
  populationDefinition: "All card-present authorizations.",
  observationWindow: "Attributes available at authorization time.",
  performanceWindow: "Outcome finalized within 90 days.",
  modelingMissionSummary: "First line.\n\nSecond paragraph with detail.",
};

const GOVERNANCE = {
  approvedUses: "Queue prioritization only.",
  prohibitedUses: "No automatic decline.",
  humanReviewRequired: "Analyst reviews every declined case.",
  overrideAuthority: "Fraud operations manager may override.",
};

function fullContext() {
  return {
    ...NARRATIVE,
    modelId: "15211",
    projectName: "Card Fraud",
    modelTypeSelection: "Fraud Classification",
    acceptedAiDrafts: [{ field: "businessObjective", action: "Improve clarity", text: "x", acceptedAt: "2026-01-01T00:00:00Z" }],
    fraudDetails: { ...GOVERNANCE, deploymentMode: "Development" },
  };
}

// --- Migration / hydration safety -----------------------------------------

test("every narrative and governance field survives a store/restore round trip", () => {
  const restored = lib.migrateStoredContext(fullContext());
  for (const [key, value] of Object.entries(NARRATIVE)) {
    assert.equal(restored[key], value, `narrative field lost: ${key}`);
  }
  for (const [key, value] of Object.entries(GOVERNANCE)) {
    assert.equal(restored.fraudDetails[key], value, `governance field lost: ${key}`);
  }
  assert.equal(restored.modelTypeSelection, "Fraud Classification");
  assert.equal(restored.fraudDetails.deploymentMode, "Development");
  assert.equal(restored.modelId, "15211");
});

test("multiline formatting and paragraph breaks are preserved exactly", () => {
  const restored = lib.migrateStoredContext(fullContext());
  assert.equal(restored.modelingMissionSummary, "First line.\n\nSecond paragraph with detail.");
  assert.ok(restored.modelingMissionSummary.includes("\n\n"), "paragraph break must survive");
});

test("a legacy project missing newer keys hydrates on defaults instead of failing", () => {
  const legacy = { businessObjective: "Legacy objective only." };
  const restored = lib.migrateStoredContext(legacy);
  assert.equal(restored.businessObjective, "Legacy objective only.");
  assert.equal(restored.targetDefinition, "");
  assert.deepEqual(restored.acceptedAiDrafts, []);
  assert.ok(restored.fraudDetails, "fraudDetails must be defaulted, not undefined");
  assert.equal(restored.fraudDetails.approvedUses, "");
});

test("absent or malformed stored content yields null so defaults are not mistaken for saved data", () => {
  assert.equal(lib.migrateStoredContext(null), null);
  assert.equal(lib.migrateStoredContext(undefined), null);
  assert.equal(lib.migrateStoredContext("not-an-object"), null);
});

test("an empty form is detectable so it can never overwrite stored content", () => {
  assert.equal(lib.isEmptyContext(lib.migrateStoredContext({})), true);
  assert.equal(lib.isEmptyContext(lib.migrateStoredContext(fullContext())), false);
  // A single governance field is enough to count as real content.
  assert.equal(lib.isEmptyContext(lib.migrateStoredContext({ fraudDetails: { overrideAuthority: "x" } })), false);
  assert.equal(lib.isEmptyContext(null), true);
});

// --- Project scoping -------------------------------------------------------

test("the local draft cache is scoped per project, not one global key", () => {
  const a = lib.draftCacheKey("project-a");
  const b = lib.draftCacheKey("project-b");
  assert.notEqual(a, b, "two projects must not share one cache key");
  assert.match(a, /project-a/);
  // The old unscoped key must not be reused.
  assert.notEqual(a, "modeling-tool-project-context");
});

test("a cached draft for one project is not readable as another project's draft", () => {
  lib.writeDraftCache("project-a", lib.migrateStoredContext(fullContext()));
  assert.ok(lib.readDraftCache("project-a"), "project-a draft should exist");
  assert.equal(lib.readDraftCache("project-b"), null, "project-b must not see project-a's draft");
  lib.clearDraftCache("project-a");
  assert.equal(lib.readDraftCache("project-a"), null);
});

// --- Change detection ------------------------------------------------------

test("unchanged content produces a stable fingerprint so it is not re-saved", () => {
  const context = lib.migrateStoredContext(fullContext());
  assert.equal(lib.contextFingerprint(context), lib.contextFingerprint({ ...context }));
  // A volatile timestamp must not make an unchanged context look dirty.
  assert.equal(
    lib.contextFingerprint({ ...context, updatedAt: "2026-01-01" }),
    lib.contextFingerprint({ ...context, updatedAt: "2030-12-31" })
  );
});

test("any edited narrative or governance field changes the fingerprint", () => {
  const base = lib.migrateStoredContext(fullContext());
  const baseline = lib.contextFingerprint(base);
  assert.notEqual(lib.contextFingerprint({ ...base, businessObjective: "changed" }), baseline);
  assert.notEqual(
    lib.contextFingerprint({ ...base, fraudDetails: { ...base.fraudDetails, overrideAuthority: "changed" } }),
    baseline
  );
});

// --- Source contract -------------------------------------------------------

test("the page wires autosave, hydration, and a navigation flush", () => {
  const page = fs.readFileSync("src/steps/Step00_ProjectContext.tsx", "utf8");
  assert.match(page, /useProjectContextAutosave/, "the page must use the autosave lifecycle");
  assert.match(page, /onHydrated: \(hydrated\) => setContext\(hydrated\)/, "hydrated backend content must populate the form");
  assert.match(page, /const flushed = await autosave\.flush\(\)/, "Continue must flush before navigating");
  assert.match(page, /if \(!flushed\)/, "a failed required save must not be treated as success");
  assert.match(page, /data-testid="project-context-save-status"/, "a truthful save status must be rendered");
  assert.match(page, /data-save-status=\{status\}/, "the save status must be inspectable");
  assert.match(page, /data-testid="retry-project-context-save"/, "a failed save must offer Retry Save");
});

test("autosave is debounced, flushes on demand, and rejects superseded saves", () => {
  const hook = fs.readFileSync("src/lib/useProjectContextAutosave.ts", "utf8");
  assert.match(hook, /const DEBOUNCE_MS = \d+/, "autosave must be debounced");
  const debounce = Number(hook.match(/const DEBOUNCE_MS = (\d+)/)[1]);
  assert.ok(debounce >= 500 && debounce <= 1000, `debounce should be 500-1000ms (was ${debounce})`);
  assert.match(hook, /setTimeout\(\(\) => \{\s*void performSave/, "typing must schedule a debounced save, not save per keystroke");
  assert.match(hook, /if \(fingerprint === savedFingerprintRef\.current\) return true/, "unchanged values must not be re-saved");
  assert.match(hook, /sequenceRef/, "saves must be sequenced");
  assert.match(hook, /if \(sequence < appliedSequenceRef\.current\) return/, "a superseded save must not report over a newer one");
  assert.match(hook, /inFlightRef\.current\?\.abort\(\)/, "an in-flight save must be abortable");
  assert.match(hook, /const flush = useCallback/, "an explicit flush must exist for navigation");
  assert.match(hook, /pagehide/, "a best-effort unload path should exist");
  // Hydration must gate editing so an empty form cannot be autosaved over stored content.
  assert.match(hook, /if \(!enabled \|\| !projectId \|\| !hydratedRef\.current\) return undefined/, "autosave must wait for hydration");
});

test("the backend record is the authoritative store and carries a revision", () => {
  const persistence = fs.readFileSync("src/lib/projectContextPersistence.ts", "utf8");
  assert.match(persistence, /projectContextRevision/, "saves must carry a revision");
  assert.match(persistence, /reason: "conflict"/, "a stale write must be reported as a conflict");
  assert.match(persistence, /current\.revision !== expectedRevision/, "the stored revision must be compared before writing");
  assert.match(persistence, /PROJECT_CONTEXT_SCHEMA_VERSION/, "a schema version must be recorded");
  assert.match(persistence, /credentials: "include"/, "authorization cookies must be sent");
  assert.match(persistence, /Never authoritative/, "the local cache must be documented as non-authoritative");
});

console.log("projectContextPersistence.test.mjs: all checks passed.");
