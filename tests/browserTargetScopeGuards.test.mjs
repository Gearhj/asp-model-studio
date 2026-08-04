import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const read = (relativePath) => fs.readFileSync(path.join(ROOT, relativePath), "utf8");

const featureProfiling = read("src/lib/featureProfiling.ts");
const adaptiveWorkflow = read("src/lib/adaptiveWorkflow.ts");
const copilot = read("src/components/CopilotCard.tsx");
const bureau = read("src/lib/creditBureau.ts");
const creditRiskPage = read("src/steps/CreditRiskStudio.tsx");
const creditRiskClient = read("src/lib/creditRiskStudio.ts");
const stepCode = read("src/components/StepPythonPanel.tsx");
const notebook = read("src/lib/notebookExport.ts");
const visualData = read("src/visual-intelligence/dataAccessLayer.ts");
const localDataset = read("src/lib/localDataset.ts");
const identityProvider = read("src/components/PredictiveIdentityProvider.tsx");
const taskContext = read("src/lib/taskContext.ts");
const visualContext = read("src/visual-intelligence/VisualIntelligenceContext.tsx");
const distributionExplorer = read("src/visual-intelligence/prototypes/DistributionExplorer.tsx");

// Browser feature profiling is structural-only. IV/correlation must be returned
// by the exact development-scoped backend artifact.
assert.doesNotMatch(featureProfiling, /function informationValue\s*\(/);
assert.doesNotMatch(featureProfiling, /function correlation\s*\(/);
assert.match(featureProfiling, /iv:\s*null/);
assert.match(featureProfiling, /correlationWithTarget:\s*null/);
assert.match(featureProfiling, /associationStatus:\s*"not_evaluated"/);
assert.match(featureProfiling, /Browser rows provide structural statistics only/);

// Browser guidance cannot infer prevalence from cached target rows.
assert.doesNotMatch(adaptiveWorkflow, /eventRateForTarget|row\[target\]/);
assert.doesNotMatch(copilot, /eventRateForTarget|context\.eventRate|row\[target\]/);
assert.match(copilot, /will not infer prevalence from browser rows/);

// Bureau special-value recommendations remain target-independent in browser
// state, and generated code refuses a target-aware browser comparison.
const bureauDetection = bureau.slice(
  bureau.indexOf("export function detectBureauSpecialValues"),
  bureau.indexOf("export function summarizeBureauHandling"),
);
assert.doesNotMatch(bureauDetection, /row\[target\]|eventDelta|targetRate/);
assert.match(bureau, /Target comparison: pending governed development-population evidence/);
assert.match(bureau, /this generated browser helper is structural-only/);

// Credit Risk Studio binds one project-linked immutable version and never
// supplies preview target evidence or a descriptive latest-version fallback.
assert.doesNotMatch(creditRiskPage, /latestVersion|previewIv|previewBadRate|Data Acquisition preview/);
assert.doesNotMatch(creditRiskPage, /function findTargetColumn/);
assert.match(creditRiskPage, /exactProjectDatasetVersion/);
assert.match(creditRiskPage, /credit-risk-exact-scope-status/);
assert.match(creditRiskPage, /targetScopeReady/);
assert.match(creditRiskClient, /assertExactDevelopmentScope/);
assert.match(creditRiskClient, /analyticalScope !== "development_population"/);
assert.match(creditRiskClient, /holdoutExcluded !== true/);

// Generated EDA code is structural until exact development membership is
// validated. The generic compatibility program may summarize predictor
// frequencies, but the EDA route must not emit a target-frequency program.
const generatedSasForRoute = stepCode.slice(
  stepCode.indexOf("function generatedSasForRoute"),
  stepCode.indexOf("function sasStatus"),
);
const generatedEdaSas = generatedSasForRoute.slice(
  generatedSasForRoute.indexOf('if (route === "/step02")'),
  generatedSasForRoute.indexOf('if (route === "/step06")'),
);
assert.doesNotMatch(generatedEdaSas, /proc freq/i);
assert.match(generatedEdaSas, /Target-directed analysis requires exact verified development membership/);
const edaCell = notebook.slice(
  notebook.indexOf('sectionKey: "eda"'),
  notebook.indexOf('sectionKey: "outliers"'),
);
assert.doesNotMatch(edaCell, /df\s*\[\s*TARGET\s*\]/);
assert.match(edaCell, /this cell does not access target values/);
assert.match(notebook, /y_development = df\.iloc\[list\(DEVELOPMENT_POSITIONS\)\]\[TARGET\]/);
assert.doesNotMatch(notebook, /y_holdout|_y_holdout|y_test\s*=|X_test\s*=/);

// The reachable Visual Intelligence prototype is structural-only when its
// authoritative server aggregate is unavailable; no local/DuckDB target rate.
assert.doesNotMatch(visualData, /filtered\.filter\(\(row\) => row\[reference\.target/);
assert.doesNotMatch(visualData, /AVG\(CASE WHEN/);
assert.match(visualData, /targetRate:\s*null/);
assert.match(visualData, /Request structural aggregates only/);

// Generic browser samples carry target contract metadata but never target
// values. Exact identity and current scope are revalidated by every consumer.
assert.match(identityProvider, /expected_dataset_id/);
assert.match(identityProvider, /expected_dataset_version_id/);
assert.match(identityProvider, /target_values_included === false/);
assert.match(identityProvider, /clearProjectDataset/);
assert.doesNotMatch(identityProvider, /dataset\.problem_type\s*=\s*inferLocalProblemType/);
assert.match(localDataset, /selectedColumns\.forEach/);
assert.match(localDataset, /containsTargetValues/);
assert.match(localDataset, /target_values_included:\s*false/);
assert.doesNotMatch(localDataset, /dataset\.rows\s*\.map\(\(row\) => row\[dataset\.target/);
assert.doesNotMatch(taskContext, /row\s*\[\s*dataset(?:\?\.|\.)(?:target|target_column)/);
assert.match(taskContext, /target-contract-metadata/);

assert.match(visualData, /workspace rows require an exact registered dataset version/);
assert.match(visualData, /expected_dataset_id/);
assert.match(visualData, /delete safe\[target\]/);
assert.match(distributionExplorer, /key !== result\.reference\.target/);
assert.match(visualContext, /if \(!exactIdentity\?\.dataset_id \|\| !exactIdentity\.dataset_version_id\)/);
assert.match(visualContext, /clearVisualDataForProject\(projectId\)/);

console.log("Browser target-scope guard scan passed.");
