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
const projectContextPath = await compile("src/lib/projectContext.ts", "projectContext.js");
const persistencePath = await compile("src/lib/projectContextPersistence.ts", "projectContextPersistence.js");

// Minimal localStorage shim for the convenience-cache functions.
globalThis.localStorage = {
  _data: new Map(),
  getItem(key) { return this._data.has(key) ? this._data.get(key) : null; },
  setItem(key, value) { this._data.set(key, String(value)); },
  removeItem(key) { this._data.delete(key); },
};

const lib = await import(pathToFileURL(persistencePath).href);
const projectContextLib = await import(pathToFileURL(projectContextPath).href);

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

function jsonResponse(body, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
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

test("the local draft cache is scoped per project and authenticated user", () => {
  const a = lib.draftCacheKey("project-a", "user-a");
  const b = lib.draftCacheKey("project-b", "user-a");
  assert.notEqual(a, b, "two projects must not share one cache key");
  assert.match(a, /project-a/);
  // The old unscoped key must not be reused.
  assert.notEqual(a, "modeling-tool-project-context");
});

test("a cached draft is isolated by both project and authenticated user", () => {
  lib.writeDraftCache("project-a", "user-a", lib.migrateStoredContext(fullContext()));
  assert.ok(lib.readDraftCache("project-a", "user-a"), "the exact user/project draft should exist");
  assert.equal(lib.readDraftCache("project-b", "user-a"), null, "another project must not see the draft");
  assert.equal(lib.readDraftCache("project-a", "user-b"), null, "another user must not see the draft");
  lib.clearDraftCache("project-a", "user-a");
  assert.equal(lib.readDraftCache("project-a", "user-a"), null);
});

test("the acknowledged Project Context compatibility copy is scoped for MDD consumers", () => {
  const context = lib.migrateStoredContext(fullContext());
  projectContextLib.saveProjectContext(context, "project-a", "user-a");
  assert.equal(
    projectContextLib.loadProjectContext("project-a", "user-a").businessObjective,
    context.businessObjective,
  );
  assert.equal(
    projectContextLib.loadProjectContext("project-a", "user-b").businessObjective,
    projectContextLib.defaultProjectContext.businessObjective,
  );
  assert.equal(
    projectContextLib.loadProjectContext("project-b", "user-a").businessObjective,
    projectContextLib.defaultProjectContext.businessObjective,
  );
});

test("hydration rejects a project response from a different route scope", async () => {
  const previousFetch = globalThis.fetch;
  globalThis.fetch = async () => jsonResponse({
    ok: true,
    project: { projectId: "project-b", metadata: {} },
  });
  try {
    await assert.rejects(
      () => lib.hydrateProjectContext("project-a"),
      /does not match the requested project/i,
    );
  } finally {
    globalThis.fetch = previousFetch;
  }
});

test("a concurrent first revision conflicts even when this tab expected no revision", async () => {
  const previousFetch = globalThis.fetch;
  let requests = 0;
  globalThis.fetch = async () => {
    requests += 1;
    return jsonResponse({
      ok: true,
      project: {
        projectId: "project-a",
        metadata: {
          projectContextRevision: "1785186305905-other-tab",
          projectContext: {
            ...fullContext(),
            businessObjective: "A different tab saved a genuinely divergent objective.",
          },
        },
      },
    });
  };
  try {
    const result = await lib.saveProjectContextToBackend({
      projectId: "project-a",
      context: lib.migrateStoredContext(fullContext()),
      expectedRevision: "",
      validationStatus: "ready",
    });
    assert.equal(result.ok, false);
    assert.equal(result.reason, "conflict");
    assert.equal(requests, 1, "a conflicting precheck must prevent the PUT");
  } finally {
    globalThis.fetch = previousFetch;
  }
});

test("an exact newer durable revision is adopted without issuing a duplicate PUT", async () => {
  const previousFetch = globalThis.fetch;
  const context = lib.migrateStoredContext(fullContext());
  let requests = 0;
  globalThis.fetch = async () => {
    requests += 1;
    return jsonResponse({
      ok: true,
      project: {
        projectId: "project-a",
        metadata: {
          projectContextRevision: "1785186305905-already-durable",
          projectContextSavedAt: "2026-08-02T21:49:01.812Z",
          projectContext: context,
        },
      },
    });
  };
  try {
    const result = await lib.saveProjectContextToBackend({
      projectId: "project-a",
      context,
      expectedRevision: "1785186305905-stale-client",
      validationStatus: "complete",
    });
    assert.equal(result.ok, true);
    assert.equal(result.revision, "1785186305905-already-durable");
    assert.equal(result.source, "background_verification");
    assert.equal(requests, 1, "exact convergence must not issue another PUT");
  } finally {
    globalThis.fetch = previousFetch;
  }
});

test("an ambiguous acknowledgement recovers the exact committed revision", async () => {
  const previousFetch = globalThis.fetch;
  const context = lib.migrateStoredContext(fullContext());
  let durableProject = null;
  let requests = 0;
  globalThis.fetch = async (_url, init = {}) => {
    requests += 1;
    if (!init.method || init.method === "GET") {
      return jsonResponse({
        ok: true,
        project: durableProject ?? {
          projectId: "project-a",
          metadata: {
            projectContextRevision: "1785186305905-current",
            projectContext: context,
          },
        },
      });
    }
    const submitted = JSON.parse(init.body);
    durableProject = {
      projectId: "project-a",
      projectName: submitted.projectName,
      metadata: submitted.metadata,
    };
    return jsonResponse({
      ok: true,
      project: {
        ...durableProject,
        metadata: { ...submitted.metadata, modelId: "ambiguous-response-model" },
      },
    });
  };
  try {
    const result = await lib.saveProjectContextToBackend({
      projectId: "project-a",
      context,
      expectedRevision: "1785186305905-current",
      validationStatus: "complete",
    });
    assert.equal(result.ok, true);
    assert.equal(result.source, "user_save");
    assert.equal(result.revision, durableProject.metadata.projectContextRevision);
    assert.equal(requests, 3, "precheck, PUT, and exact verification GET are required");
  } finally {
    globalThis.fetch = previousFetch;
  }
});

test("a 200 save acknowledgement with mismatched metadata fails closed", async () => {
  const previousFetch = globalThis.fetch;
  const context = lib.migrateStoredContext(fullContext());
  globalThis.fetch = async (_url, init = {}) => {
    if (!init.method || init.method === "GET") {
      return jsonResponse({
        ok: true,
        project: {
          projectId: "project-a",
          metadata: {
            projectContextRevision: "1785186305905-current",
            projectContext: context,
          },
        },
      });
    }
    const submitted = JSON.parse(init.body);
    return jsonResponse({
      ok: true,
      project: {
        projectId: "project-a",
        projectName: submitted.projectName,
        metadata: {
          ...submitted.metadata,
          modelId: "different-model",
        },
      },
    });
  };
  try {
    const result = await lib.saveProjectContextToBackend({
      projectId: "project-a",
      context,
      expectedRevision: "1785186305905-current",
      validationStatus: "ready",
    });
    assert.equal(result.ok, false);
    assert.equal(result.reason, "error");
    assert.match(result.message, /exact saved Project Context revision/i);
  } finally {
    globalThis.fetch = previousFetch;
  }
});

test("a Project Context metadata save preserves governed workflow identity", async () => {
  const previousFetch = globalThis.fetch;
  const context = lib.migrateStoredContext(fullContext());
  let submitted;
  globalThis.fetch = async (_url, init = {}) => {
    if (!init.method || init.method === "GET") {
      return jsonResponse({
        ok: true,
        project: {
          projectId: "project-a",
          metadata: {
            projectContextRevision: "1785186305905-current",
            projectContext: context,
          },
        },
      });
    }
    submitted = JSON.parse(init.body);
    return jsonResponse({
      ok: true,
      project: {
        projectId: "project-a",
        projectName: submitted.projectName,
        projectType: "predictive-modeling",
        workflowType: "credit-risk-studio",
        metadata: submitted.metadata,
      },
    });
  };
  try {
    const result = await lib.saveProjectContextToBackend({
      projectId: "project-a",
      context,
      expectedRevision: "1785186305905-current",
      validationStatus: "ready",
    });
    assert.equal(result.ok, true);
    assert.equal(result.source, "user_save");
    assert.equal(Object.hasOwn(submitted, "projectType"), false);
    assert.equal(Object.hasOwn(submitted, "workflowType"), false);
  } finally {
    globalThis.fetch = previousFetch;
  }
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

test("backend JSON key sorting cannot turn an accepted AI draft into a conflict", () => {
  const context = lib.migrateStoredContext({
    ...fullContext(),
    acceptedAiDrafts: [{
      field: "modelingMissionSummary",
      action: "Draft from current project context",
      text: "Governed summary",
      acceptedAt: "2026-08-02T22:16:49.838Z",
      acceptedBy: "project-context-test-user",
    }],
  });
  const backendOrdered = {
    ...context,
    fraudDetails: Object.fromEntries(Object.entries(context.fraudDetails).reverse()),
    acceptedAiDrafts: [{
      acceptedAt: "2026-08-02T22:16:49.838Z",
      acceptedBy: "project-context-test-user",
      action: "Draft from current project context",
      field: "modelingMissionSummary",
      text: "Governed summary",
    }],
  };
  assert.equal(
    lib.contextFingerprint(context),
    lib.contextFingerprint(backendOrdered),
    "object key order is storage formatting, not a semantic Project Context change",
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

test("the page wires hydration and one acknowledged explicit-save path", () => {
  const page = fs.readFileSync("src/steps/Step00_ProjectContext.tsx", "utf8");
  assert.match(page, /useProjectContextAutosave/, "the page must use the autosave lifecycle");
  assert.match(page, /onHydrated: \(hydrated\) => setContext\(hydrated\)/, "hydrated backend content must populate the form");
  assert.match(page, /const persisted = await autosave\.saveNow\(saved\)/, "completion must use the acknowledged autosave client");
  assert.match(page, /if \(!persisted\)/, "a failed required save must not be treated as success");
  assert.doesNotMatch(page, /savePredictiveProjectContextToDatabase/, "Continue must not issue a duplicate legacy project PUT");
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
  assert.match(hook, /scopeGeneration !== scopeGenerationRef\.current/, "a prior project/user scope must not publish after unmount");
  assert.match(hook, /scopeActiveRef\.current = false/, "unmount must close the save scope before a late callback can start work");
  assert.match(hook, /!scopeActiveRef\.current\) return false/, "explicit saves must refuse an inactive route/user scope");
  assert.match(hook, /sequence !== sequenceRef\.current/, "a superseded save must not report over a newer one");
  assert.match(hook, /inFlightRef\.current\?\.abort\(\)/, "an in-flight save must be abortable");
  assert.match(hook, /const flush = useCallback/, "an explicit flush must exist for navigation");
  assert.match(hook, /pagehide/, "a best-effort unload path should exist");
  // Hydration must gate editing so an empty form cannot be autosaved over stored content.
  assert.match(hook, /!authenticatedUserId \|\| !hydratedRef\.current \|\| !scopeActiveRef\.current/, "autosave must wait for an active, authenticated hydration scope");
  assert.match(hook, /writeDraftCache\(projectId, authenticatedUserId, context\)/, "an edit must be cached before the debounce expires");
  assert.match(hook, /Recovered a newer unsaved local draft/, "a newer user/project draft must survive authoritative rehydration");
});

test("authoritative provider publication refreshes the scoped MDD compatibility copy without making it identity authority", () => {
  const provider = fs.readFileSync("src/components/PredictiveIdentityProvider.tsx", "utf8");
  assert.match(provider, /updateScopedProjectContextCompatibilityCopy/, "provider hydration must synchronize scoped Project Context content for MDD readers");
  assert.match(provider, /saveProjectContext\(/, "the compatibility copy must use the scoped Project Context writer");
  assert.match(provider, /provider never reads it as identity authority/i, "the compatibility copy must be documented as non-authoritative");
});

test("the backend record is the authoritative store and carries a revision", () => {
  const persistence = fs.readFileSync("src/lib/projectContextPersistence.ts", "utf8");
  assert.match(persistence, /projectContextRevision/, "saves must carry a revision");
  assert.match(persistence, /reason: "conflict"/, "a stale write must be reported as a conflict");
  assert.match(persistence, /current\.revision !== expectedRevision/, "the stored revision must be compared before writing");
  assert.match(persistence, /PROJECT_CONTEXT_SCHEMA_VERSION/, "a schema version must be recorded");
  assert.match(persistence, /returnedRevision !== revision/, "success requires the exact backend-acknowledged revision");
  assert.match(persistence, /credentials: "include"/, "authorization cookies must be sent");
  assert.match(persistence, /Never authoritative/, "the local cache must be documented as non-authoritative");
});

console.log("projectContextPersistence.test.mjs: all checks passed.");
