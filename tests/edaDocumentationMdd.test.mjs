import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const client = readFileSync("src/lib/edaDocumentationApi.ts", "utf8");
const panel = readFileSync(
  "src/components/documentation/EdaDocumentationLiveLink.tsx",
  "utf8"
);
const studio = readFileSync("src/steps/ModelDocumentationStudio.tsx", "utf8");
const evidenceCenter = readFileSync("src/steps/EvidenceGraph.tsx", "utf8");

for (const section of [
  "overview",
  "target",
  "predictors",
  "relationships",
  "stability_and_segments",
  "findings",
]) {
  assert.match(
    client,
    new RegExp(`"${section}"`),
    `Canonical client contract is missing ${section}.`
  );
}

for (const field of [
  "project_id",
  "dataset_id",
  "dataset_version",
  "target",
  "predictor_manifest_id",
  "eda_analysis_version",
  "confirmed_at",
  "confirmed_by",
  "current_approved",
  "draft",
  "history",
  "source_lineage",
  "evidence_references",
  "stale_reason",
]) {
  assert.match(
    client,
    new RegExp(`\\b${field}\\b`),
    `Canonical client contract is missing ${field}.`
  );
}

for (const functionName of [
  "getEdaDocumentationState",
  "saveEdaDocumentationDraft",
  "invalidateEdaDocumentation",
  "publishEdaDocumentationUpdate",
  "subscribeEdaDocumentationUpdates",
]) {
  assert.match(
    client,
    new RegExp(`export (?:async )?function ${functionName}\\(`),
    `EDA documentation client must export ${functionName}.`
  );
}

assert.match(
  client,
  /export const confirmEdaDocumentation = completeEdaDocumentation;/,
  "The legacy confirmation export must remain a direct alias of the single governed completion path."
);

assert.match(
  client,
  /credentials: "include"/,
  "Every EDA documentation request must use the authenticated session."
);
assert.match(client, /\/eda\/documentation\/\$\{encodeURIComponent\(projectId\)\}/);
assert.match(client, /"\/eda\/documentation\/draft"/);
assert.match(client, /"\/eda\/confirmation"/);
assert.match(
  client,
  /\/eda\/documentation\/\$\{encodeURIComponent\(projectId\)\}\/invalidate/
);
assert.match(
  client,
  /atlas-eda-documentation-updated/,
  "Client must expose one immediate refresh event."
);
assert.match(
  client,
  /BroadcastChannel/,
  "EDA documentation updates must cross browser tabs without duplicating canonical content in browser storage."
);
assert.doesNotMatch(
  client,
  /localStorage|sessionStorage|indexedDB/,
  "The API client must not duplicate canonical EDA documentation in browser storage."
);

for (const label of [
  "EDA documentation live link",
  "Current approved EDA documentation",
  "Draft changes",
  "Not approved",
  "Stale after upstream change",
  "Active source lineage",
  "Predictor manifest",
  "Approved evidence links",
  "EDA confirmation history",
  "Documentation impact",
  "Reconfirmation required",
  "Status unverified",
  "Last verified source lineage",
]) {
  assert.match(
    panel,
    new RegExp(label),
    `MDD live-link panel is missing ${label}.`
  );
}

assert.match(
  panel,
  /subscribeEdaDocumentationUpdates/,
  "MDD must refetch immediately after EDA confirmation or invalidation."
);
assert.match(
  panel,
  /atlas-dataset-updated/,
  "MDD must refetch after an upstream dataset event."
);
assert.match(
  panel,
  /visibilitychange/,
  "MDD polling must resume when the page becomes visible."
);
assert.match(
  panel,
  /document\.visibilityState === "visible"/,
  "Background polling must pause while the page is hidden."
);
assert.match(
  panel,
  /findChangedSections/,
  "Draft section differences must be derived without mutating approved content."
);
assert.match(
  panel,
  /safeEvidenceHref/,
  "Evidence links must pass through a protocol allowlist."
);
assert.match(
  panel,
  /href\.startsWith\("\/\/"\)/,
  "Evidence links must reject protocol-relative URLs."
);
assert.match(
  panel,
  /\/model-evidence-center\?evidenceId=/,
  "Evidence references must link to the supported Evidence Center route."
);
assert.match(
  evidenceCenter,
  /useSearchParams/,
  "Evidence Center must read deep-link selection from the route."
);
assert.match(
  evidenceCenter,
  /item\.evidenceId === requestedEvidenceId/,
  "Evidence Center must select the requested evidence record."
);
assert.doesNotMatch(
  panel,
  /JSON\.stringify\(record\.sections/,
  "Documentation content must be rendered as readable fields, not raw JSON."
);

assert.match(
  studio,
  /import EdaDocumentationLiveLink from "\.\.\/components\/documentation\/EdaDocumentationLiveLink"/
);
assert.match(
  studio,
  /<EdaDocumentationLiveLink projectId=\{projectId\} \/>/,
  "Model Documentation Studio must render the live governed EDA section."
);

console.log("EDA documentation MDD frontend integration checks passed.");
