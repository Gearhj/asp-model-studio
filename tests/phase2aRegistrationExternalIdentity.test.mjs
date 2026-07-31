import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const ROOT = new URL("..", import.meta.url);

async function source(path) {
  return readFile(new URL(path, ROOT), "utf8");
}

function between(text, start, end) {
  const startIndex = text.indexOf(start);
  assert.notEqual(startIndex, -1, `Missing source marker: ${start}`);
  const endIndex = text.indexOf(end, startIndex + start.length);
  assert.notEqual(endIndex, -1, `Missing source marker: ${end}`);
  return text.slice(startIndex, endIndex);
}

test("creation APIs expose the exact version created by the operation", async () => {
  const registry = await source("server/datasets/dataset_registry.py");
  const dataframeCreation = between(
    registry,
    "def create_dataset_from_dataframe(",
    "async def add_dataset_version(",
  );

  assert.match(
    dataframeCreation,
    /summary\["created_dataset_version_id"\]\s*=\s*version_id/,
  );
  assert.match(
    dataframeCreation,
    /summary\["created_version"\]\s*=\s*version_summary/,
  );
});

test("workspace and upload activation consume created ID, never latestVersion", async () => {
  const [router, main, acquisition] = await Promise.all([
    source("server/datasets/dataset_router.py"),
    source("server/main.py"),
    source("src/steps/Step01_DataAcquisition.tsx"),
  ]);
  const workspaceRoute = between(
    router,
    "def register_workspace(",
    '@router.get("/datasets/{dataset_id}/versions")',
  );
  const uploadRoute = between(
    main,
    'async def upload_csv(',
    "# Router registration",
  );
  const registrationHandler = between(
    acquisition,
    "async function handleRegisterDevelopmentDataset()",
    "const existingDatasetPicker",
  );

  for (const backendRoute of [workspaceRoute, uploadRoute]) {
    assert.match(
      backendRoute,
      /dataset\.get\("created_dataset_version_id"\)/,
    );
    assert.match(
      backendRoute,
      /"created_dataset_version_id":\s*dataset_version_id/,
    );
    assert.match(backendRoute, /"created_version":\s*dataset\.get\("created_version"\)/);
    assert.doesNotMatch(backendRoute, /latestVersion/);
  }

  assert.match(
    registrationHandler,
    /registration\.created_dataset_version_id/,
  );
  assert.match(registrationHandler, /registration\.created_version/);
  assert.match(
    registrationHandler,
    /dataset_version_id:\s*createdVersionId/,
  );
  assert.doesNotMatch(registrationHandler, /latestVersion/);
});

test("Balance & Split sends exact development, TEST, and OOT version IDs", async () => {
  const split = await source("src/steps/Step06_BalancingSplit.tsx");
  const request = between(
    split,
    'requestJson<SplitStatus>("/balancing_split/config"',
    "verifySplitStatusIdentity(",
  );

  assert.match(
    request,
    /development_dataset_version_id:\s*\n?\s*datasetIdentity\.dataset_version_id/,
  );
  assert.match(
    request,
    /test_dataset_version_id:\s*separateTestEnabled\s*\?\s*testDatasetVersion/,
  );
  assert.match(
    request,
    /oot_dataset_version_id:\s*ootEnabled\s*\?\s*ootDatasetVersion/,
  );
  assert.doesNotMatch(request, /latestVersion/);
  assert.doesNotMatch(request, /versions\s*\[\s*0\s*\]/);
});

test("external pickers pin an explicit selected immutable version", async () => {
  const split = await source("src/steps/Step06_BalancingSplit.tsx");
  const picker = split.slice(split.indexOf("function ExternalDatasetPicker("));

  assert.match(
    picker,
    /\(selected\?\.versions\s*\?\?\s*\[\]\)\.map\(\(version\)/,
  );
  assert.match(
    picker,
    /<option key=\{version\.versionId\} value=\{version\.versionId\}>/,
  );
  assert.doesNotMatch(picker, /latestVersion/);
});

test("split backend requires and persists canonical external version IDs", async () => {
  const backend = await source("server/splitting/split_router.py");

  assert.match(backend, /test_dataset_version_id:\s*str\s*=\s*""/);
  assert.match(backend, /oot_dataset_version_id:\s*str\s*=\s*""/);
  assert.match(
    backend,
    /if not test_dataset_version_id:[\s\S]*exact immutable TEST[\s\S]*dataset_version_id/,
  );
  assert.match(
    backend,
    /if not oot_dataset_version_id:[\s\S]*exact immutable OOT[\s\S]*dataset_version_id/,
  );
  assert.match(
    backend,
    /resolve_registered_version\(\s*dataset_id,\s*dataset_version_id,\s*user=user/,
  );
  assert.match(
    backend,
    /"dataset_version_id":\s*dataset_version_id/,
  );
  assert.match(
    backend,
    /config\["test_dataset_version_id"\]\s*=\s*test_dataset_version_id/,
  );
  assert.match(
    backend,
    /config\["oot_dataset_version_id"\]\s*=\s*oot_dataset_version_id/,
  );
});
