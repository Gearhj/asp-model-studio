import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const ROOT = new URL("../", import.meta.url);
const read = (path) =>
  readFileSync(new URL(path, ROOT), "utf8").replace(/\r\n/g, "\n");

const acquisition = read("src/steps/Step01_DataAcquisition.tsx");
const eda = read("src/steps/Step02_EDA.tsx");
const documentationApi = read("src/lib/edaDocumentationApi.ts");
const documentationLiveLink = read(
  "src/components/documentation/EdaDocumentationLiveLink.tsx",
);

function includesAll(source, markers, context) {
  for (const marker of markers) {
    assert.match(
      source,
      new RegExp(marker.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")),
      `${context}: missing ${marker}`,
    );
  }
}

test("Data Acquisition exposes one guided, explicit Analysis Partition contract", () => {
  includesAll(
    acquisition,
    [
      'data-testid="analysis-partition-readiness"',
      'data-testid="analysis-partition-holdout-ratio"',
      'data-testid="create-analysis-partition"',
      "Reserve Development and Final Evaluation Populations",
      "Development / Final Holdout Split",
      "/analysis-partitions/status",
      "/analysis-partitions/preview",
      "/analysis-partitions/confirm",
      "analysis_partition_id",
      "development_partition_id",
      "sealed_holdout_partition_id",
      "final_holdout_status",
      "holdout_isolation_status",
    ],
    "guided Analysis Partition workspace",
  );

  assert.match(
    acquisition,
    /\/analysis-partitions\/status[\s\S]{0,1000}method:\s*["']GET["']/,
    "partition readiness must be read from the backend instead of inferred in the browser",
  );
  assert.match(
    acquisition,
    /\/analysis-partitions\/confirm[\s\S]{0,1600}method:\s*["']POST["'][\s\S]{0,1600}reset_existing:\s*false/,
    "confirmation must be an explicit, non-resetting backend command",
  );
  assert.match(acquisition, /INITIAL_HOLDOUT_OPTIONS\s*=\s*\[0\.3,\s*0\.2,\s*0\.1\]/);
  assert.match(acquisition, /development_share:\s*policy\.developmentShare/);
  assert.match(acquisition, /holdout_share:\s*policy\.holdoutShare/);
  assert.match(acquisition, /random_seed:\s*policy\.randomSeed/);
  assert.match(acquisition, /stratification_policy:\s*policy\.stratificationPolicy/);
  assert.match(acquisition, /policy\.stratificationPolicy\s*===\s*["']target["']\s*\?\s*target\s*:\s*["']["']/);
  assert.doesNotMatch(acquisition, /confirmation_acknowledged/);
  assert.match(
    acquisition,
    /analysisPartitionMatches\([\s\S]{0,500}policy/,
    "the confirmation response must match the exact reviewer-selected policy before progression",
  );
  assert.match(
    acquisition,
    /readiness\s*===\s*["']current["']|status\s*===\s*["']current["']/,
    "only a backend-current partition may grant EDA progression",
  );
});

test("Continue to EDA requires both acquisition completion and a current partition", () => {
  const stepShellStart = acquisition.lastIndexOf("<StepShell");
  const stepShellEnd = acquisition.indexOf("</StepShell>", stepShellStart);
  assert.ok(stepShellStart >= 0 && stepShellEnd > stepShellStart, "StepShell wiring is missing");
  const stepShell = acquisition.slice(stepShellStart, stepShellEnd + 1);

  assert.match(stepShell, /nextPath=["']\/step02["']/);
  assert.match(
    stepShell,
    /nextDisabled=\{!acquisitionStatus\.canContinue\}/,
    "the StepShell gate must use the unified Data Acquisition readiness model",
  );
  assert.match(
    acquisition,
    /if \(!baseAcquisitionStatus\.canContinue\) \{?\s*return baseAcquisitionStatus;[\s\S]{0,4000}?if \(analysisPartitionIsCurrent\) return baseAcquisitionStatus;/,
    "the unified readiness model must require base completion and Analysis Partition currency",
  );
  assert.match(
    acquisition,
    /create-analysis-partition[\s\S]{0,500}disabled=/,
    "the confirmation command must expose its disabled state",
  );
});

test("EDA maps governed readiness conflicts to precise recovery instead of dataset re-registration", () => {
  includesAll(
    eda,
    [
      "analysis_partition_required",
      "analysis_partition_stale",
      "analysis_partition_contradictory",
      "predictor_authorization_required",
      "target_contract_stale",
      "dataset_identity_unavailable",
      "Analysis Partition",
    ],
    "typed EDA readiness errors",
  );
  assert.match(
    eda,
    /typeof\s+(?:rawDetail|detail)\s*===\s*["']string["']/,
    "plain-string FastAPI detail payloads must remain visible",
  );
  assert.match(
    eda,
    /(?:domain|kind):\s*["'](?:analytical_scope|analysis_partition|identity|authorization|transport|documentation)["']/,
    "EDA errors must carry a domain/kind in addition to an HTTP status",
  );
  assert.doesNotMatch(
    eda,
    /ATLAS could not find the registered backend dataset for this project\. Return to Data Acquisition and re-register the dataset/,
    "an analytical-partition 409 must never be presented as a missing registered dataset",
  );
  const partitionMappingStart = eda.indexOf("analysis_partition_required");
  const partitionMappingEnd = eda.indexOf(
    "dataset_identity_unavailable",
    partitionMappingStart,
  );
  assert.ok(
    partitionMappingStart >= 0 && partitionMappingEnd > partitionMappingStart,
    "the structured readiness-code mapping is missing",
  );
  const partitionMapping = eda.slice(
    partitionMappingStart,
    Math.min(eda.length, partitionMappingEnd + 1800),
  );
  assert.doesNotMatch(
    partitionMapping,
    /re-register the dataset/i,
    "generic dataset re-registration is not valid recovery for governed partition conflicts",
  );

  const blockerStart = eda.indexOf("const activeBlockerMessage");
  const blockerEnd = eda.indexOf("const quickSummaryItems", blockerStart);
  assert.ok(blockerStart >= 0 && blockerEnd > blockerStart, "active blocker priority is missing");
  const blockerContract = eda.slice(blockerStart, blockerEnd);
  assert.ok(
    blockerContract.indexOf("error") < blockerContract.indexOf("documentationBlockerMessage"),
    "the primary analytical failure must be shown before a secondary documentation-sync failure",
  );
});

test("the EDA shell distinguishes manifest loading and failure from a verified zero", () => {
  assert.match(eda, /Checking manifest(?:\u2026|\.\.\.)/);
  assert.match(eda, /Manifest not verified/);
  assert.doesNotMatch(eda, /Manifest pending/);
  assert.doesNotMatch(
    eda,
    /overview\?\.headline\?\.predictors\s*\?\?\s*authorizedPredictors\.length/,
    "a missing workspace response must not silently render zero authorized predictors",
  );
  assert.doesNotMatch(
    eda,
    /const predictorCount\s*=\s*Math\.max\(/,
    "an unavailable manifest must not be coerced through Math.max into zero",
  );
  assert.match(
    eda,
    /predictorManifestState|manifestState|predictorCount\s*(?:===|==)\s*null/,
    "the predictor count display must represent an unverified state explicitly",
  );
});

test("EDA documentation failures preserve a typed request contract and verified identity", () => {
  includesAll(
    documentationApi,
    [
      "EdaDocumentationRequestError",
      "status",
      "code",
      "recovery",
    ],
    "EDA documentation request error",
  );
  assert.match(
    documentationApi,
    /export\s+class\s+EdaDocumentationRequestError\s+extends\s+Error/,
  );
  assert.match(
    documentationApi,
    /throw\s+new\s+EdaDocumentationRequestError/,
    "HTTP failures must retain status/code/recovery instead of becoming plain Error",
  );
  assert.match(
    documentationApi,
    /(?:detail\?\.code|detail\.code|structuredDetail\?\.code|structuredDetail\.code)/,
    "structured FastAPI error codes must survive documentation API normalization",
  );

  assert.match(documentationLiveLink, /usePredictiveIdentity\(/);
  assert.match(documentationLiveLink, /verifiedPredictiveIdentity\(/);
  assert.doesNotMatch(
    documentationLiveLink,
    /requireLocalDatasetCanonicalIdentity\([\s\S]{0,200}loadLocalDataset\(/,
    "the live link must bind to the provider-verified identity, not browser-local identity",
  );
});
