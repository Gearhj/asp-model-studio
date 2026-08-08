import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync, existsSync } from "node:fs";
import { join } from "node:path";

const root = process.cwd();
const read = (path) => readFileSync(join(root, path), "utf8");
const countOccurrences = (text, needle) => (text.match(new RegExp(needle.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"), "g")) ?? []).length;

test("Credit Risk Studio route and sidebar entry are registered", () => {
  const app = read("src/apps/ModelingApp.tsx");
  const sidebar = read("src/components/Sidebar.tsx");

  assert.match(app, /CreditRiskStudio/);
  assert.match(app, /path="\/credit-risk-studio"/);
  assert.match(sidebar, /Credit Risk Studio/);
  assert.match(sidebar, /to="\/credit-risk-studio"/);
});

test("Credit Risk Studio renders required workflow sections and options", () => {
  const page = read("src/steps/CreditRiskStudio.tsx");
  const lib = read("src/lib/creditRiskStudio.ts");

  [
    "Project Context",
    "Data Acquisition",
    "Credit Bureau Data Review",
    "EDA",
    "Outliers",
    "Missing Values",
    "Feature Engineering",
    "Balance & Split",
    "Model Training",
    "Evaluation",
    "Interpretation",
    "Scoring",
    "Documentation Review",
    "Model Implementation",
    "Model Monitoring",
    "Predictive Modeling Workflow in Credit Risk Mode",
    "Main workflow",
    "Predictive Modeling specialized for underwriting",
    "Credit Risk Studio workflow",
    "Purpose",
    "Inputs",
    "Outputs",
    "Recommended next action",
    "Evidence generated",
  ].forEach((label) => assert.match(page, new RegExp(label.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"))));

  assert.match(page, /useSearchParams/);
  assert.match(page, /setSearchParams\(\{ step: step\.slug \}\)/);
  assert.match(page, /workflowStepForSlug/);
  assert.match(page, /workflowStepForOverlay/);
  assert.doesNotMatch(page, /wrapperTabs/);

  ["Mortgage", "Auto", "Credit Card", "Application Underwriting", "Portfolio Management", "Collections", "Default", "Charge-off", "90+ DPD"].forEach((label) => {
    assert.match(lib, new RegExp(label.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")));
  });
});

test("Credit Risk Studio includes scorecard scaling formulas and preview", () => {
  const page = read("src/steps/CreditRiskStudio.tsx");
  const lib = read("src/lib/creditRiskStudio.ts");

  assert.match(page, /PDO \/ ln\(2\)/);
  assert.match(page, /BaseScore - Factor \* ln\(BaseOdds\)/);
  assert.match(page, /Offset \+ Factor \* ln\(odds\)/);
  assert.match(page, /Factor/);
  assert.match(page, /Offset/);
  assert.match(lib, /scorecardPreview/);
  assert.match(lib, /Math\.log\(2\)/);
});

test("Credit Risk Studio backend endpoints and evidence creation exist", () => {
  assert.ok(existsSync(join(root, "server/credit_risk/credit_risk_router.py")));
  assert.ok(existsSync(join(root, "server/credit_risk/credit_risk_store.py")));

  const main = read("server/main.py");
  const router = read("server/credit_risk/credit_risk_router.py");
  const store = read("server/credit_risk/credit_risk_store.py");

  assert.match(main, /credit_risk_router/);
  [
    "/credit-risk/profile",
    "/credit-risk/profile/project/{project_id}",
    "/credit-risk/readiness",
    "/credit-risk/evidence",
    "/credit-risk/export/excel",
    "/credit-risk/woe-iv/run",
    "/credit-risk/woe-iv/{analysis_id}",
    "/credit-risk/woe-iv/project/{project_id}",
    "/credit-risk/woe-iv/save",
    "/credit-risk/woe-iv/export/excel",
    "/credit-risk/woe-iv/save-evidence",
    "/credit-risk/woe-iv/apply-manual-bins",
    "/credit-risk/woe-iv/generate-code",
    "/credit-risk/scorecard/train",
    "/credit-risk/scorecard/{model_id}",
    "/credit-risk/scorecard/project/{project_id}",
    "/credit-risk/scorecard/export/excel",
    "/credit-risk/scorecard/save-evidence",
    "/credit-risk/scorecard/generate-code",
    "/credit-risk/scorecard/register-model",
    "/credit-risk/ml/train",
    "/credit-risk/ml/{model_id}",
    "/credit-risk/ml/project/{project_id}",
    "/credit-risk/ml/export/excel",
    "/credit-risk/ml/save-evidence",
    "/credit-risk/champion-comparison/run",
    "/credit-risk/champion-comparison/save-decision",
    "/credit-risk/champion-comparison/save-evidence",
  ].forEach((endpoint) => assert.match(router, new RegExp(endpoint.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"))));

  assert.match(store, /financialDomain/);
  assert.match(store, /credit_risk/);
  assert.match(store, /Credit Risk Studio/);
  assert.match(store, /upsert_evidence/);
});

test("Credit Risk Studio includes functional scorecard modeling workflow", () => {
  const page = read("src/steps/CreditRiskStudio.tsx");
  const lib = read("src/lib/creditRiskStudio.ts");
  const engine = read("server/credit_risk/scorecard_engine.py");
  const router = read("server/credit_risk/credit_risk_router.py");

  assert.ok(page.indexOf("\"Traditional Scorecard Path\"") < page.indexOf("\"AI/ML Underwriting Path\""));
  assert.ok(page.indexOf("\"AI/ML Underwriting Path\"") < page.indexOf("\"Champion / Challenger Comparison\""));

  [
    "Scorecard Model Training",
    "Model Setup",
    "WOE Variable Selection",
    "Train Scorecard Model",
    "Train raw logistic baseline without WOE",
    "PDO Score Scaling Inputs",
    "PDO / ln(2)",
    "BaseScore - Factor * ln(BaseOdds)",
    "Offset + Factor * log(odds)",
    "Scorecard Points Table",
    "Model Performance",
    "Champion Candidate",
    "Trained / Needs Review",
    "Detailed Lift Table",
    "Score Distribution",
    "Bad Rate by Decile",
    "Lift / Decile Chart",
    "KS Chart",
    "Cutoff Strategy Preview",
    "Generated Code",
    "SAS-compatible",
    "Save Scorecard Model Evidence",
    "Save Model Performance Evidence",
    "Save Cutoff Strategy Evidence",
    "Save Scorecard Points Evidence",
  ].forEach((label) => assert.match(page, new RegExp(label.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"))));

  ["trainScorecardModel", "getLatestScorecardForProject", "saveScorecardEvidence", "generateScorecardCode", "registerScorecardModel", "exportScorecardExcel"].forEach((symbol) => assert.match(lib, new RegExp(symbol)));
  assert.match(engine, /LogisticRegression/);
  assert.match(engine, /roc_auc_score/);
  assert.match(engine, /build_lift_table/);
  assert.match(engine, /build_scorecard_points/);
  assert.match(engine, /proc logistic data=work\.governed_development_woe descending/i);
  assert.match(engine, /holdout_excluded/);
  assert.match(engine, /Scorecard Points/);
  assert.match(router, /post_scorecard_train/);
  assert.match(router, /post_scorecard_export/);
  assert.match(router, /post_scorecard_evidence/);
});

test("Credit Risk Studio includes Phase 15D dual-track workflow redesign sections", () => {
  const page = read("src/steps/CreditRiskStudio.tsx");
  const lib = read("src/lib/creditRiskStudio.ts");
  const types = read("server/credit_risk/credit_risk_types.py");
  const router = read("server/credit_risk/credit_risk_router.py");
  const mlEngine = read("server/credit_risk/ml_engine.py");

  [
    "Modeling Approach",
    "Traditional Scorecard",
    "AI/ML Underwriting",
    "Compare Both",
    "Traditional Scorecard Path",
    "AI/ML Underwriting Path",
    "Champion / Challenger Comparison",
    "ATLAS recommends building a traditional scorecard baseline and an AI/ML challenger",
    "Monotonic Constraints",
    "Feature Importance",
    "SHAP is not available in this local environment",
    "Surrogate Scorecard",
    "Select Scorecard as Champion",
    "Select AI/ML as Champion",
    "Keep AI/ML as Challenger",
    "Save Champion / Challenger Evidence",
    "Model to use",
    "Traditional Scorecard",
    "AI/ML Challenger",
    "Champion Model",
    "Model type for explanation",
    "Scorecard Readiness",
    "AI/ML Readiness",
    "Credit Risk EDA Variable Review",
    "Target distribution",
    "Missingness Profile",
    "Candidate Variable Ranking",
    "Characteristic Screening",
    "Protected / Sensitive",
    "Leakage Risk",
    "Use for WOE / IV",
    "WOE / IV and Manual Characteristic Binning",
    "Send approved WOE variables to scorecard training",
    "PDO Scaling and Scorecard Points",
    "Model Validation",
    "KS Table",
    "Calibration Table",
    "Cutoff and Decision Strategy",
    "Approval rate vs bad rate",
    "Expected profit by cutoff",
    "Generate Reason Code Draft",
    "ATLAS can generate adverse-action evidence and reason-code candidates",
    "Monitoring and Portfolio Risk",
    "Evidence and Documentation",
    "Export Credit Risk Evidence Pack",
  ].forEach((label) => assert.match(page, new RegExp(label.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"))));

  [
    "CreditRiskMlTrainRequest",
    "CreditRiskMlModel",
    "trainCreditRiskMlModel",
    "getLatestCreditRiskMlModelForProject",
    "saveCreditRiskMlEvidence",
    "runCreditRiskChampionComparison",
    "saveCreditRiskChampionDecision",
    "saveCreditRiskChampionEvidence",
  ].forEach((symbol) => assert.match(lib, new RegExp(symbol)));

  [
    "selectedModelingApproach",
    "monotonicConstraints",
    "championDecision",
    "CreditRiskMlTrainRequest",
    "ChampionComparisonRunRequest",
  ].forEach((symbol) => assert.match(types, new RegExp(symbol)));

  assert.match(router, /post_ml_train/);
  assert.match(router, /post_champion_comparison/);
  assert.match(mlEngine, /train_ml_model/);
  assert.match(mlEngine, /run_champion_comparison/);
});

test("Credit Risk Studio includes Phase 15E HELOC dataset binding and QA fixes", () => {
  const page = read("src/steps/CreditRiskStudio.tsx");
  const lib = read("src/lib/creditRiskStudio.ts");
  const types = read("server/credit_risk/credit_risk_types.py");
  const router = read("server/credit_risk/credit_risk_router.py");

  [
    "Active dataset:",
    "Refresh Dataset Schema",
    "Dataset schema mismatch. Reload selected dataset before continuing.",
    "ATLAS could not load the selected dataset schema. Use Refresh Dataset Schema or reselect the dataset.",
    "handleDatasetChange",
    "refreshDatasetSchema",
    "targetColumn",
    "eventValue",
    "nonEventValue",
    "originalTargetLabelColumn",
    "splitColumn",
    "validationDatasetId",
    "ootDatasetId",
    "Synthetic holdout",
    "Development Population Target Summary",
    "Exact governed development scope",
    "Target evidence is pending an exact project-linked dataset version",
    "Bureau Special Value Profile",
    "Bureau special values such as -7, -8, and -9 are preserved",
    "Special Value %",
    "Confirm Project Setup and Continue",
    "Save Target Definition and Continue",
    "Save EDA Evidence and Continue",
    "Save Characteristic Screening Evidence",
    "Save Scorecard Progress and Continue",
    "Save AI/ML Progress and Continue",
    "Save Champion Decision and Continue",
    "Open Model Evidence Center / Open Model Documentation Studio",
    "RiskPerformance",
    "bad_flag",
    "atlas_split",
    "ExternalRiskEstimate",
    "MSinceOldestTradeOpen",
    "NumSatisfactoryTrades",
    "NetFractionRevolvingBurden",
    "PercentTradesWBalance",
    "Original Target Label / Excluded",
    "Split Indicator / Excluded",
    "HELOC_TRAIN",
    "Predictive Modeling specialized for underwriting",
    "Predictive Modeling Workflow in Credit Risk Mode",
    "Underwriting tools",
    "Evidence and Documentation",
    "Project Context",
    "Data Acquisition",
    "Credit Bureau Data Review",
    "Outliers",
    "Missing Values",
    "Feature Engineering",
    "Balance & Split",
    "Model Training",
    "Evaluation",
    "Interpretation",
    "Scoring",
    "Documentation Review",
    "Model Implementation",
    "Model Monitoring",
    "Open Model Diagnostics",
    "Open Model Documentation Studio",
    "Open Model Evidence Center",
    "WOE / IV and Manual Characteristic Binning",
    "Traditional Scorecard Modeling",
    "PDO Scaling and Scorecard Points",
    "AI/ML Underwriting Challenger",
    "Champion / Challenger",
    "Export Credit Risk Evidence Pack",
  ].forEach((label) => assert.match(page, new RegExp(label.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"))));

  [
    "project-context",
    "data-acquisition",
    "eda",
    "outliers",
    "missing-values",
    "feature-engineering",
    "balance-split",
    "model-training",
    "evaluation",
    "interpretation",
    "scoring",
    "documentation-review",
    "model-implementation",
    "model-monitoring",
  ].forEach((slug) => assert.match(page, new RegExp(`slug: "${slug}"`)));

  assert.match(page, /buildVariableMappings/);
  assert.match(page, /isHelocBureauField/);
  assert.match(page, /exactProjectDatasetVersion/);
  assert.match(page, /isCreditRiskPredictorCandidate/);
  assert.match(page, /predictorColumns: woeRequest\.predictorColumns\.filter/);
  assert.match(page, /selectedVariables: scorecardRequest\.selectedVariables\.filter/);
  assert.match(page, /selectedVariables: mlRequest\.selectedVariables\.filter/);
  assert.match(page, /getCreditRiskDatasetSummary/);
  assert.doesNotMatch(page, /Run WOE \/ IV"\s*}/);
  assert.doesNotMatch(page, /MedHouseVal|AveRooms|AveBedrms|HouseAge/);
  assert.match(lib, /CreditRiskTargetSummary/);
  assert.match(lib, /getCreditRiskDatasetSummary/);
  assert.match(types, /CreditRiskDatasetSummaryRequest/);
  assert.match(router, /post_credit_risk_dataset_summary/);
  assert.match(router, /specialValueProfile/);
});

test("Credit Risk Studio includes Phase 15I layout, state, and population target fixes", () => {
  const page = read("src/steps/CreditRiskStudio.tsx");
  const dataAcquisition = read("src/steps/Step01_DataAcquisition.tsx");

  [
    "CompactMetric",
    "Show readiness details",
    "Predictive Modeling specialized for underwriting. Uses the full ATLAS workflow with credit-risk overlays, evidence capture, diagnostics, documentation, and monitoring.",
    "normalizeCreditRiskProfile",
    "preferredCreditRiskDataset",
    "DataAcquisitionCreditRiskOverlay",
    "Target setup incomplete. Review Target Setup and Dataset Role Assignment in Data Acquisition before continuing.",
    "Open Dataset Library",
    "Save Data Acquisition Evidence",
    "Continue to EDA",
    "HELOC_TRAIN",
    "HELOC_TEST",
    "HELOC_OOT",
    "bad_flag",
    "RiskPerformance",
    "atlas_split",
    "Synthetic holdout",
    "Mapped Documentation Sections",
    "Fair Lending and Governance Considerations",
  ].forEach((label) => assert.match(page, new RegExp(label.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"))));

  [
    "Source and Target",
    "Target Column",
    "Event / Positive Value",
    "Non-event / Negative Value",
    "Data Quality",
    "Predictor Authorization and Variable Review",
    "Data Lineage and Reproducibility",
  ].forEach((label) => assert.match(dataAcquisition, new RegExp(label.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"))));
  const sourceCommand = dataAcquisition.slice(dataAcquisition.indexOf('data-testid="source-command-section"'), dataAcquisition.indexOf("<DataPreview"));
  assert.doesNotMatch(sourceCommand, /HELOC_TRAIN|HELOC_TEST|HELOC_OOT|RiskPerformance|atlas_split|bad_flag/);

  assert.match(page, /<details className="mx-4 my-3 rounded-lg/);
  assert.match(page, /<summary[^>]*>Show readiness details<\/summary>/);
  assert.match(page, /activeWorkflowSlug/);
  assert.match(page, /activeWorkflowStep\.name === "Data Acquisition"/);
  assert.match(page, /active === "Population and Target" && activeWorkflowStep\.name === "Project Context"/);
  assert.match(page, /exactProjectDatasetVersion/);
  assert.match(page, /profile\.datasetVersionId === exactVersion/);
  assert.match(page, /target-directed evidence pending exact governed development scope/);
  assert.doesNotMatch(page, /staleOrMissingTarget|staleRegressionState|findTargetColumn/);
  assert.doesNotMatch(page, /REG_TRAIN/);
  assert.doesNotMatch(page, /MedHouseVal|AveRooms|AveBedrms|HouseAge/);
});

test("Credit Risk Studio includes Phase 15J UX correction", () => {
  const page = read("src/steps/CreditRiskStudio.tsx");
  const dataAcquisition = read("src/steps/Step01_DataAcquisition.tsx");

  [
    "CreditRiskRightRail",
    "Current Step Guide",
    "Required inputs",
    "Recommended next action",
    "Critical warnings",
    "Open Underwriting Tools",
    "Evidence Readiness",
    "Mapped Documentation Sections",
    "Champion / Challenger",
    "Model Diagnostics",
    "Confirm Data Acquisition and Continue",
    "Target distribution",
    "Good / bad count",
    "Bad rate",
    "Missingness table",
    "Special bureau value profile",
    "Candidate Predictor Ranking",
    "Outlier Detection Table",
    "Special bureau value warning",
    "Treatment selection",
    "Save Outlier Evidence",
    "Confirm Outliers and Continue",
    "Missing Value Profile",
    "Save Missing Value Evidence",
    "Confirm Missing Values and Continue",
    "Confirm Balance & Split and Continue",
  ].forEach((label) => assert.match(page, new RegExp(label.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"))));
  assert.doesNotMatch(page, /Variable distribution table/);

  [
    "Source and Target",
    "Data Lineage and Reproducibility",
    "Target Column",
    "Event / Positive Value",
    "Non-event / Negative Value",
    "Data Quality",
    "Predictor Authorization and Variable Review",
  ].forEach((label) => assert.match(dataAcquisition, new RegExp(label.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"))));

  assert.match(page, /<details className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">/);
  assert.match(page, /<summary className="cursor-pointer text-sm font-semibold text-slate-950">Open Underwriting Tools<\/summary>/);
  assert.match(page, /activeWorkflowStep\.name === "Outliers"/);
  assert.match(page, /activeWorkflowStep\.name === "Missing Values"/);
  assert.match(page, /activeWorkflowStep\.name === "Balance & Split"/);
  assert.match(page, /isCreditRiskPredictorCandidate\(row\.name, profile\)/);
  const sourceCommand = dataAcquisition.slice(dataAcquisition.indexOf('data-testid="source-command-section"'), dataAcquisition.indexOf("<DataPreview"));
  assert.doesNotMatch(sourceCommand, /RiskPerformance|bad_flag|atlas_split/);
});

test("Credit Risk Studio includes Phase 15K workflow routing and step mapping fixes", () => {
  const page = read("src/steps/CreditRiskStudio.tsx");

  [
    "HELOC Traditional Scorecard Test Run",
    "Project name field",
    "Rename project",
    "Save project name action",
    "Project name saved.",
    "setProjectName",
    "saveProjectName",
    "saveAndOpenWorkflowStep",
    "Confirm Data Acquisition and Continue",
    "Governed development-population evidence is pending. Showing target-independent schema review only.",
    "Target summary unavailable because the exact target contract is not selected.",
    "Confirm EDA and Continue",
    "Numeric variable outlier profile",
    "Reviewer notes",
    "Bureau special value profile",
    "-7 count",
    "-8 count",
    "-9 count",
    "Special value rate",
    "EDA, Outliers, and Missing Values have not been completed. Tier 1 underwriting models should document these steps before feature engineering.",
    "Synthetic holdout",
  ].forEach((label) => assert.match(page, new RegExp(label.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"))));

  const expectedOrder = [
    "project-context",
    "data-acquisition",
    "eda",
    "outliers",
    "missing-values",
    "feature-engineering",
    "balance-split",
    "model-training",
    "evaluation",
    "interpretation",
    "scoring",
    "documentation-review",
    "model-implementation",
    "model-monitoring",
  ];
  let previousIndex = -1;
  expectedOrder.forEach((slug) => {
    const index = page.indexOf(`slug: "${slug}"`);
    assert.ok(index > previousIndex, `${slug} should appear after the prior workflow route`);
    previousIndex = index;
  });

  const mainWorkflowDefinition = page.slice(page.indexOf("const predictiveWorkflowSteps = ["), page.indexOf("const auxiliaryCreditRiskSteps = ["));
  assert.doesNotMatch(mainWorkflowDefinition, /credit-bureau-data-review/, "Credit Bureau Review must not be a numbered Credit Risk Studio workflow step.");
  assert.match(page, /slug: "credit-bureau-data-review"/);
  assert.match(page, /<Step01BCreditBureauReview \/>/);
  assert.match(page, /onContinue=\{\(\) => saveAndOpenWorkflowStep\("eda"/);
  assert.match(page, /label="Confirm EDA and Continue"[\s\S]*saveAndOpenWorkflowStep\("outliers"/);
  assert.match(page, /Confirm Outliers and Continue/);
  assert.match(page, /saveAndOpenWorkflowStep\("missing-values"/);
  assert.match(page, /Confirm Missing Values and Continue/);
  assert.match(page, /saveAndOpenWorkflowStep\("feature-engineering"/);
  assert.match(page, /activeWorkflowStep\.name === "Balance & Split"[\s\S]*saveAndOpenWorkflowStep\("model-training"/);
  assert.match(page, /activeWorkflowStep\.name === "EDA"[\s\S]*title="EDA"/);
  assert.match(page, /<CreditRiskEdaPanel profile=\{profile\} woeAnalysis=\{woeAnalysis\} variableCounts=\{variableCounts\} \/>[\s\S]*<Step02EDA \/>/);
  assert.match(page, /Confirm EDA and Continue"[\s\S]*saveAndOpenWorkflowStep\("outliers"/);
  assert.match(page, /Confirm Outliers and Continue[\s\S]*onClick=\{onContinue\}/);
  assert.match(page, /activeWorkflowStep\.name === "Outliers"[\s\S]*saveAndOpenWorkflowStep\("missing-values"/);
  assert.match(page, /Confirm Missing Values and Continue[\s\S]*onClick=\{onContinue\}/);
  assert.match(page, /activeWorkflowStep\.name === "Missing Values"[\s\S]*saveAndOpenWorkflowStep\("feature-engineering"/);
  assert.match(page, /activeWorkflowStep\.name === "Balance & Split"[\s\S]*saveAndOpenWorkflowStep\("model-training"/);
  assert.doesNotMatch(page, /active === "Credit Risk EDA" && !\["Outliers", "Missing Values"\]/);
  assert.match(page, /exactProjectDatasetVersion/);
  assert.doesNotMatch(page, /latestVersion/);
});

test("Credit Risk Studio EDA exports and downstream layout cleanup remain in place", () => {
  const page = read("src/steps/CreditRiskStudio.tsx");
  const featureEngineeringRoute = page.slice(page.indexOf('activeWorkflowStep.name === "Feature Engineering"'), page.indexOf('active === "Modeling Approach"'));

  [
    "Download predictor ranking CSV",
    "Download visualization data JSON",
    "Download bad-rate table CSV",
    "Download special-value profile CSV",
    "atlas-eda-candidate-predictor-ranking.csv",
    "atlas-eda-visualizations.json",
    "atlas-eda-bad-rate-spread.csv",
    "atlas-eda-special-value-profile.csv",
    "Approved Predictor Review",
    "Download approved predictors CSV",
    "Approved predictors for WOE / IV",
    "Bad-rate comparisons are pending governed development-population evidence.",
    "Browser preview rows are not used.",
  ].forEach((label) => assert.match(page, new RegExp(label.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"))));

  assert.match(page, /className="credit-risk-embedded-step"/);
  assert.match(read("src/components/StepShell.tsx"), /hideEmbeddedNext = location\.pathname === "\/credit-risk-studio"/);
  assert.doesNotMatch(page, /function OutliersCreditRiskOverlay|function MissingValuesCreditRiskOverlay|Credit-risk EDA overlays|Outlier treatment controls|Credit-risk outlier treatment overlay/);
  assert.doesNotMatch(featureEngineeringRoute, /Reviewer Note/);
});

test("Credit Risk Studio includes Phase 15L real predictive workflow integration", () => {
  const page = read("src/steps/CreditRiskStudio.tsx");

  [
    "Step01DataAcquisition",
    "Step01BCreditBureauReview",
    "Step02EDA",
    "Step03Outliers",
    "Step04MissingValues",
    "Step05FeatureEngineering",
    "Step06BalanceSplit",
    "Step07ModelTraining",
    "Step08Evaluation",
    "Step09Interpretation",
    "Step10Scoring",
    "Step11DocumentationReview",
    "Step12ModelImplementation",
    "Step13ModelMonitoring",
    "RealPredictiveStepEmbed",
    "Real ATLAS Data Acquisition Workflow",
    "Real ATLAS Credit Bureau Data Review Workflow",
    "Real ATLAS EDA Workflow",
    "Real ATLAS Outliers Workflow",
    "Real ATLAS Missing Values Workflow",
    "Real ATLAS Feature Engineering Workflow",
    "Real ATLAS Balance & Split Workflow",
    "Real ATLAS Model Training Workflow",
    "Real ATLAS Evaluation Workflow",
    "Real ATLAS Interpretation Workflow",
    "Real ATLAS Scoring Workflow",
    "Real ATLAS Documentation Review Workflow",
    "Real ATLAS Model Implementation Workflow",
    "Real ATLAS Model Monitoring Workflow",
    "WOE / IV",
    "Manual Characteristic Binning",
    "Lock approved bins",
    "Generated Code",
    "Traditional Scorecard",
    "AI/ML Underwriting Challenger",
    "Compare Both",
    "Production-style training must use the verified development population and exclude the sealed holdout.",
    "score distribution",
    "Scored datasets",
  ].forEach((label) => assert.match(page, new RegExp(label.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"))));

  [
    "Predictive Modeling workflow running in Credit Risk Mode",
    "Credit-risk overlay panels",
    "Credit-risk EDA overlays",
    "Credit-risk outlier treatment overlay",
    "Outlier treatment controls",
    "Credit-risk missing value treatment overlay",
    "Credit-risk model training paths",
  ].forEach((label) => assert.doesNotMatch(page, new RegExp(label.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"))));

  assert.match(page, /slug: "credit-bureau-data-review"/);
  assert.match(page, /<Step01BCreditBureauReview \/>/);
  assert.match(page, /<Step02EDA \/>/);
  assert.match(page, /<Step03Outliers \/>/);
  assert.match(page, /<Step04MissingValues \/>/);
  assert.match(page, /<Step05FeatureEngineering \/>/);
  assert.match(page, /<Step06BalanceSplit \/>/);
  assert.match(page, /<Step07ModelTraining \/>/);
  assert.match(page, /<Step08Evaluation \/>/);
  assert.match(page, /<Step09Interpretation \/>/);
  assert.match(page, /<Step10Scoring \/>/);
  assert.match(page, /<Step11DocumentationReview \/>/);
  assert.match(page, /<Step12ModelImplementation \/>/);
  assert.match(page, /<Step13ModelMonitoring \/>/);
  assert.match(page, /isCreditRiskPredictorCandidate/);
  assert.doesNotMatch(page, /Credit-risk overlay panels/);
});

test("Credit Risk Studio includes Phase 15M QA fixes", () => {
  const page = read("src/steps/CreditRiskStudio.tsx");
  const dataAcquisition = read("src/steps/Step01_DataAcquisition.tsx");

  [
    "BureauSpecialValueTreatmentPanel",
    "Apply selected treatment to all bureau special values",
    "Apply only to selected special value",
    "Apply to all rows",
    "Global treatment rationale",
    "Bureau special values -7, -8, and -9 are preserved as explicit special-value treatments for credit-risk modeling.",
    "Create special bin",
    "Create indicator and impute",
    "Convert to missing",
    "Preserve raw special value",
    "Review manually",
    "Treatment selections persist",
    "Evidence uses the selected global treatment and rationale",
    "EmbeddedPredictiveStepBoundary",
    "Unable to load this Credit Risk Studio step.",
    "The step failed while rendering the embedded Predictive Modeling component.",
    "Retry",
    "Refresh Dataset Schema",
    "Bad-rate comparisons are pending governed development-population evidence.",
    "Download bad-rate table CSV",
    "Browser preview rows are not used.",
    "Save EDA Evidence",
    "Confirm EDA and Continue",
  ].forEach((label) => assert.match(page, new RegExp(label.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"))));

  [
    "Preview method",
    "Preview row limit",
    "Profile row limit",
    "Preview and profiling settings do not change the registered modeling dataset.",
    "Target Setup",
    "Predictor Authorization and Variable Review",
    "Data Quality",
    "Data Lineage and Reproducibility",
  ].forEach((label) => assert.match(dataAcquisition, new RegExp(label.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"))));
  assert.match(dataAcquisition, /predictorEligibility/);
  assert.match(dataAcquisition, /fetchFullFeatureProfile/);
  assert.doesNotMatch(dataAcquisition, /Python Synchronization|creditRiskLeakageRole/);
  assert.match(page, /localStorage\.setItem\(BUREAU_SPECIAL_TREATMENT_KEY/);
  assert.match(page, /specialValueFilter !== "All"/);
  assert.match(page, /selectedTreatment/);
  assert.match(page, /<Step03Outliers \/>/);
  assert.match(page, /<Step04MissingValues \/>/);
  assert.doesNotMatch(page, /function CreditBureauDataReviewStep/);
  [
    "Feature relationship / correlation to target",
    "Credit-risk EDA overlays",
    "Outlier treatment controls",
    "Credit-risk outlier treatment overlay",
    "Credit-risk missing value treatment overlay",
  ].forEach((label) => assert.doesNotMatch(page, new RegExp(label.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"))));
});

test("Credit Risk Studio Phase 15O keeps Data Acquisition ordered and non-duplicative", () => {
  const page = read("src/steps/CreditRiskStudio.tsx");
  const overlay = page.slice(page.indexOf("function DataAcquisitionCreditRiskOverlay"), page.indexOf("function CreditRiskRightRail"));
  const dataAcquisition = read("src/steps/Step01_DataAcquisition.tsx");

  [
    "Source and Target",
    "<TargetSetup",
    "<DataPreview",
    "Data Quality",
    "<BureauReviewPanel",
    "Predictor Authorization and Variable Review",
    "<AnalysisPartitionWorkspace",
    "Data Lineage and Reproducibility",
  ].reduce((previousIndex, label) => {
    const index = dataAcquisition.indexOf(label);
    assert.ok(index > previousIndex, `${label} is not in the expected Data Acquisition order.`);
    return index;
  }, -1);

  assert.ok(dataAcquisition.indexOf("<UploadPanel") > dataAcquisition.indexOf("Source and Target"));
  assert.ok(dataAcquisition.indexOf("<TargetSetup") > dataAcquisition.indexOf("<UploadPanel"));
  assert.ok(dataAcquisition.indexOf("<UploadPanel") < dataAcquisition.indexOf("<DataPreview"));
  assert.ok(dataAcquisition.indexOf("<TargetSetup") < dataAcquisition.indexOf("<DataPreview"));
  const sourceCommand = dataAcquisition.slice(dataAcquisition.indexOf('data-testid="source-command-section"'), dataAcquisition.indexOf("<DataPreview"));
  assert.doesNotMatch(sourceCommand, /HELOC Risk Model TEST|HELOC_TRAIN|HELOC_TEST|HELOC_OOT|RiskPerformance|bad_flag|atlas_split/);
  assert.equal(countOccurrences(dataAcquisition, 'htmlFor="data-acquisition-target-column"'), 1, "Target Column should have one canonical accessible label.");
  assert.equal(countOccurrences(dataAcquisition, 'data-testid="target-column-select"'), 1, "Target Column should have one canonical control.");
  ["Event / Positive Value", "Non-event / Negative Value"].forEach((label) => {
    assert.equal(countOccurrences(dataAcquisition, `label="${label}"`), 1, `${label} should appear as one canonical control.`);
  });

  [
    "Potential leakage candidates",
    "Constant columns",
    "Near-zero variance",
    "High-cardinality categoricals",
    "Legitimate date ranges",
    "disabled checked={false}",
    "Eligible predictor.",
  ].forEach((label) => assert.match(dataAcquisition, new RegExp(label.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"))));

  [
    'Select label="Training dataset"',
    'Select label="Validation dataset"',
    'Select label="OOT dataset"',
    'Select label="Target column"',
    'TextArea label="Dataset lineage notes"',
    "Open Population and Target",
  ].forEach((label) => assert.doesNotMatch(overlay, new RegExp(label.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"))));

  assert.doesNotMatch(overlay, /BureauDataDetectionPanel/);

  ["Open Dataset Library", "Refresh Dataset Schema", "Save Data Acquisition Evidence", "Confirm Data Acquisition and Continue"].forEach((label) => {
    assert.equal(countOccurrences(overlay, label), 1, `${label} should appear once in the Credit Risk Studio Data Acquisition overlay.`);
  });
});

test("Credit Risk Studio true wrapper keeps embedded predictive steps inside studio routes", () => {
  const page = read("src/steps/CreditRiskStudio.tsx");
  const shell = read("src/components/StepShell.tsx");
  const app = read("src/apps/ModelingApp.tsx");

  assert.match(page, /setSearchParams\(\{ step: step\.slug \}\)/);
  assert.match(page, /RealPredictiveStepEmbed/);
  assert.doesNotMatch(page, /Open in full Predictive Modeling/);
  assert.match(page, /atlas:credit-risk-refresh-dataset-schema/);
  assert.match(page, /fullPredictiveRoute/);
  assert.match(shell, /preserveCreditRiskStudioRoute/);
  assert.match(shell, /hideEmbeddedNext = location\.pathname === "\/credit-risk-studio"/);
  assert.match(shell, /!\{hideEmbeddedNext\} &&|!hideEmbeddedNext &&/);
  assert.match(shell, /window\.location\.pathname !== "\/credit-risk-studio"/);
  assert.match(shell, /"\/step05": "feature-engineering"/);
  assert.match(shell, /"\/step01b": "credit-bureau-data-review"/);
  assert.match(shell, /"\/step03": "outliers"/);
  assert.match(shell, /"\/step12": "model-implementation"/);
  assert.match(shell, /"\/step13": "model-monitoring"/);
  assert.match(shell, /\/credit-risk-studio\?step=\$\{slug\}/);
  assert.match(app, /path="\/credit-risk-studio"/);
  assert.doesNotMatch(page, /navigate\("\/step05"|navigate\('\/step05'/);
});

test("Credit Risk Studio outliers direct load has embedded fallback and HELOC treatment controls", () => {
  const page = read("src/steps/CreditRiskStudio.tsx");
  const outliers = read("src/steps/Step04_Outliers.tsx");

  assert.match(page, /slug: "outliers"/);
  assert.match(page, /activeWorkflowStep\.name === "Outliers"/);
  assert.match(page, /<Step03Outliers \/>/);
  assert.match(page, /Unable to load this Credit Risk Studio step/);
  assert.match(page, /Retry/);
  assert.match(page, /Refresh Dataset Schema/);
  assert.doesNotMatch(page, /Open in full Predictive Modeling/);
  assert.doesNotMatch(page, /Credit-risk outlier treatment overlay|Outlier treatment controls/);
  assert.match(outliers, /Outlier Analysis/);
  assert.match(outliers, /globalMethod/);
  assert.match(outliers, /normalizedConfig/);
  assert.match(outliers, /applyGlobalSelection/);
  assert.match(outliers, /\/outliers\/apply/);
  assert.match(outliers, /Full-data flagged/);
  assert.match(page, /Save Outlier Evidence/);
  assert.match(page, /Confirm Outliers and Continue/);
  assert.match(outliers, /nextPath="\/step04"/);
});

test("Credit Risk Studio keeps workflow actions top-loaded and Studio-routed", () => {
  const page = read("src/steps/CreditRiskStudio.tsx");
  const eda = read("src/steps/Step02_EDA.tsx");

  assert.match(page, /title="Real ATLAS EDA Workflow" overlayPlacement="after"/);
  assert.match(page, /resetKey=\{`eda:\$\{profile\.datasetId \|\| "none"\}:\$\{profile\.targetColumn \|\| "none"\}:\$\{schema\.length\}:/);
  assert.match(page, /boundaryResetKey = resetKey \|\| fullPredictiveRoute/);
  assert.match(page, /onContinue=\{\(\) => saveAndOpenWorkflowStep\("eda"/);
  assert.match(page, /label="Confirm Bureau Review and Continue"[\s\S]*saveAndOpenWorkflowStep\("eda"/);
  assert.doesNotMatch(page, /label="Confirm Bureau Review and Continue" disabled=\{schemaMismatch \|\| !schema\.length\}/);
  assert.match(page, /catch \(error\) \{[\s\S]*openWorkflowStep\(slug\)/);
  assert.match(page, /activeWorkflowStep\.name === "Outliers"[\s\S]*label="Confirm Outliers and Continue"[\s\S]*saveAndOpenWorkflowStep\("missing-values"/);
  assert.match(page, /activeWorkflowStep\.name === "Missing Values"[\s\S]*label="Confirm Missing Values and Continue"[\s\S]*saveAndOpenWorkflowStep\("feature-engineering"/);
  assert.match(page, /className="credit-risk-embedded-step"/);
  assert.doesNotMatch(eda, /Mark Complete & Next Step/);
  assert.doesNotMatch(eda, /handleContinue/);
  assert.match(read("src/components/StepShell.tsx"), /hideEmbeddedNext = location\.pathname === "\/credit-risk-studio"/);
  assert.doesNotMatch(page, /<Link to=\{fullPredictiveRoute\}/);
});

test("Credit Risk Studio supports weak-signal and VIF-based feature exclusion", () => {
  const dataAcquisition = read("src/steps/Step01_DataAcquisition.tsx");
  const featureEngineering = read("src/steps/Step05_EncodingScaling.tsx");

  [
    "WEAK_IV_THRESHOLD = 0.01",
    "WEAK_CORRELATION_THRESHOLD = 0.05",
    "Uncheck weak-signal features automatically",
    "applyWeakSignalFilter",
    "saveKeptSelection",
  ].forEach((label) => assert.match(dataAcquisition, new RegExp(label.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"))));

  [
    "VIF_AUTO_EXCLUDE_THRESHOLD = 10",
    "vifCandidateNames",
    "persistVifSelection",
    "excludeHighVifFeatures",
    "Uncheck VIF",
    'type="checkbox"',
    "Excluded after VIF review",
    "selectedByFeature",
    "saveFeatureManifest(",
  ].forEach((label) => assert.match(featureEngineering, new RegExp(label.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"))));
});

test("Credit Risk Studio Balance & Split has final IV feature gate before Model Training", () => {
  const page = read("src/steps/CreditRiskStudio.tsx");
  const training = read("src/steps/Step06_Train.tsx");
  const trainerService = read("server/training/trainer_service.py");
  const evalService = read("server/evaluation/eval_service.py");
  const metadataRouter = read("server/core/metadata_router.py");
  const balanceRoute = page.slice(page.indexOf('activeWorkflowStep.name === "Balance & Split"'), page.indexOf('activeWorkflowStep.name === "EDA"'));

  [
    "FinalModelFeatureReviewPanel",
    "Final feature gate before model training",
    "Review IV-ranked predictors",
    "Use in model training",
    "Apply IV recommended set",
    "Download final feature review CSV",
    "finalFeatureReviewRows",
    "setFinalModelFeatureSelection",
    "applyIvRecommendedFinalFeatures",
    "scorecardRequest.selectedVariables",
    "mlRequest.selectedVariables",
    "!finalModelSelectedVariables.length",
    "autoIvRunKey",
    "balanceSplitAutoIvKey",
    "finalIvPredictorColumns",
    "Governed development WOE / IV",
    "Pending governed evidence",
    "Run governed development-population WOE / IV",
    "Running WOE / IV automatically for Balance & Split final feature review.",
    "saveWoeIvAnalysis",
    "WOE / IV loaded for Balance & Split final feature review.",
    "statusMessage={woeMessage}",
  ].forEach((label) => assert.match(page, new RegExp(label.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"))));

  assert.match(balanceRoute, /<FinalModelFeatureReviewPanel/);
  assert.doesNotMatch(balanceRoute, /previewIvByVariable|finalFeaturePreviewIv/);
  assert.match(balanceRoute, /Confirm Balance & Split and Continue/);
  assert.match(balanceRoute, /saveAndOpenWorkflowStep\("model-training"/);
  assert.match(page, /activeWorkflowStep\.name !== "Balance & Split"/);
  assert.match(page, /runWoeIvAnalysis\(request\)\s*\.then\(saveWoeIvAnalysis\)/);
  assert.match(page, /disabled=\{!hasIvValues\}/);
  [
    "getFeatureManifest",
    "selectedFeatures",
    "selected_original_features",
    "selected_engineered_features",
    "feature_manifest_version",
    "trained_feature_names",
  ].forEach((label) => assert.match(training, new RegExp(label.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"))));
  assert.match(trainerService, /_sanitize_feature_frame/);
  assert.match(trainerService, /excluded_target_features/);
  assert.match(trainerService, /trained_feature_names/);
  assert.doesNotMatch(trainerService, /riskperformance|bad_flag/);
  assert.match(evalService, /_filter_target_derived_rows/);
  assert.match(evalService, /_is_target_derived_feature/);
  assert.match(metadataRouter, /invalidate_downstream_training_state\(/);
  assert.match(metadataRouter, /analysis_partition_service\.invalidate\(/);
});

test("Credit Risk Studio feature preview defaults to 10 rows with matching label", () => {
  const featureEngineering = read("src/steps/Step05_EncodingScaling.tsx");
  assert.match(featureEngineering, /previewRowLimit, setPreviewRowLimit\] = useState\(10\)/);
  assert.match(featureEngineering, /previewFeaturePlan\([\s\S]{0,120}datasetIdentity,[\s\S]{0,120}drafts,[\s\S]{0,120}previewRowLimit,[\s\S]{0,120}controller\.signal/);
  assert.match(featureEngineering, /Preview rows/);
  assert.match(featureEngineering, /\[10, 25, 50, 100\]/);
  assert.match(featureEngineering, /preview\.rows\.map/);
});

test("Credit Risk Studio overlays remain inside real Feature Engineering, Training, Evaluation, and Interpretation steps", () => {
  const page = read("src/steps/CreditRiskStudio.tsx");
  const featureEngineering = read("src/steps/Step05_EncodingScaling.tsx");
  const training = read("src/steps/Step06_Train.tsx");
  const evaluation = read("src/steps/Step08_Evaluation.tsx");
  const interpretation = read("src/steps/Step09_Interpretation.tsx");
  const scoring = read("src/steps/Step10_Scoring.tsx");
  const workflowConfig = read("src/config/workflows.ts");
  const workflowStore = read("src/state/useWorkflowStore.ts");
  [
    "Real ATLAS Feature Engineering Workflow",
    "Real ATLAS Model Training Workflow",
    "Real ATLAS Evaluation Workflow",
    "Real ATLAS Interpretation Workflow",
  ].forEach((label) => assert.match(page, new RegExp(label.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"))));
  ["Feature Engineering", "Predictor Redundancy Check"].forEach((label) => assert.match(featureEngineering, new RegExp(label.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"))));
  ["Transparent Models", "Tree and Ensemble Models", "Logistic Regression"].forEach((label) => assert.match(training, new RegExp(label.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"))));
  assert.doesNotMatch(training, /Mark Complete &amp; Go to Evaluation|Mark Complete & Go to Evaluation/);
  ["AUC", "PR-AUC", "Lift, Gain, and Capture", "RMSE"].forEach((label) => assert.match(evaluation, new RegExp(label.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"))));
  assert.doesNotMatch(evaluation, /Mark Complete &amp; Interpret Model|Mark Complete & Interpret Model/);
  ["Feature Importance", "RFE", "Final Model Sensitivity Analysis"].forEach((label) => assert.match(interpretation, new RegExp(label.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"))));
  assert.match(interpretation, /getNextStepPath\("step09"\)/);
  assert.match(interpretation, /nextPath=\{getNextStepPath\("step09"\)\}/);
  assert.match(scoring, /data-testid="train-scoring-zone"[\s\S]*title="Development TRAIN output"/);
  assert.match(scoring, /data-testid="test-scoring-zone"[\s\S]*title="External Validation Dataset \/ TEST Scored Output"/);
  assert.match(scoring, /data-testid="oot-scoring-zone"[\s\S]*title="Out-of-Time Dataset \/ OOT Scored Output"/);
  assert.doesNotMatch(scoring, /Mark Complete &amp; Build Document|Mark Complete & Build Document|navigate\("\/step11"\)/);
  assert.match(page, /Interpretation \/ RFE Final Model/);
  assert.match(page, /normalizeWorkflowOrder\("credit-risk-studio"\)/);
  assert.ok(page.indexOf('name: "Evaluation"') < page.indexOf('name: "Interpretation"'), "Credit Risk Studio must run Evaluation before RFE final-model selection.");
  assert.ok(page.indexOf('name: "Interpretation"') < page.indexOf('name: "Scoring"'), "Credit Risk Studio side panel must run RFE before Scoring.");
  assert.ok(page.indexOf('name: "Evaluation"') < page.indexOf('name: "Interpretation"'), "Credit Risk Studio workflow rail must show Evaluation before Interpretation.");
  assert.ok(page.indexOf('name: "Interpretation"') < page.indexOf('name: "Scoring"'), "Credit Risk Studio workflow rail must show Interpretation before Scoring.");
  assert.ok(workflowConfig.indexOf('shortLabel: "Train"') < workflowConfig.indexOf('shortLabel: "Evaluate"'), "Top progress bar must show Train before Evaluate.");
  assert.ok(workflowConfig.indexOf('shortLabel: "Evaluate"') < workflowConfig.indexOf('shortLabel: "Interpret"'), "Top progress bar must show Evaluate before Interpret.");
  assert.ok(workflowConfig.indexOf('shortLabel: "Interpret"') < workflowConfig.indexOf('shortLabel: "Score"'), "Top progress bar must show Interpret before Score.");
  const evaluationSection = page.slice(page.indexOf('activeWorkflowStep.name === "Evaluation"'), page.indexOf('active === "Explainability and Adverse Action"'));
  const interpretationSection = page.slice(page.indexOf('activeWorkflowStep.name === "Interpretation"'), page.indexOf('active === "Cutoff and Decision Strategy"'));
  const scoringSection = page.slice(page.indexOf('activeWorkflowStep.name === "Scoring"'), page.indexOf('active === "Monitoring and Portfolio Risk"'));
  assert.match(evaluationSection, /saveAndOpenWorkflowStep\("interpretation"/);
  assert.match(interpretationSection, /saveAndOpenWorkflowStep\("scoring"/);
  assert.match(scoringSection, /saveAndOpenWorkflowStep\("documentation-review"/);
  assert.doesNotMatch(evaluationSection, /saveAndOpenWorkflowStep\("scoring"/);
  assert.ok(workflowConfig.indexOf('label: "Evaluation"') < workflowConfig.indexOf('label: "Interpretation"'), "Predictive workflow config must run Evaluation before RFE final-model selection.");
  assert.ok(workflowConfig.indexOf('label: "Interpretation"') < workflowConfig.indexOf('label: "Scoring"'), "Predictive workflow config must run RFE before Scoring.");
  assert.match(workflowConfig, /id: "credit-risk-studio"[\s\S]*steps: creditRiskStudioSteps/);
  assert.match(workflowConfig, /const creditRiskStudioSteps: WorkflowStep\[\] = predictiveModelingSteps;/);
  assert.doesNotMatch(workflowConfig, /id: "step01b"/);
  assert.match(workflowStore, /normalizeWorkflowOrder/);
  assert.ok(workflowStore.indexOf('"step08", // Evaluation') < workflowStore.indexOf('"step09", // Model Interpretation'), "Workflow store order must run Evaluation before RFE final-model selection.");
  assert.ok(workflowStore.indexOf('"step09", // Model Interpretation') < workflowStore.indexOf('"step10", // Final Scoring'), "Workflow store order must run RFE before Scoring.");
  assert.doesNotMatch(page, /FeatureEngineeringCreditRiskOverlay|ModelTrainingCreditRiskOverlay|EvaluationCreditRiskOverlay|InterpretationCreditRiskOverlay/);
});

test("Final model sensitivity evaluates +/-20 percent and excludes leakage and bureau special values", () => {
  const service = read("server/evaluation/eval_service.py");
  const interpretation = read("src/steps/Step09_Interpretation.tsx");

  assert.match(service, /excluded_sensitivity_features = \{"riskperformance", "bad_flag", "atlas_split"\}/);
  assert.match(service, /for pct in \[-0\.2, 0\.2\]/);
  assert.match(service, /numeric\.where\(special_mask, numeric \* \(1 \+ pct\)\)/);
  assert.match(service, /Sensitivity analysis excludes special bureau values from percentage perturbation/);
  assert.match(service, /negative_scenario_prediction/);
  assert.match(service, /positive_scenario_prediction/);
  assert.match(service, /direction_explanation/);
  assert.match(interpretation, /Negative Scenario Prediction/);
  assert.match(interpretation, /Positive Scenario Prediction/);
  assert.match(interpretation, /Baseline Prediction/);
  assert.match(interpretation, /Direction/);
  assert.match(interpretation, /special_value_note/);
});

test("Project Overview surfaces scorecard model status and metrics", () => {
  const overview = read("src/steps/ProjectOverview.tsx");
  assert.match(overview, /getLatestScorecardForProject/);
  assert.match(overview, /Scorecard Model/);
  assert.match(overview, /Modeling Approach/);
  assert.match(overview, /AI\/ML Status/);
  assert.match(overview, /Champion Decision/);
  assert.match(overview, /Champion Model/);
  assert.match(overview, /AI\/ML AUC/);
  assert.match(overview, /Selected Champion/);
  assert.match(overview, /Evidence Readiness/);
  assert.match(overview, /Champion Scorecard/);
  assert.match(overview, /Credit Risk Studio wrapper readiness/);
  assert.match(overview, /Predictive Workflow/);
  assert.match(overview, /Underwriting Tools/);
  assert.match(overview, /Model Diagnostics/);
  assert.match(overview, /Documentation Studio/);
  assert.match(overview, /Model Evidence Center/);
  assert.match(overview, /Monitoring Readiness/);
  assert.match(overview, /Open Model Diagnostics/);
  assert.match(overview, /Open Model Documentation Studio/);
  assert.match(overview, /AUC/);
  assert.match(overview, /KS/);
  assert.match(overview, /Gini/);
  assert.match(overview, /Selected Cutoff/);
  [
    "Target",
    "EDA",
    "Screening",
    "Approach",
    "Scorecard",
    "AI/ML",
    "Compare",
    "Cutoff",
    "Adverse Action",
    "Monitoring",
    "Evidence",
  ].forEach((label) => assert.match(overview, new RegExp(label.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"))));
});

test("Credit Risk Studio is visible from project overview and downstream evidence systems", () => {
  const overview = read("src/steps/ProjectOverview.tsx");
  const evidenceCenter = read("src/steps/EvidenceGraph.tsx");
  const documentationStudio = read("src/steps/ModelDocumentationStudio.tsx");

  assert.match(overview, /Credit Risk Profile/);
  assert.match(overview, /Open Credit Risk Studio/);
  assert.match(overview, /getCreditRiskProfileForProject/);
  assert.match(evidenceCenter, /Credit Risk Evidence|credit_risk|Credit Risk/);
  assert.match(documentationStudio, /credit_risk|Credit Risk|evidence/i);
});

test("Credit Risk Studio includes WOE IV analysis and manual characteristic binning workbench", () => {
  const page = read("src/steps/CreditRiskStudio.tsx");
  const lib = read("src/lib/creditRiskStudio.ts");
  const types = read("server/credit_risk/credit_risk_types.py");
  const engine = read("server/credit_risk/woe_iv_engine.py");

  [
    "Run WOE / IV Analysis",
    "WOE / IV definitions",
    "WOE = ln(Distribution Good / Distribution Bad)",
    "IV contribution = (Distribution Good - Distribution Bad) * WOE",
    "IV Ranking",
    "Selected Variable Detail",
    "Bad Rate by Bin",
    "WOE by Bin",
    "IV Contribution by Bin",
    "Population Distribution by Bin",
    "Manual Characteristic Binning",
    "Save manual bins",
    "Lock approved bins",
    "Export WOE / IV to Excel",
    "Generate Code",
    "Save WOE / IV Evidence",
    "Save Manual Binning Evidence",
  ].forEach((label) => assert.match(page, new RegExp(label.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"))));

  [
    "runWoeIvAnalysis",
    "getLatestWoeIvAnalysisForProject",
    "saveWoeIvAnalysis",
    "applyManualWoeBins",
    "saveWoeIvEvidence",
    "generateWoeIvCode",
    "exportWoeIvExcel",
  ].forEach((symbol) => assert.match(lib, new RegExp(symbol)));

  assert.match(types, /WoeIvRunRequest/);
  assert.match(types, /WoeIvManualBinsRequest/);
  assert.match(engine, /smoothing/);
  assert.match(engine, /dist_good/);
  assert.match(engine, /dist_bad/);
  assert.match(engine, /woe/);
  assert.match(engine, /ivContribution/);
  assert.match(engine, /apply_manual_bins/);
  assert.match(engine, /create_woe_iv_evidence/);
});

test("Project Overview surfaces WOE IV status for credit risk projects", () => {
  const overview = read("src/steps/ProjectOverview.tsx");
  assert.match(overview, /getLatestWoeIvAnalysisForProject/);
  assert.match(overview, /WOE \/ IV Analysis/);
  assert.match(overview, /Top IV Variable/);
  assert.match(overview, /Variables Reviewed/);
  assert.match(overview, /WOE Review Items/);
});
