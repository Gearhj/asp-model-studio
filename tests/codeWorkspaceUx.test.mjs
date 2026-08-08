// CODE-DATAACQ-001..004: frontend contract for the Multi-Language Code Workspace.
// Verifies the UI no longer asserts capability on its own, no longer emits an
// unresolvable dataset placeholder, and binds SAS/Python to the active identity.
import fs from "node:fs";
import assert from "node:assert/strict";

const panel = fs.readFileSync("src/components/StepPythonPanel.tsx", "utf8");
const codeExecution = fs.readFileSync("src/lib/codeExecution.ts", "utf8");
const packageJson = JSON.parse(fs.readFileSync("package.json", "utf8"));

assert.equal(packageJson.scripts["test:code-workspace"], "node tests/codeWorkspaceUx.test.mjs && .\\.venv\\Scripts\\python.exe tests\\code_workspace_test.py");

// --- CODE-DATAACQ-001: honest capability -----------------------------------

assert.doesNotMatch(panel, /supportBadge: "Executable"/, "Python must not be hard-coded as Executable.");
assert.match(panel, /: pythonBadge,/, "Non-Data-Acquisition Python capability must still come from the backend.");
assert.match(panel, /fetchPythonCapability\(\)/, "Capability must be fetched from the backend.");
assert.match(codeExecution, /\/python\/capability/, "A dedicated capability endpoint must be called.");
assert.match(panel, /workflowRoute !== "\/step01" && exactDataAcquisitionContextReady && pythonRunnable && Boolean\(pythonDraft\.trim\(\)\) && pythonContextEvaluation\.canUseAsCurrent/, "Data Acquisition metadata code must not execute, and other pages must require exact context, runtime availability, and a current draft.");
assert.match(panel, /const pythonRunnable = pythonCapability\?\.available === true/, "Runnability must require explicit backend availability.");
// Every state the brief requires must be representable.
for (const state of ["Runtime not configured", "Runtime misconfigured", "Runtime disabled", "Checking runtime"]) {
  assert.ok(panel.includes(state), `Python capability state must be renderable: ${state}`);
}
assert.match(codeExecution, /"executable" \| "not_configured" \| "misconfigured" \| "disabled"/, "Capability states must be typed.");

// --- CODE-DATAACQ-002: no placeholder dataset path -------------------------

