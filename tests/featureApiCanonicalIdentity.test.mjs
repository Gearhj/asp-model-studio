import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const source = (relativePath) =>
  fs.readFileSync(path.join(root, relativePath), "utf8");

test("feature manifest clients send exact version expectations and validate responses", () => {
  const manifest = source("src/lib/featureManifest.ts");
  assert.match(manifest, /expected_dataset_id:\s*identity\.dataset_id/);
  assert.match(manifest, /expected_dataset_version_id:\s*identity\.dataset_version_id/);
  assert.match(manifest, /assertExactDatasetIdentity\(identity,\s*payload/);
});

test("full-data profile clients send and verify the canonical dataset triple", () => {
  const featureProfile = source("src/lib/featureProfiling.ts");
  const qualityProfile = source("src/lib/enterpriseDataAccess.ts");
  for (const client of [featureProfile, qualityProfile]) {
    assert.match(client, /expected_dataset_id/);
    assert.match(client, /expected_dataset_version_id/);
    assert.match(client, /assertExactDatasetIdentity/);
  }
});

test("feature and profile services validate identity before reading the frame", () => {
  const featureService = source("server/features/feature_service.py");
  const featureProfile = source("server/preprocessing/feature_profile_service.py");
  const qualityProfile = source("server/preprocessing/quality_profile_service.py");
  assert.ok(
    featureService.indexOf("identity = _active_identity(") <
      featureService.indexOf("df = DATASTORE.get_base_df()", featureService.indexOf("def preview_features(")),
  );
  for (const profile of [featureProfile, qualityProfile]) {
    assert.ok(
      profile.indexOf("identity = assert_expected_active_identity(") <
        profile.indexOf("df = DATASTORE.get_base_df()"),
    );
  }
});
