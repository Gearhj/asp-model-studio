import assert from "node:assert/strict";
import { createServer } from "node:http";
import { readFile, stat } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import path from "node:path";
import test from "node:test";

import { chromium } from "@playwright/test";

const ROOT = fileURLToPath(new URL("../", import.meta.url));
const BUILD_DIRECTORY = path.resolve(
  process.argv[2] ?? path.join(ROOT, ".tmp", "bureau-review-automatic-detection-build"),
);
const projectId = "isolated-heloc-automatic-special-values";
const datasetId = "isolated-heloc-dataset";
const datasetVersionId = "isolated-heloc-version";
const currentActivationRevision = 2;
const predictorAuthorizationId = "predictor-auth-isolated-heloc-v2";
const targetContractId = "target-contract-isolated-heloc-bad-flag-v2";

function specialValueReview({ activationRevision = currentActivationRevision } = {}) {
  return {
    special_value_review_id: `special-review-isolated-heloc-r${activationRevision}`,
    project_id: projectId,
    dataset_id: datasetId,
    dataset_version_id: datasetVersionId,
    activation_revision: activationRevision,
    predictor_authorization_id: predictorAuthorizationId,
    target_contract_id: targetContractId,
    analysis_partition_id: null,
    analysis_partition_revision: null,
    development_partition_id: null,
    analysis_partition_assignment_hash: null,
    analysis_partition_artifact_hash: null,
    development_target_checksum: null,
    source_checksum: "source-checksum-isolated-heloc",
    structural_scope: "full_governed_population_predictors_only",
    target_analysis_scope: "not_available",
    target_evidence_available: false,
    target_evidence_status: "unavailable",
    target_evidence_unavailable_reason: "Analysis Partition is not sealed.",
    full_governed_population_rows: 6,
    development_rows: 0,
    detection_fingerprint: `detection-fingerprint-r${activationRevision}`,
    status: "not_started",
    detected_count: 2,
    reviewed_count: 0,
    open_count: 2,
    open_items: ["NetFractionInstallBurden", "PercentTradesNeverDelq"],
    blocks_confirmation: true,
    blocks_continuation: true,
    confirmation_allowed: false,
    revision: 1,
    variable_decisions: [],
    reviewer_rationale: "",
    confirmed_at: null,
    updated_at: "2026-08-06T12:00:00Z",
    authority: "backend_durable_exact_version",
    browser_cache_authority: false,
  };
}

function specialProfile(value, count) {
  return {
    value,
    definition:
      "Observed bounded negative code; provider meaning has not been assigned.",
    count,
    frequency: count / 6,
    event_count: null,
    event_rate: null,
    regular_event_rate: null,
    event_rate_delta: null,
    recommended_handling: "Leave value unchanged as a governed special code",
  };
}

