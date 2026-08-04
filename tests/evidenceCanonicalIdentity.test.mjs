import assert from "node:assert/strict";
import { mkdir, mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { pathToFileURL } from "node:url";
import test, { after } from "node:test";
import ts from "typescript";

const ROOT = new URL("..", import.meta.url);
const TMP_DIR = await mkdtemp(path.join(tmpdir(), "atlas-evidence-lineage-"));
const identitySource = await readFile(
  new URL("src/lib/datasetIdentity.ts", ROOT),
  "utf8",
);
const identityOutput = ts.transpileModule(identitySource, {
  compilerOptions: {
    module: ts.ModuleKind.ES2022,
    target: ts.ScriptTarget.ES2022,
  },
}).outputText;
await mkdir(TMP_DIR, { recursive: true });
const identityPath = path.join(TMP_DIR, "datasetIdentity.mjs");
await writeFile(identityPath, identityOutput, "utf8");
const identity = await import(pathToFileURL(identityPath).href);

after(async () => {
  await rm(TMP_DIR, { recursive: true, force: true });
});

const CANONICAL = {
  project_id: "project-001",
  dataset_id: "dataset-heloc",
  dataset_version_id: "version-immutable-001",
};

test("canonical evidence envelope exposes exact snake-case lineage only", () => {
  const envelope = identity.buildCanonicalEvidenceEnvelope(CANONICAL, {
    splitId: "split-001",
  });
  assert.equal(envelope.lineage_contract, "canonical_dataset_version");
  assert.equal(envelope.project_id, CANONICAL.project_id);
  assert.equal(envelope.dataset_id, CANONICAL.dataset_id);
  assert.equal(envelope.dataset_version_id, CANONICAL.dataset_version_id);
  assert.equal(envelope.lineage.project_id, CANONICAL.project_id);
  assert.equal(envelope.lineage.dataset_id, CANONICAL.dataset_id);
  assert.equal(
    envelope.lineage.dataset_version_id,
    CANONICAL.dataset_version_id,
  );
  assert.equal(envelope.lineage.splitId, "split-001");
  assert.equal(Object.hasOwn(envelope, "projectId"), false);
  assert.equal(Object.hasOwn(envelope, "datasetIds"), false);
  assert.equal(Object.hasOwn(envelope.lineage, "datasetVersion"), false);
});

test("canonical evidence envelope cannot be built from legacy aliases", () => {
  assert.throws(
    () =>
      identity.buildCanonicalEvidenceEnvelope({
        projectId: CANONICAL.project_id,
        datasetId: CANONICAL.dataset_id,
        datasetVersion: CANONICAL.dataset_version_id,
      }),
    (error) =>
      error instanceof identity.DatasetIdentityError &&
      error.code === "missing_canonical_identity",
  );
});

test("all Phase 2A evidence surfaces use the canonical evidence envelope", async () => {
  const pages = [
    "src/steps/Step02_EDA.tsx",
    "src/components/BureauReviewPanel.tsx",
    "src/steps/Step04_Outliers.tsx",
    "src/steps/Step04_MissingValues.tsx",
    "src/steps/Step05_EncodingScaling.tsx",
    "src/steps/Step06_BalancingSplit.tsx",
    "src/steps/Step06_Train.tsx",
  ];
  for (const page of pages) {
    const source = await readFile(new URL(page, ROOT), "utf8");
    assert.match(
      source,
      /createEvidence\(\{[\s\S]{0,1200}?\.\.\.buildCanonicalEvidenceEnvelope\(datasetIdentity,/,
      `${page} must bind evidence to the exact active dataset identity.`,
    );
  }
});

test("Data Acquisition supplies its exact active identity to bureau evidence", async () => {
  const source = await readFile(
    new URL("src/steps/Step01_DataAcquisition.tsx", ROOT),
    "utf8",
  );
  assert.match(
    source,
    /<BureauReviewPanel[\s\S]*?datasetIdentity=\{activeDatasetIdentity\}/,
  );
});

test("evidence client types and response checks preserve canonical authority", async () => {
  const source = await readFile(
    new URL("src/lib/evidenceGraph.ts", ROOT),
    "utf8",
  );
  for (const marker of [
    "lineage_contract?:",
    "project_id?: string",
    "dataset_id?: string",
    "dataset_version_id?: string",
    "requireCanonicalDatasetIdentity",
    "assertExactDatasetIdentity",
    "Evidence persistence response",
  ]) {
    assert.ok(source.includes(marker), `Evidence client is missing ${marker}.`);
  }
});
