import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const read = (path) => readFile(new URL(`../${path}`, import.meta.url), "utf8");
const [workflows, newProject, packageJsonText] = await Promise.all([
  read("src/config/workflows.ts"),
  read("src/steps/NewProject.tsx"),
  read("package.json"),
]);
const packageJson = JSON.parse(packageJsonText);

function projectOptionBlock(value) {
  const marker = `{ value: "${value}"`;
  const start = workflows.indexOf(marker);
  if (start === -1) return "";
  const end = workflows.indexOf(" },", start);
  return workflows.slice(start, end + 3);
}

test("workflow library exposes the revised governed project cards", () => {
  for (const value of [
    "predictive-modeling",
    "ab-testing",
    "optimization",
    "time_series_forecasting",
    "llm_generative_ai",
    "graph-analytics",
    "computer-vision",
    "reinforcement-learning",
    "custom-workflow",
  ]) {
    assert.ok(projectOptionBlock(value), `Missing project card ${value}`);
  }
  for (const removed of ["forecasting", "time-series", "nlp", "segmentation", "experimental-design"]) {
    assert.equal(projectOptionBlock(removed), "", `Removed top-level project card still exists: ${removed}`);
  }
});

test("segmentation is repositioned as an Analytics Workbench pattern", () => {
  assert.match(newProject, /Analysis Patterns Available Inside Analytics Workbench/);
  assert.match(newProject, /Population Segmentation/);
  assert.match(newProject, /Cluster, profile, compare, and label customer, account, merchant, or transaction populations/);
});

test("new workflow test commands are registered", () => {
  assert.equal(packageJson.scripts["test:workflow-library"], "node tests/workflowLibrary.test.mjs");
  assert.equal(packageJson.scripts["test:time-series-forecasting"], "node tests/timeSeriesForecasting.test.mjs");
  assert.equal(packageJson.scripts["test:llm-workflow"], "node tests/llmWorkflow.test.mjs");
});