function automaticDetectionResponse() {
  const review = specialValueReview();
  return {
    ok: true,
    scope: "full_dataset",
    analysis_scope: "mixed_governed_scopes",
    structural_scope: "full_governed_population_predictors_only",
    row_count: 6,
    full_governed_population_rows: 6,
    target: "bad_flag",
    event_value: 1,
    detected: true,
    confidence: 0.98,
    manual_declaration: "auto",
    reasons: ["Recurring bounded negative sentinel candidates were observed."],
    likely_variable_count: 2,
    variables_with_special_values: 2,
    rows_with_special_values: 3,
    variables: [
      {
        variable: "NetFractionInstallBurden",
        confidence: 0.98,
        reasons: ["Recurring bounded negative codes were observed."],
        datatype: "int64",
        special_value_count: 2,
        special_value_frequency: 2 / 6,
        ordinary_value_count: 4,
        null_count: 0,
        parse_failure_count: 0,
        likely_bureau: true,
        special_values: [specialProfile(-8, 1), specialProfile(-9, 1)],
      },
      {
        variable: "PercentTradesNeverDelq",
        confidence: 0.96,
        reasons: ["Recurring bounded negative code was observed."],
        datatype: "int64",
        special_value_count: 1,
        special_value_frequency: 1 / 6,
        ordinary_value_count: 5,
        null_count: 0,
        parse_failure_count: 0,
        likely_bureau: true,
        special_values: [specialProfile(-9, 1)],
      },
    ],
    metadata_source: "dataset_observed",
    reviewed_at: "2026-08-06T12:00:00Z",
    project_id: projectId,
    dataset_id: datasetId,
    dataset_version_id: datasetVersionId,
    activation_revision: currentActivationRevision,
    predictor_authorization_id: predictorAuthorizationId,
    target_contract_id: targetContractId,
    correlation_id: "bureau-isolated-auto-detection",
    target_analysis_scope: "not_available",
    analysis_partition_id: null,
    analysis_partition_revision: null,
    development_partition_id: null,
    analysis_partition_assignment_hash: null,
    analysis_partition_artifact_hash: null,
    development_target_checksum: null,
    scope_contract: {
      structural_evidence: "full_governed_population_predictors_only",
      target_evidence: "not_available",
      single_scope_inference_allowed: false,
    },
    structural_evidence: {
      scope: "full_governed_population_predictors_only",
      population_count: 6,
      target_accessed: false,
      measures: ["special_value_count", "special_value_frequency"],
    },
    target_evidence: {
      available: false,
      status: "unavailable",
      scope: "not_available",
      population_id: null,
      population_count: 0,
      analysis_partition_id: null,
      analysis_partition_revision: null,
      assignment_hash: null,
      artifact_hash: null,
      source_checksum: null,
      development_target_checksum: null,
      holdout_excluded: true,
      final_holdout_accessed: false,
      measures: [],
    },
    final_holdout_accessed: false,
    special_value_review: review,
  };
}

function jsonResponse(route, status, payload) {
  return route.fulfill({
    status,
    contentType: "application/json",
    body: JSON.stringify(payload),
  });
}

const contentTypes = {
  ".css": "text/css; charset=utf-8",
  ".html": "text/html; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  ".svg": "image/svg+xml",
};

async function startStaticServer() {
  const root = await stat(BUILD_DIRECTORY).then((value) => {
    assert.ok(value.isDirectory(), `isolated build directory is missing: ${BUILD_DIRECTORY}`);
    return BUILD_DIRECTORY;
  });
  const server = createServer(async (request, response) => {
    try {
      const pathname = decodeURIComponent(new URL(request.url ?? "/", "http://isolated.test").pathname);
      const relative = pathname === "/"
        ? "tests/bureauReviewAutomaticDetection.isolated.entry.html"
        : pathname.replace(/^\/+/, "");
      const requested = path.resolve(root, relative);
      if (requested !== root && !requested.startsWith(`${root}${path.sep}`)) {
        response.writeHead(403).end("Forbidden");
        return;
      }
      const body = await readFile(requested);
      response.writeHead(200, {
        "Content-Type": contentTypes[path.extname(requested)] ?? "application/octet-stream",
        "Cache-Control": "no-store",
      });
      response.end(body);
    } catch {
      response.writeHead(404, { "Content-Type": "text/plain; charset=utf-8" });
      response.end("Not found");
    }
  });
  await new Promise((resolve, reject) => {
    server.once("error", reject);
    server.listen(0, "127.0.0.1", resolve);
  });
  const address = server.address();
  assert.ok(address && typeof address === "object", "isolated static listener was unavailable");
  return { server, origin: `http://127.0.0.1:${address.port}` };
}

