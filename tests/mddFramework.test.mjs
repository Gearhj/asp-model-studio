import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";

assert.ok(existsSync("server/persistence/migrations/0010_validator_aligned_mdd.sql"));
const framework = readFileSync("server/model_documentation/mdd_framework.py", "utf8");
assert.match(framework, /Model Objectives, Business Context, and Key Model Risks/);
assert.match(framework, /time_series_forecasting/);
assert.match(framework, /optimization/);
assert.match(framework, /llm_genai/);
const store = readFileSync("server/model_documentation/documentation_store.py", "utf8");
assert.match(store, /validator_aligned_mdd/);
assert.match(store, /Not applicable requires a documented rationale/);
const router = readFileSync("server/model_documentation/documentation_router.py", "utf8");
assert.match(router, /generate-version-control-summary/);
assert.match(router, /Document changes exist that are not included in the version-control summary/);
assert.doesNotMatch(readFileSync("src/components/Sidebar.tsx", "utf8"), /MDD Studio/);
console.log("Validator-aligned MDD framework static tests passed.");
