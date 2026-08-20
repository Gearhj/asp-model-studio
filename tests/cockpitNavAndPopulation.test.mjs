// Phase 6E.1 — cockpit Previous/Next navigation + two-layer population clarity (static source checks).
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const ROOT = new URL("..", import.meta.url);
const read = (p) => readFile(new URL(p, ROOT), "utf8");
const [shell, steps1] = await Promise.all([
  read("src/sports/cockpit/PaModelingCockpit.tsx"),
  read("src/sports/cockpit/cockpitSteps1.tsx"),
]);

// Parse the STEPS array (id, n, label) in source order.
const STEPS = [...shell.matchAll(/\{\s*id:\s*"([^"]+)",\s*n:\s*"(\d\d)",\s*label:\s*"([^"]+)"/g)]
  .map((m) => ({ id: m[1], n: m[2], label: m[3] }));

// ---------------------------------------------------------------- navigation
test("all 15 cockpit steps are present in canonical order", () => {
  assert.equal(STEPS.length, 15);
  assert.deepEqual(STEPS.map((s) => s.id), [
    "objective", "population", "profile", "outliers", "missing", "features", "segmentation",
    "split", "modellab", "tuning", "evaluation", "calibration", "simulation", "champion", "registry",
  ]);
  assert.deepEqual(STEPS.map((s) => s.n), Array.from({ length: 15 }, (_, i) => String(i + 1).padStart(2, "0")));
});

test("adjacent Previous/Next destinations are correct (index ± 1)", () => {
  const idx = (id) => STEPS.findIndex((s) => s.id === id);
  const nextOf = (id) => (idx(id) < STEPS.length - 1 ? STEPS[idx(id) + 1] : null);
  const prevOf = (id) => (idx(id) > 0 ? STEPS[idx(id) - 1] : null);
  assert.equal(nextOf("objective").id, "population");   // 01 → 02
  assert.equal(nextOf("population").id, "profile");      // 02 → 03
  assert.equal(nextOf("profile").id, "outliers");       // 03 → 04
  assert.equal(nextOf("outliers").id, "missing");       // 04 Outliers → 05 Missing Values
  assert.equal(STEPS[idx("outliers")].label, "Outliers");
  assert.equal(STEPS[idx("missing")].label, "Missing Values");
  assert.equal(nextOf("champion").id, "registry");      // 14 → 15
  assert.equal(prevOf("registry").id, "champion");      // 15 ← 14
});

test("Step 1 has no Previous; Step 15 has no Next", () => {
  assert.equal(STEPS[0].id, "objective");
  assert.equal(STEPS[STEPS.length - 1].id, "registry");
  // footer computes prev/next with end guards
  assert.ok(shell.includes("idx > 0 ? STEPS[idx - 1] : null"));
  assert.ok(shell.includes("idx < STEPS.length - 1 ? STEPS[idx + 1] : null"));
});

test("a Previous/Next footer renders on every step, after the step content", () => {
  assert.ok(shell.includes("function StepFooter"));
  // rendered immediately after the active step body
  assert.ok(/\{step\.render\(\{ projectId, go \}\)\}\s*<StepFooter active=\{active\} go=\{go\} \/>/.test(shell));
  // shows position "Step X of 15"
  assert.ok(shell.includes("Step {idx + 1} of {STEPS.length}"));
});

test("navigation preserves state — internal step swap, no app reload / external route", () => {
  // go() only swaps local step state (zustand store is untouched) and scrolls to the content top.
  assert.ok(shell.includes("const go = (id: string) =>") && shell.includes("setActive(id)"));
  assert.ok(shell.includes("scrollIntoView"));
  assert.ok(!/go = \(id[^}]*window\.location/.test(shell));
  assert.ok(!shell.includes("window.location.reload"));
  // the left navigator remains for direct expert navigation
  assert.ok(shell.includes("onClick={() => setActive(s.id)}"));
});

// ---------------------------------------------------------------- population clarity
test("Data & Population shows the two-layer summary (registered evidence vs modeling matrix)", () => {
  assert.ok(steps1.includes("Registered source evidence"));
  assert.ok(steps1.includes("Gen-2 modeling / evaluation matrix"));
  assert.ok(steps1.includes("registeredTotalRows") && steps1.includes("modelingTotalRows"));
  assert.ok(steps1.includes("2021–2025") && steps1.includes("2023–2025"));
});

test("all five seasons render from source-evidence with a prior-history distinction", () => {
  // seasons list is driven by sourceEvidence.perSeason (five rows), not the 3-row modeling perSeason
  assert.ok(steps1.includes("src?.perSeason"));
  assert.ok(steps1.includes("PRIOR_HISTORY") || /roleTone/.test(steps1));
  // prior-history rows get the neutral slate tone (not alarming, not a dev/val/frozen color)
  assert.ok(steps1.includes("roleTone"));
  assert.ok(steps1.includes('/DEVELOP/i.test(role) ? "emerald" : "slate"'));
});

test("a plain-language explanation of the two-layer population is present", () => {
  assert.ok(steps1.includes("Why aren't 2021–2022 in training?"));
  assert.ok(steps1.includes("prior construction") && steps1.includes("not discarded"));
});

test("the modeling matrix preview is labelled and noted as target-only", () => {
  assert.ok(steps1.includes('title="Gen-2 modeling matrix preview"'));
  assert.ok(steps1.includes("do not appear as target rows in this preview"));
});