test("BureauReviewPanel automatically detects HELOC negative codes and hands them to predictor review", async (t) => {
  const { server, origin } = await startStaticServer();
  let browser;
  t.after(async () => {
    await browser?.close();
    server.closeAllConnections?.();
    await new Promise((resolve) => server.close(resolve));
  });

  browser = await chromium.launch({ headless: true });
  const page = await browser.newPage();
  page.setDefaultTimeout(15_000);
  const browserErrors = [];
  page.on("pageerror", (error) => browserErrors.push(error.message));
  page.on("console", (message) => {
    if (message.type() === "error") browserErrors.push(message.text());
  });
  const detectionRequests = [];
  const bureauApiRequestOrder = [];
  const unexpectedApiRequests = [];
  let detectionPosted = false;

  await page.route("**/api/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    if (url.pathname === "/api/data/bureau-detection" && request.method() === "POST") {
      bureauApiRequestOrder.push("POST /api/data/bureau-detection");
      detectionPosted = true;
      detectionRequests.push(request.postDataJSON());
      await jsonResponse(route, 200, automaticDetectionResponse());
      return;
    }
    if (url.pathname === "/api/data/special-value-review" && request.method() === "GET") {
      bureauApiRequestOrder.push("GET /api/data/special-value-review");
      await jsonResponse(route, 200, {
        ok: true,
        special_value_review: detectionPosted
          ? specialValueReview()
          : specialValueReview({ activationRevision: 1 }),
      });
      return;
    }
    if (url.pathname.endsWith("/bureau-metadata/annotations")) {
      await jsonResponse(route, 404, { detail: "No exact catalog binding." });
      return;
    }
    unexpectedApiRequests.push(`${request.method()} ${url.pathname}`);
    await jsonResponse(route, 500, { detail: "Unexpected isolated API request." });
  });

  await page.goto(
    `${origin}/tests/bureauReviewAutomaticDetection.isolated.entry.html`,
    { waitUntil: "domcontentloaded", timeout: 15_000 },
  );
  await page.waitForFunction(
    () => {
      const callback = document.querySelector(
        '[data-testid="automatic-special-value-callback"]',
      );
      return (
        callback?.getAttribute("data-ready") === "true" ||
        document.body.textContent?.includes("Bureau review requires attention")
      );
    },
    undefined,
    { timeout: 15_000 },
  ).catch(async (error) => {
    throw new Error(
      `isolated component did not settle: ${error.message}; browser errors: ${browserErrors.join(" | ") || "none"}; body: ${(await page.locator("body").innerText().catch(() => "unavailable")).slice(0, 500)}`,
    );
  });

  assert.equal(
    detectionRequests.length,
    1,
    "a stale same-dataset review must not prevent automatic detection POST",
  );
  assert.equal(
    bureauApiRequestOrder[0],
    "POST /api/data/bureau-detection",
    "automatic detection must run before a stale prior durable review can block it",
  );
  assert.deepEqual(detectionRequests[0], {
    project_id: projectId,
    expected_dataset_id: datasetId,
    expected_dataset_version_id: datasetVersionId,
    target: "bad_flag",
    event_value: 1,
    manual_declaration: "auto",
    treatment_selections: [],
    reviewer_rationale: "",
  });
  assert.deepEqual(unexpectedApiRequests, []);

  const rows = page.locator('[data-testid="special-value-feature-row"]');
  await assert.doesNotReject(() => rows.first().waitFor({ state: "visible" }));
  assert.equal(await rows.count(), 2);
  const installBurden = rows.filter({
    has: page.getByText("NetFractionInstallBurden", { exact: true }),
  });
  const neverDelinquent = rows.filter({
    has: page.getByText("PercentTradesNeverDelq", { exact: true }),
  });
  await assert.doesNotReject(() => installBurden.waitFor({ state: "visible" }));
  await assert.doesNotReject(() => neverDelinquent.waitFor({ state: "visible" }));
  assert.match(await installBurden.innerText(), /-8/);
  assert.match(await installBurden.innerText(), /-9/);
  assert.match(await neverDelinquent.innerText(), /-9/);

  const callback = page.getByTestId("automatic-special-value-callback");
  assert.equal(await callback.getAttribute("data-ready"), "true");
  assert.deepEqual(JSON.parse(await callback.textContent()), [
    { variable: "NetFractionInstallBurden", values: [-8, -9], count: 2 },
    { variable: "PercentTradesNeverDelq", values: [-9], count: 1 },
  ]);
});
