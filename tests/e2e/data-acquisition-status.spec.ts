import { test, expect } from "@playwright/test";
import { createPredictiveModelingProject } from "./helpers/project";
import { fillProjectContextNarrative, CLASSIFICATION_NARRATIVE } from "./helpers/projectContext";
import { goNext } from "./helpers/workflow";
import { attachDiagnostics } from "./helpers/diagnostics";
import { shot } from "./helpers/screenshots";

// Pinned to the COMPLETE CLASS_TRAIN registration by id -- the older
// same-named registration has no full artifact.
const DATASET_ID = "ds_class_train_982c7a7d_35930";
const VERSION_ID = "v_1784989835930_982c7a7d";

const EXPECTED = { rows: 170884, columns: 31, events: 360, nonEvents: 170524, duplicates: 52, missingColumns: 29 };

test.describe("Data Acquisition status and predictor interpretation integrity", () => {
  // The pinned version is owned by the local development user and the dataset
  // ACL correctly refuses anyone else, so the walkthrough runs AS the owner
  // rather than weakening the ACL.
  test.use({ extraHTTPHeaders: { "X-ATLAS-USER-ID": "local-user" } });

  test("one consistent status model, truthful pre-load identity, conservative high-IV semantics", async ({ page }, testInfo) => {
    test.setTimeout(12 * 60_000);
    const { log, dump } = attachDiagnostics(page, testInfo);

    // ---------- 1-3. Open the project and reach Data Acquisition ----------
    await createPredictiveModelingProject(page, {
      name: "Credit Card Transaction Fraud Model - TEST",
      modelId: `00001-${Date.now()}`,
    });
    await fillProjectContextNarrative(page, CLASSIFICATION_NARRATIVE);
    await goNext(page, /\/step01/);

    // The breadcrumb must name THIS page (guards the completed Part A work).
    await expect(page.getByTestId("atlas-breadcrumb-current")).toHaveText("Data Acquisition");

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
    expect(projectId).not.toBe("");

    // ---------- 4. Link the exact governed Dataset Version ----------------
    const api = page.context().request;
    const link = await api.post(`http://127.0.0.1:8001/api/projects/${projectId}/datasets/link`, {
      data: { datasetId: DATASET_ID, versionId: VERSION_ID, role: "modeling" },
    });
    expect(link.ok(), `link failed: ${await link.text()}`).toBeTruthy();

    // ---------- 10, 14. The authoritative profile ------------------------
    const response = await api.post("http://127.0.0.1:8001/api/data/target-profile", {
      data: {
        project_id: projectId, dataset_id: DATASET_ID, version_id: VERSION_ID,
        target: "Class", event_value: 1, non_event_value: 0, problem_type: "classification", include_iv: true,
      },
      timeout: 300_000,
    });
    expect(response.ok(), `profile failed: ${await response.text()}`).toBeTruthy();
    const profile = await response.json();

    expect(profile.quality.populationRows).toBe(EXPECTED.rows);
    expect(profile.quality.columnCount).toBe(EXPECTED.columns);
    expect(profile.targetMapping.eventCount).toBe(EXPECTED.events);
    expect(profile.targetMapping.nonEventCount).toBe(EXPECTED.nonEvents);
    expect(profile.quality.duplicateRows).toBe(EXPECTED.duplicates);
    expect(profile.quality.columnsWithMissingValues).toBe(EXPECTED.missingColumns);
    expect(Math.abs(profile.targetMapping.eventRate - EXPECTED.events / EXPECTED.rows)).toBeLessThan(1e-12);

    // 14. The target is not a predictor near-zero-variance defect.
    expect(profile.quality.nearZeroVarianceColumns).not.toContain("Class");
    expect(profile.quality.constantColumns).not.toContain("Class");
    expect(profile.quality.targetExcludedFromPredictorFindings).toBe("Class");
    // ...but it remains in Target Health.
    expect(profile.quality.eventRate).toBeGreaterThan(0);

    // ---------- 15-16. High IV is review-worthy, never a leakage verdict --
    const eligible = profile.predictors.filter((row: any) => row.eligible);
    const available = eligible.filter((row: any) => row.ivStatus === "available");
    const unusuallyStrong = available.filter((row: any) => row.iv >= 0.5);
    expect(unusuallyStrong.length).toBeGreaterThan(0);
    for (const row of unusuallyStrong) {
      expect(row.ivStrength.key).toBe("unusually_strong");
      expect(row.ivStrength.label.toLowerCase()).toContain("review");
    }
    const serialized = JSON.stringify(profile);
    expect(serialized).not.toContain("confirmed_leakage");
    expect(serialized).not.toContain("likely_leakage");

    // ---------- 17-18. Counts exclude the target -------------------------
    const targetRow = profile.predictors.find((row: any) => row.predictor === "Class");
    expect(targetRow?.eligible, "the target must not be an eligible predictor").toBeFalsy();
    expect(available.length).toBe(30);
    const genuinelyUnavailable = eligible.filter((row: any) => row.ivStatus !== "available");
    expect(genuinelyUnavailable.length, "no real predictor should be unavailable here").toBe(0);

    console.log("DA_STATUS_RECONCILIATION:", JSON.stringify({
      rows: profile.quality.populationRows, duplicates: profile.quality.duplicateRows,
      missingColumns: profile.quality.columnsWithMissingValues,
      events: profile.targetMapping.eventCount, evaluated: available.length,
      unusuallyStrong: unusuallyStrong.length,
      nzvContainsClass: profile.quality.nearZeroVarianceColumns.includes("Class"),
    }));

    // ---------- 5, 11-13. Page-level status ------------------------------
    await page.reload();
    await page.waitForLoadState("networkidle");
    const body = page.locator("body");
    // 5/18. A registered, linked asset is never described as "Not registered".
    await expect(body).not.toContainText("Not registered");

    // 12. The page must not report Ready AND Blocked for one state.
    // Asserted on the status VALUE, not raw prose: the label "Modeling
    // Readiness" legitimately contains the substring "Ready".
    const text = await body.innerText();
    const readinessMatch = text.match(/Modeling Readiness\s*(Blocked|Ready with warnings|Ready|Not evaluated)/i);
    expect(readinessMatch, "Modeling Readiness must render a known shared-model state").not.toBeNull();
    const readinessValue = (readinessMatch?.[1] ?? "").toLowerCase();
    console.log("DA_STATUS_READINESS_LABEL:", readinessValue);
    // Exactly one value is reported, so Ready and Blocked cannot co-occur.
    expect(["blocked", "ready with warnings", "ready", "not evaluated"]).toContain(readinessValue);
    if (readinessValue.startsWith("ready")) {
      expect(text, "a ready page must not also declare itself blocked").not.toMatch(/Modeling Readiness\s*Blocked/i);
    }

    await shot(page, testInfo, "da-01-selected-not-loaded");
    await shot(page, testInfo, "da-03-unified-readiness-state");
    await shot(page, testInfo, "da-04-variable-summary-high-iv");
    await shot(page, testInfo, "da-05-predictor-evaluation-counts");

    // ---------- 19. No page errors from this phase -----------------------
    const phaseFailures = log.failedResponses.filter((entry) => /\/api\/data\/target-profile/.test(entry));
    console.log("DA_STATUS_FAILED_RESPONSES:", JSON.stringify(log.failedResponses));
    expect(phaseFailures, `profiling failures: ${phaseFailures.join(" | ")}`).toEqual([]);
    expect(log.pageErrors, `uncaught page errors: ${log.pageErrors.join(" | ")}`).toEqual([]);

    await dump();
  });
});
