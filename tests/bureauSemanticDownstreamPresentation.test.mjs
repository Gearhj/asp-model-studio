import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import ts from "typescript";

const ROOT = new URL("../", import.meta.url);
const read = (path) =>
  readFileSync(new URL(path, ROOT), "utf8").replace(/\r\n/g, "\n");

const clientSource = read("src/lib/bureauSemanticAnnotations.ts");
const componentSource = read("src/components/BureauSemanticContextPanel.tsx");
const pageSources = new Map([
  ["EDA", read("src/steps/Step02_EDA.tsx")],
  ["Outliers", read("src/steps/Step04_Outliers.tsx")],
  ["Missing Values", read("src/steps/Step04_MissingValues.tsx")],
  ["Feature Engineering", read("src/steps/Step05_EncodingScaling.tsx")],
]);

async function compileClient() {
  const patched = clientSource
    .replace(
      /import \{ DATASET_API_BASE \} from "\.\/datasetLibrary";/,
      'const DATASET_API_BASE = "/api/data";',
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
  return import(
    `data:text/javascript;base64,${Buffer.from(output).toString("base64")}`
  );
}

const api = await compileClient();

function annotation(overrides = {}) {
  return {
    datasetField: "SyntheticField",
    mappingState: "exact_verified",
    mappingAccepted: true,
    candidateAttributeCode: "SYN001",
    authorityState: "provider_exact",
    providerAuthoritative: true,
    nonAuthoritativeReasons: [],
    bindingStatus: "active",
    bindingCurrent: true,
    entitlementVerified: true,
    ...overrides,
  };
}

test("each downstream page mounts one shared read-only exact-envelope consumer", () => {
  assert.equal(
    (componentSource.match(/fetchBureauSemanticAnnotations\(\{/g) ?? []).length,
    1,
  );
  for (const [pageName, source] of pageSources) {
    assert.equal(
      (source.match(/<BureauSemanticContextPanel/g) ?? []).length,
      1,
      `${pageName} must mount one semantic context consumer`,
    );
    assert.match(source, new RegExp(`pageName="${pageName}"`));
    assert.doesNotMatch(source, /fetchBureauSemanticAnnotations/);
  }
  assert.match(componentSource, /datasetIdentity\.project_id/);
  assert.match(componentSource, /datasetIdentity\.dataset_id/);
  assert.match(componentSource, /datasetIdentity\.dataset_version_id/);
});

test("only exact and approved-alias mappings that pass every authority check render as provider-authoritative", () => {
  assert.equal(
    api.bureauSemanticAuthorityPresentation(annotation()).providerAuthoritative,
    true,
  );
  assert.equal(
    api.bureauSemanticAuthorityPresentation(
      annotation({
        mappingState: "approved_alias",
        authorityState: "provider_definition_via_approved_alias",
      }),
    ).providerAuthoritative,
    true,
  );

  for (const mappingState of [
    "transformed_or_derived",
    "probable_review_required",
    "ambiguous_review_required",
    "recoding_evidence_required",
    "unresolved",
    "out_of_catalog",
    "rejected",
  ]) {
    const presentation = api.bureauSemanticAuthorityPresentation(
      annotation({ mappingState }),
    );
    assert.equal(
      presentation.providerAuthoritative,
      false,
      `${mappingState} must remain non-authoritative even when an input attempts to forge provider authority`,
    );
    assert.equal(presentation.label, "Heuristic / non-authoritative");
  }

  for (const overrides of [
    { bindingStatus: "stale" },
    { bindingCurrent: false },
    { entitlementVerified: false },
    { mappingAccepted: false },
    { nonAuthoritativeReasons: ["not_current"] },
  ]) {
    assert.equal(
      api.bureauSemanticAuthorityPresentation(annotation(overrides))
        .providerAuthoritative,
      false,
    );
  }
});

test("the compact panel exposes bounded definition and exact revision lineage without raw catalog access", () => {
  for (const required of [
    "View provider definition and lineage",
    "annotation.description",
    "annotation.dataType",
    "annotation.units",
    "annotation.ordinaryRange",
    "annotation.specialDefinitions",
    "annotationSet.bindingRevision",
    "annotationSet.crosswalkRevision",
    "annotationSet.catalogKey.dictionaryVersion",
    "bindingRevisionChecksum",
    "catalogChecksum",
  ]) {
    assert.ok(componentSource.includes(required), `Missing presentation: ${required}`);
  }
  assert.match(componentSource, /Non-authoritative \(identity unavailable\)/);
  assert.match(
    componentSource,
    /if \(!failedClosed && contract\?\.state !== "available"\) return null/,
  );
  assert.doesNotMatch(componentSource, /Loading context|No authoritative provider context/);
  assert.doesNotMatch(
    componentSource,
    /\/catalogs|\/attributes|\/special-values|full_catalog|raw_catalog|catalog\/download|catalog\/export/,
  );
});

test("semantic presentation cannot mutate treatment, imputation, predictor, partition, or feature state", () => {
  assert.match(
    componentSource,
    /does\s+not change calculations, treatments, predictor authorization, the\s+Analysis Partition, or the feature manifest/,
  );
  assert.doesNotMatch(
    componentSource,
    /method:\s*"(?:POST|PUT|PATCH|DELETE)"|localStorage|sessionStorage|indexedDB|window\.location|useNavigate|applyOutlier|MissingConfig|saveFeatureManifest|materialize|predictor_authorization_mutated/,
  );
  assert.doesNotMatch(componentSource, /\.map\(async|Promise\.all/);

  const outliers = pageSources.get("Outliers");
  const missing = pageSources.get("Missing Values");
  const featureEngineering = pageSources.get("Feature Engineering");
  const eda = pageSources.get("EDA");
  assert.match(eda, /activeCanonicalHandoff\.context\.predictor_authorization\s*\.authorized_predictors/);
  assert.match(outliers, /datasetFields=\{allRows\.map\(\(row\) => row\.feature\)\}/);
  assert.match(missing, /datasetFields=\{\(summary\?\.columns \?\? \[\]\)\.map\(\(column\) => column\.name\)\}/);
  assert.match(featureEngineering, /datasetFields=\{eligibleOriginals\.map\(\(feature\) => feature\.feature_name\)\}/);
  for (const source of pageSources.values()) {
    assert.doesNotMatch(
      source,
      /<BureauSemanticContextPanel[\s\S]{0,300}(?:onChange|onApply|onSave|onMaterialize|onAuthorize)=/,
    );
  }
});
