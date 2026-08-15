import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const ROOT = new URL("../", import.meta.url);
const read = (path) => readFileSync(new URL(path, ROOT), "utf8").replace(/\r\n/g, "\n");
const acquisition = read("src/steps/Step01_DataAcquisition.tsx");
const balancing = read("src/steps/Step06_BalancingSplit.tsx");

test("Data Acquisition offers only the three product splits and a governed backend preview", () => {
  assert.match(acquisition, /INITIAL_HOLDOUT_OPTIONS\s*=\s*\[0\.3,\s*0\.2,\s*0\.1\]/);
  assert.match(acquisition, /Reserve Development and Final Evaluation Populations/);
  assert.match(acquisition, /Development \/ Final Holdout Split/);
  assert.match(acquisition, /holdoutShare === 0\.3/);
  assert.match(acquisition, /holdoutShare === 0\.1/);
  assert.match(acquisition, /PARTITION_DEFAULTS\.holdoutShare/);
  assert.match(acquisition, /\/analysis-partitions\/preview/);
  assert.match(acquisition, /preview_fingerprint/);
  assert.match(acquisition, /rationaleRequired/);
  assert.match(acquisition, /Create &amp; Seal Analysis Partition/);
  assert.match(acquisition, /% Development \/.*% Final Holdout/);
  assert.match(acquisition, /aria-label="Split option guidance"/);
  assert.match(acquisition, /aria-current=/);
  assert.doesNotMatch(acquisition, /aria-label="Split option guidance"[\s\S]{0,1200}onClick=\{\(\) => props\.onHoldoutShare/);
  assert.doesNotMatch(acquisition, /analysis-partition-confirmation-checkbox/);
  assert.doesNotMatch(acquisition, /Confirm & Seal Analysis Partition/);
  assert.doesNotMatch(acquisition, /confirmation_acknowledged/);
});

test("backend preview renders classification rates and regression coverage, not only counts", () => {
  for (const marker of [
    "Development event rate",
    "Holdout event rate",
    "Full-population event rate",
    "Absolute event-rate difference",
    "Target-band coverage",
    "Extreme-value coverage",
    "Target quantile",
    "represented_bands",
    "coverage_rate",
    "low_extreme_represented",
    "high_extreme_represented",
  ]) assert.ok(acquisition.includes(marker), `missing preview detail: ${marker}`);

  const previewStart = acquisition.indexOf('data-testid="analysis-partition-preview"');
  const previewEnd = acquisition.indexOf("function MessageList", previewStart);
  const preview = acquisition.slice(previewStart, previewEnd);
  assert.ok(previewStart >= 0 && previewEnd > previewStart);
  assert.doesNotMatch(preview, /\?\?\s*["']Recorded["']|\|\|\s*["']Current["']|\?\?\s*["']Evaluated["']/);
  assert.match(preview, /Unavailable/);
  assert.match(acquisition, /function analysisPartitionPreviewHasRequiredEvidence/);
  assert.match(acquisition, /Boolean\(preview\.previewFingerprint\)/);
  assert.match(acquisition, /String\(sufficiency\.overall_status \?\? ["']["']\)/);
  assert.match(acquisition, /const previewEvidenceComplete = analysisPartitionPreviewHasRequiredEvidence/);
  assert.doesNotMatch(acquisition, /rawPreview\.recommendation_status \?\? rawPreview\.status \?\? ["']acceptable["']/);
});

test("partition creation waits for an exact durable current response without bypassing final DA handoff", () => {
  assert.match(acquisition, /createOrReuseAnalysisPartition[\s\S]*previewFingerprint[\s\S]*selectionRationale/);
  assert.match(acquisition, /confirmed\.phase\s*===\s*["']current["']/);
  const createStart = acquisition.indexOf("async function confirmRecommendedAnalysisPartition()");
  const createEnd = acquisition.indexOf("async function retryAnalysisPartitionDocumentation()", createStart);
  assert.ok(createStart >= 0 && createEnd > createStart);
  assert.doesNotMatch(
    acquisition.slice(createStart, createEnd),
    /navigate\(|projectWorkflowRoute\(projectId,\s*["']\/step02["']\)/,
    "sealing a partition must not bypass Special-Value Review and the final DA read-back",
  );
  assert.match(acquisition, /nextPath="\/step02"/);
  assert.match(acquisition, /fetchCanonicalDataAcquisitionEdaHandoff\([\s\S]*exactTargetMapping[\s\S]*exactPersistedContracts[\s\S]*exactPartition/);
});

test("pending partition documentation is read-only and has one explicit retry action", () => {
  for (const marker of [
    'readiness === "documentation_pending"',
    'phase: "documentation_pending"',
    '"sealed-analysis-partition-summary"',
    'data-testid="complete-analysis-partition-documentation"',
    "Complete Partition Documentation",
    "Evidence and MDD read-back must complete before EDA",
    "partitionPresent = current || documentationPending",
    "!partitionPresent",
  ]) assert.ok(acquisition.includes(marker), `missing documentation-retry marker: ${marker}`);

  assert.match(acquisition, /partitionPresent \? \([\s\S]*sealed-analysis-partition-summary/);
  assert.match(acquisition, /!partitionPresent \? \([\s\S]*data-testid="analysis-partition-preview"/);
  assert.match(acquisition, /!partitionPresent \? \([\s\S]*data-testid="create-analysis-partition"/);
  assert.doesNotMatch(acquisition, /window\.location\.(?:reload|assign)|location\.reload/);
});

test("documentation retry is exact, project scoped, and leaves navigation to the final DA action", () => {
  assert.match(acquisition, /\/analysis-partitions\/complete-documentation/);
  for (const field of [
    "project_id: identity.project_id",
    "dataset_id: identity.dataset_id",
    "dataset_version_id: identity.dataset_version_id",
    "target_contract_id:",
    "predictor_authorization_id:",
    "analysis_partition_id:",
    "revision:",
  ]) assert.ok(acquisition.includes(field), `missing exact retry field: ${field}`);
  assert.match(acquisition, /completed\.analysis_partition_id === partition\.analysis_partition_id/);
  assert.match(acquisition, /Number\(completed\.revision\) === Number\(partition\.revision\)/);
  assert.match(acquisition, /completed\.artifact_hash === partition\.artifact_hash/);
  assert.match(acquisition, /completed\.assignment_hash === partition\.assignment_hash/);
  const retryStart = acquisition.indexOf("async function retryAnalysisPartitionDocumentation()");
  const retryEnd = acquisition.indexOf("function leaveAnalysisPartitionResetMode()", retryStart);
  assert.ok(retryStart >= 0 && retryEnd > retryStart);
  assert.match(acquisition.slice(retryStart, retryEnd), /if \(completed\.phase === "current"\)/);
  assert.doesNotMatch(acquisition.slice(retryStart, retryEnd), /navigate\(/);
  assert.match(acquisition, /Safe failure stage:/);
});

test("regression previews and resets normalize to unstratified membership", () => {
  assert.match(acquisition, /problemType\s*===\s*["']regression["']\s*\?\s*["']none["']/);
  assert.match(acquisition, /targetInfo\.kind\s*===\s*["']continuous["'][\s\S]{0,160}["']none["']/);
});

test("the current partition is a complete read-only governed summary", () => {
  for (const marker of [
    '"current-analysis-partition-summary"',
    "Analysis Partition Current",
    "Development rows",
    "Final holdout rows",
    "Partition method",
    "Random seed",
    "Stratification",
    "Created by",
    "Created at",
    "View Partition Evidence",
    "MDD status",
    "Change Split Ratio",
    "?analysisPartition=reset",
  ]) assert.ok(acquisition.includes(marker), `missing current-partition marker: ${marker}`);

  assert.match(acquisition, /expected_current_partition_id:\s*previousPartition\.analysis_partition_id/);
  assert.match(acquisition, /expected_current_revision:\s*Number\(previousPartition\.revision\)/);
  const summaryStart = acquisition.indexOf('"current-analysis-partition-summary"');
  const summaryEnd = acquisition.indexOf("A split-ratio change requires", summaryStart);
  const summary = acquisition.slice(summaryStart, summaryEnd);
  assert.ok(summaryStart >= 0 && summaryEnd > summaryStart);
  assert.doesNotMatch(summary, /\|\|\s*["']Verified["']|\?\?\s*["']Recorded["']/);
  assert.match(summary, /Partition evidence unavailable/);
});

test("Balance and Split references the Data Acquisition partition without duplicate membership controls", () => {
  for (const marker of [
    'data-testid="analysis-partition-read-only-summary"',
    "Data Acquisition Analysis Partition",
    "Development rows",
    "Final holdout rows",
    "Partition method",
    "Seed",
    "Stratification policy",
    "Seal",
    "Evidence",
    "MDD",
    "Choose Validation Approach",
    "Validation approach",
    "Traditional TRAIN / TEST / OOT setup",
    "Number of folds",
    "Shuffle before folding",
    "Fold-local preprocessing",
    "fit_transform_per_fold",
    "model_native_per_fold",
    "Validation design rationale",
    "external-validation",
    "Final Predictor Review",
  ]) assert.ok(balancing.includes(marker), `missing Balance & Split marker: ${marker}`);

  assert.doesNotMatch(balancing, />Holdout size</);
  assert.doesNotMatch(balancing, />Random seed</);
  assert.doesNotMatch(balancing, />Stratification</);
  assert.doesNotMatch(balancing, /Retained temporarily as migration reference/);
});

test("Validation Design fails closed on exact partition identity and does not restore membership from config or browser drafts", () => {
  for (const marker of [
    "${context} Analysis Partition",
    "outerPartitionId !== nestedPartitionId",
    "outerRevision !== nestedRevision",
    "partition.target",
    "final_holdout_status",
    "holdout_isolation_status",
    "stratificationPolicy",
    "analysis_partition_id: exactPartition.analysis_partition_id",
    "analysis_partition_revision: exactPartition.revision",
    "stratify: inheritedStratify",
  ]) assert.ok(balancing.includes(marker), `missing exact-partition guard: ${marker}`);

  const draftStart = balancing.indexOf("type ValidationDraft");
  const draftEnd = balancing.indexOf("type Distribution", draftStart);
  const draft = balancing.slice(draftStart, draftEnd);
  assert.doesNotMatch(draft, /holdoutSize|randomSeed|stratification/);
  assert.doesNotMatch(balancing, /config\.test_size|config\.random_seed/);
  assert.doesNotMatch(balancing, /distributions\?\.full_dataset/);
  assert.match(balancing, /distributions\?\.train_before_balancing/);
  assert.match(
    balancing,
    /distributions\?\.train_before_balancing\s*\?\?\s*[\s\S]{0,80}distributions\?\.development_population/,
  );

  const decisionStart = balancing.indexOf('subject: status.validation_design_id');
  const decisionEnd = balancing.indexOf("systemRecommendation", decisionStart);
  const decision = balancing.slice(decisionStart, decisionEnd);
  assert.doesNotMatch(decision, /testSize|randomSeed|stratif/);
  assert.match(decision, /analysisPartitionId/);
  assert.match(decision, /analysisPartitionRevision/);
});

test("Validation Design keeps fold-local preprocessing and CV-safe balancing configurable", () => {
  assert.match(balancing, /fold_local_preprocessing:\s*foldLocalPreprocessing/);
  assert.match(balancing, /data-testid="fold-local-preprocessing"/);
  assert.match(balancing, /Applied only to each training fold/);
  assert.match(balancing, /Fold-local resampling selected/);
  assert.doesNotMatch(balancing, /Choose no resampling for this CV design/);
  assert.doesNotMatch(balancing, /balanceMethod\s*!==\s*["']none["'][\s\S]{0,180}Choose No resampling/);
  assert.doesNotMatch(balancing, /Balanced target · no resampling recommended|Recommended: No balancing required/);
  assert.match(balancing, /Development event rate · \{formatPercent\(targetStats\.eventRate\)\}/);
  assert.match(balancing, /Current policy · \{balanceMethodLabel\(balanceMethod\)\}/);
  assert.match(balancing, /schema_compatibility_confirmed:\s*false/);
  assert.match(balancing, /target_mapping_verified:\s*false/);
  assert.doesNotMatch(balancing, /schema_compatibility_confirmed:\s*separateTestEnabled|target_mapping_verified:\s*separateTestEnabled/);
});

test("Validation Design describes partition membership as inherited and reports documentation truthfully", () => {
  for (const marker of [
    "Review Inherited Analysis Partition",
    "Data Acquisition already created",
    "without changing partition membership",
    "Partition evidence unavailable",
  ]) assert.ok(balancing.includes(marker), `missing inherited-partition copy: ${marker}`);
  assert.doesNotMatch(balancing, /Choose a protected holdout|Create an untouched holdout|Hold out \$\{/);

  const summaryStart = balancing.indexOf('data-testid="analysis-partition-read-only-summary"');
  const summaryEnd = balancing.indexOf('data-testid="analysis-partition-reset-impact"', summaryStart);
  const summary = balancing.slice(summaryStart, summaryEnd > summaryStart ? summaryEnd : summaryStart + 8000);
  assert.doesNotMatch(summary, /\?\?\s*["']Verified["']|\?\?\s*["']Recorded["']/);
});
