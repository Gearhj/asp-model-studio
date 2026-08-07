import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import ts from "typescript";

const ROOT = new URL("../", import.meta.url);
const read = (path) => readFile(new URL(path, ROOT), "utf8");

const [clientSource, workspaceSource, bindingPanelSource] = await Promise.all([
  read("src/lib/bureauMetadata.ts"),
  read("src/components/BureauMetadataCrosswalkWorkspace.tsx"),
  read("src/components/BureauMetadataBindingPanel.tsx"),
]);

async function compileClient() {
  const patched = clientSource
    .replace(
      'import { DATASET_API_BASE } from "./datasetLibrary";',
      'const DATASET_API_BASE = "http://127.0.0.1:8001/api";',
    )
    .replace(
      /import \{[\s\S]*?\} from "\.\/datasetIdentity";/,
      "const requireCanonicalDatasetIdentity = (input) => input;",
    );
  const output = ts.transpileModule(patched, {
    compilerOptions: { module: ts.ModuleKind.ES2022, target: ts.ScriptTarget.ES2022 },
  }).outputText;
  return import(`data:text/javascript;base64,${Buffer.from(output).toString("base64")}`);
}

const api = await compileClient();
const checksum = (value) => value.repeat(64);
const identity = {
  project_id: "project-crosswalk",
  dataset_id: "dataset-crosswalk",
  dataset_version_id: "version-crosswalk",
  activation_revision: 7,
};
const lineage = {
  ...identity,
  target_contract_id: "target-contract",
  predictor_authorization_id: "predictor-authorization",
  schema_checksum: checksum("a"),
  catalog_key: {
    provider: "Synthetic Bureau",
    product: "Synthetic Product",
    edition: "LAB",
    dictionary_version: "v1",
  },
  catalog_checksum: checksum("b"),
};
const states = [
  "exact_verified",
  "approved_alias",
  "transformed_or_derived",
  "probable_review_required",
  "ambiguous_review_required",
  "recoding_evidence_required",
  "unresolved",
  "out_of_catalog",
  "rejected",
];

function jsonResponse(status, payload) {
  return { ok: status >= 200 && status < 300, status, json: async () => payload };
}

function decision(field, state = "unresolved") {
  return {
    dataset_field: field,
    mapping_state: state,
    candidate_attribute_code: state === "unresolved" || state === "out_of_catalog" || state === "rejected" ? null : `CODE_${field}`,
    alternative_attribute_codes: state === "ambiguous_review_required" ? [`CODE_${field}`, `ALT_${field}`] : [],
    source_attribute_codes: [],
    evidence: [{
      evidence_id: `evidence-${field}`,
      evidence_kind: state === "unresolved" ? "unresolved_assessment" : "semantic_analysis",
      authority_id: "bounded-authority",
      checksum: checksum("c"),
      created_by: "actor",
      created_at: "2026-08-05T20:00:00Z",
    }],
    analyst_confirmed: false,
    transformation_or_recoding_concerns: state === "recoding_evidence_required" ? ["Needs recoding evidence"] : [],
  };
}

function governancePayload({ revision = 1, lifecycle = "draft", bindingRevision = 2 } = {}) {
  return {
    ok: true,
    governance: {
      governance_id: "crosswalk-governance",
      revision,
      lifecycle_state: lifecycle,
      lineage,
      source_crosswalk_id: "candidate-crosswalk",
      source_crosswalk_checksum: checksum("d"),
      decisions: [decision("field_one")],
      audit: { occurred_at: "2026-08-05T20:00:00Z" },
      revision_checksum: checksum("e"),
      dataset_mutated: false,
      target_contract_mutated: false,
      treatment_mutated: false,
      predictor_authorization_mutated: false,
      analysis_partition_mutated: false,
      feature_manifest_mutated: false,
    },
    binding: { revision: bindingRevision },
    binding_linked: true,
    dataset_mutated: false,
    target_contract_mutated: false,
    treatment_mutated: false,
    predictor_authorization_mutated: false,
    analysis_partition_mutated: false,
    feature_manifest_mutated: false,
  };
}

test("the client and workspace preserve all nine governance states exactly", () => {
  assert.deepEqual([...api.BUREAU_CROSSWALK_STATES], states);
  for (const state of states) {
    assert.ok(clientSource.includes(`"${state}"`), `client omitted ${state}`);
    assert.ok(workspaceSource.includes(`${state}:`), `workspace omitted ${state}`);
  }
  assert.match(workspaceSource, /Generic field names remain unresolved unless evidence supports an explicit decision/);
});

