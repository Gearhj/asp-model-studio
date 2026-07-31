import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const read = (path) => readFileSync(path, "utf8");

test("EDA backend requests compare the exact active Dataset Library identity", () => {
  const types = read("server/eda/workspace_types.py");
  const service = read("server/eda/workspace_service.py");
  assert.match(types, /expected_dataset_id:\s*Optional\[str\]/);
  assert.match(types, /expected_dataset_version_id:\s*Optional\[str\]/);
  assert.match(service, /assert_expected_active_identity\(/);
  assert.match(
    service,
    /expected_dataset_version_id=getattr\([\s\S]*"expected_dataset_version_id"/,
  );
  assert.match(service, /"project_id": request\.project_id/);
  assert.match(service, /"dataset_version_id": DATASTORE\.meta\.get\("dataset_version_id"\)/);
});

test("relationship and secondary EDA responses carry and verify canonical identity", () => {
  const step = read("src/steps/Step02_EDA.tsx");
  const relationship = read(
    "src/components/eda/visual/RelationshipExplorer.tsx",
  );
  const distribution = read(
    "src/components/eda/visual/PredictorDistributionExplorer.tsx",
  );
  for (const source of [step, relationship, distribution]) {
    assert.match(source, /expected_dataset_id/);
    assert.match(source, /expected_dataset_version_id/);
    assert.match(source, /assertExactDatasetIdentity\(/);
  }
  assert.match(relationship, /dataset_version_id:\s*string/);
  assert.match(distribution, /dataset_version_id:\s*string/);
});

test("EDA findings persistence is scoped to the canonical triple without global migration", () => {
  const step = read("src/steps/Step02_EDA.tsx");
  assert.match(step, /canonicalDatasetStorageKey\(/);
  assert.match(step, /FINDINGS_KEY_PREFIX/);
  assert.doesNotMatch(step, /localStorage\.getItem\(FINDINGS_KEY_PREFIX\)/);
  assert.doesNotMatch(step, /localStorage\.setItem\(FINDINGS_KEY_PREFIX/);
  assert.match(step, /localStorage\.setItem\(findingsStorageKey/);
  assert.doesNotMatch(
    step,
    /datasetIdentity\?\.datasetId\s*\?\?\s*resolvedOverview\.dataset_version/,
  );
});

test("EDA documentation persists dataset_version_id and derives the compatibility alias", () => {
  const types = read("server/eda/documentation_types.py");
  const service = read("server/eda/documentation_service.py");
  const api = read("src/lib/edaDocumentationApi.ts");
  const payload = read("src/lib/edaDocumentationPayload.ts");
  assert.match(types, /dataset_version_id:\s*str/);
  assert.match(service, /value\["dataset_version"\]\s*=\s*value\["dataset_version_id"\]/);
  assert.match(service, /dataset_version_id\s*=\s*str\(context\.get\("dataset_version_id"\)\s*or\s*""\)/);
  assert.doesNotMatch(
    service,
    /context\.get\("dataset_version_id"\)\s*or\s*context\.get\("dataset_version"\)/,
  );
  assert.match(api, /expected_dataset_version_id/);
  assert.match(api, /assertEdaDocumentationStateIdentity/);
  assert.match(payload, /dataset_version_id:\s*input\.datasetVersion/);
});
