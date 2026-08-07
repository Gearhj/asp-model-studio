import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const ROOT = new URL("../", import.meta.url);
const read = (file) => readFile(new URL(file, ROOT), "utf8");
const [entry, browser, runtime] = await Promise.all([
  read("tests/bureauMetadataIntegration.isolated.entry.tsx"),
  read("tests/bureauMetadataIntegration.production.acceptance.mjs"),
  read("tests/bureau_metadata_integration_runtime_app.py"),
]);

test("isolated acceptance mounts the real binding, crosswalk, and special-value production surfaces", () => {
  assert.match(entry, /import BureauMetadataBindingPanel from "\.\.\/src\/components\/BureauMetadataBindingPanel"/);
  assert.match(entry, /import BureauReviewPanel from "\.\.\/src\/components\/BureauReviewPanel"/);
  assert.match(entry, /<BureauMetadataBindingPanel[\s\S]*?<BureauReviewPanel/);
  assert.match(browser, /production_components_exercised:[\s\S]*"BureauMetadataBindingPanel"[\s\S]*"BureauMetadataCrosswalkWorkspace"[\s\S]*"BureauReviewPanel"/);
  assert.match(browser, /acceptance_surface: "isolated_synthetic_entry_mounting_production_components"/);
});

test("Project B visibly covers every required mapping state and a blocked contradiction", () => {
  for (const [field, state] of [
    ["SYN000", "exact_verified"],
    ["ALIAS_SCORE", "approved_alias"],
    ["SYN004", "probable_review_required"],
    ["AMBIGUOUS_FIELD", "ambiguous_review_required"],
    ["LOCAL_ONLY", "unresolved"],
    ["SYN005", "rejected"],
  ]) {
    assert.match(browser, new RegExp(`dataset_field: "${field}"[\\s\\S]{0,260}mapping_state: "${state}"`));
  }
  assert.match(runtime, /"ALIAS_SCORE"[\s\S]*?"approved_institutional_alias"[\s\S]*?"synthetic-alias-policy-beta-v1"/);
  assert.match(runtime, /"AMBIGUOUS_FIELD"[\s\S]*?"multiple_possible_matches"[\s\S]*?\["SYN002", "SYN003"\]/);
  assert.match(browser, /contradictoryChecks\.has\("datatype"\)/);
  assert.match(browser, /contradictoryChecks\.has\("ordinary_range"\)/);
  assert.match(browser, /contradictoryChecks\.has\("special_values"\)/);
  assert.match(browser, /getByTestId\("synthetic-contradiction-SYN000"\)/);
});

test("treatment review proves in-place interaction, stable guide context, scroll preservation, and row expansion", () => {
  assert.match(browser, /getByTestId\("special-value-feature-table"\)/);
  assert.match(browser, /getByTestId\("special-value-treatment-SYN000"\)/);
  assert.match(browser, /selectOption\("convert_to_category"\)/);
  assert.match(browser, /afterTreatment\.href !== beforeTreatment\.href/);
  assert.match(browser, /afterTreatment\.navigationEntries !== beforeTreatment\.navigationEntries/);
  assert.match(browser, /Math\.abs\(afterTreatment\.scrollY - beforeTreatment\.scrollY\) > 5/);
  assert.match(browser, /getByTestId\("synthetic-atlas-guide-stable"\)/);
  assert.match(browser, /getByTestId\("review-special-value-codes-SYN000"\)/);
  assert.match(browser, /getByTestId\("special-value-code-details-row"\)/);
  assert.match(browser, /getByTestId\("bureau-semantic-source-details"\)/);
  assert.match(browser, /Special-value code metadata did not collapse in place/);
});

test("Project A verifies exact binding and canonical annotation identity after existing state and reloads", () => {
  const bindingStart = browser.indexOf("function assertExactBindingIdentity");
  const annotationStart = browser.indexOf("function assertExactCanonicalAnnotationIdentity");
  const helperEnd = browser.indexOf("\nconst screenshots", annotationStart);
  assert.ok(bindingStart >= 0 && annotationStart > bindingStart && helperEnd > annotationStart);
  const bindingHelper = browser.slice(bindingStart, annotationStart);
  const annotationHelper = browser.slice(annotationStart, helperEnd);

  for (const field of [
    "project_id",
    "dataset_id",
    "dataset_version_id",
    "catalog_version_id",
    "catalog_checksum",
  ]) assert.ok(bindingHelper.includes(field), `binding helper omitted ${field}`);
  assert.match(bindingHelper, /binding\.stale_reason !== null/);
  assert.match(bindingHelper, /summary\.current !== true/);
  assert.match(bindingHelper, /bindingRevision: positiveRevision/);
  assert.match(bindingHelper, /crosswalkRevision: binding\.crosswalk_revision == null/);
  assert.match(bindingHelper, /snapshot\[field\] !== expected\[field\]/);

  for (const field of [
    "annotation_set_id",
    "annotation_set_checksum",
    "binding_revision_checksum",
    "crosswalk_revision_checksum",
    "annotation_id",
  ]) assert.ok(annotationHelper.includes(field), `annotation helper omitted ${field}`);
  assert.match(annotationHelper, /annotation\.binding_id !== binding\.bindingId/);
  assert.match(annotationHelper, /annotation\.catalog_version_id !== catalog\.id/);
  assert.match(annotationHelper, /annotation\.crosswalk_revision !== binding\.crosswalkRevision/);
  assert.match(annotationHelper, /annotationIds: JSON\.stringify\(annotationIds\)/);
  assert.match(annotationHelper, /snapshot\[field\] !== expected\[field\]/);

  assert.match(
    browser,
    /const retainedBinding = await api[\s\S]{0,320}assertExactBindingIdentity\(retainedBinding/,
  );
  assert.match(
    browser,
    /const firstReloadBinding = assertExactBindingIdentity[\s\S]{0,700}expected: canonicalAnnotations/,
  );
  assert.match(
    browser,
    /const reloadedBinding = assertExactBindingIdentity[\s\S]{0,700}expected: canonicalAnnotations/,
  );
  assert.doesNotMatch(browser, /if \(binding\.status !== 200\) throw new Error\("Project A binding did not persist\."\)/);
  assert.match(browser, /exact_binding_identity_verified_after_every_reload: true/);
  assert.match(browser, /exact_annotation_identity_verified_after_every_reload: true/);
});

test("evidence matrix names every required sanitized screenshot and exact canonical handoff", () => {
  for (const screenshot of [
    "bureau-metadata-compact-binding-summary.png",
    "bureau-metadata-entitled-catalog-selection.png",
    "bureau-metadata-crosswalk-table-all-states.png",
    "bureau-metadata-crosswalk-exact-state.png",
    "bureau-metadata-crosswalk-unresolved-state.png",
    "bureau-metadata-visible-contradiction.png",
    "bureau-metadata-table-first-special-review.png",
    "bureau-metadata-expanded-code-level-metadata.png",
    "bureau-metadata-project-c-no-entitlement.png",
    "bureau-metadata-canonical-eda-handoff.png",
    "bureau-metadata-api-only-multi-user-isolation.png",
  ]) assert.ok(browser.includes(screenshot), `missing screenshot contract: ${screenshot}`);
  assert.match(entry, /isolated\/canonical-eda-handoff/);
  assert.match(browser, /synthetic-canonical-eda-handoff/);
  assert.match(browser, /final_holdout_accessed !== false/);
  assert.match(browser, /training_started !== false/);
  assert.match(browser, /\["5174", "8001"\]\.includes\(url\.port\)/);
  assert.match(browser, /atlas_guide_limitation:/);
});