// Scoped to the Python generator: the defect was an unresolvable path in generated
// *executable* Python. The SAS export templates legitimately contain user-filled
// placeholders because ATLAS never executes them (template-only, external SAS).
const pythonGenerator = panel.slice(
  panel.indexOf("function generatedPythonForRoute"),
  panel.indexOf("function combinedSavedCode")
);
assert.doesNotMatch(pythonGenerator, /path\/to\//, "Generated executable Python must contain no placeholder path.");
assert.doesNotMatch(pythonGenerator, /dataset-library-export/, "The unresolvable export placeholder must be gone.");
assert.doesNotMatch(pythonGenerator, /Path\(/, "Generated Python must not construct a dataset path at all.");
assert.match(panel, /buildDataAcquisitionPythonContext/, "Data Acquisition Python must use the exact backend-confirmed generator.");
assert.match(panel, /fetchDataAcquisitionReproducibilityContext/, "Data Acquisition must fetch one exact backend context.");
assert.match(panel, /Generated code is withheld until the backend confirms/, "Unconfirmed changes must withhold stale code.");
// The exact backend identity is used for the Data Acquisition request context.
assert.match(panel, /datasetId: currentReproducibilityContext\.identity\.dataset_id/, "Exact datasetId must travel with any supported request.");
assert.match(panel, /versionId: currentReproducibilityContext\.identity\.dataset_version_id/, "Exact versionId must travel with any supported request.");
assert.match(panel, /\.authorized_predictors/, "Backend-authorized predictors must drive the exact context.");

// --- Runtime contract shown above the editor -------------------------------

assert.match(panel, /Runtime objects available: df \(authorized dataset version/, "The runtime contract must be visible above the editor.");
assert.match(panel, /TARGET \(selected target column\)/, "TARGET must be documented.");
assert.match(panel, /SELECTED_FEATURES \(approved predictor list\)/, "SELECTED_FEATURES must be documented.");

// --- CODE-DATAACQ-003: SAS identity ----------------------------------------

assert.doesNotMatch(panel, /reg_train/, "The frontend must never reference a regression-era default table.");
assert.match(panel, /function sasDatasetName\(\)/, "A single SAS table identity helper must exist.");
assert.match(panel, /CODE-DATAACQ-003/, "The SAS identity rule should be documented at its source.");
assert.match(panel, /function sasColumnReference\(value: string\)/, "SAS column references need one injection-safe formatter.");
assert.match(panel, /normalized\.replace\(\/'\/g, "''"\)/, "SAS name literals must double embedded quotes.");
assert.match(panel, /numericCandidates\.map\(sasColumnReference\)/, "Every generated SAS predictor reference must be safely formatted.");
assert.doesNotMatch(panel, /tables \$\{target\}|var \$\{numericCandidates\.join/, "Raw governed column names must never be interpolated into SAS statements.");

// --- Part H: generated SAS must not be guaranteed to fail ------------------

assert.match(panel, /function generatedSasCompatibleProgram/, "SAS-compatible mode needs its own supported-subset generator.");
assert.match(panel, /sasMode === "compatible"[\s\S]{0,100}\? generatedSasCompatibleProgram/, "Compatible mode must use the supported-subset program outside Data Acquisition.");
const compatibleGenerator = panel.slice(
  panel.indexOf("function generatedSasCompatibleProgram"),
  panel.indexOf("function generatedSasForRoute")
);
for (const unsupported of ["proc import", "libname", "proc logistic"]) {
  assert.ok(
    !compatibleGenerator.toLowerCase().includes(unsupported),
    `SAS-compatible starter code must not emit unsupported ${unsupported}`
  );
}
for (const supported of ["proc contents", "proc freq", "proc means"]) {
  assert.ok(compatibleGenerator.toLowerCase().includes(supported), `SAS-compatible starter code should use ${supported}`);
}

// --- Backend surface referenced by the UI ----------------------------------

const sandboxPolicy = fs.readFileSync("server/code_execution/sandbox_policy.py", "utf8");
const datasetBinding = fs.readFileSync("server/code_execution/dataset_binding.py", "utf8");
const sasCompatible = fs.readFileSync("server/code_execution/sas_compatible.py", "utf8");
const pythonExecution = fs.readFileSync("server/python_execution.py", "utf8");

assert.equal(fs.existsSync("server/code_execution/SANDBOX.md"), true, "The sandbox contract must be documented.");
assert.match(sandboxPolicy, /SHELL_METACHARACTERS/, "Shell metacharacters must be rejected.");
assert.match(sandboxPolicy, /approved_interpreters/, "An approved-interpreter allowlist is required.");
assert.match(sandboxPolicy, /must include a \{script\} placeholder/, "The template must bind the submitted script.");
assert.match(pythonExecution, /authorize_modeling_scope\(user, request\.projectId, "view"\)/, "Execution must be project-authorized.");
assert.match(pythonExecution, /Depends\(require_user\)/, "Execution must require an authenticated user.");
assert.match(pythonExecution, /MAX_STREAM_CHARS/, "Captured output must be bounded.");

assert.match(datasetBinding, /ATLAS_DATASET_PATH/, "The path contract must be provided.");
// Scoped to the emitted prelude, not the module docstring (which quotes the old
// defect for context).
const preludeBuilder = datasetBinding.slice(
  datasetBinding.indexOf("def build_runtime_prelude"),
  datasetBinding.indexOf("def runtime_contract_description")
);
assert.doesNotMatch(preludeBuilder, /path\/to\//, "No placeholder path may be emitted into the runtime prelude.");
assert.match(preludeBuilder, /staged_path\.name/, "The sandbox must receive a workdir-relative filename, not a server path.");
assert.match(datasetBinding, /require_dataset/, "Dataset binding must go through the authorization check.");

// SAS backend identity + honest status.
assert.match(sasCompatible, /def active_table_identity/, "A single authoritative SAS identity function is required.");
assert.match(sasCompatible, /def _derive_status/, "Status must be derived from the statement report.");
assert.match(sasCompatible, /return_code = 0 if status == "completed" else 1/, "Only a completed run may return code 0.");
assert.match(sasCompatible, /"executionKind": "sas_compatible_translated"/, "SAS execution must be labelled translated, not native.");
assert.match(sasCompatible, /not a SASPy session or a licensed SAS runtime/, "The engine note must disclaim native SAS.");
// The hard-coded regression-era aliases are gone.
assert.doesNotMatch(sasCompatible, /"work\.reg_train": df/, "The hard-coded work.reg_train alias must be removed.");
assert.doesNotMatch(sasCompatible, /Use work\.reg_train/, "Guidance must not name a stale regression table.");

console.log("codeWorkspaceUx.test.mjs: all checks passed.");
