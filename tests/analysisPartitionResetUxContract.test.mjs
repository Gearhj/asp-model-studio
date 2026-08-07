import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const ROOT = new URL("../", import.meta.url);
const read = (path) =>
  readFileSync(new URL(path, ROOT), "utf8").replace(/\r\n/g, "\n");

const acquisition = read("src/steps/Step01_DataAcquisition.tsx");
const balancingSplit = read("src/steps/Step06_BalancingSplit.tsx");

function escapeRegExp(value) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function requireMarkers(source, markers, context) {
  for (const marker of markers) {
    assert.match(
      source,
      new RegExp(escapeRegExp(marker)),
      `${context}: missing ${marker}`,
    );
  }
}

function functionBodyContaining(source, marker) {
  const markerIndex = source.indexOf(marker);
  assert.ok(markerIndex >= 0, `missing reset command marker: ${marker}`);

  const prefix = source.slice(0, markerIndex);
  const starts = [
    ...prefix.matchAll(
      /(?:async\s+)?function\s+[A-Za-z_$][\w$]*\s*\([^)]*\)\s*(?::\s*[^\n{]+)?\s*\{/g,
    ),
  ];
  assert.ok(starts.length, `expected ${marker} to be issued from a named function`);
  const start = starts.at(-1).index;
  const openingBrace = source.indexOf("{", start);
  let depth = 0;
  let quote = "";
  let escaped = false;
  let lineComment = false;
  let blockComment = false;

  for (let index = openingBrace; index < source.length; index += 1) {
    const character = source[index];
    const next = source[index + 1];

    if (lineComment) {
      if (character === "\n") lineComment = false;
      continue;
    }
    if (blockComment) {
      if (character === "*" && next === "/") {
        blockComment = false;
        index += 1;
      }
      continue;
    }
    if (quote) {
      if (escaped) {
        escaped = false;
      } else if (character === "\\") {
        escaped = true;
      } else if (character === quote) {
        quote = "";
      }
      continue;
    }
    if (character === "/" && next === "/") {
      lineComment = true;
      index += 1;
      continue;
    }
    if (character === "/" && next === "*") {
      blockComment = true;
      index += 1;
      continue;
    }
    if (character === '"' || character === "'" || character === "`") {
      quote = character;
      continue;
    }
    if (character === "{") depth += 1;
    if (character === "}") {
      depth -= 1;
      if (depth === 0) return source.slice(start, index + 1);
    }
  }
  assert.fail(`could not isolate the function containing ${marker}`);
}

test("Balance & Split previews reset impact and enters only the explicit reset route", () => {
  requireMarkers(
    balancingSplit,
    [
      "/analysis-partitions/reset-impact",
      'data-testid="analysis-partition-reset-impact"',
      'projectWorkflowRoute(projectId, "/step01")',
      "?analysisPartition=reset",
    ],
    "governed reset handoff",
  );
  assert.match(
    balancingSplit,
    /Reset requires explicit acknowledgement in Data Acquisition and invalidates:[\s\S]{0,1800}Return to Data Acquisition to reset/,
    "the user must see the downstream impact before entering reset mode",
  );
});

test("normal Data Acquisition offers a bounded ratio choice before the first seal", () => {
  assert.match(acquisition, /developmentShare:\s*0\.8/);
  assert.match(acquisition, /holdoutShare:\s*0\.2/);
  assert.match(acquisition, /randomSeed:\s*42/);
  assert.match(acquisition, /stratificationPolicy:\s*["']target["']/);
  assert.match(acquisition, /INITIAL_HOLDOUT_OPTIONS\s*=\s*\[0\.3,\s*0\.2,\s*0\.1\]/);
  assert.match(acquisition, /data-testid="analysis-partition-holdout-ratio"/);
  assert.match(acquisition, /Development \/ Final Holdout Split/);
  assert.match(acquisition, /Create &amp; Seal Analysis Partition/);

  const normalConfirmation = functionBodyContaining(acquisition, "reset_existing: false");
  requireMarkers(
    normalConfirmation,
    [
      "development_share: policy.developmentShare",
      "holdout_share: policy.holdoutShare",
      "random_seed: policy.randomSeed",
      "stratification_policy: policy.stratificationPolicy",
      "preview_fingerprint: previewFingerprint",
      "reset_existing: false",
      "acknowledge_invalidation: false",
    ],
    "normal partition confirmation",
  );
});

test("reset mode remains the only way to replace already sealed membership", () => {
  requireMarkers(
    acquisition,
    [
      "analysisPartition",
      "reset",
      'data-testid="analysis-partition-reset-workspace"',
      'data-testid="analysis-partition-reset-holdout-share"',
      "Fixed random seed",
      "Fixed stratification",
      'data-testid="analysis-partition-reset-reason"',
      'data-testid="analysis-partition-reset-invalidation-acknowledgement"',
      'data-testid="confirm-analysis-partition-reset"',
      "/analysis-partitions/reset-preview",
      "analysis_partition_reset_change_required",
      "Choose a different governed split ratio to preview a replacement revision.",
      'analysisPartition.phase === "confirming"',
      "Boolean(analysisPartitionResetCompleted)",
      "expected_current_partition_id",
      "expected_current_revision",
    ],
    "explicit Analysis Partition reset workspace",
  );
  assert.doesNotMatch(
    acquisition,
    /data-testid="analysis-partition-reset-random-seed"|data-testid="analysis-partition-reset-stratification-policy"/,
    "a split-ratio change must not expose direct seed or stratification editors",
  );
  assert.match(
    acquisition,
    /(?:URLSearchParams|searchParams)[\s\S]{0,800}analysisPartition[\s\S]{0,300}reset/,
    "reset mode must come from the explicit query parameter",
  );

  assert.match(
    acquisition,
    /analysisPartitionResetMode\s*\?\s*\(\s*<AnalysisPartitionResetWorkspace/,
    "the editable workspace must be rendered only in explicit reset mode",
  );
  assert.match(
    acquisition,
    /analysis-partition-reset-reason[\s\S]{0,600}(?:value|onChange)=/,
    "the reset reason must be controlled",
  );
  assert.match(
    acquisition,
    /analysis-partition-reset-invalidation-acknowledgement[\s\S]{0,600}(?:checked|onChange)=/,
    "invalidation acknowledgement must be controlled and explicit",
  );
  assert.doesNotMatch(
    acquisition,
    /canReset=\{Boolean\(activeDatasetIdentity\s*&&\s*target\s*&&\s*selected\.length\)\}/,
    "the governed split-change gate must not depend on a stale browser predictor count",
  );
  assert.match(
    acquisition,
    /currentDurablePredictorAuthorizationId\(\s*analysisPartitionResetImpact\.partition,?\s*\)/,
    "the governed split-change gate must use only the backend's current durable predictor authorization",
  );
  const resetConfirmation = functionBodyContaining(
    acquisition,
    "Rechecking the exact split-change impact",
  );
  assert.doesNotMatch(
    resetConfirmation,
    /persistDataset\(/,
    "a split change must not persist an unrelated browser predictor-selection draft",
  );
  assert.match(
    resetConfirmation,
    /latestPredictorAuthorizationId\s*=\s*currentDurablePredictorAuthorizationId\(latest\)/,
    "reset confirmation must bind the latest exact durable predictor authorization",
  );
  assert.doesNotMatch(
    resetConfirmation,
    /latest\.predictor_authorization_id\s*\?\?/,
    "reset confirmation must not fall back to the partition's stale creation authorization",
  );
});

test("reset submits an acknowledged replacement policy to the governed confirm endpoint", () => {
  const resetCommand = functionBodyContaining(acquisition, "reset_existing: true");
  requireMarkers(
    resetCommand,
    [
      "/analysis-partitions/confirm",
      'method: "POST"',
      "development_share:",
      "holdout_share:",
      "random_seed:",
      "stratification_policy:",
      "stratification_field:",
      "preview_fingerprint:",
      "reset_reason:",
      "reset_existing: true",
      "acknowledge_invalidation: true",
      "expected_current_partition_id: previousPartition.analysis_partition_id",
      "expected_current_revision: Number(previousPartition.revision)",
    ],
    "reset POST contract",
  );
  assert.doesNotMatch(
    resetCommand,
    /holdout_share:\s*PARTITION_DEFAULTS\.holdoutShare/,
    "reset mode must submit the reviewer-edited holdout share",
  );
  assert.doesNotMatch(
    resetCommand,
    /random_seed:\s*PARTITION_DEFAULTS\.randomSeed/,
    "reset mode must submit the reviewer-edited random seed",
  );
});

test("reset accepts only a newer positive sealed revision and leaves downstream stale", () => {
  const resetCommand = functionBodyContaining(acquisition, "reset_existing: true");
  requireMarkers(
    resetCommand,
    [
      "readiness",
      "current",
      "revision",
      "analysisPartitionIdentityMatches",
      "analysisPartitionPolicyMatches",
      "stale",
    ],
    "verified reset result",
  );
  assert.match(
    acquisition,
    /function\s+analysisPartitionIdentityMatches[\s\S]{0,1800}final_holdout_status\s*===\s*["']sealed["'][\s\S]{0,300}holdout_isolation_status\s*===\s*["']verified["']/,
    "the identity verifier used by reset must prove a sealed, isolated holdout",
  );
  assert.match(
    resetCommand,
    /Number\([^)]*revision[^)]*\)\s*>\s*0|[A-Za-z_$]*revision\s*>\s*0/i,
    "a reset response needs a positive durable revision",
  );
  assert.match(
    resetCommand,
    /[A-Za-z_$]*revision\s*>\s*[A-Za-z_$]*(?:previous|prior)[A-Za-z_$]*revision/i,
    "the replacement revision must be newer than the partition it replaces",
  );
  assert.doesNotMatch(
    resetCommand,
    /window\.location|navigate\s*\(|onNext\s*\(|continueTo/i,
    "a successful reset must remain on Data Acquisition for stale downstream review",
  );

  requireMarkers(
    acquisition,
    [
      'data-testid="analysis-partition-downstream-stale"',
      "downstream",
      "stale",
    ],
    "post-reset stale-state disclosure",
  );
});
