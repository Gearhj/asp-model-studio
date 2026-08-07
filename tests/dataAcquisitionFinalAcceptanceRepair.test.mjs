import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const ROOT = new URL("../", import.meta.url);
const read = (path) =>
  readFileSync(new URL(path, ROOT), "utf8").replace(/\r\n/g, "\n");

const acquisition = read("src/steps/Step01_DataAcquisition.tsx");
const handoff = read("src/lib/dataAcquisitionEdaHandoff.ts");
const identityProvider = read("src/components/PredictiveIdentityProvider.tsx");
const eda = read("src/steps/Step02_EDA.tsx");
const guide = read("src/components/CopilotCard.tsx");
const specialValues = read("src/components/BureauReviewPanel.tsx");
const bureauClient = read("src/lib/bureauDetection.ts");
const bureauMetadataClient = read("src/lib/creditBureau.ts");
const workspaceTypes = read("server/eda/workspace_types.py");
const workspaceService = read("server/eda/workspace_service.py");
const edaRouter = read("server/eda/eda_router.py");

function between(source, startMarker, endMarker, label) {
  const start = source.indexOf(startMarker);
  const end = source.indexOf(endMarker, start + startMarker.length);
  assert.notEqual(start, -1, `Missing ${label} start marker.`);
  assert.ok(end > start, `Missing ${label} end marker.`);
  return source.slice(start, end);
}

