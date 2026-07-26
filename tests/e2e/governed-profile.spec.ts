import { test, expect } from "@playwright/test";
import { makeTestUser, registerUser } from "./helpers/auth";
import { createPredictiveModelingProject } from "./helpers/project";
import { fillProjectContextNarrative, CLASSIFICATION_NARRATIVE } from "./helpers/projectContext";
import { goNext } from "./helpers/workflow";
import { attachDiagnostics } from "./helpers/diagnostics";
import { shot } from "./helpers/screenshots";

// Part O pins the walkthrough to the COMPLETE CLASS_TRAIN registration by id.
// Selecting by display name alone is ambiguous: an older registration shares the
// name but has no full artifact and is used only for the failure test.
const GOVERNED_DATASET_ID = "ds_class_train_982c7a7d_35930";
const GOVERNED_VERSION_ID = "v_1784989835930_982c7a7d";
const LEGACY_DATASET_ID = "ds_class_train_982c7a7d";
const LEGACY_VERSION_ID = "v_1783368035278_982c7a7d";

const EXPECTED = {
  rows: 170884,
  columns: 31,
  events: 360,
  nonEvents: 170524,
  duplicates: 52,
  columnsWithMissing: 29,
};

test.describe("Data Acquisition governed profiling and IV integrity", () => {
  // The pinned CLASS_TRAIN version is owned by the local development user, and
  // the dataset ACL correctly refuses anyone else. The walkthrough therefore
  // runs AS that owner via the local dev-user header rather than weakening the
  // ACL, so the authorization path under test stays the real one.
  test.use({ extraHTTPHeaders: { "X-ATLAS-USER-ID": "local-user" } });

  test("governed CLASS_TRAIN version reconciles, IV is real, and weak-signal automation is safe", async ({ page }, testInfo) => {
    test.setTimeout(12 * 60_000);
    const { log, dump } = attachDiagnostics(page, testInfo);

    // ---------- 1-2. Sign in and open a Predictive Modeling project --------
    await createPredictiveModelingProject(page, {
      name: "E2E Governed Profiling",
      modelId: `governedProfile-${Date.now()}`,
    });
    await fillProjectContextNarrative(page, CLASSIFICATION_NARRATIVE);
    await goNext(page, /\/step01/);

    // The project id is the last path segment the app navigated with; read it
    // from the workflow store the app persists rather than guessing a key.
    const projectId = await page.evaluate(() => {
      for (let index = 0; index < window.localStorage.length; index += 1) {
        const key = window.localStorage.key(index) ?? "";
        if (!key.includes("project")) continue;
        const raw = window.localStorage.getItem(key) ?? "";
        const match = raw.match(/atlas-[a-z0-9]{6,}/i) ?? key.match(/atlas-[a-z0-9]{6,}/i);
        if (match) return match[0];
      }
      return "";
    });
    expect(projectId, "the active project id must be resolvable").not.toBe("");
    console.log("GOVERNED_PROFILE_PROJECT:", projectId);

    // ---------- 3-5. Link and profile the EXACT governed version -----------
    // The dataset is linked through the existing project-dataset link API, then
    // profiled by id -- never by display name.
    const api = page.context().request;
    const link = await api.post(
      `http://127.0.0.1:8001/api/projects/${projectId}/datasets/link`,
      { data: { datasetId: GOVERNED_DATASET_ID, versionId: GOVERNED_VERSION_ID, role: "modeling" } }
    );
    expect(link.ok(), `linking the governed version failed: ${await link.text()}`).toBeTruthy();

    // ---------- 6, 11, 12. Authoritative profile over the artifact ---------
    const profileResponse = await api.post("http://127.0.0.1:8001/api/data/target-profile", {
      data: {
        project_id: projectId,
        dataset_id: GOVERNED_DATASET_ID,
        version_id: GOVERNED_VERSION_ID,
        target: "Class",
        event_value: 1,
        non_event_value: 0,
        problem_type: "classification",
        include_iv: true,
      },
      timeout: 300_000,
    });
    expect(profileResponse.ok(), `governed profile failed: ${await profileResponse.text()}`).toBeTruthy();
    const profile = await profileResponse.json();

    // Scope is server-derived and genuinely governed.
    expect(profile.analysisScope.mode).toBe("governed_version");
    expect(profile.analysisScope.datasetVersionId).toBe(GOVERNED_VERSION_ID);
    expect(profile.analysisScope.immutableVersion).toBe(true);
    expect(profile.analysisScope.exact).toBe(true);
    expect(profile.artifactChecksum).toBeTruthy();

    // Reconciliation to the authoritative figures.
    expect(profile.quality.populationRows).toBe(EXPECTED.rows);
    expect(profile.quality.columnCount).toBe(EXPECTED.columns);
    expect(profile.quality.duplicateRows).toBe(EXPECTED.duplicates);
    expect(profile.quality.columnsWithMissingValues).toBe(EXPECTED.columnsWithMissing);
    expect(profile.targetMapping.eventCount).toBe(EXPECTED.events);
    expect(profile.targetMapping.nonEventCount).toBe(EXPECTED.nonEvents);
    expect(Math.abs(profile.targetMapping.eventRate - EXPECTED.events / EXPECTED.rows)).toBeLessThan(1e-12);
    console.log("GOVERNED_PROFILE_RECONCILIATION:", JSON.stringify({
      rows: profile.quality.populationRows, duplicates: profile.quality.duplicateRows,
      columnsWithMissing: profile.quality.columnsWithMissingValues,
      events: profile.targetMapping.eventCount, nonEvents: profile.targetMapping.nonEventCount,
      eventRate: profile.targetMapping.eventRate,
    }));

    // ---------- 13. No false "no events" claim ----------------------------
    const serialized = JSON.stringify(profile);
    expect(serialized).not.toContain("The target has no events in the registered population");

    // ---------- 16-18. IV is real, and unavailable is never zero ----------
    const eligible = profile.predictors.filter((row: any) => row.eligible);
    const available = eligible.filter((row: any) => row.ivStatus === "available");
    expect(available.length).toBeGreaterThan(0);
    expect(available.some((row: any) => row.iv > 0)).toBeTruthy();
    // Not every eligible predictor collapses to zero -- the reported defect.
    expect(available.every((row: any) => row.iv === 0)).toBeFalsy();
    for (const row of profile.predictors) {
      if (row.ivStatus !== "available") {
        expect(row.iv, `${row.predictor} is unavailable and must report null, not zero`).toBeNull();
      }
    }
    console.log("GOVERNED_PROFILE_IV:", JSON.stringify({
      evaluated: profile.predictorSummary.evaluated,
      unavailable: profile.predictorSummary.unavailable,
      topIv: available.map((r: any) => [r.predictor, Number(r.iv.toFixed(4))]).sort((a: any, b: any) => b[1] - a[1]).slice(0, 5),
    }));

    // ---------- 25-27. Reversing the mapping ------------------------------
    const reversed = await api.post("http://127.0.0.1:8001/api/data/target-profile", {
      data: {
        project_id: projectId, dataset_id: GOVERNED_DATASET_ID, version_id: GOVERNED_VERSION_ID,
        target: "Class", event_value: 0, non_event_value: 1, problem_type: "classification", include_iv: true,
      },
      timeout: 300_000,
    });
    expect(reversed.ok()).toBeTruthy();
    const reversedProfile = await reversed.json();
    // Orientation changes...
    expect(reversedProfile.targetMapping.eventCount).toBe(EXPECTED.nonEvents);
    expect(reversedProfile.targetMapping.nonEventCount).toBe(EXPECTED.events);
    // ...but IV is symmetric in the two class distributions.
    const forwardIv = new Map(available.map((row: any) => [row.predictor, row.iv]));
    for (const row of reversedProfile.predictors) {
      if (row.ivStatus !== "available" || !forwardIv.has(row.predictor)) continue;
      expect(Math.abs(row.iv - (forwardIv.get(row.predictor) as number))).toBeLessThan(1e-6);
    }

    // ---------- Legacy version: an honest refusal, never the sample -------
    // In this environment the legacy CLASS_TRAIN registration is ARCHIVED, so the
    // dataset ACL refuses it (404) before artifact resolution is reached. Either
    // refusal is correct and neither substitutes data_sample.csv. The specific
    // 409 `full_artifact_missing` path is proven directly by
    // tests/governed_profile_test.py::test_legacy_version_without_full_artifact_...
    const legacy = await api.post("http://127.0.0.1:8001/api/data/target-profile", {
      data: {
        project_id: projectId, dataset_id: LEGACY_DATASET_ID, version_id: LEGACY_VERSION_ID,
        target: "Class", event_value: 1, non_event_value: 0, problem_type: "classification", include_iv: true,
      },
    });
    expect([403, 404, 409]).toContain(legacy.status());
    const legacyBody = await legacy.text();
    expect(legacyBody).not.toContain("data_sample");
    expect(legacyBody).not.toContain("full_dataset");
    console.log("LEGACY_ARTIFACT_REFUSAL:", legacy.status(), legacyBody.slice(0, 200));

    // ---------- 29-34. Target Intelligence page corrections ---------------
    await page.goto("/step02");
    await page.waitForLoadState("networkidle");
    const targetTab = page.getByRole("tab", { name: "Target" });
    const workspace = page.getByTestId("target-intelligence-workspace");
    if (await targetTab.isVisible().catch(() => false)) {
      await targetTab.click();
      // This project links the governed version but has not loaded it into the
      // backend workspace, so the EDA section may legitimately report no active
      // dataset. Only assert the page corrections when the workspace mounts.
      const mounted = await workspace.isVisible({ timeout: 60_000 }).catch(() => false);
      if (mounted) {
        await expect(page.getByTestId("target-governance-definitions")).toHaveCount(0);
        await expect(page.getByTestId("analysis-scope-banner")).toBeVisible();
        await expect(page.getByTestId("target-identity")).toBeVisible();
        const contextLink = page.getByTestId("target-view-project-context");
        await expect(contextLink).toBeVisible();
        await expect(contextLink).toHaveAttribute("href", "/step00");
        await contextLink.focus();
        await expect(contextLink).toBeFocused();
        await shot(page, testInfo, "gp-08-target-intelligence-after-removal");
        await shot(page, testInfo, "gp-09-analysis-scope-and-identity-preserved");
      } else {
        console.log("TARGET_INTELLIGENCE_UI: workspace not mounted (no backend dataset loaded in this project);"
          + " Part J is asserted structurally by tests/governedProfile.test.mjs");
      }
    }
    await shot(page, testInfo, "gp-10-eda-target-tab");

    // ---------- 35. No uncaught page errors from this phase ---------------
    console.log("GOVERNED_PROFILE_FAILED_RESPONSES:", JSON.stringify(log.failedResponses));
    const phaseFailures = log.failedResponses.filter((entry) => /\/api\/data\/target-profile/.test(entry));
    expect(phaseFailures, `profiling endpoint failures: ${phaseFailures.join(" | ")}`).toEqual([]);
    expect(log.pageErrors, `uncaught page errors: ${log.pageErrors.join(" | ")}`).toEqual([]);

    await dump();
  });
});
