import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const source = readFileSync("src/lib/auditAssurance.ts", "utf8");

test("frontend audit-assurance contracts are versioned and identity-complete", () => {
  assert.match(source, /AUDIT_ASSURANCE_CONTRACT_VERSION = "1\.0"/);
  for (const field of [
    "project_id",
    "dataset_id",
    "dataset_version_id",
    "activation_revision",
    "target_contract_id",
    "predictor_authorization_id",
    "analysis_partition_id",
    "feature_manifest_id",
    "validation_design_id",
    "training_run_id",
    "candidate_id",
    "evaluation_package_id",
    "interpretation_package_id",
    "model_version_id",
  ]) {
    assert.match(source, new RegExp(`\\b${field}\\b`));
  }
});

test("display names, first/latest selectors, and browser authority fail closed", () => {
  assert.match(source, /project display name cannot substitute for project_id/i);
  assert.match(source, /dataset display name cannot substitute for dataset_id/i);
  assert.match(source, /first\/latest fallback selection/);
  assert.match(source, /Browser or client state cannot be an audit authority/);
});

test("role separation prevents automated or developer claims from becoming independent conclusions", () => {
  assert.match(source, /System observations must be attributed to a service identity/);
  assert.match(source, /validation_conclusion: "independent_validation"/);
  assert.match(source, /internal_audit_conclusion: "internal_audit"/);
  assert.match(source, /automated check is an observation, not an independent audit conclusion/i);
});

test("bounded projections prohibit raw, holdout-membership, and provider-catalog content", () => {
  for (const forbidden of [
    "raw_rows",
    "dataset_rows",
    "customer_records",
    "sealed_holdout_membership",
    "holdout_positions",
    "restricted_catalog_content",
    "provider_catalog_rows",
  ]) {
    assert.match(source, new RegExp(`"${forbidden}"`));
  }
  assert.match(source, /assertBoundedAuditProjection/);
});

test("deterministic serialization and manifest hashing are contract utilities only", () => {
  assert.match(source, /Object\.entries\([\s\S]*\.sort\(/);
  assert.match(source, /deterministicAuditJson/);
  assert.match(source, /globalThis\.crypto\.subtle\.digest\("SHA-256"/);
  assert.doesNotMatch(source, /fetch\(|localStorage|sessionStorage/);
});

