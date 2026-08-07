import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const read = (path) => readFile(new URL(`../${path}`, import.meta.url), "utf8");

const [client, screen, app, acceptance] = await Promise.all([
  read("src/lib/bureauCatalogAdmin.ts"),
  read("src/steps/BureauCatalogAdmin.tsx"),
  read("src/apps/ModelingApp.tsx"),
  read("tests/bureauCatalogAdmin.productionAuth.acceptance.mjs"),
]);

const syntheticVersion = {
  catalog_version_id: "synthetic-version-002",
  catalog_id: "synthetic-catalog-a",
  provider_name: "Synthetic Bureau A",
  product_name: "Synthetic Attributes",
  edition: "LAB",
  source_release_version: "test-v2",
  normalized_catalog_checksum: "a".repeat(64),
  record_count: 3,
  special_value_definition_count: 2,
  integrity_status: "verified",
  installation_status: "installed",
  entitlement_status: "entitled",
};

const syntheticAttribute = {
  attribute_code: "SYN001",
  display_name: "Synthetic count",
  description: "Synthetic fixture text only.",
  ordinary_valid_min: "0",
  ordinary_valid_max: "9",
  special_value_count: 1,
};

test("the client exposes only the planned restricted administration routes", () => {
  for (const route of [
    'catalogFetch("/admin/bureau-catalogs")',
    "/admin/bureau-catalogs/${encodeURIComponent(versionId)}/validate",
    "/admin/bureau-catalogs/${encodeURIComponent(versionId)}/retire",
    "/admin/bureau-catalogs/${encodeURIComponent(input.versionId)}/attributes?",
    "/admin/bureau-catalogs/${encodeURIComponent(versionId)}/attributes/${encodeURIComponent(code)}",
  ]) {
    assert.ok(client.includes(route), `Missing restricted route: ${route}`);
  }
  assert.match(client, /credentials: "include"/);
  assert.doesNotMatch(client, /\/export|\/download|exportCatalog|downloadCatalog|createObjectURL|navigator\.clipboard/);
  assert.doesNotMatch(client, /latestCatalog|firstCatalog|catalogs\[0\].*lookup/);
});