test("candidate review calls one exact bounded server preview and never downloads a catalog", async () => {
  const calls = [];
  globalThis.fetch = async (url, init = {}) => {
    calls.push({ url: String(url), init });
    return jsonResponse(200, {
      ok: true,
      persisted: false,
      source: {
        crosswalk_id: "candidate-crosswalk",
        crosswalk_checksum: checksum("d"),
        project_id: identity.project_id,
        dataset_id: identity.dataset_id,
        dataset_version_id: identity.dataset_version_id,
        mappings: [{
          dataset_field: "field_one",
          candidate_attribute_code: "CODE_1",
          match_status: "probable_semantic_match",
          confidence: 0.62,
          ambiguity: [],
          transformation_or_recoding_concerns: [],
        }],
      },
      initial_decisions: [decision("field_one", "probable_review_required")],
      summary: {
        authorized_predictor_count: 1,
        candidate_count: 1,
        dataset_mutated: false,
        target_contract_mutated: false,
        treatment_mutated: false,
        predictor_authorization_mutated: false,
        analysis_partition_mutated: false,
        feature_manifest_mutated: false,
      },
    });
  };
  const result = await api.previewBureauMetadataCrosswalk({
    projectId: identity.project_id,
    datasetIdentity: identity,
  });
  assert.equal(calls.length, 1);
  assert.match(calls[0].url, /\/projects\/project-crosswalk\/datasets\/dataset-crosswalk\/versions\/version-crosswalk\/bureau-metadata\/crosswalk\/preview$/);
  assert.equal(calls[0].init.credentials, "include");
  assert.equal(result.persisted, false);
  assert.equal(result.candidates.length, 1);
  assert.equal(result.stateCounts.probable_review_required, 1);
  assert.doesNotMatch(calls[0].url, /attributes|special-values|catalogs|download|export/);
});

test("explicit decision batches pin exact revisions and never submit catalog content or modeling mutations", async () => {
  const calls = [];
  globalThis.fetch = async (url, init = {}) => {
    calls.push({ url: String(url), init });
    return jsonResponse(200, governancePayload({ revision: 2, lifecycle: "review_required", bindingRevision: 8 }));
  };
  const result = await api.saveBureauMetadataCrosswalkDecisions({
    projectId: identity.project_id,
    datasetIdentity: identity,
    expectedCrosswalkRevision: 1,
    expectedBindingRevision: 7,
    decisions: [{
      datasetField: "field_one",
      mappingState: "rejected",
      rationale: "Candidate evidence does not support the mapping.",
    }],
    analystReason: "Analyst reviewed bounded candidate evidence.",
    confirmCrosswalk: false,
  });
  const body = JSON.parse(calls[0].init.body);
  assert.equal(body.expected_crosswalk_revision, 1);
  assert.equal(body.expected_binding_revision, 7);
  assert.equal(body.confirm_crosswalk, false);
  assert.equal(body.decisions[0].mapping_state, "rejected");
  assert.equal(result.partialMetadataState, false);
  assert.equal(result.governance.bindingRevision, 8);
  assert.doesNotMatch(calls[0].init.body, /catalog_description|catalog_rows|provider_definition|dataset_mutated|target_contract_mutated|analysis_partition_mutated|feature_manifest_mutated/);
});

test("confirmation is explicit and retains every supplied field decision", async () => {
  const calls = [];
  globalThis.fetch = async (url, init = {}) => {
    calls.push({ url: String(url), init });
    return jsonResponse(200, governancePayload({ revision: 3, lifecycle: "confirmed", bindingRevision: 9 }));
  };
  await api.saveBureauMetadataCrosswalkDecisions({
    projectId: identity.project_id,
    datasetIdentity: identity,
    expectedCrosswalkRevision: 2,
    expectedBindingRevision: 8,
    decisions: [{ datasetField: "field_one", mappingState: "rejected", rationale: "Explicit rejection." }],
    analystReason: "Confirm the complete evidence-reviewed crosswalk.",
    confirmCrosswalk: true,
  });
  const body = JSON.parse(calls[0].init.body);
  assert.equal(body.confirm_crosswalk, true);
  assert.equal(body.decisions.length, 1);
  assert.equal(body.analyst_reason, "Confirm the complete evidence-reviewed crosswalk.");
  assert.match(workspaceSource, /disabled=\{busy \|\| !reasonReady \|\| !allConfirmable\}/);
});

