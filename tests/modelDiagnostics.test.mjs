import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

const root = process.cwd();
const read = (file) => fs.readFileSync(path.join(root, file), "utf8");

const app = read("src/apps/ModelingApp.tsx");
const sidebar = read("src/components/Sidebar.tsx");
const scoring = read("src/steps/Step10_Scoring.tsx");
const featureEngineering = read("src/steps/Step05_EncodingScaling.tsx");
const balancingSplit = read("src/steps/Step06_BalancingSplit.tsx");
const modelTraining = read("src/steps/Step06_Train.tsx");
const evaluation = read("src/steps/Step08_Evaluation.tsx");
const diagnostics = read("src/steps/ModelDiagnostics.tsx");
const diagnosticsLib = read("src/lib/modelDiagnostics.ts");
const scoringRouter = read("server/scoring/scoring_router.py");
const evalRouter = read("server/evaluation/eval_router.py");
const evalService = read("server/evaluation/eval_service.py");
const edaWorkspaceService = read("server/eda/workspace_service.py");
const diagRouter = read("server/model_diagnostics/diagnostics_router.py");
const diagStore = read("server/model_diagnostics/diagnostics_store.py");
const main = read("server/main.py");
const datasetLibrary = read("src/steps/DatasetLibrary.tsx");
const datasetDetail = read("src/steps/DatasetDetail.tsx");
const chartStudio = read("src/steps/ChartStudio.tsx");
const workbench = read("src/steps/AnalyticsWorkbench.tsx");
const outliers = read("src/steps/Step04_Outliers.tsx");
const packageJson = JSON.parse(read("package.json"));

assert.equal(packageJson.scripts["test:model-diagnostics"], "node tests/modelDiagnostics.test.mjs", "package script must run Model Diagnostics tests.");
assert.match(app, /path="\/model-diagnostics"/, "Model Diagnostics route must be registered.");
assert.match(sidebar, /Model Diagnostics/, "Sidebar must expose Model Diagnostics.");
assert.match(main, /model_diagnostics_router/);
assert.match(main, /scoring_router/);

