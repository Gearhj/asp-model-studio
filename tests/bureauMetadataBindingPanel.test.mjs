import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import ts from "typescript";

const ROOT = new URL("../", import.meta.url);
const read = (path) => readFile(new URL(path, ROOT), "utf8");

const [clientSource, panelSource, acquisitionSource] = await Promise.all([
  read("src/lib/bureauMetadata.ts"),
  read("src/components/BureauMetadataBindingPanel.tsx"),
  read("src/steps/Step01_DataAcquisition.tsx"),
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
    compilerOptions: {
      module: ts.ModuleKind.ES2022,
      target: ts.ScriptTarget.ES2022,
    },
  }).outputText;
  return import(`data:text/javascript;base64,${Buffer.from(output).toString("base64")}`);
}

const api = await compileClient();
const checksum = "a".repeat(64);
const previewChecksum = "b".repeat(64);
const identity = {
  project_id: "project-synthetic",
  dataset_id: "dataset-synthetic",
  dataset_version_id: "version-synthetic",
  activation_revision: 4,
};
const catalogPayload = {
  catalog_version_id: "catalog-version-synthetic",
  normalized_catalog_checksum: checksum,
  provider_name: "Synthetic Bureau",
  product_name: "Synthetic Product",
  edition: "LAB",
  source_release_version: "synthetic-v1",
  record_count: 12,
  special_value_definition_count: 3,
  integrity_status: "verified",
  retired_status: "active",
};
const responseIdentity = {
  project_id: identity.project_id,
  dataset_id: identity.dataset_id,
  dataset_version_id: identity.dataset_version_id,
  activation_revision: identity.activation_revision,
  schema_checksum: "c".repeat(64),
  target_contract_id: "target-contract-synthetic",
  predictor_authorization_id: "predictor-auth-synthetic",
  catalog_version_id: catalogPayload.catalog_version_id,
  catalog_checksum: checksum,
  catalog_key: {
    provider: catalogPayload.provider_name,
    product: catalogPayload.product_name,
    edition: catalogPayload.edition,
    dictionary_version: catalogPayload.source_release_version,
  },
};

function jsonResponse(status, payload) {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => payload,
  };
}

test("the non-admin client uses only bounded exact binding routes", () => {
  assert.match(clientSource, /"\/bureau-catalogs\?offset=0&limit=50"/);
  assert.match(clientSource, /\/projects\/\$\{encodeURIComponent\(exactProjectId\)\}\/datasets\//);
  assert.match(clientSource, /\/versions\/\$\{encodeURIComponent\(identity\.dataset_version_id\)\}\/bureau-metadata\/binding/);
  assert.match(clientSource, /exactBindingPath\(input\.projectId, identity\)\}\/preview/);
  assert.match(clientSource, /exactBindingPath\(input\.projectId, identity\)\}\/confirm/);
  assert.match(clientSource, /credentials: "include"/);
  assert.doesNotMatch(clientSource, /\/admin\/bureau-catalogs|\/attributes|\/special-values|\/export|\/download/);
  assert.doesNotMatch(clientSource, /localStorage|sessionStorage|indexedDB|window\.location|useNavigate/);
  assert.doesNotMatch(clientSource, /catalogs\s*\[\s*0\s*\]|firstCatalog|latestCatalog/);
});

test("catalog inventory and an absent exact binding remain explicit and unbound", async () => {
  const calls = [];
  globalThis.fetch = async (url, init = {}) => {
    calls.push({ url: String(url), init });
    if (String(url).includes("/bureau-catalogs?")) {
      return jsonResponse(200, { ok: true, returned: 1, versions: [catalogPayload] });
    }
    return jsonResponse(404, { detail: { code: "bureau_metadata_binding_not_found" } });
  };
  const catalogs = await api.listEntitledBureauCatalogs();
  const binding = await api.getBureauMetadataBinding({
    projectId: identity.project_id,
    datasetIdentity: identity,
  });
  assert.equal(catalogs.length, 1);
  assert.equal(catalogs[0].catalogVersionId, catalogPayload.catalog_version_id);
  assert.equal(catalogs[0].catalogChecksum, checksum);
  assert.equal(binding, null);
  assert.equal(calls[0].init.credentials, "include");
  assert.match(
    calls[1].url,
    /\/api\/projects\/project-synthetic\/datasets\/dataset-synthetic\/versions\/version-synthetic\/bureau-metadata\/binding$/,
  );
});

