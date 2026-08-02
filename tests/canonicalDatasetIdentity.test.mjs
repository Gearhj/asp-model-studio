import assert from "node:assert/strict";
import { mkdir, mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import test, { after } from "node:test";
import ts from "typescript";

const ROOT = new URL("..", import.meta.url);
const TMP_DIR = await mkdtemp(
  path.join(tmpdir(), "atlas-canonical-dataset-identity-"),
);

async function transpileSource(sourcePath, outputName) {
  const source = await readFile(new URL(sourcePath, ROOT), "utf8");
  const output = ts.transpileModule(source, {
    compilerOptions: {
      module: ts.ModuleKind.ES2022,
      target: ts.ScriptTarget.ES2022,
      importsNotUsedAsValues: ts.ImportsNotUsedAsValues.Remove,
    },
  }).outputText.replace(
    /from\s+["']\.\/datasetIdentity["'];/g,
    'from "./datasetIdentity.mjs";',
  );
  await mkdir(TMP_DIR, { recursive: true });
  const outputPath = path.join(TMP_DIR, outputName);
  await writeFile(outputPath, output, "utf8");
  return import(pathToFileURL(outputPath).href);
}

after(async () => {
  await rm(TMP_DIR, { recursive: true, force: true });
});
const identity = await transpileSource("src/lib/datasetIdentity.ts", "datasetIdentity.mjs");
const access = await transpileSource("src/lib/enterpriseDataAccess.ts", "enterpriseDataAccess.mjs");
const datasetLibrary = await transpileSource("src/lib/datasetLibrary.ts", "datasetLibrary.mjs");

class MemoryStorage {
  #values = new Map();

  clear() {
    this.#values.clear();
  }

  getItem(key) {
    return this.#values.has(key) ? this.#values.get(key) : null;
  }

  setItem(key, value) {
    this.#values.set(key, String(value));
  }

  removeItem(key) {
    this.#values.delete(key);
  }
}

globalThis.localStorage = new MemoryStorage();

const REGISTERED = {
  project_id: "project-001",
  dataset_id: "dataset-heloc",
  dataset_version_id: "v_registered_001",
};

function buildAccessMetadata() {
  return access.buildDataAccessMetadata({
    dataset: {
      headers: ["risk_score", "bad_flag"],
      rows: [
        { risk_score: 640, bad_flag: 0 },
        { risk_score: 515, bad_flag: 1 },
      ],
      target: "bad_flag",
    },
    sourceType: "existing",
    sourceLabel: "HELOC registered version",
    samplingMethod: "full",
    samplingDetail: "All rows",
  });
}

test("browser-generated access metadata cannot masquerade as canonical dataset identity", () => {
  const metadata = buildAccessMetadata();

  assert.match(metadata.accessMetadataId, /^\d{14}-[a-f0-9]{8}$/);
  assert.match(metadata.accessSourceId, /^existing-[a-f0-9]{8}$/);
  assert.equal(Object.hasOwn(metadata, "version"), false);
  assert.equal(Object.hasOwn(metadata, "datasetId"), false);
  assert.notEqual(metadata.accessMetadataId, REGISTERED.dataset_version_id);
});

test("legacy browser access fields are reclassified without becoming canonical identity", () => {
  localStorage.clear();
  localStorage.setItem(
    access.DATA_ACCESS_METADATA_KEY,
    JSON.stringify({
      version: "20260729212115-f471e706",
      datasetId: "existing-f471e706",
      hash: "f471e706",
      sourceType: "existing",
      sourceLabel: "Legacy access snapshot",
    }),
  );

  const metadata = access.loadDataAccessMetadata();
  assert.equal(metadata.accessMetadataId, "20260729212115-f471e706");
  assert.equal(metadata.accessSourceId, "existing-f471e706");
  assert.equal(Object.hasOwn(metadata, "version"), false);
  assert.equal(Object.hasOwn(metadata, "datasetId"), false);
});

test("browser access history persists explicit subordinate identifiers", () => {
  localStorage.clear();
  const metadata = buildAccessMetadata();
  const history = access.recordDataAccessHistory(
    {
      headers: ["risk_score", "bad_flag"],
      rows: [{ risk_score: 640, bad_flag: 0 }],
      target: "bad_flag",
      selected_columns: ["risk_score"],
    },
    metadata,
  );

  assert.equal(history[0].accessMetadataId, metadata.accessMetadataId);
  assert.equal(history[0].accessSourceId, metadata.accessSourceId);
  assert.equal(Object.hasOwn(history[0], "version"), false);
  assert.equal(Object.hasOwn(history[0], "datasetId"), false);
});

test("the exact registered version survives access metadata and target payload construction", () => {
  const accessMetadata = {
    access_metadata_id: "20260729212115-f471e706",
    profile_snapshot_id: "profile-f471e706",
  };
  const activated = identity.assertExactDatasetActivation(REGISTERED, {
    ...REGISTERED,
    dataset_version_label: "HELOC immutable registration",
  });
  const payload = identity.buildTargetPersistencePayload(activated, {
    target: "bad_flag",
    event_value: 1,
    non_event_value: 0,
    selected_columns: ["risk_score"],
  });

  assert.equal(accessMetadata.access_metadata_id, "20260729212115-f471e706");
  assert.equal(payload.expected_dataset_id, "dataset-heloc");
  assert.equal(payload.expected_dataset_version_id, "v_registered_001");
  assert.equal(Object.hasOwn(payload, "dataset_version_id"), false);
  assert.equal(Object.hasOwn(payload, "version"), false);
});

test("activation fails closed for a different dataset, version, or project", () => {
  for (const contradictory of [
    { ...REGISTERED, dataset_id: "dataset-other" },
    { ...REGISTERED, dataset_version_id: "v_other" },
    { ...REGISTERED, project_id: "project-other" },
  ]) {
    assert.throws(
      () => identity.assertExactDatasetActivation(REGISTERED, contradictory),
      (error) => error instanceof identity.DatasetIdentityError && error.code === "dataset_activation_mismatch",
    );
  }
});

test("canonical identity cannot be synthesized from a deprecated or subordinate version value", () => {
  assert.throws(
    () =>
      identity.requireCanonicalDatasetIdentity({
        project_id: "project-001",
        dataset_id: "dataset-heloc",
        version: "20260729212115-f471e706",
      }),
    (error) => error instanceof identity.DatasetIdentityError && error.code === "missing_canonical_identity",
  );
});

test("pre-training identity accepts only an exact canonical LocalDataset or library pair", () => {
  const fromCanonical = identity.requireLocalDatasetCanonicalIdentity(
    REGISTERED.project_id,
    {
      dataset_id: REGISTERED.dataset_id,
      dataset_version_id: REGISTERED.dataset_version_id,
      dataset_version: REGISTERED.dataset_version_id,
      dataset_library: {
        datasetId: REGISTERED.dataset_id,
        versionId: REGISTERED.dataset_version_id,
      },
    },
  );
  assert.deepEqual(fromCanonical, REGISTERED);

  const fromExactLibraryReference =
    identity.requireLocalDatasetCanonicalIdentity(REGISTERED.project_id, {
      dataset_library: {
        datasetId: REGISTERED.dataset_id,
        versionId: REGISTERED.dataset_version_id,
      },
    });
  assert.deepEqual(fromExactLibraryReference, REGISTERED);
});

test("pre-training identity rejects conflicting canonical and nested library pairs", () => {
  assert.throws(
    () =>
      identity.requireLocalDatasetCanonicalIdentity(REGISTERED.project_id, {
        dataset_id: REGISTERED.dataset_id,
        dataset_version_id: REGISTERED.dataset_version_id,
        dataset_library: {
          datasetId: REGISTERED.dataset_id,
          versionId: "v_registered_002",
        },
      }),
    (error) =>
      error instanceof identity.DatasetIdentityError &&
      error.code === "dataset_identity_mismatch",
  );
});

test("pre-training identity rejects a legacy-only or contradictory compatibility version", () => {
  assert.throws(
    () =>
      identity.requireLocalDatasetCanonicalIdentity(REGISTERED.project_id, {
        dataset_version: REGISTERED.dataset_version_id,
      }),
    (error) =>
      error instanceof identity.DatasetIdentityError &&
      error.code === "missing_canonical_identity",
  );
  assert.throws(
    () =>
      identity.requireLocalDatasetCanonicalIdentity(REGISTERED.project_id, {
        dataset_id: REGISTERED.dataset_id,
        dataset_version_id: REGISTERED.dataset_version_id,
        dataset_version: "browser-profile-f471e706",
      }),
    (error) =>
      error instanceof identity.DatasetIdentityError &&
      error.code === "dataset_identity_mismatch",
  );
});

test("pre-training response verification rejects identity drift and a false legacy alias", () => {
  assert.deepEqual(
    identity.assertExactDatasetIdentity(REGISTERED, {
      ...REGISTERED,
      dataset_version: REGISTERED.dataset_version_id,
    }),
    REGISTERED,
  );
  for (const contradictory of [
    { ...REGISTERED, dataset_id: "dataset-other" },
    { ...REGISTERED, dataset_version_id: "v_registered_002" },
    {
      ...REGISTERED,
      dataset_version: "browser-profile-f471e706",
    },
  ]) {
    assert.throws(
      () => identity.assertExactDatasetIdentity(REGISTERED, contradictory),
      (error) =>
        error instanceof identity.DatasetIdentityError &&
        error.code === "dataset_identity_mismatch",
    );
  }
});

test("browser preparation state is namespaced by the exact canonical triple", () => {
  const first = identity.canonicalDatasetStorageKey(
    "atlas:test-state",
    REGISTERED,
  );
  const second = identity.canonicalDatasetStorageKey("atlas:test-state", {
    ...REGISTERED,
    dataset_version_id: "v_registered_002",
  });

  assert.equal(
    first,
    "atlas:test-state:project-001:dataset-heloc:v_registered_001",
  );
  assert.notEqual(first, second);
  assert.throws(
    () =>
      identity.canonicalDatasetStorageKey("atlas:test-state", {
        project_id: REGISTERED.project_id,
        dataset_id: REGISTERED.dataset_id,
        dataset_version: REGISTERED.dataset_version_id,
      }),
    (error) =>
      error instanceof identity.DatasetIdentityError &&
      error.code === "missing_canonical_identity",
  );
});

test("reopen resolves only the exact persisted authorized version", () => {
  const candidates = [
    { ...REGISTERED, dataset_version_id: "v_registered_002" },
    { ...REGISTERED, dataset_id: "dataset-other" },
    { ...REGISTERED, dataset_version_label: "Exact persisted version" },
  ];

  const reopened = identity.resolveExactReopenDatasetIdentity(REGISTERED, candidates);
  assert.equal(reopened.dataset_version_id, "v_registered_001");

  assert.throws(
    () => identity.resolveExactReopenDatasetIdentity(REGISTERED, candidates.slice(0, 2)),
    (error) => error instanceof identity.DatasetIdentityError && error.code === "dataset_reopen_unresolved",
  );
});

test("activation succeeds only with one committed link and exact selection revision", () => {
  const response = {
    ok: true,
    ...REGISTERED,
    row_count: 6275,
    column_count: 26,
    headers: [],
    selected_columns: [],
    activation_revision: 7,
    link: {
      project_id: REGISTERED.project_id,
      dataset_id: REGISTERED.dataset_id,
      link_status: "active",
    },
    active_selection: {
      ...REGISTERED,
      activation_status: "active",
      activation_revision: 7,
    },
  };
  const result = datasetLibrary.requireDurableDatasetActivation(REGISTERED, response);
  assert.deepEqual(result.canonical, { ...REGISTERED, activation_revision: 7 });
  assert.equal(result.activationRevision, "7");

  assert.throws(
    () => datasetLibrary.requireDurableDatasetActivation(REGISTERED, {
      ...response,
      link: { ...response.link, link_status: "pending" },
    }),
    /active durable project-dataset link/,
  );
  assert.throws(
    () => datasetLibrary.requireDurableDatasetActivation(REGISTERED, {
      ...response,
      active_selection: { ...response.active_selection, activation_revision: 8 },
    }),
    /contradictory durable selection revisions/,
  );
  assert.throws(
    () => datasetLibrary.requireDurableDatasetActivation(REGISTERED, {
      ...response,
      active_selection: { ...response.active_selection, dataset_version_id: "version-other" },
    }),
    /different project, dataset, or immutable version/,
  );
  assert.throws(
    () => datasetLibrary.requireDurableDatasetActivation(REGISTERED, {
      ...response,
      activation_revision: 7.5,
      active_selection: { ...response.active_selection, activation_revision: 7.5 },
    }),
    /durable activation revision/,
  );
});

test("canonical identity preserves only a positive durable activation revision", () => {
  assert.deepEqual(
    identity.requireCanonicalDatasetIdentity({
      ...REGISTERED,
      activation_revision: "9",
    }),
    { ...REGISTERED, activation_revision: 9 },
  );
  for (const invalid of [0, -1, 1.5, "latest", ""] ) {
    if (invalid === "") continue;
    assert.throws(
      () => identity.requireCanonicalDatasetIdentity({
        ...REGISTERED,
        activation_revision: invalid,
      }),
      /invalid activation_revision/,
    );
  }
});

test("frontend contracts expose canonical fields and contain no ordering-based reopen fallback", async () => {
  const [
    localDatasetSource,
    datasetLibrarySource,
    identitySource,
    outliersSource,
    missingSource,
    featureSource,
    splitSource,
    trainingSource,
  ] = await Promise.all([
    readFile(new URL("src/lib/localDataset.ts", ROOT), "utf8"),
    readFile(new URL("src/lib/datasetLibrary.ts", ROOT), "utf8"),
    readFile(new URL("src/lib/datasetIdentity.ts", ROOT), "utf8"),
    readFile(new URL("src/steps/Step04_Outliers.tsx", ROOT), "utf8"),
    readFile(new URL("src/steps/Step04_MissingValues.tsx", ROOT), "utf8"),
    readFile(new URL("src/steps/Step05_EncodingScaling.tsx", ROOT), "utf8"),
    readFile(new URL("src/steps/Step06_BalancingSplit.tsx", ROOT), "utf8"),
    readFile(new URL("src/steps/Step06_Train.tsx", ROOT), "utf8"),
  ]);

  assert.match(localDatasetSource, /\bdataset_id\?: string;/);
  assert.match(localDatasetSource, /\bdataset_version_id\?: string;/);
  assert.match(localDatasetSource, /@deprecated Compatibility-only field/);
  assert.match(datasetLibrarySource, /DatasetActivationResponse = CanonicalDatasetIdentity/);
  assert.match(datasetLibrarySource, /jsonFetch<DatasetActivationResponse>/);
  assert.doesNotMatch(identitySource, /latestVersion|versions?\s*\[\s*0\s*\]/);
  for (const source of [
    outliersSource,
    missingSource,
    featureSource,
    splitSource,
    trainingSource,
  ]) {
    assert.match(source, /requireLocalDatasetCanonicalIdentity/);
    assert.match(source, /dataset_version_id/);
    assert.doesNotMatch(source, /data_access\?\.(?:datasetId|version)/);
  }
  for (const source of [
    outliersSource,
    missingSource,
    featureSource,
    splitSource,
    trainingSource,
  ]) {
    assert.match(
      source,
      /buildCanonicalEvidenceEnvelope\(datasetIdentity,/,
      "Phase 2A evidence must send the canonical snake-case identity envelope.",
    );
  }
  assert.doesNotMatch(splitSource, /versions\.at\(-1\)|latestVersion\s*\?/);
});
