import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const read = (path) => readFileSync(new URL(`../${path}`, import.meta.url), "utf8");

const evaluation = read("src/steps/Step08_Evaluation.tsx");
const interpretation = read("src/steps/Step09_Interpretation.tsx");
const scoring = read("src/steps/Step10_Scoring.tsx");
const candidates = read("src/lib/interpretationCandidates.ts");
const journal = read("src/lib/decisionJournal.ts");

assert.doesNotMatch(evaluation, /Select for Interpretation/, "Evaluation must not use the rejected checkbox-selection pattern.");
assert.doesNotMatch(evaluation, /type=["']checkbox["']/, "Evaluation must not expose model-selection checkboxes.");
assert.match(evaluation, /Review locked candidate/, "Evaluation must expose an explicit locked-candidate review action.");
assert.match(evaluation, /Add to Comparison/, "Evaluation must expose a comparison-tray action.");
assert.match(evaluation, /Open Interpretation/, "Evaluation must expose direct Interpretation navigation.");
assert.match(evaluation, /saveInterpretationCandidates\(activeIdentity, limited\)/, "Evaluation must persist the comparison tray by exact canonical dataset identity.");
assert.match(evaluation, /comparison\.length >= 4/, "Evaluation must cap the persistent comparison tray at four candidates.");
assert.match(evaluation, /nextDisabled=\{!selectedModel \|\| !exactEvaluationPackageId\}/, "Evaluation cannot continue without one exact candidate and its completed evaluation package.");
assert.match(evaluation, /evaluation_package_id=\$\{encodeURIComponent\(exactEvaluationPackageId\)\}/, "Evaluation must hand Interpretation an explicit immutable package identity.");
assert.match(evaluation, /candidate_decision_id=\$\{encodeURIComponent\(selectionDecision\.decision_id\)\}/, "Evaluation must hand Interpretation the exact locked candidate decision.");
assert.doesNotMatch(evaluation, /current leaderboard champion/i, "Evaluation must not imply automatic Champion approval.");

assert.doesNotMatch(interpretation, /loadInterpretationCandidates\(activeIdentity\)/, "Interpretation must not use browser-local candidate state as authority.");
assert.match(interpretation, /No models selected for Interpretation/, "Interpretation must provide a recovery state when no candidates were selected.");
assert.match(interpretation, /setModels\(\[requestedSelection\]\)/, "Interpretation must limit analysis to the exact server-returned locked candidate.");
assert.match(interpretation, /const location = useLocation\(\)/, "Interpretation must observe same-route query changes instead of snapshotting the first browser URL.");
assert.match(interpretation, /new URLSearchParams\(location\.search\)/, "Interpretation must parse the router-authoritative query.");
assert.match(interpretation, /\[location\.search\]/, "Interpretation query identity must be recomputed whenever the route query changes.");
assert.match(interpretation, /requestedQuery\.get\("candidate_id"\)/, "Interpretation must honor exact candidate navigation from Evaluation.");
assert.match(interpretation, /requestedQuery\.get\("evaluation_package_id"\)/, "Interpretation must require the explicit Evaluation package identity.");
assert.match(interpretation, /requestedQuery\.get\("candidate_decision_id"\)/, "Interpretation must require the explicit locked decision identity.");
assert.match(interpretation, /new URLSearchParams\(search\)\.get\("compare"\)/, "Interpretation must consume the explicit Evaluation comparison handoff.");
assert.match(interpretation, /exactComparisonRows\(/, "Interpretation must resolve comparison candidates again from exact backend candidate rows.");
assert.match(interpretation, /verifiedSelectionMetric\(row\)/, "Interpretation comparison cards must require verified non-holdout selection evidence.");
assert.match(interpretation, /data-testid="interpretation-candidate-comparison"/, "Interpretation must visibly preserve the Evaluation comparison context.");
assert.match(interpretation, /Challenger cards cannot open the final holdout, replace the locked candidate, drive Interpretation analyses, or be promoted/, "Interpretation comparison context must remain selection evidence only.");
assert.match(interpretation, /aria-label="Decision boundary X feature"/, "Interpretation must expose a stable accessible X-feature boundary control.");
assert.match(interpretation, /aria-label="Decision boundary Y feature"/, "Interpretation must expose a stable accessible Y-feature boundary control.");
assert.match(interpretation, /updateBoundaryFeature\("x", e\.target\.value\)/, "Selecting a real X feature must atomically leave the PCA-only projection pair.");
assert.match(interpretation, /updateBoundaryFeature\("y", e\.target\.value\)/, "Selecting a real Y feature must atomically leave the PCA-only projection pair.");
assert.match(interpretation, /fallback_used === true/, "Interpretation must reject any decision fallback.");
assert.match(interpretation, /const boundarySequence = useRef\(0\)/, "Decision-boundary requests must have a latest-request sequence guard.");
assert.match(interpretation, /boundarySequence\.current !== sequence/, "A stale boundary response must never replace the newest selected feature pair.");
assert.doesNotMatch(
  interpretation,
  /if \(finalPromotion\?\.modelVersionId\) params\.set\("model_version_id"/,
  "Promoting a model must not change the base Interpretation query and transiently clear its completed Evaluation package.",
);
assert.match(
  interpretation,
  /params\.set\("model_version_id", modelVersionId\);/,
  "Registered-model diagnostics must still bind explicitly to the durable promoted model version.",
);
assert.match(
  scoring,
  /const trainingContext = new URLSearchParams\(\{[\s\S]*?project_id: projectId,[\s\S]*?dataset_id: expectedIdentity\.dataset_id,[\s\S]*?dataset_version_id: expectedIdentity\.dataset_version_id,[\s\S]*?target: expectedTarget,[\s\S]*?problem_type: expectedProblemType/,
  "Scoring must request the last training run with the exact canonical dataset identity.",
);
assert.doesNotMatch(
  scoring,
  /const trainingContext = new URLSearchParams\(\{[\s\S]*?dataset_version: expectedIdentity\.dataset_version_id/,
  "Scoring must not use the legacy dataset-version alias while omitting dataset_id.",
);

assert.match(candidates, /canonicalDatasetStorageKey\("atlas-interpretation-candidates"/, "Candidate state must be scoped by the canonical project, dataset, and version.");
assert.match(journal, /evaluation_candidate_selected/, "Candidate selections must be audit events.");
assert.match(journal, /evaluation_candidate_removed/, "Candidate removals must be audit events.");

console.log("Predictive gold-standard workflow selection contract checks passed.");