assert.match(scoring, /Register Scored Dataset|Save Scored Output to Dataset Library/, "Scoring page must expose scored-output registration.");
assert.match(scoring, /TRAIN Scored Output/, "Scoring page must expose TRAIN scored-output registration.");
assert.match(scoring, /TEST Scored Output/, "Scoring page must expose TEST scored-output registration.");
assert.match(scoring, /OOT Scored Output/, "Scoring page must expose OOT scored-output registration.");
assert.match(scoring, /scoreDevelopmentSplit/, "Scoring page must be able to score the development TRAIN split.");
assert.match(scoring, /Register Scored Output/, "Scoring page must show a visible scored-output registration panel.");
assert.match(scoring, /Save Scored Output to Dataset Library/, "Scoring page must make scored-output saving obvious.");
assert.match(scoring, /Register Full Scored Output/, "Scoring page must register full scored output.");
assert.match(scoring, /scored_rows/, "Scoring page must consume full scored rows when available.");
assert.match(scoring, /scored_columns/, "Scoring page must consume full scored columns when available.");
assert.match(scoring, /full_scored_output/, "Scoring page must label full scored output registration.");
assert.match(scoring, /Feature columns preserved/, "Scoring page must show feature-preservation readiness.");
assert.match(scoring, /Target column detected/, "Scoring page must show target detection readiness.");
assert.match(scoring, /Residual columns/, "Scoring page must show residual-field readiness.");
assert.match(scoring, /Warning: this scored output contains predictions only/, "Scoring page must warn for legacy prediction-only scored rows.");
assert.match(scoring, /predicted_value/, "Regression scored output registration should preserve prediction semantics.");
assert.match(scoring, /atlas_residual/, "Regression scored output registration should include residual aliases.");
assert.match(scoring, /atlas_abs_residual/, "Regression scored output registration should include absolute residual aliases.");
assert.match(scoring, /atlas_squared_residual/, "Regression scored output registration should include squared residual aliases.");
assert.match(scoring, /atlas_percent_error/, "Regression scored output registration should include percent error aliases.");
assert.match(scoring, /targetColumn/, "Scoring registration should pass target column metadata.");
assert.match(scoring, /MedHouseVal/, "Regression target examples such as MedHouseVal should be preserved in scored output metadata or previews.");
assert.match(scoring, /Residual Diagnostics/, "Regression scored output should advertise residual diagnostics availability.");
assert.match(scoring, /Pozzolo Prior Correction \/ Undersampling Calibration/, "Scoring page must show Pozzolo correction in classification/scoring context.");
assert.match(scoring, /alpha = \[pi \/ \(1 - pi\)\] \/ \[pi_s \/ \(1 - pi_s\)\]/, "Scoring page must show Pozzolo alpha equation.");
assert.match(scoring, /p_corrected = \(alpha \* p_s\) \/ \(1 - p_s \+ alpha \* p_s\)/, "Scoring page must show Pozzolo probability equation.");
assert.match(scoring, /Use this when a classification model was trained on a sampled or balanced class distribution/, "Scoring page must scope Pozzolo correction to classification probability calibration.");
assert.match(scoring, /registerScoredDataset/, "Scoring page must call scored registration API.");
assert.match(evalRouter, /\/score\/development-split/, "Backend must expose development TRAIN split scoring.");
assert.match(evalService, /def score_development_split/, "Evaluation service must score development TRAIN and TEST splits.");
assert.match(evalService, /"target_column"/, "Scoring response must include target column metadata.");
assert.match(evalService, /"actual"/, "Scoring preview rows must preserve actual target values when available.");
assert.match(evalService, /"scored_rows"/, "Scoring response must include full scored rows.");
assert.match(evalService, /"scored_columns"/, "Scoring response must include full scored columns.");
assert.match(evalService, /build_full_scored_output_frame/, "Scoring service must build full scored output rows.");
assert.match(evalService, /dataframe_to_json_records/, "Scoring service must JSON-serialize full scored rows.");
for (const scoredField of ["predicted_value", "atlas_residual", "atlas_abs_residual", "atlas_squared_residual", "atlas_percent_error", "split"]) {
  assert.match(evalService, new RegExp(scoredField), `Full scored output missing ${scoredField}.`);
}
assert.match(scoringRouter, /@router\.post\("\/scoring\/register-scored-dataset"\)/, "Backend scored registration endpoint is missing.");
assert.match(scoringRouter, /datasetRole.*scored_output/s, "Registered scored datasets must be labeled scored_output.");
assert.match(scoringRouter, /full_scored_output/, "Registered scored datasets must default to full scored output row scope.");
assert.match(scoringRouter, /atlas_score_decile/, "Scored registration should derive decile when score is available.");
assert.match(scoringRouter, /atlas_residual/, "Scored registration should derive residual when actual and prediction are available.");
assert.match(scoringRouter, /atlas_abs_residual/, "Scored registration should derive absolute residual when actual and prediction are available.");
assert.match(scoringRouter, /atlas_squared_residual/, "Scored registration should derive squared residual when actual and prediction are available.");
assert.match(scoringRouter, /atlas_percent_error/, "Scored registration should derive percent error when actual and prediction are available.");
assert.match(scoringRouter, /targetColumn/, "Scored registration should accept explicit target column metadata.");
assert.match(scoringRouter, /blocked_actual\s*=\s*\{[^}]*predicted_value[^}]*prediction[^}]*score[^}]*probability/s, "Scored registration must not infer prediction/score fields as actual target.");
assert.match(diagStore, /if not score_col and prediction_col/, "Regression diagnostics must fall back to prediction when score/probability is absent.");
assert.match(diagStore, /binary_actual/, "Classification-only diagnostics must check binary actual outcomes.");
assert.match(diagStore, /positiveClass/, "Diagnostics must support positive-class override.");
assert.match(diagStore, /blocked_actual\s*=\s*\{[^}]*predicted_value[^}]*prediction[^}]*score[^}]*probability/s, "Actual role detection must block prediction/score/probability aliases.");
assert.match(diagStore, /source\.get\("targetColumn"\)/, "Diagnostics should prefer registered targetColumn metadata for actual mapping.");
assert.match(diagStore, /def diagnostic_mode\(/, "Diagnostics must classify outputs as regression, classification, prediction-only, or unmapped.");
assert.match(diagStore, /def mapping_warnings_for_roles\(/, "Diagnostics must emit mapping warnings.");
for (const fn of ["prediction_summary", "prediction_extremes", "residual_extremes", "prediction_band_summary", "regression_fit_summary", "split_comparison"]) {
  assert.match(diagStore, new RegExp(`def ${fn}\\(`), `Diagnostics store missing ${fn}.`);
}
for (const field of ["diagnosticMode", "mappingWarnings", "predictionSummary", "actualDistribution", "classificationMetrics", "detailedLiftTable", "topPredictions", "bottomPredictions", "largestAbsoluteErrors", "topOverpredictions", "topUnderpredictions", "predictionBandSummary", "regressionFitSummary", "populationWaterfall", "vifAnalysis", "pozzoloCalibration", "kpiAggregation", "splitComparison"]) {
  assert.match(diagStore, new RegExp(`"${field}"`), `Diagnostics result must include ${field}.`);
  assert.match(diagnosticsLib, new RegExp(field), `Diagnostics TypeScript contract must include ${field}.`);
}

for (const term of ["Score Distribution", "Prediction Distribution", "Predicted Value Summary", "Top 10 Highest Predictions", "Bottom 10 Lowest Predictions", "Largest Absolute Errors", "Top Overpredictions", "Top Underpredictions", "Prediction Band Summary", "Regression Fit Summary", "Scored Split Comparison", "Residual Diagnostics", "Actual Distribution", "Actual vs Predicted", "Calibration", "Classification Diagnostics Note", "Classification Summary Metrics", "Detailed Classification Lift Table", "Population Waterfall", "KPI Aggregation", "VIF / Multicollinearity Analysis", "VIF_j = 1 / (1 - R_j^2)", "Pozzolo Prior Correction / Undersampling Calibration", "Segment Performance", "Generated Diagnostics Code", "Field Mapping", "Actual column", "Prediction column", "Residual column", "Positive class value", "Refresh Diagnostics Fields", "Re-register Full Scored Dataset"]) {
  assert.match(diagnostics, new RegExp(term.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")), `Model Diagnostics UI missing ${term}.`);
}
assert.match(diagnostics, /Lift\/Decile and Calibration require a binary outcome and probability score/, "Regression scored output should show classification diagnostic guidance instead of lift/calibration charts.");
assert.match(diagnostics, /Export to Excel/);
assert.match(diagnostics, /Export to Word/);
assert.match(diagnostics, /Export to PowerPoint/);
assert.match(diagnostics, /Save Diagnostics as Insight/);
assert.match(diagnostics, /Register scored output from the Predictive Modeling Scoring step/);
assert.match(diagnostics, /Go to Scoring/);
assert.match(diagnostics, /Open Dataset Library/);
assert.match(diagnostics, /runUserPython/);
assert.match(diagnostics, /runAnalyticsPreviewSql/);
assert.match(diagnostics, /runUserR/);
assert.match(diagnostics, /runUserSasCompatible/);
assert.match(diagnostics, /Numeric segment columns with many distinct values are binned into quantiles/, "Segment override guidance should disclose numeric binning.");
assert.match(diagnostics, /Field Mapping and Prediction Quality Warnings/, "Model Diagnostics should expose mapping and prediction warnings.");

assert.match(diagnosticsLib, /registerScoredDataset/);
assert.match(diagnosticsLib, /runModelDiagnostics/);
assert.match(diagnosticsLib, /exportModelDiagnostics/);
assert.match(diagnosticsLib, /isScoredOutputDataset/);
assert.match(diagRouter, /@router\.get\("\/model-diagnostics\/run"\)/);
assert.match(diagRouter, /actual: Optional\[str\]/);
assert.match(diagRouter, /prediction: Optional\[str\]/);
assert.match(diagRouter, /positiveClass: Optional\[str\]/);
assert.match(diagRouter, /@router\.post\("\/model-diagnostics\/insights"\)/);
assert.match(diagRouter, /@router\.get\("\/model-diagnostics\/system\/diagnostics"\)/);
assert.match(diagRouter, /@router\.get\("\/model-diagnostics\/export\/\{export_format\}"\)/);
for (const fn of ["compute_model_diagnostics", "classification_summary_metrics", "detailed_lift_table", "population_waterfall", "vif_analysis", "pozzolo_calibration_detail", "kpi_aggregation", "lift_deciles", "calibration_bins", "residual_summary", "actual_vs_predicted", "segment_performance", "generated_code"]) {
  assert.match(diagStore, new RegExp(`def ${fn}\\(`), `Diagnostics store missing ${fn}.`);
}
for (const sheet of ["Prediction Summary", "Top 10 Highest Predictions", "Bottom 10 Lowest Predictions", "Largest Absolute Errors", "Top Overpredictions", "Top Underpredictions", "Prediction Band Summary", "Regression Fit Summary", "Classification Metrics", "Detailed Lift Table", "Population Waterfall", "VIF Analysis", "Pozzolo Calibration", "KPI Aggregation", "Split Comparison"]) {
  assert.match(diagStore, new RegExp(sheet.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")), `Diagnostics Excel export missing ${sheet}.`);
}
for (const codeTerm of ["Prediction summary", "Top 10 highest predictions", "Bottom 10 lowest predictions", "Largest residual errors", "Prediction band summary", "Detailed lift table", "VIF_j = 1 / (1 - R_j^2)", "Pozzolo correction", "proc means", "proc sort", "proc print", "proc rank", "groups=10", "descending"]) {
  assert.match(diagStore, new RegExp(codeTerm.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")), `Generated diagnostics code missing ${codeTerm}.`);
}

assert.match(datasetLibrary, /Scored Output/);
assert.match(datasetDetail, /Open Model Diagnostics/);
assert.match(datasetDetail, /Scored Output Completeness/, "Dataset Detail must show scored-output completeness.");
for (const completenessTerm of ["Feature columns present", "Target column present", "Prediction column present", "Residual fields present", "Rows reviewed", "Columns reviewed", "Diagnostic readiness", "Ready for regression diagnostics", "Prediction-only, actual target missing", "Prediction-only, original features missing", "Ready for classification diagnostics", "Needs field mapping", "Re-register Full Scored Dataset"]) {
  assert.match(datasetDetail, new RegExp(completenessTerm.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")), `Dataset Detail completeness panel missing ${completenessTerm}.`);
}
assert.match(chartStudio, /Open in Model Diagnostics/);
assert.match(workbench, /Scored output context detected/);

for (const vifTerm of ["Predictor Redundancy Check", "VIF", "Use in model", "VIF_AUTO_EXCLUDE_THRESHOLD = 10", "Uncheck VIF", "Excluded after VIF review", "saveFeatureManifest"]) {
  assert.match(featureEngineering, new RegExp(vifTerm.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")), `Feature Engineering VIF card missing ${vifTerm}.`);
}
for (const vifTerm of ["def _vif", "work.shape[1] < 2 or len(work) < 5", "np.linalg.lstsq", "1 / max(1 - r_squared", '"high" if vif >= 10', '"review" if vif >= 5']) {
  assert.match(edaWorkspaceService, new RegExp(vifTerm.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")), `Backend Feature Engineering VIF analysis missing ${vifTerm}.`);
}
for (const vifTerm of ["VIF_EXCLUDED_FIELD_RE", "Diagnostic/output field", "Non-numeric variable", "Too many missing values", "Constant variable", "Singular matrix", "Not enough rows", "Tolerance = 1 / VIF"]) {
  assert.match(diagStore, new RegExp(vifTerm.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")), `Backend VIF analysis missing ${vifTerm}.`);
}

for (const term of ["Training and Validation Design", "Data Acquisition Analysis Partition", "read-only reference", "sealed final holdout", "Cross-validation stays inside the development population", "Final-holdout, TEST, and OOT target distributions are not inspected here"]) {
  assert.match(balancingSplit, new RegExp(term.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")), `Balance & Split validation design missing ${term}.`);
}
assert.doesNotMatch(balancingSplit, /Additional validation designs|Planned future validation designs/);

for (const term of ["Training Readiness", "Algorithm Selection", "Execution Policy", "Selected Model Bench", "primaryTrainingActionLabel", "Parallel model workers", "Actual concurrency is capped by preflight", "Probability calibration", "Hyperparameter search", "Governed defaults", "Cancel Training", "Live Training", "Candidate Leaderboard"]) {
  assert.match(modelTraining, new RegExp(term.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")), `Model Training UX missing ${term}.`);
}
for (const term of ["Best use:", "Interpretability:", "Scaling:", "Categorical:", "Probability:", "Tuning:"]) {
  assert.match(modelTraining, new RegExp(term.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")), `Model Training algorithm card missing ${term}.`);
}

for (const term of ["Recommended action", "Final holdout - reporting only", "verified selection evidence only", "cannot reorder the leaderboard", "does not derive, optimize, or recommend a threshold", "cannot affect candidate selection, feature selection, or threshold tuning"]) {
  assert.match(evaluation, new RegExp(term.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")), `Evaluation interpretation missing ${term}.`);
}

for (const sheet of ["Summary", "Field Mapping", "Actual Summary", "Actual vs Predicted", "Residual Diagnostics", "Generated Code", "Metadata", "Governance Notes", "Segment Performance", "Split Comparison", "KPI Aggregation"]) {
  assert.match(diagStore, new RegExp(sheet.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")), `Diagnostics export missing ${sheet}.`);
}
assert.match(diagnosticsLib, /exportModelDiagnostics\(format: DiagnosticsExportFormat, datasetId: string, versionId\?: string, overrides\?:/, "Diagnostics export must accept current field overrides.");
assert.match(diagRouter, /target: Optional\[str\]/, "Diagnostics export endpoint must accept target override.");
assert.match(diagRouter, /positiveClass: Optional\[str\]/, "Diagnostics export endpoint must accept positive class override.");
assert.match(diagnostics, /export created from the current field mapping and diagnostic results/, "Diagnostics export success message should confirm current mapping/result export.");

assert.match(outliers, /NONE/, "Outliers must support a None method.");
assert.match(outliers, /None — preserve observed values/, "Outliers global method list must expose None.");
assert.match(outliers, /USE_GLOBAL/, "Outliers individual method list must expose Use global method.");
assert.match(outliers, /effectiveMethod\(config\[row\.feature\], globalMethod\)/, "Variable-level None must affect full-data outlier counts.");
assert.match(outliers, /localStorage\.setItem\([\s\S]{0,120}canonicalDatasetStorageKey\(CONFIG_KEY, datasetIdentity\)/, "Outlier method selections must persist under the exact canonical dataset identity.");
assert.match(outliers, /\/outliers\/apply/, "Outlier treatments must be materialized through the backend.");

console.log("Model Diagnostics Phase 10G checks passed.");