test("search access is bounded and exact identifiers are URL encoded", () => {
  assert.match(client, /ATTRIBUTE_QUERY_LIMIT = 120/);
  assert.match(client, /BUREAU_CATALOG_PAGE_SIZE = 25/);
  assert.match(client, /BUREAU_CATALOG_MAX_PAGE_SIZE = 50/);
  assert.match(client, /Math\.max\(0, Math\.floor\(Number\(input\.offset\) \|\| 0\)\)/);
  assert.match(client, /Math\.min\(BUREAU_CATALOG_MAX_PAGE_SIZE/);
  assert.match(client, /new URLSearchParams\(\{ offset: String\(offset\), limit: String\(limit\) \}\)/);
  assert.match(client, /encodeURIComponent\(input\.versionId\)/);
  assert.match(client, /encodeURIComponent\(code\)/);
  assert.match(client, /has_more/);
  assert.match(client, /does not support an unfiltered full scan/);
});

test("synthetic structural contracts cover safe metadata and exact attribute records", () => {
  assert.equal(syntheticVersion.record_count, 3);
  assert.equal(syntheticVersion.normalized_catalog_checksum.length, 64);
  assert.equal(syntheticAttribute.attribute_code, "SYN001");
  for (const field of [
    "versionId",
    "catalogId",
    "provider",
    "product",
    "edition",
    "dictionaryVersion",
    "catalogChecksum",
    "attributeCount",
    "specialValueCount",
    "integrityStatus",
    "installStatus",
    "entitlementStatus",
  ]) {
    assert.ok(client.includes(field), `Missing safe version field: ${field}`);
  }
  for (const field of ["attributeCode", "ordinaryValidMin", "ordinaryValidMax", "specialValueCount", "sourcePage"]) {
    assert.ok(client.includes(field), `Missing bounded attribute field: ${field}`);
  }
});

test("the screen makes restriction, version identity, and lifecycle controls visible", () => {
  for (const label of [
    "Restricted platform administration",
    "Bureau Catalog Administration",
    "Exact installed version",
    "Checksum prefix",
    "Integrity",
    "Installation",
    "Entitlement",
    "Validate integrity",
    "Retire version",
    "Confirm catalog retirement",
    "Attribute search",
    "Exact attribute lookup",
  ]) {
    assert.ok(screen.includes(label), `Missing visible administration label: ${label}`);
  }
  assert.match(screen, /checksumPrefix\(catalog\.catalogChecksum\)/);
  assert.match(screen, /retireConfirmation/);
  assert.match(screen, /Confirm retirement/);
  assert.match(screen, /does not delete the catalog or rewrite existing governed lineage/);
});

test("the screen has keyboard, focus, responsive, loading, empty, and denial states", () => {
  assert.match(screen, /focus-visible:outline/);
  assert.match(screen, /type="search"/);
  assert.match(screen, /role="search"/);
  assert.match(screen, /role="alert"/);
  assert.match(screen, /aria-live="polite"/);
  assert.match(screen, /aria-busy=\{loading\}/);
  assert.match(screen, /confirmRetireRef\.current\?\.focus\(\)/);
  assert.match(screen, /sm:grid-cols/);
  assert.match(screen, /xl:grid-cols/);
  assert.match(screen, /overflow-x-auto/);
  assert.match(screen, /Loading entitled catalog versions/);
  assert.match(screen, /No entitled catalog versions/);
  assert.match(screen, /Retry authorization check/);
});

test("admin denial and entitlement filtering fail closed", () => {
  assert.match(client, /if \(status === 401\)/);
  assert.match(client, /if \(status === 403\)/);
  assert.match(client, /not authenticated for catalog administration/);
  assert.match(client, /restricted to entitled platform administrators/);
  assert.match(client, /listEntitledBureauCatalogVersions/);
  assert.match(screen, /listEntitledBureauCatalogVersions/);
  assert.match(screen, /Server-filtered entitled versions only/);
  assert.match(screen, /No entitled catalog versions/);
  assert.doesNotMatch(screen, /filter\([^\n]*entitlementStatus/);
  assert.match(app, /element=\{<CatalogAdministratorRoute user=\{authUser\} \/>\}/);
  assert.match(app, /String\(user\.role \|\| ""\)\.trim\(\)\.toLowerCase\(\) !== "admin"/);
  assert.match(app, /bureau-catalog-admin-route-denied/);
  assert.match(app, /No catalog request was made and no project or dataset state changed/);
});

test("inventory refresh preserves only an exact selection and never chooses a positional catalog", () => {
  assert.match(screen, /preferredVersionId[\s\S]*catalog\.versionId === preferredVersionId/);
  assert.match(screen, /current[\s\S]*catalog\.versionId === current/);
  assert.match(screen, /return "";/);
  assert.doesNotMatch(screen, /nextCatalogs\s*\[\s*0\s*\]/);
  assert.doesNotMatch(screen, /nextCatalogs\.(?:at|find)\s*\(\s*(?:0|\(.*?\)\s*=>\s*true)/);
});

test("the production-auth harness selects only the exact expected catalog before inspecting details", () => {
  const helperStart = acceptance.indexOf("async function selectExactExpectedCatalog");
  const helperEnd = acceptance.indexOf("\nasync function assertTwoEntitledProviders", helperStart);
  assert.ok(helperStart >= 0 && helperEnd > helperStart, "Exact catalog selection helper is missing.");
  const helper = acceptance.slice(helperStart, helperEnd);

  assert.match(helper, /admin\/bureau-catalogs\?offset=0&limit=50/);
  assert.match(helper, /catalog\?\.catalog_version_id === expectedId/);
  assert.match(helper, /listing\.matches\.length !== 1/);
  assert.match(helper, /catalog\.catalog_version_id === exactVersionId/);
  assert.match(helper, /getByRole\("button", \{ name: exactAccessibleName \}\)/);
  assert.match(helper, /getAttribute\("aria-pressed"\)/);
  assert.match(helper, /getByTestId\("bureau-catalog-selection-required"\)/);
  assert.doesNotMatch(helper, /catalogs\s*\[\s*0\s*\]|\.first\(\)|\.at\(\s*0\s*\)/);

  assert.match(
    acceptance,
    /await assertTwoEntitledProviders\(page\);\s*await selectExactExpectedCatalog\(page, expectedSecondaryVersionId\);\s*await selectExactExpectedCatalog\(page, expectedVersionId\);/,
  );
  assert.match(
    acceptance,
    /await page\.reload[\s\S]*?await assertTwoEntitledProviders\(page\);\s*await selectExactExpectedCatalog\(page, expectedVersionId\);/,
  );
  assert.doesNotMatch(
    acceptance,
    /getByText\(expectedVersionId, \{ exact: false \}\)\.waitFor\(\)/,
  );
});

test("an unresolved inventory requires explicit selection before restricted detail renders", () => {
  assert.match(screen, /data-testid="bureau-catalog-selection-required"/);
  assert.match(screen, /Select an exact catalog version/);
  assert.match(screen, /before ATLAS loads any restricted catalog details/);
  assert.match(screen, /No first or latest version is selected automatically/);
  assert.match(screen, /selectedCatalog \? \([\s\S]*<CatalogSelectionRequired \/>/);
});

test("authenticated user and active project context are preserved", () => {
  assert.match(client, /credentials: "include"/);
  assert.match(screen, /current authenticated administrator and tenant context/);
  assert.match(screen, /does not change the active modeling project or dataset identity/);
  assert.doesNotMatch(screen, /localStorage|sessionStorage|setActiveProject|setCurrentProject|useNavigate|window\.location/);
  assert.doesNotMatch(client, /localStorage|sessionStorage|projectId=/);
});

test("the UI offers bounded inspection without content exfiltration controls or physical paths", () => {
  assert.match(screen, /pages of \{BUREAU_CATALOG_PAGE_SIZE\}/);
  assert.match(screen, /Bulk export, download, and copy-all actions are not available/);
  assert.match(screen, /There is no bulk copy or export action/);
  assert.match(screen, /Inspect exact/);
  assert.match(screen, /Similar-code and latest-version fallback are prohibited/);
  assert.doesNotMatch(screen, /navigator\.clipboard|createObjectURL|download=|href=\{.*export/i);
  assert.doesNotMatch(screen, /artifactRoot|full_catalog_path|source_path|restricted_root|[A-Z]:\\\\/);
});

test("source fixtures contain no real vendor definitions", () => {
  assert.match(JSON.stringify(syntheticVersion), /Synthetic Bureau A/);
  assert.match(JSON.stringify(syntheticAttribute), /Synthetic fixture text only/);
  assert.doesNotMatch(client, /Experian_Premier_Credit_Bureau|credit_bureau_premier\.csv/);
  assert.doesNotMatch(screen, /Experian_Premier_Credit_Bureau|credit_bureau_premier\.csv/);
});
