import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const read = (path) => readFileSync(new URL(`../${path}`, import.meta.url), "utf8");

const evaluation = read("src/steps/Step08_Evaluation.tsx");
const interpretation = read("src/steps/Step09_Interpretation.tsx");
const candidates = read("src/lib/interpretationCandidates.ts");
const journal = read("src/lib/decisionJournal.ts");

assert.doesNotMatch(evaluation, /Select for Interpretation/, "Evaluation must not use the rejected checkbox-selection pattern.");
assert.doesNotMatch(evaluation, /type=["']checkbox["']/, "Evaluation must not expose model-selection checkboxes.");
assert.match(evaluation, /Review Model/, "Evaluation must expose an explicit model-review action.");
assert.match(evaluation, /Add to Comparison/, "Evaluation must expose a comparison-tray action.");
assert.match(evaluation, /Open Interpretation/, "Evaluation must expose direct Interpretation navigation.");
assert.match(evaluation, /saveInterpretationCandidates\(projectId, limited\)/, "Evaluation must persist the comparison tray by project.");
assert.match(evaluation, /comparison\.length >= 4/, "Evaluation must cap the persistent comparison tray at four candidates.");
assert.match(evaluation, /nextDisabled=\{!comparison\.length\}/, "Evaluation cannot continue without at least one Interpretation candidate.");
assert.doesNotMatch(evaluation, /current leaderboard champion/i, "Evaluation must not imply automatic Champion approval.");

assert.match(interpretation, /loadInterpretationCandidates\(projectId\)/, "Interpretation must load the explicit Evaluation candidate contract.");
assert.match(interpretation, /No models selected for Interpretation/, "Interpretation must provide a recovery state when no candidates were selected.");
assert.match(interpretation, /selectedCandidates = ranked\.filter/, "Interpretation must limit analysis to selected trained candidates.");
assert.match(interpretation, /new URLSearchParams\(window\.location\.search\)\.get\("model"\)/, "Interpretation must honor direct model-review navigation from Evaluation.");

assert.match(candidates, /atlas-interpretation-candidates:/, "Candidate state must be project scoped.");
assert.match(journal, /evaluation_candidate_selected/, "Candidate selections must be audit events.");
assert.match(journal, /evaluation_candidate_removed/, "Candidate removals must be audit events.");

console.log("Predictive gold-standard workflow selection contract checks passed.");