test("preview sends only the exact selected catalog identity and returns bounded counts", async () => {
  const calls = [];
  const catalog = {
    catalogVersionId: catalogPayload.catalog_version_id,
    catalogChecksum: checksum,
    provider: catalogPayload.provider_name,
    product: catalogPayload.product_name,
    edition: catalogPayload.edition,
    dictionaryVersion: catalogPayload.source_release_version,
    entitlementState: "authorized",
    integrityState: "verified",
    lifecycleState: "active",
    attributeCount: 12,
    specialDefinitionCount: 3,
  };
  globalThis.fetch = async (url, init = {}) => {
    calls.push({ url: String(url), init });
    return jsonResponse(200, {
      ok: true,
      preview: {
        identity: responseIdentity,
        preview_checksum: previewChecksum,
        expected_revision: 0,
        entitlement_state: "authorized",
        integrity_state: "verified",
        mapping_counts: {
          authoritative_mapping_count: 4,
          review_required_count: 2,
          unresolved_count: 1,
          special_definition_count: 3,
        },
        evidence_count: 3,
        current: false,
        stale: false,
        impact: {
          dataset_mutated: false,
          treatment_mutated: false,
          predictor_authorization_mutated: false,
          analysis_partition_mutated: false,
        },
      },
    });
  };
  const preview = await api.previewBureauMetadataBinding({
    projectId: identity.project_id,
    datasetIdentity: identity,
    catalog,
    expectedRevision: 0,
  });
  assert.equal(calls.length, 1);
  assert.match(calls[0].url, /\/bureau-metadata\/binding\/preview$/);
  assert.deepEqual(JSON.parse(calls[0].init.body), {
    catalog_version_id: catalogPayload.catalog_version_id,
    catalog_checksum: checksum,
  });
  assert.equal(preview.mappingCounts.authoritative, 4);
  assert.equal(preview.mappingCounts.reviewRequired, 2);
  assert.equal(preview.mappingCounts.unresolved, 1);
  assert.equal(preview.mappingCounts.specialDefinitions, 3);
  assert.equal(preview.previewChecksum, previewChecksum);
  assert.equal(preview.current, false);
  assert.equal(preview.stale, false);
});

test("a preview that reports workflow mutation fails closed", async () => {
  const catalog = {
    catalogVersionId: catalogPayload.catalog_version_id,
    catalogChecksum: checksum,
    provider: catalogPayload.provider_name,
    product: catalogPayload.product_name,
    edition: catalogPayload.edition,
    dictionaryVersion: catalogPayload.source_release_version,
    entitlementState: "authorized",
    integrityState: "verified",
    lifecycleState: "active",
    attributeCount: 12,
    specialDefinitionCount: 3,
  };
  globalThis.fetch = async () => jsonResponse(200, {
    ok: true,
    preview: {
      identity: responseIdentity,
      preview_checksum: previewChecksum,
      expected_revision: 0,
      impact: {
        dataset_mutated: true,
        treatment_mutated: false,
        predictor_authorization_mutated: false,
        analysis_partition_mutated: false,
      },
    },
  });
  await assert.rejects(
    api.previewBureauMetadataBinding({
      projectId: identity.project_id,
      datasetIdentity: identity,
      catalog,
      expectedRevision: 0,
    }),
    (error) => {
      assert.equal(error.code, "bureau_metadata_preview_mutation_conflict");
      assert.match(error.message, /impermissible workflow mutation/i);
      return true;
    },
  );
});

