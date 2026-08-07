import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import ts from "typescript";

const ROOT = new URL("../", import.meta.url);
const read = (path) =>
  readFileSync(new URL(path, ROOT), "utf8").replace(/\r\n/g, "\n");

const clientSource = read("src/lib/bureauSemanticAnnotations.ts");
const handoffSource = read("src/lib/dataAcquisitionEdaHandoff.ts");
const panelSource = read("src/components/BureauReviewPanel.tsx");

async function compileClient() {
  const patched = clientSource
    .replace(
      /import \{ DATASET_API_BASE \} from "\.\/datasetLibrary";/,
      'const DATASET_API_BASE = "/api/data";',
    )
    .replace(
      /import \{[\s\S]*?\} from "\.\/datasetIdentity";/,
      `const requireCanonicalDatasetIdentity = (value) => {
        for (const field of ["project_id", "dataset_id", "dataset_version_id"]) {
          if (typeof value?.[field] !== "string" || !value[field].trim()) {
            throw new Error("missing exact identity");
          }
        }
        return value;
      };`,
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
const identity = {
  project_id: "project-semantic",
  dataset_id: "dataset-semantic",
  dataset_version_id: "version-semantic",
  activation_revision: 7,
};
const checksum = (value) => value.repeat(64);
const mutationProof = {
  dataset_mutated: false,
  target_contract_mutated: false,
  treatment_mutated: false,
  predictor_authorization_mutated: false,
  analysis_partition_mutated: false,
  feature_manifest_mutated: false,
};

function validEnvelope() {
  const catalogKey = {
    provider: "Synthetic Provider",
    product: "Synthetic Product",
    edition: "Synthetic Edition",
    dictionary_version: "2026.1",
  };
  return {
    ok: true,
    annotation_set: {
      annotation_set_id: "annotation-set-1",
      annotation_set_checksum: checksum("a"),
      project_id: identity.project_id,
      dataset_id: identity.dataset_id,
      dataset_version_id: identity.dataset_version_id,
      schema_checksum: checksum("b"),
      catalog_version_id: "catalog-version-1",
      catalog_key: catalogKey,
      catalog_checksum: checksum("c"),
      binding_id: "binding-1",
      binding_revision: 4,
      binding_revision_checksum: checksum("d"),
      crosswalk_id: "crosswalk-1",
      crosswalk_revision: 3,
      crosswalk_revision_checksum: checksum("e"),
      accepted_annotation_count: 1,
      source: "exact_current_binding_and_accepted_crosswalk_decisions",
      ...mutationProof,
    },
    annotations: [
      {
        annotation_id: "annotation-1",
        dataset_field: "SyntheticField",
        mapping_state: "exact_verified",
        mapping_accepted: true,
        candidate_attribute_code: "SYN001",
        authority_state: "provider_exact",
        provider_authoritative: true,
        non_authoritative_reasons: [],
        binding_id: "binding-1",
        binding_revision: 4,
        binding_revision_checksum: checksum("d"),
        binding_status: "active",
        binding_current: true,
        entitlement_verified: true,
        crosswalk_id: "crosswalk-1",
        crosswalk_revision: 3,
        catalog_version_id: "catalog-version-1",
        catalog_key: catalogKey,
        catalog_checksum: checksum("c"),
        description: "Provider-authoritative synthetic attribute description.",
        data_type: "integer",
        units: "months",
        attribute_definition_checksum: checksum("f"),
        ordinary_range: {
          attribute_code: "SYN001",
          definition_id: "range-SYN001",
          definition_checksum: checksum("a"),
          ordinary_min: "0",
          ordinary_max: "120",
          range_expression: "0 through 120 months",
        },
        special_definitions: [{
          attribute_code: "SYN001",
          definition_id: "special-SYN001-minus-nine",
          definition_checksum: checksum("b"),
          value_code: "-9",
          semantic_family: "no_hit",
          meaning: "No eligible bureau record was returned.",
        }],
        ...mutationProof,
      },
    ],
  };
}

test("bounded client issues one exact-version GET and returns the exact annotation lineage", async () => {
  const calls = [];
  globalThis.fetch = async (url, init) => {
    calls.push({ url, init });
    return {
      ok: true,
      status: 200,
      json: async () => validEnvelope(),
    };
  };
  const contract = await api.fetchBureauSemanticAnnotations({
    projectId: identity.project_id,
    datasetIdentity: identity,
  });
  assert.equal(calls.length, 1);
  assert.equal(
    calls[0].url,
    "/api/data/projects/project-semantic/datasets/dataset-semantic/versions/version-semantic/bureau-metadata/annotations",
  );
  assert.equal(calls[0].init.method, "GET");
  assert.equal(calls[0].init.credentials, "include");
  assert.equal(contract.state, "available");
  assert.equal(contract.annotationSet.bindingId, "binding-1");
  assert.equal(contract.annotationSet.crosswalkRevision, 3);
  assert.equal(contract.annotationSet.annotationSetChecksum, checksum("a"));
  assert.equal(contract.annotations[0].providerAuthoritative, true);
  assert.equal(contract.annotations[0].description, "Provider-authoritative synthetic attribute description.");
  assert.equal(contract.annotations[0].dataType, "integer");
  assert.equal(contract.annotations[0].units, "months");
  assert.equal(contract.annotations[0].ordinaryRange.expression, "0 through 120 months");
  assert.equal(contract.annotations[0].specialDefinitions[0].semanticFamily, "no_hit");
  assert.equal(contract.annotations[0].attributeDefinitionChecksum, checksum("f"));
});

test("404 and 403 remain safe non-authoritative states without reading an error payload", async () => {
  for (const [status, reason] of [
    [404, "not_bound"],
    [403, "not_entitled"],
  ]) {
    globalThis.fetch = async () => ({
      ok: false,
      status,
      json: async () => {
        throw new Error("restricted payload must not be read");
      },
    });
    const contract = await api.fetchBureauSemanticAnnotations({
      projectId: identity.project_id,
      datasetIdentity: identity,
    });
    assert.deepEqual(contract, {
      state: "unavailable",
      authoritative: false,
      reason,
      annotations: [],
    });
  }
});

test("stale or contradictory exact-version annotations fail closed", () => {
  const wrongVersion = validEnvelope();
  wrongVersion.annotation_set.dataset_version_id = "different-version";
  assert.throws(
    () => api.assertBureauSemanticAnnotationContract(wrongVersion, identity),
    /do not match the current exact dataset binding/i,
  );

  const staleBinding = validEnvelope();
  staleBinding.annotations[0].binding_current = false;
  assert.throws(
    () => api.assertBureauSemanticAnnotationContract(staleBinding, identity),
    /authority does not match|contradicts its exact annotation-set identity/i,
  );
});

test("provider authority cannot be asserted for derived or unresolved mappings", () => {
  const derived = validEnvelope();
  Object.assign(derived.annotations[0], {
    mapping_state: "transformed_or_derived",
    authority_state: "non_authoritative_derived",
    provider_authoritative: false,
    non_authoritative_reasons: ["derived_mapping"],
  });
  const safeDerived = api.assertBureauSemanticAnnotationContract(derived, identity);
  assert.equal(safeDerived.annotations[0].providerAuthoritative, false);
  assert.equal(safeDerived.annotations[0].authorityState, "non_authoritative_derived");

  const forgedDerived = structuredClone(derived);
  forgedDerived.annotations[0].provider_authoritative = true;
  forgedDerived.annotations[0].authority_state = "provider_exact";
  forgedDerived.annotations[0].non_authoritative_reasons = [];
  assert.throws(
    () => api.assertBureauSemanticAnnotationContract(forgedDerived, identity),
    /authority does not match/i,
  );

  const unresolved = validEnvelope();
  Object.assign(unresolved.annotations[0], {
    mapping_state: "unresolved",
    candidate_attribute_code: null,
    authority_state: "non_authoritative_unresolved",
    provider_authoritative: false,
    non_authoritative_reasons: ["mapping_unresolved"],
  });
  assert.throws(
    () => api.assertBureauSemanticAnnotationContract(unresolved, identity),
    /unresolved field cannot expose provider semantics/i,
  );
});

test("provider semantic content stays within the bounded presentation contract", () => {
  const oversizedDescription = validEnvelope();
  oversizedDescription.annotations[0].description = "x".repeat(1_025);
  assert.throws(
    () => api.assertBureauSemanticAnnotationContract(oversizedDescription, identity),
    /missing description/i,
  );

  const tooManyDefinitions = validEnvelope();
  tooManyDefinitions.annotations[0].special_definitions = Array.from(
    { length: 65 },
    (_, index) => ({
      attribute_code: "SYN001",
      definition_id: `definition-${index}`,
      definition_checksum: checksum("c"),
      value_code: String(index),
      semantic_family: "other",
      meaning: "Bounded synthetic definition.",
    }),
  );
  assert.throws(
    () => api.assertBureauSemanticAnnotationContract(tooManyDefinitions, identity),
    /invalid special-definition collection/i,
  );
});

test("canonical DA-to-EDA handoff fetches once and carries exact bounded semantic identities", () => {
  assert.equal(
    (handoffSource.match(/fetchBureauSemanticAnnotations\(\{/g) ?? []).length,
    1,
  );
  for (const field of [
    "bureau_semantic_annotation_set_id",
    "bureau_semantic_annotation_set_checksum",
    "bureau_metadata_schema_checksum",
    "bureau_metadata_binding_id",
    "bureau_metadata_binding_revision",
    "bureau_metadata_binding_revision_checksum",
    "bureau_metadata_crosswalk_id",
    "bureau_metadata_crosswalk_revision",
    "bureau_metadata_crosswalk_revision_checksum",
    "bureau_metadata_catalog_version_id",
    "bureau_metadata_catalog_checksum",
  ]) {
    assert.ok(handoffSource.includes(field), `Missing semantic handoff field ${field}`);
  }
  assert.match(handoffSource, /semanticLineageKeys\.some/);
  assert.match(handoffSource, /data_acquisition_handoff_mismatch/);
});

test("Special-Value Review remains table-first and separates every semantic source", () => {
  assert.match(panelSource, /<TableHeader className="w-40">Catalog match state<\/TableHeader>/);
  assert.match(panelSource, /aria-label=\{`Selected treatment for \$\{variable\.variable\}`\}/);
  for (const label of [
    "Provider catalog definition",
    "Analyst-approved crosswalk",
    "Dataset-observed behavior",
    "ATLAS heuristic detection",
    "Unverified candidate",
  ]) {
    assert.ok(panelSource.includes(label), `Missing separate semantic source: ${label}`);
  }
  assert.ok(panelSource.includes(
    "No authoritative catalog mapping is available for this field. ATLAS will continue to show observed special-value behavior, but it will not assign a provider definition without approved mapping evidence.",
  ));
  assert.equal(
    (panelSource.match(/fetchBureauSemanticAnnotations\(\{/g) ?? []).length,
    1,
  );
  assert.match(clientSource, /"not_bound" \| "not_entitled" \| "service_unavailable"/);
  assert.match(panelSource, /reason: "service_unavailable"/);
  assert.match(panelSource, /const annotationContractPromise = fetchBureauSemanticAnnotations/);
  assert.match(panelSource, /setResult\(payload\);[\s\S]*annotationContractPromise\.then/);
  assert.doesNotMatch(panelSource, /Promise\.all\(\[[\s\S]*fetchBureauDetection/);
  assert.doesNotMatch(clientSource, /localStorage|sessionStorage|window\.location|URLSearchParams/);
  assert.doesNotMatch(panelSource, /window\.location\.reload/);
  assert.doesNotMatch(panelSource, /semanticAnnotations[\s\S]{0,80}updateVariableDefault/);
  for (const semanticLabel of [
    "Description:",
    "Data type / units:",
    "Ordinary range:",
    "Authority basis:",
    "Catalog revision:",
    "definition checksum",
  ]) {
    assert.ok(panelSource.includes(semanticLabel), `Missing bounded semantic detail: ${semanticLabel}`);
  }
  assert.match(panelSource, /verifiedCatalogDefinition && annotation/);
  assert.match(
    panelSource,
    /annotation\.mappingState === "exact_verified"[\s\S]{0,120}annotation\.mappingState === "approved_alias"/,
  );
  assert.match(panelSource, /!annotation\.providerAuthoritative \|\| !annotation\.mappingAccepted/);
});
