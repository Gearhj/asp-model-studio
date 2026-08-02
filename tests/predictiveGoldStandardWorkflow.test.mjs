import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const read = (path) => readFileSync(new URL(`../${path}`, import.meta.url), "utf8");

const evaluation = read("src/steps/Step08_Evaluation.tsx");
const interpretation = read("src/steps/Step09_Interpretation.tsx");
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
assert.match(interpretation, /new URLSearchParams\(window\.location\.search\)\.get\("candidate_id"\)/, "Interpretation must honor exact candidate navigation from Evaluation.");
assert.match(interpretation, /new URLSearchParams\(window\.location\.search\)\.get\("evaluation_package_id"\)/, "Interpretation must require the explicit Evaluation package identity.");
assert.match(interpretation, /new URLSearchParams\(window\.location\.search\)\.get\("candidate_decision_id"\)/, "Interpretation must require the explicit locked decision identity.");
assert.match(interpretation, /fallback_used === true/, "Interpretation must reject any decision fallback.");

assert.match(candidates, /canonicalDatasetStorageKey\("atlas-interpretation-candidates"/, "Candidate state must be scoped by the canonical project, dataset, and version.");
assert.match(journal, /evaluation_candidate_selected/, "Candidate selections must be audit events.");
assert.match(journal, /evaluation_candidate_removed/, "Candidate removals must be audit events.");

console.log("Predictive gold-standard workflow selection contract checks passed.");
