import assert from "node:assert/strict";
import { mkdir, readFile, rm, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import test from "node:test";
import ts from "typescript";

const ROOT = new URL("..", import.meta.url);
const TMP_DIR = fileURLToPath(new URL("../.tmp/visual-motion-foundation-tests", import.meta.url));

async function transpile(sourcePath, outputPath) {
  const source = await readFile(new URL(sourcePath, ROOT), "utf8");
  const output = ts.transpileModule(source, {
    compilerOptions: {
      module: ts.ModuleKind.ES2022,
      target: ts.ScriptTarget.ES2022,
    },
  }).outputText;
  await mkdir(path.dirname(outputPath), { recursive: true });
  await writeFile(outputPath, output, "utf8");
}

await rm(TMP_DIR, { recursive: true, force: true });
await transpile("src/visual-intelligence/motion.ts", path.join(TMP_DIR, "motion.js"));
await transpile("src/visual-intelligence/useReducedMotion.ts", path.join(TMP_DIR, "useReducedMotion.js"));

const motion = await import(pathToFileURL(path.join(TMP_DIR, "motion.js")).href);
const reducedMotion = await import(pathToFileURL(path.join(TMP_DIR, "useReducedMotion.js")).href);

test("motion tokens stay within the EDA brief's timing bands", () => {
  const durations = motion.ATLAS_MOTION_TOKENS.durationMs;
  assert.ok(durations.enter >= 400 && durations.enter <= 700);
  assert.ok(durations.update >= 250 && durations.update <= 400);
  assert.ok(durations.highlight >= 100 && durations.highlight <= 180);
});

test("stagger timing is deterministic and capped", () => {
  const first = Array.from({ length: 500 }, (_, index) =>
    motion.deterministicStaggerDelay(index, 500),
  );
  const second = Array.from({ length: 500 }, (_, index) =>
    motion.deterministicStaggerDelay(index, 500),
  );
  assert.deepEqual(first, second);
  assert.equal(first[0], 0);
  assert.equal(first.at(-1), motion.ATLAS_MOTION_TOKENS.stagger.maxTotalMs);
  assert.ok(first.every((delay, index) => index === 0 || delay >= first[index - 1]));
});

test("reduced motion and export mode render the final state immediately", () => {
  const reduced = motion.resolveAtlasMotion("enter", {
    reducedMotion: true,
    markCount: 30,
  });
  assert.equal(reduced.enabled, false);
  assert.equal(reduced.durationMs, 0);
  assert.equal(reduced.delayFor(29), 0);
  assert.equal(reduced.disabledReason, "reduced-motion");

  const exported = motion.atlasEChartsMotionOptions({ exportMode: true, markCount: 30 });
  assert.equal(exported.animation, false);
  assert.equal(exported.animationDuration, 0);
  assert.equal(exported.animationDurationUpdate, 0);
  assert.equal(exported.animationDelay, 0);
});

test("large-data motion preserves updates but suppresses per-mark stagger", () => {
  const resolved = motion.resolveAtlasMotion("enter", {
    largeData: true,
    markCount: 25_000,
  });
  assert.equal(resolved.enabled, true);
  assert.equal(resolved.staggered, false);
  assert.equal(resolved.delayFor(24_999), 0);
});

test("ECharts adapter is immutable and applies shared enter/update timing", () => {
  const source = { series: [{ type: "bar", data: [1, 2, 3] }] };
  const option = motion.withAtlasEChartsMotion(source, { markCount: 3 });
  assert.notEqual(option, source);
  assert.equal("animation" in source, false);
  assert.equal(option.animation, true);
  assert.equal(option.animationDuration, motion.ATLAS_MOTION_TOKENS.durationMs.enter);
  assert.equal(option.animationDurationUpdate, motion.ATLAS_MOTION_TOKENS.durationMs.update);
  assert.equal(typeof option.animationDelay, "function");
});

test("chart controller aborts only the previous revision and exposes settlement", async () => {
  const controller = motion.createChartMotionController();
  const first = controller.beginRevision();
  const second = controller.beginRevision();
  assert.equal(first.signal.aborted, true);
  assert.equal(second.signal.aborted, false);
  assert.equal(controller.isCurrent(first.revision), false);
  assert.equal(controller.isCurrent(second.revision), true);

  let release;
  const work = new Promise((resolve) => {
    release = resolve;
  });
  const tracked = controller.track(work);
  let settled = false;
  const waiting = controller.whenSettled().then(() => {
    settled = true;
  });
  await Promise.resolve();
  assert.equal(settled, false);
  release("done");
  assert.equal(await tracked, "done");
  await waiting;
  assert.equal(settled, true);
});

test("reduced-motion subscription supports modern media-query listeners", () => {
  let listener = null;
  let removed = false;
  const media = {
    matches: true,
    addEventListener: (_type, next) => {
      listener = next;
    },
    removeEventListener: (_type, next) => {
      removed = next === listener;
    },
  };
  const matchMedia = (query) => {
    assert.equal(query, reducedMotion.REDUCED_MOTION_MEDIA_QUERY);
    return media;
  };
  assert.equal(reducedMotion.readReducedMotionPreference(matchMedia), true);
  let notifications = 0;
  const unsubscribe = reducedMotion.subscribeReducedMotionPreference(
    () => {
      notifications += 1;
    },
    matchMedia,
  );
  listener();
  assert.equal(notifications, 1);
  unsubscribe();
  assert.equal(removed, true);
});

test("transition names are stable and safely scoped", () => {
  assert.equal(
    motion.atlasTransitionName("predictor distribution", "mean / median"),
    "atlas-predictor-distribution-mean-median",
  );
});

test.after(async () => {
  await rm(TMP_DIR, { recursive: true, force: true });
});