test("confirmation pins preview checksum and optimistic revision without browser evidence", async () => {
  const calls = [];
  const catalog = {
    catalogVersionId: catalogPayload.catalog_version_id,
    catalogChecksum: checksum,
    provider: catalogPayload.provider_name,
    product: catalogPayload.product_name,
    edition: catalogPayload.edition,
    dictionaryVersion: catalogPayload.source_release_version,
    entitlementState: "authorized",
    integrityState: "verified",
    lifecycleState: "active",
    attributeCount: 12,
    specialDefinitionCount: 3,
  };
  const preview = {
    identity: {
      projectId: identity.project_id,
      datasetId: identity.dataset_id,
      datasetVersionId: identity.dataset_version_id,
      activationRevision: identity.activation_revision,
      catalogVersionId: catalog.catalogVersionId,
      catalogChecksum: checksum,
      provider: catalog.provider,
      product: catalog.product,
      edition: catalog.edition,
      dictionaryVersion: catalog.dictionaryVersion,
    },
    previewChecksum,
    expectedRevision: 0,
    entitlementState: "authorized",
    integrityState: "verified",
    mappingCounts: { authoritative: 4, reviewRequired: 2, unresolved: 1, specialDefinitions: 3 },
    evidenceCount: 3,
    current: true,
    stale: false,
    datasetMutated: false,
    treatmentMutated: false,
    predictorAuthorizationMutated: false,
    analysisPartitionMutated: false,
  };
  globalThis.fetch = async (url, init = {}) => {
    calls.push({ url: String(url), init });
    return jsonResponse(200, {
      ok: true,
      binding: {
        binding_id: "binding-synthetic",
        revision: 1,
        status: "active",
        identity: responseIdentity,
        actor_id: "actor-synthetic",
        server_recorded_at: "2026-08-05T20:00:00Z",
        evidence: [
          { evidence_kind: "dataset_lineage" },
          { evidence_kind: "catalog_registry" },
          { evidence_kind: "catalog_entitlement" },
        ],
        revision_checksum: "d".repeat(64),
      },
      summary: {
        current: true,
        stale: false,
        entitlement_state: "authorized",
        integrity_state: "verified",
        mapping_counts: {
          authoritative_mapping_count: 4,
          review_required_count: 2,
          unresolved_count: 1,
          special_definition_count: 3,
        },
        evidence_count: 3,
      },
    });
  };
  const result = await api.confirmBureauMetadataBinding({
    projectId: identity.project_id,
    datasetIdentity: identity,
    catalog,
    preview,
    analystRationale: "Synthetic exact-version review.",
  });
  assert.match(calls[0].url, /\/bureau-metadata\/binding\/confirm$/);
  assert.deepEqual(JSON.parse(calls[0].init.body), {
    catalog_version_id: catalog.catalogVersionId,
    catalog_checksum: checksum,
    expected_revision: 0,
    preview_checksum: previewChecksum,
    analyst_rationale: "Synthetic exact-version review.",
  });
  assert.equal(result.bindingId, "binding-synthetic");
  assert.equal(result.bindingRevision, 1);
  assert.equal(result.evidenceCount, 3);
  assert.doesNotMatch(calls[0].init.body, /evidence|mapping_counts|target_contract|predictor_authorization/);
});

test("the panel exposes all safe states while requiring explicit catalog selection", () => {
  for (const required of [
    'data-state="hidden"',
    "Exact dataset identity is required.",
    "No entitled bureau catalog version is available.",
    "No authoritative bureau metadata mapping exists for this exact dataset version.",
    "Candidate preview · not authoritative",
    'data-testid="bureau-metadata-confirmed-summary"',
    "Authoritative",
    "Review required",
    "Unresolved",
    "Special definitions",
    "Evidence",
    "Binding revision",
    "Crosswalk revision",
    "current",
    "stale",
  ]) {
    assert.ok(panelSource.includes(required), `Missing safe binding state or summary: ${required}`);
  }
  assert.match(panelSource, /useState\(""\)/);
  assert.match(panelSource, /<option value="">Select an exact catalog version<\/option>/);
  assert.match(panelSource, /disabled=\{!selectedCatalog \|\| actionPending !== null\}/);
  assert.match(panelSource, /const previewReady = Boolean\(preview\)/);
  assert.doesNotMatch(panelSource, /preview && (?:preview\.current|!preview\.stale)/);
  assert.doesNotMatch(panelSource, /catalogs\s*\[\s*0\s*\]|setSelectedCatalogVersionId\([^)]*catalogs/);
  assert.doesNotMatch(panelSource, /localStorage|sessionStorage|indexedDB|window\.location|location\.reload|useNavigate/);
  assert.doesNotMatch(panelSource, /special-value treatment.*onClick|mapping decision|attribute description/i);
});

test("Step01 places the compact binding panel immediately before Special-Value Review", () => {
  assert.match(acquisitionSource, /import BureauMetadataBindingPanel from "\.\.\/components\/BureauMetadataBindingPanel"/);
  const bindingIndex = acquisitionSource.indexOf("<BureauMetadataBindingPanel");
  const reviewIndex = acquisitionSource.indexOf("<BureauReviewPanel", bindingIndex);
  assert.ok(bindingIndex >= 0, "Bureau Metadata Binding panel is not mounted.");
  assert.ok(reviewIndex > bindingIndex, "Binding panel must appear before Special-Value Review.");
  const between = acquisitionSource.slice(bindingIndex, reviewIndex);
  assert.match(between, /datasetIdentity=\{activeDatasetIdentity\}/);
  assert.match(between, /featureNames=\{headers\.filter\(\(header\) => header !== target\)\}/);
  assert.doesNotMatch(between, /navigate|reload|saveBureauMetadata|updateSpecialValueReview/);
});