test("a structured partial link state is preserved and retried by exact revision", async () => {
  const calls = [];
  globalThis.fetch = async (url, init = {}) => {
    calls.push({ url: String(url), init });
    if (String(url).endsWith("/decisions")) {
      return jsonResponse(409, {
        ok: false,
        partial_metadata_state: true,
        governance_persisted: true,
        binding_linked: false,
        governance_id: "crosswalk-governance",
        crosswalk_revision: 4,
        crosswalk_revision_checksum: checksum("f"),
        error: { message: "The exact binding revision changed." },
        dataset_mutated: false,
        target_contract_mutated: false,
        treatment_mutated: false,
        predictor_authorization_mutated: false,
        analysis_partition_mutated: false,
        feature_manifest_mutated: false,
      });
    }
    return jsonResponse(200, governancePayload({ revision: 4, lifecycle: "review_required", bindingRevision: 10 }));
  };
  const partial = await api.saveBureauMetadataCrosswalkDecisions({
    projectId: identity.project_id,
    datasetIdentity: identity,
    expectedCrosswalkRevision: 3,
    expectedBindingRevision: 9,
    decisions: [{ datasetField: "field_one", mappingState: "rejected", rationale: "Explicit rejection." }],
    analystReason: "Persist reviewed decision and exact link.",
  });
  assert.equal(partial.partialMetadataState, true);
  assert.equal(partial.governancePersisted, true);
  assert.equal(partial.crosswalkRevision, 4);
  const linked = await api.retryBureauMetadataCrosswalkBinding({
    projectId: identity.project_id,
    datasetIdentity: identity,
    crosswalkRevision: 4,
    expectedBindingRevision: 9,
    analystReason: "Retry only the exact persisted binding link.",
  });
  assert.equal(linked.bindingRevision, 10);
  assert.match(calls[1].url, /\/crosswalk\/binding-link$/);
  assert.deepEqual(JSON.parse(calls[1].init.body), {
    crosswalk_revision: 4,
    expected_binding_revision: 9,
    analyst_reason: "Retry only the exact persisted binding link.",
  });
});

test("revision history is server bounded and a mutating response fails closed", async () => {
  const calls = [];
  globalThis.fetch = async (url, init = {}) => {
    calls.push({ url: String(url), init });
    if (String(url).includes("/history")) {
      return jsonResponse(200, {
        ok: true,
        lineage,
        returned: 1,
        total_revisions: 1,
        revisions: [governancePayload().governance],
      });
    }
    const payload = governancePayload();
    payload.dataset_mutated = true;
    return jsonResponse(200, payload);
  };
  const history = await api.getBureauMetadataCrosswalkHistory({
    projectId: identity.project_id,
    datasetIdentity: identity,
    limit: 10_000,
  });
  assert.equal(history.returned, 1);
  assert.match(calls[0].url, /\/history\?limit=100$/);
  await assert.rejects(
    api.getCurrentBureauMetadataCrosswalk({ projectId: identity.project_id, datasetIdentity: identity }),
    (error) => error.code === "bureau_crosswalk_mutation_conflict",
  );
});

test("the contained workspace is mounted without browser persistence, route navigation, or reload/reset behavior", () => {
  assert.match(bindingPanelSource, /import BureauMetadataCrosswalkWorkspace from "\.\/BureauMetadataCrosswalkWorkspace"/);
  assert.match(bindingPanelSource, /<BureauMetadataCrosswalkWorkspace/);
  assert.match(bindingPanelSource, /bindingCurrent=\{binding\.current && !binding\.stale\}/);
  assert.match(workspaceSource, /data-testid="bureau-crosswalk-decision-table"/);
  assert.match(workspaceSource, /data-testid="bureau-crosswalk-partial-state"/);
  assert.match(workspaceSource, /data-testid="bureau-crosswalk-confirmed-compact"/);
  assert.match(workspaceSource, /does not change the dataset, target contract, treatment, predictor authorization, Analysis Partition, feature manifest, or workflow route/);
  assert.doesNotMatch(workspaceSource, /localStorage|sessionStorage|indexedDB|window\.location|location\.reload|useNavigate|navigate\(|scrollTo|scrollIntoView|form\s+action=/);
  assert.doesNotMatch(clientSource, /\/bureau-metadata\/crosswalk\/attributes|\/bureau-metadata\/crosswalk\/catalog|full_catalog|raw_catalog/);
});
