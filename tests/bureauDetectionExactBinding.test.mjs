import assert from "node:assert/strict";
import { mkdir, readFile, rm, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import test from "node:test";
import ts from "typescript";

const ROOT = new URL("..", import.meta.url);
const TMP_DIR = fileURLToPath(
  new URL("../.tmp/bureau-detection-binding-tests", import.meta.url),
);

async function compile() {
  await rm(TMP_DIR, { recursive: true, force: true });
  const source = await readFile(
    new URL("src/lib/bureauDetection.ts", ROOT),
    "utf8",
  );
  const patched = source
    .replace(
      /import \{[\s\S]*?\} from "\.\/creditBureau";/,
      `const BUREAU_METADATA_KEY = "metadata";
       const BUREAU_TREATMENT_KEY = "treatment";
       const loadBureauMetadata = () => [];
       const loadBureauTreatmentDecisions = () => [];`,
    )
    .replace(/\(import\.meta\.env\.VITE_API_BASE as string \| undefined\)/g, "undefined");
  const output = ts.transpileModule(patched, {
    compilerOptions: {
      module: ts.ModuleKind.ES2022,
      target: ts.ScriptTarget.ES2022,
    },
  }).outputText;
  const outPath = path.join(TMP_DIR, "bureauDetection.js");
  await mkdir(TMP_DIR, { recursive: true });
  await writeFile(outPath, output, "utf8");
  return import(pathToFileURL(outPath).href);
}

const api = await compile();
const state = {
  declaration: "auto",
  rationale: "",
  decisions: [],
  variableDefaults: [],
  status: "draft",
  evidenceStatus: "not_recorded",
};
const identity = {
  project_id: "project-exact",
  dataset_id: "dataset-exact",
  dataset_version_id: "version-exact",
  activation_revision: 3,
};

test("bureau request carries the exact canonical Dataset Library identity", async () => {
  const calls = [];
  globalThis.fetch = async (url, init) => {
    calls.push({ url, body: JSON.parse(init.body) });
    return { ok: true, json: async () => ({ ok: true }) };
  };
  await api.fetchBureauDetection({
    projectId: "project-exact",
    datasetIdentity: identity,
    target: "bad_flag",
    eventValue: 1,
    state,
    metadata: [],
  });
  assert.equal(calls.length, 1);
  assert.equal(calls[0].body.project_id, "project-exact");
  assert.equal(calls[0].body.expected_dataset_id, "dataset-exact");
  assert.equal(
    calls[0].body.expected_dataset_version_id,
    "version-exact",
  );
});

test("structured backend failures render safe corrective text and correlation", async () => {
  globalThis.fetch = async () => ({
    ok: false,
    json: async () => ({
      detail: {
        code: "dataset_identity_mismatch",
        message: "The requested dataset identity is not active.",
        corrective_action: "Reload Data Acquisition.",
        correlation_id: "bureau-safe-reference",
      },
    }),
  });
  await assert.rejects(
    api.fetchBureauDetection({
      projectId: "project-exact",
      datasetIdentity: identity,
      state,
      metadata: [],
    }),
    (error) => {
      assert.match(error.message, /requested dataset identity is not active/i);
      assert.match(error.message, /Reload Data Acquisition/);
      assert.match(error.message, /bureau-safe-reference/);
      assert.doesNotMatch(error.message, /\[object Object\]/);
      return true;
    },
  );
});

test("the panel waits for canonical identity and reacts to exact-version changes", async () => {
  const panel = await readFile(
    new URL("src/components/BureauReviewPanel.tsx", ROOT),
    "utf8",
  );
  assert.match(panel, /if \(!datasetIdentity\)/);
  assert.match(panel, /fetchBureauDetection\(\{[\s\S]*datasetIdentity,/);
  assert.match(panel, /datasetIdentity\?\.dataset_id/);
  assert.match(panel, /datasetIdentity\?\.dataset_version_id/);
});

const reviewLineage = {
  projectId: "project-exact",
  datasetIdentity: identity,
  activationRevision: 3,
  predictorAuthorizationId: "predictor-auth-exact",
  targetContractId: "target-contract-exact",
};

function durableReview(overrides = {}) {
  return {
    special_value_review_id: "special-review-exact",
    project_id: "project-exact",
    dataset_id: "dataset-exact",
    dataset_version_id: "version-exact",
    activation_revision: 3,
    predictor_authorization_id: "predictor-auth-exact",
    target_contract_id: "target-contract-exact",
    detection_fingerprint: "fingerprint-exact",
    status: "not_started",
    detected_count: 1,
    reviewed_count: 0,
    open_count: 1,
    open_items: ["ExternalRiskEstimate"],
    blocks_confirmation: true,
    blocks_continuation: true,
    confirmation_allowed: false,
    revision: 4,
    variable_decisions: [],
    reviewer_rationale: "",
    confirmed_at: null,
    updated_at: "2026-08-03T00:00:00Z",
    authority: "backend_durable_exact_version",
    browser_cache_authority: false,
    ...overrides,
  };
}

test("durable GET is exact-version scoped and validates every lineage authority", async () => {
  const calls = [];
  globalThis.fetch = async (url, init) => {
    calls.push({ url: String(url), init });
    return {
      ok: true,
      status: 200,
      json: async () => ({
        ok: true,
        special_value_review: durableReview(),
      }),
    };
  };
  const result = await api.fetchSpecialValueReview({ lineage: reviewLineage });
  assert.equal(result.revision, 4);
  assert.equal(calls.length, 1);
  const url = new URL(calls[0].url);
  assert.equal(url.pathname, "/api/data/special-value-review");
  assert.equal(url.searchParams.get("project_id"), "project-exact");
  assert.equal(url.searchParams.get("expected_dataset_id"), "dataset-exact");
  assert.equal(
    url.searchParams.get("expected_dataset_version_id"),
    "version-exact",
  );
  assert.equal(calls[0].init.credentials, "include");

  assert.throws(
    () => api.assertSpecialValueReviewContract(
      durableReview({ predictor_authorization_id: "wrong-auth" }),
      reviewLineage,
    ),
    /does not match the exact project, dataset version, activation, predictor authorization, and target contract/i,
  );
});

test("durable PUT uses optimistic revision, fingerprint, exact identity, and backend decisions", async () => {
  const calls = [];
  const current = durableReview();
  const confirmed = durableReview({
    status: "confirmed",
    reviewed_count: 1,
    open_count: 0,
    open_items: [],
    blocks_confirmation: false,
    blocks_continuation: false,
    confirmation_allowed: true,
    revision: 5,
    variable_decisions: [
      {
        variable: "ExternalRiskEstimate",
        policy: "preserve_informative",
        rationale: "",
        overrides: [],
      },
    ],
  });
  globalThis.fetch = async (url, init) => {
    calls.push({ url: String(url), init, body: JSON.parse(init.body) });
    return {
      ok: true,
      status: 200,
      json: async () => ({ ok: true, special_value_review: confirmed }),
    };
  };
  const variableDecisions = confirmed.variable_decisions;
  const result = await api.updateSpecialValueReview({
    lineage: reviewLineage,
    current,
    intent: "confirm",
    variableDecisions,
    reviewerRationale: "Reviewed exact detection.",
  });
  assert.equal(result.status, "confirmed");
  assert.equal(calls[0].init.method, "PUT");
  assert.deepEqual(calls[0].body, {
    project_id: "project-exact",
    expected_dataset_id: "dataset-exact",
    expected_dataset_version_id: "version-exact",
    expected_revision: 4,
    detection_fingerprint: "fingerprint-exact",
    intent: "confirm",
    variable_decisions: variableDecisions,
    reviewer_rationale: "Reviewed exact detection.",
  });
});

test("browser review persistence is explicitly a draft cache, never confirmation authority", () => {
  const storage = new Map();
  globalThis.localStorage = {
    getItem: (key) => storage.get(key) ?? null,
    setItem: (key, value) => storage.set(key, value),
  };
  globalThis.window = { dispatchEvent() {} };
  api.saveBureauReviewState({
    ...state,
    status: "confirmed",
    evidenceStatus: "ready",
    confirmedAt: "2026-08-03T00:00:00Z",
  });
  const stored = JSON.parse(storage.get(api.BUREAU_REVIEW_KEY));
  assert.equal(stored.status, "draft");
  assert.equal(stored.browserCacheAuthority, false);
  assert.equal("confirmedAt" in stored, false);
  assert.equal(api.loadBureauReviewState().status, "draft");
});
