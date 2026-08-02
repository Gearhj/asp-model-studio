import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import {
  resolveWorkflowActionBarBounds,
  workflowActionBarClearance,
} from "../src/lib/workflowActionBarLayout.ts";

const ROOT = new URL("../", import.meta.url);
const read = (path) => readFileSync(new URL(path, ROOT), "utf8").replace(/\r\n/g, "\n");

test("fixed workflow action bar follows the measured main column at desktop widths and zoom levels", () => {
  const layouts = [
    {
      label: "1920 CSS px at 100% zoom with full guide",
      viewportWidth: 1920,
      rect: { left: 284, right: 1568 },
      guideLeft: 1584,
    },
    {
      label: "1536 CSS px at 125% zoom with full guide",
      viewportWidth: 1536,
      rect: { left: 284, right: 1184 },
      guideLeft: 1200,
    },
    {
      label: "1280 CSS px at 150% zoom with full guide",
      viewportWidth: 1280,
      rect: { left: 268, right: 928 },
      guideLeft: 944,
    },
  ];

  for (const layout of layouts) {
    const bounds = resolveWorkflowActionBarBounds(layout.rect, layout.viewportWidth);
    assert.equal(bounds.left, layout.rect.left, layout.label);
    assert.equal(bounds.left + bounds.width, layout.rect.right, layout.label);
    assert.ok(bounds.left + bounds.width < layout.guideLeft, layout.label);
  }
});

test("workflow action bar expands with its content column when the guide is collapsed", () => {
  const fullGuide = resolveWorkflowActionBarBounds({ left: 284, right: 1568 }, 1920);
  const compactGuide = resolveWorkflowActionBarBounds({ left: 284, right: 1814 }, 1920);
  const hiddenGuide = resolveWorkflowActionBarBounds({ left: 284, right: 1896 }, 1920);

  assert.ok(compactGuide.width > fullGuide.width);
  assert.ok(hiddenGuide.width > compactGuide.width);
  assert.equal(hiddenGuide.left + hiddenGuide.width, 1896);
});

test("workflow action bar clamps safely inside narrow viewports", () => {
  assert.deepEqual(
    resolveWorkflowActionBarBounds({ left: -24, right: 812 }, 800),
    { left: 12, width: 776 },
  );
});

test("fixed workflow action bar reserves its rendered height below final content", () => {
  assert.equal(workflowActionBarClearance(88), 112);
  assert.equal(workflowActionBarClearance(151.25), 176);
  assert.equal(workflowActionBarClearance(Number.NaN), 144);
});

test("Outliers, Missing Values, and Feature Engineering share the measured action bar", () => {
  const shell = read("src/components/StepShell.tsx");
  const pages = [
    read("src/steps/Step04_Outliers.tsx"),
    read("src/steps/Step04_MissingValues.tsx"),
    read("src/steps/Step05_EncodingScaling.tsx"),
  ];

  assert.match(shell, /resolveWorkflowActionBarBounds/);
  assert.match(shell, /data-workflow-action-scope=\{nextAlwaysVisible \? "main-content-column"/);
  assert.doesNotMatch(shell, /lg:left-\[17rem\]|lg:right-6/);
  for (const page of pages) assert.match(page, /\bnextAlwaysVisible\b/);
});