test("1-5 canonical handoff carries one exact DA identity into EDA and Atlas Guide", () => {
  const request = between(
    handoff,
    "export function buildCanonicalEdaRequestContract(",
    "export function assertExactEdaResponseLineage(",
    "canonical EDA request",
  );
  for (const field of [
    "project_id",
    "dataset_id",
    "dataset_version_id",
    "activation_revision",
    "target_contract_id",
    "target:",
    "positive_value",
    "negative_value",
    "non_event_value",
    "predictor_authorization_id",
    "analysis_partition_id",
    "analysis_partition_revision",
    "special_value_review_id",
    "special_value_review_revision",
  ]) {
    assert.ok(request.includes(field), `Missing exact handoff field: ${field}`);
  }
  assert.match(eda, /buildCanonicalEdaRequestContract\((?:activeCanonicalHandoff|requestHandoff)\)/);
  assert.match(eda, /assertExactEdaResponseLineage\(requestHandoff, payload\)/);
  assert.match(guide, /dataAcquisitionContextReadiness\.context/);
  assert.match(guide, /MiniContext label="Dataset" value=\{context\.datasetId/);
  assert.match(guide, /MiniContext label="Dataset version" value=\{context\.datasetVersionId/);
  assert.match(guide, /dataAcquisitionContext\?\.target_contract\?\.target/);
});

test("6-8 display labels and stale browser state cannot replace backend identity", () => {
  const request = between(
    handoff,
    "export function buildCanonicalEdaRequestContract(",
    "export function assertExactEdaResponseLineage(",
    "canonical EDA request",
  );
  assert.doesNotMatch(request, /project_name|projectName|dataset_name|datasetName/);
  assert.doesNotMatch(eda, /loadLocalDataset|requireLocalDatasetCanonicalIdentity/);
  assert.match(identityProvider, /const generation = \+\+requestGeneration\.current/);
  assert.match(identityProvider, /controller\.signal\.aborted \|\| generation !== requestGeneration\.current/);
  assert.match(identityProvider, /context\.project_id !== routeProjectId/);
  assert.match(identityProvider, /context\.identity\.dataset_id !== activeIdentity\.dataset_id/);
  assert.match(identityProvider, /context\.identity\.dataset_version_id !== activeIdentity\.dataset_version_id/);
  assert.doesNotMatch(eda, /datasetIdentity\?\.dataset_id \?\? datasetDisplayName/);
});

test("9-13 prerequisite-first entry, verified continuation, deep links, and project isolation are explicit", () => {
  assert.match(handoff, /Special-Value Treatment Review is incomplete\./);
  assert.match(handoff, /review\.status === "confirmed" \|\| review\.status === "not_required"/);
  assert.match(eda, /fetchCanonicalDataAcquisitionEdaHandoff\(\{/);
  assert.match(eda, /dataAcquisitionContextReadiness\.status === "loading"/);
  assert.match(handoff, /context\.project_id !== expectedProjectId/);
  assert.match(acquisition, /nextPath="\/step02"/);
  const finalAction = between(
    acquisition,
    "onNext={async () => {",
    "      }}\n    >",
    "final Data Acquisition action",
  );
  const persist = finalAction.indexOf("await persistDataset()");
  const partitionReadback = finalAction.indexOf("await readAnalysisPartitionReadiness(");
  const exactHandoff = finalAction.indexOf("await fetchCanonicalDataAcquisitionEdaHandoff(");
  const publish = finalAction.indexOf("notifyReproducibilityContextConfirmed()");
  assert.ok(persist >= 0 && partitionReadback > persist && exactHandoff > partitionReadback && publish > exactHandoff);
  assert.match(finalAction, /exactTargetMapping[\s\S]*exactPersistedContracts[\s\S]*exactPartition/);
  assert.match(identityProvider, /routeKey: location\.pathname/);
  assert.match(identityProvider, /dataAcquisitionContextReadiness\.routeKey === location\.pathname/);
});

test("14-15 target-directed EDA materializes development only and proves holdout non-access", () => {
  assert.match(handoff, /payload\.scope !== "development_population"/);
  assert.match(handoff, /finalHoldoutAccessed !== false/);
  assert.match(handoff, /sealed_final_holdout_excluded/);
  assert.match(workspaceService, /analysis_partition_service\.materialize_development\(/);
  assert.match(workspaceService, /"final_holdout_accessed": False/);
  assert.match(workspaceService, /"final_holdout_used_for_selection": False/);
  assert.match(edaRouter, /predictor_only_shape/);
  assert.match(edaRouter, /predictor_only_relationships\(/);
  assert.match(edaRouter, /canonical_lineage_required=True/);
  assert.match(workspaceTypes, /analysis_partition_revision: Optional\[int\]/);
});

test("14b every nested EDA analytical request carries and verifies the exact canonical handoff", () => {
  const targetWorkspace = read("src/components/eda/TargetIntelligenceWorkspace.tsx");
  const targetApi = read("src/lib/targetIntelligenceApi.ts");
  const relationships = read("src/components/eda/visual/RelationshipExplorer.tsx");
  const distributions = read("src/components/eda/visual/PredictorDistributionExplorer.tsx");
  const vifExplorer = read("src/components/eda/visual/VifExplorer.tsx");
  const vifPlan = read("src/components/eda/visual/VifResolutionPlanPanel.tsx");
  assert.match(targetWorkspace, /canonicalRequest: buildCanonicalEdaRequestContract\(canonicalHandoff\)/);
  assert.match(targetWorkspace, /assertExactEdaResponseLineage\(canonicalHandoff, payload\)/);
  assert.match(targetApi, /canonicalLineage: request\.canonicalRequest/);
  assert.match(targetApi, /REQUIRED_EDA_LINEAGE_FIELDS/);
  assert.match(relationships, /\.\.\.buildCanonicalEdaRequestContract\(canonicalHandoff\)/);
  assert.match(relationships, /assertExactEdaResponseLineage\(canonicalHandoff, payload\)/);
  assert.match(distributions, /assertExactEdaResponseLineage\(canonicalHandoff, payload\)/);
  assert.match(distributions, /fetchDistribution\(body, datasetVersion, canonicalHandoff, force\)/);
  assert.match(vifExplorer, /decisionStorageKey\(lineageKey\)/);
  assert.match(vifExplorer, /decisionState\.lineageKey === lineageKey/);
  assert.match(vifPlan, /useEffect\(\(\) => \{[\s\S]*setPlan\(null\)[\s\S]*\}, \[lineageKey\]\)/);
  const vifWorkspace = between(
    eda,
    "const simulateVif = useCallback",
    "const handleCorrelationVariable = useCallback",
    "nested VIF requests",
  );
  assert.equal(
    (vifWorkspace.match(/assertExactEdaResponseLineage\(props\.canonicalHandoff, payload\)/g) ?? []).length,
    3,
  );
  assert.match(eda, /activeHandoffKeyRef\.current !== requestHandoffKey/);
});

test("16-24 split-ratio changes are discoverable, previewed, acknowledged, and revision-safe", () => {
  assert.match(acquisition, /INITIAL_HOLDOUT_OPTIONS\s*=\s*\[0\.3,\s*0\.2,\s*0\.1\]/);
  assert.match(acquisition, /partitionPresent \? \([\s\S]*current-analysis-partition-summary/);
  assert.match(acquisition, /partitionPresent \? \([\s\S]*\) : \([\s\S]*analysis-partition-holdout-ratio/);
  assert.match(acquisition, /Change Split Ratio [^\r\n<]* Creates New Revision/);
  assert.match(acquisition, /data-testid="analysis-partition-reset-workspace"/);
  assert.match(acquisition, /Current partition remains unchanged until explicit confirmation|current revision remains unchanged until explicit confirmation/i);
  assert.match(acquisition, /data-testid="analysis-partition-reset-preview"/);
  assert.match(acquisition, /props\.preview\.developmentRows/);
  assert.match(acquisition, /props\.preview\.holdoutRows/);
  assert.match(acquisition, /data-testid="analysis-partition-reset-current-counts"/);
  assert.match(acquisition, /Current eligible rows/);
  assert.match(acquisition, /Current development rows/);
  assert.match(acquisition, /Current final holdout rows/);
  assert.match(acquisition, /MIN_ANALYSIS_PARTITION_RATIONALE_LENGTH\s*=\s*10/);
  assert.match(acquisition, /!props\.preview\.rationaleRequired\s*\|\|[\s\S]{0,120}MIN_ANALYSIS_PARTITION_RATIONALE_LENGTH/);
  assert.match(acquisition, /data-testid="analysis-partition-reset-reason"/);
  assert.match(acquisition, /data-testid="analysis-partition-reset-invalidation-acknowledgement"/);
  assert.match(acquisition, /Create New Analysis Partition Revision/);
  assert.match(acquisition, /expected_current_partition_id:\s*previousPartition\.analysis_partition_id/);
  assert.match(acquisition, /expected_current_revision:\s*Number\(previousPartition\.revision\)/);
  const resetConfirmationStart = acquisition.indexOf("async function confirmGovernedAnalysisPartitionReset");
  const resetConfirmationEnd = acquisition.indexOf("\n  // `dataAcquisitionDisabledReason`", resetConfirmationStart);
  assert.ok(resetConfirmationStart >= 0 && resetConfirmationEnd > resetConfirmationStart);
  const resetConfirmation = acquisition.slice(resetConfirmationStart, resetConfirmationEnd);
  assert.doesNotMatch(resetConfirmation, /persistDataset\(/);
  assert.match(resetConfirmation, /currentDurablePredictorAuthorizationId\(latest\)/);
  assert.doesNotMatch(resetConfirmation, /latest\.predictor_authorization_id\s*\?\?/);
  assert.match(acquisition, /Leave current partition unchanged|current Analysis Partition was not changed/i);
  for (const liveId of [
    "atlas-mrzpau4t",
    "ds_heloc_train_6bdb184b_05905",
    "v_1785186305905_6bdb184b",
    "analysis-partition-688c2184b4e9b8181946-r1",
  ]) {
    assert.doesNotMatch(`${acquisition}\n${handoff}\n${eda}`, new RegExp(liveId));
  }
});

test("25-30 special-value review is one feature table with inline policy and expandable code evidence", () => {
  assert.doesNotMatch(specialValues, /Variable Navigator/);
  assert.match(specialValues, /data-testid="special-value-feature-table"/);
  assert.match(specialValues, /filteredVariables\.map\(\(variable, variableIndex\)/);
  assert.match(specialValues, /aria-label=\{`Selected treatment for \$\{variable\.variable\}`\}/);
  assert.match(specialValues, /<option value="unresolved_first">Unresolved first<\/option>/);
  assert.match(specialValues, /data-testid="special-value-code-details-row"/);
  for (const heading of [
    "Attribute",
    "Number of special codes",
    "Special-code summary",
    "Affected rows",
    "Population percentage",
    "Largest event-rate difference",
    "Recommended treatment",
    "Selected treatment",
    "Rationale status",
    "Overrides",
    "Review status",
    "Details action",
  ]) {
    assert.ok(specialValues.includes(heading), `Missing feature table column: ${heading}`);
  }
  for (const detail of [
    "Special value",
    "Definition",
    "Count",
    "Population share",
    "Development event count",
    "Development event rate",
    "Development regular-value event rate",
    "Development event-rate difference",
    "Override action",
    "Rationale",
  ]) {
    assert.ok(specialValues.includes(detail), `Missing code-level detail: ${detail}`);
  }
});

test("31 bureau values remain distinct from missingness and outliers with development-only target evidence", () => {
  assert.match(specialValues, /separate from true nulls, parse failures, and ordinary outliers/);
  assert.match(specialValues, /Development population only/);
  assert.match(specialValues, /sealed final holdout was not accessed/);
  assert.match(bureauClient, /target_analysis_scope: "development_population"/);
});

test("32-34 completion, first-blocker navigation, and confirmed summary are exact", () => {
  assert.match(specialValues, /const reviewedCount = durableReview\?\.reviewed_count \?\? 0/);
  assert.match(specialValues, /const unresolvedCount = durableReview\?\.open_count \?\? likelyVariables\.length/);
  assert.match(specialValues, /firstUnresolvedVariable/);
  assert.match(acquisition, /FOCUS_FIRST_SPECIAL_VALUE_REVIEW_EVENT/);
  assert.match(acquisition, /window\.dispatchEvent\([\s\S]*FOCUS_FIRST_SPECIAL_VALUE_REVIEW_EVENT/);
  assert.match(specialValues, /setVariableSearch\(""\)/);
  assert.match(specialValues, /setReviewFilter\("all"\)/);
  assert.match(specialValues, /setTreatmentFilter\("all"\)/);
  assert.match(specialValues, /scrollIntoView\(\{ behavior: "smooth", block: "center" \}\)/);
  assert.match(specialValues, /data-testid="confirmed-special-value-summary"/);
  assert.match(specialValues, /Reviewed: \{reviewedCount\}\/\{likelyVariables\.length\}/);
  assert.match(specialValues, /Durable revision:/);
  assert.match(specialValues, /Evidence:/);
  assert.match(specialValues, /Review or Change Treatments/);
  assert.match(specialValues, /Retry Evidence/);
});

test("35 bulk and row-level treatments remain explicit unsaved drafts until save or confirmation", () => {
  assert.match(specialValues, /function explicitVariableDefault\(/);
  assert.match(specialValues, /<option value="" disabled>Select treatment<\/option>/);
  assert.match(specialValues, /if \(!policy\) \{[\s\S]*unresolved: 1/);
  assert.doesNotMatch(specialValues, /missingDefaults\.map\([\s\S]*handling: "preserve_informative"/);
  assert.match(specialValues, /Apply selected default to unresolved attributes/);
  assert.match(specialValues, /Selecting a bulk treatment changes nothing until you[\s\S]*press Apply/);
  assert.match(specialValues, /they are neither saved nor confirmed automatically/);
  assert.match(specialValues, /browser draft[\s\S]*Save Draft Review or confirm explicitly to make it durable/);
  const bulk = between(
    specialValues,
    "function applyBulkTreatment()",
    "function updateOverride(",
    "bulk treatment handler",
  );
  assert.doesNotMatch(bulk, /persistReview\(|updateSpecialValueReview\(/);
});

test("special-value authority, evidence, replacement, sorting, and scopes fail closed", () => {
  const reviewService = read("server/preprocessing/special_value_review_service.py");
  const reviewRepository = read("server/persistence/repositories/special_value_review_repository.py");
  const detectionService = read("server/preprocessing/bureau_detection_service.py");
  assert.match(bureauClient, /bureauReviewDraftKey\(projectId: string\)/);
  assert.match(bureauClient, /Project-scoped callers must never inherit another project's legacy draft/);
  assert.match(specialValues, /validatedDetectionContextRef/);
  assert.match(specialValues, /bureauDraftMatchesContract\(scopedDraft, exactReview\)/);
  assert.match(specialValues, /durableOpenVariables\.has\(variable\.variable\)/);
  assert.match(specialValues, /!explicitVariableDefault\(state, variable\.variable\)/);
  assert.match(specialValues, /affected_rows_desc/);
  assert.match(specialValues, /special_code_count_desc/);
  assert.match(specialValues, /event_rate_delta_desc/);
  assert.match(specialValues, /special-value-replacement-/);
  assert.match(specialValues, /exactEvidenceReadBack/);
  assert.match(specialValues, /await getEvidence\(createdEvidence\.evidenceId\)/);
  assert.match(reviewService, /governed_replacement_value_required/);
  assert.match(reviewService, /cannot use another detected special code/);
  assert.match(reviewRepository, /_assert_confirmed_replacements\(/);
  assert.match(reviewRepository, /variable_row=variable_row/);
  assert.match(handoff, /analysisPartitionId:[\s\S]*context\.analysis_partition\.analysis_partition_id/);
  assert.match(handoff, /analysisPartitionRevision: context\.analysis_partition\.revision/);
  assert.match(bureauClient, /special_value_review_id: contract\.special_value_review_id/);
  assert.match(bureauClient, /special_value_review_revision: contract\.revision/);
  assert.match(bureauMetadataClient, /bureauMetadataStorageKey\(scope/);
  assert.doesNotMatch(
    specialValues,
    /Upload metadata CSV|saveBureauMetadata|parseBureauMetadataCsv/,
  );
  assert.doesNotMatch(bureauClient, /loadBureauMetadata|metadata:\s*input\.metadata/);
  assert.match(
    specialValues,
    /const payload = await fetchBureauDetection\(\{[\s\S]*?assertSpecialValueReviewContract\(payload\.special_value_review, lineage\);[\s\S]*?const exactReview = await fetchSpecialValueReview\(\{ lineage, signal \}\);/,
  );
  assert.doesNotMatch(specialValues, /fetchSpecialValueReviewForIdentity\(/);
  assert.match(specialValues, /annotationContractPromise/);
  assert.match(specialValues, /projectWorkflowRoute\(projectId, "\/step01"\)/);
  for (const field of [
    "analysis_partition_id",
    "analysis_partition_revision",
    "analysis_partition_assignment_hash",
    "analysis_partition_artifact_hash",
    "development_target_checksum",
    "source_checksum",
  ]) {
    assert.ok(reviewService.includes(field), `Missing review lineage field: ${field}`);
  }
  assert.match(detectionService, /"structural_scope": "full_governed_population_predictors_only"/);
  assert.match(detectionService, /"target_analysis_scope": target_analysis_scope/);
  assert.match(detectionService, /"final_holdout_accessed": False/);
});

test("special-value profiles flow into predictor review with retryable exact profiling", () => {
  assert.match(specialValues, /onReviewResult\?: \(result: BureauReviewPanelResult \| null\)/);
  assert.match(acquisition, /onReviewResult=\{handleBureauReviewResult\}/);
  assert.match(acquisition, /const bureauSpecialValueProfiles = useMemo/);
  assert.match(acquisition, /variable\.special_value_count/);
  assert.match(acquisition, /variable\.special_value_frequency/);
  assert.match(acquisition, /variable\.special_values\.map\(\(profile\) => profile\.value\)/);
  for (const testId of [
    "predictor-special-value-count",
    "predictor-special-value-rate",
    "predictor-special-value-codes",
    "predictor-special-value-review-status",
    "feature-profile-error",
    "feature-profile-retry",
  ]) {
    assert.match(acquisition, new RegExp(`data-testid="${testId}"`));
  }
  assert.match(acquisition, /datasetId: activeDatasetIdentity\?\.dataset_id/);
  assert.match(acquisition, /versionId: activeDatasetIdentity\?\.dataset_version_id/);
  assert.match(acquisition, /setFeatureProfileRetryRevision\(\(revision\) => revision \+ 1\)/);
  assert.match(acquisition, /const fallbackColumns = Array\.from/);
  assert.match(acquisition, /new Set\(\[\.\.\.headers, \.\.\.bureauSpecialValueProfiles\.keys\(\)\]\)/);
  assert.match(acquisition, /type: specialValues\?\.datatype \?\? "Unavailable"/);
  assert.match(acquisition, /iv: null,[\s\S]{0,80}corr: null/);
  assert.match(acquisition, /typeof row\.distinct === "number"/);
});
