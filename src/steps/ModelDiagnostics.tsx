import { useEffect, useMemo, useState } from "react";
import type React from "react";
import { Link, useSearchParams } from "react-router-dom";
import { Activity, BarChart3, Code2, Download, RefreshCw, Save, Sparkles } from "lucide-react";
import BrandLogo from "../components/BrandLogo";
import { CodeExecutionResult } from "../components/code/CodeExecutionResult";
import { getDataset, getDatasetPreview, listDatasets, type DatasetPreview, type DatasetSummary, type DatasetVersionSummary } from "../lib/datasetLibrary";
import { exportModelDiagnostics, isScoredOutputDataset, runModelDiagnostics, saveModelDiagnosticInsight, type DiagnosticsExportFormat, type ModelDiagnosticsResult } from "../lib/modelDiagnostics";
import { runAnalyticsPreviewSql } from "../lib/analyticsWorkbench";
import { runUserPython, runUserR, runUserSasCompatible, type CodeRunResult } from "../lib/codeExecution";
import { createEvidence } from "../lib/evidenceGraph";
import { useWorkflowStore } from "../state/useWorkflowStore";

type DatasetDetail = DatasetSummary & { versions?: DatasetVersionSummary[]; sourceInfo?: Record<string, unknown> };
type CodeTab = "python" | "sql" | "r" | "sas";

export default function ModelDiagnostics() {
  const projectId = useWorkflowStore((state) => state.projectId);
  const [params, setParams] = useSearchParams();
  const [datasets, setDatasets] = useState<DatasetSummary[]>([]);
  const [datasetId, setDatasetId] = useState(params.get("datasetId") ?? "");
  const [dataset, setDataset] = useState<DatasetDetail | null>(null);
  const [versionId, setVersionId] = useState(params.get("versionId") ?? "");
  const [preview, setPreview] = useState<DatasetPreview>({ columns: [], rows: [] });
  const [diagnostics, setDiagnostics] = useState<ModelDiagnosticsResult | null>(null);
  const [fieldOverrides, setFieldOverrides] = useState({
    actual: "",
    prediction: "",
    score: "",
    residual: "",
    segment: "",
    positiveClass: "1",
  });
  const [codeTab, setCodeTab] = useState<CodeTab>("python");
  const [codeResult, setCodeResult] = useState<CodeRunResult | null>(null);
  const [runningCode, setRunningCode] = useState(false);
  const [message, setMessage] = useState("");
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    listDatasets()
      .then((payload) => {
        setDatasets(payload.datasets);
        const scored = payload.datasets.filter(isScoredOutputDataset);
        if (!datasetId && scored[0]) setDatasetId(scored[0].datasetId);
      })
      .catch((error) => setMessage(error instanceof Error ? error.message : "ATLAS could not load scored datasets."));
  }, []);

  useEffect(() => {
    if (!datasetId) return;
    getDataset(datasetId)
      .then((loaded) => {
        const resolved = versionId || loaded.versions?.[loaded.versions.length - 1]?.versionId || loaded.latestVersion?.versionId || "";
        setDataset(loaded);
        setVersionId(resolved);
        setParams((current) => {
          current.set("datasetId", datasetId);
          if (resolved) current.set("versionId", resolved);
          return current;
        });
      })
      .catch((error) => setMessage(error instanceof Error ? error.message : "ATLAS could not load this scored dataset."));
  }, [datasetId]);

  useEffect(() => {
    if (!datasetId || !versionId) return;
    getDatasetPreview(datasetId, versionId)
      .then(setPreview)
      .catch(() => setPreview({ columns: [], rows: [] }));
    refreshDiagnostics().catch(() => undefined);
  }, [datasetId, versionId]);

  async function refreshDiagnostics() {
    if (!datasetId) return;
    setLoading(true);
    setMessage("");
    try {
      const overrides = {
        actual: fieldOverrides.actual || undefined,
        prediction: fieldOverrides.prediction || undefined,
        score: fieldOverrides.score || undefined,
        residual: fieldOverrides.residual || undefined,
        segment: fieldOverrides.segment || undefined,
        positiveClass: fieldOverrides.positiveClass || undefined,
      };
      setDiagnostics(await runModelDiagnostics(datasetId, versionId, overrides));
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "ATLAS could not compute model diagnostics.");
    } finally {
      setLoading(false);
    }
  }

  async function saveInsight() {
    if (!diagnostics || !datasetId || !versionId) return;
    try {
      await saveModelDiagnosticInsight({
        title: `${diagnostics.dataset.name} diagnostics`,
        summary: diagnosticSummary(diagnostics),
        datasetId,
        versionId,
        projectId,
        evidence: {
          metrics: diagnostics.scoreDistribution.summary,
          columnRoles: diagnostics.columnRoles,
          liftDecile: diagnostics.liftDecile.slice(0, 10),
          residualDiagnostics: diagnostics.residualDiagnostics.summary,
        },
      });
      setMessage("Model diagnostics saved as an ATLAS insight.");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "ATLAS could not save this diagnostic insight.");
    }
  }

  async function saveCreditRiskDiagnosticEvidence(technique: "psi" | "cutoff_optimization" | "fair_lending" | "challenger_champion") {
    if (!diagnostics || !datasetId) return;
    const titles = {
      psi: "PSI Evidence",
      cutoff_optimization: "Cutoff Optimization Evidence",
      fair_lending: "Fair Lending Review Note",
      challenger_champion: "Challenger / Champion Evidence",
    };
    const summaries = {
      psi: "Population stability evidence captured from scored-output diagnostics.",
      cutoff_optimization: "Cutoff review evidence captured from score distribution, lift, and prediction band diagnostics.",
      fair_lending: "Fair Lending review note captured from model diagnostics for governance documentation.",
      challenger_champion: "Challenger/champion comparison evidence captured from diagnostics and split comparison.",
    };
    await createEvidence({
      projectId,
      projectName: "",
      evidenceType: "model_diagnostics",
      title: titles[technique],
      summary: summaries[technique],
      sourcePage: "Model Diagnostics",
      sourceRoute: `/model-diagnostics?datasetId=${encodeURIComponent(datasetId)}${versionId ? `&versionId=${encodeURIComponent(versionId)}` : ""}`,
      artifactType: "model_diagnostic_credit_risk_hook",
      artifactId: technique,
      datasetIds: [datasetId],
      tags: ["credit_risk", technique, "model_risk", technique === "fair_lending" ? "fair_lending" : ""].filter(Boolean),
      financialDomain: "credit_risk",
      financialTechnique: technique,
      regulatoryRelevance: {
        adverseAction: technique === "cutoff_optimization",
        fairLending: technique === "fair_lending" || technique === "cutoff_optimization",
        modelRisk: true,
        explainability: technique !== "psi",
        pricingDecision: technique === "cutoff_optimization",
      },
      creditRiskContext: {
        productType: "Credit Card",
        modelPurpose: "Portfolio Monitoring",
        targetEvent: diagnostics.columnRoles.actual || "Observed outcome",
        targetWindow: "Monitoring window",
      },
      supportsSections: technique === "fair_lending"
        ? ["Fair Lending / Compliance Considerations", "Model Limitations"]
        : technique === "challenger_champion"
          ? ["Candidate Models", "Champion Model", "Monitoring Recommendations"]
          : ["Model Diagnostics", "Monitoring Recommendations"],
      status: "ready",
      importance: technique === "fair_lending" ? "critical" : "high",
      payload: {
        columnRoles: diagnostics.columnRoles,
        scoreSummary: diagnostics.scoreDistribution.summary,
        liftDecile: diagnostics.liftDecile?.slice(0, 10),
        splitComparison: diagnostics.splitComparison,
        vif: diagnostics.vifAnalysis?.rows?.slice(0, 20),
      },
      governance: {
        note: "Saved through Model Diagnostics credit-risk evidence hooks.",
      },
    });
    setMessage(`${titles[technique]} saved to the Model Evidence Center.`);
  }

  async function downloadExport(format: DiagnosticsExportFormat) {
    if (!datasetId) return;
    try {
      const { blob, filename } = await exportModelDiagnostics(format, datasetId, versionId, {
        actual: fieldOverrides.actual || undefined,
        prediction: fieldOverrides.prediction || undefined,
        score: fieldOverrides.score || undefined,
        residual: fieldOverrides.residual || undefined,
        segment: fieldOverrides.segment || undefined,
        positiveClass: fieldOverrides.positiveClass || undefined,
      });
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = filename;
      link.click();
      URL.revokeObjectURL(url);
      setMessage(`Model diagnostics ${format} export created from the current field mapping and diagnostic results.`);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "ATLAS could not export model diagnostics.");
    }
  }

  async function runCode() {
    if (!diagnostics) return;
    const code = diagnostics.generatedCode[codeTab];
    setRunningCode(true);
    try {
      if (codeTab === "python") {
        setCodeResult(await runUserPython({ code, projectId, workflowStep: "model-diagnostics", context: { previewRows: preview.rows, datasetName: dataset?.name } }));
      } else if (codeTab === "sql") {
        setCodeResult(await runAnalyticsPreviewSql({ sql: code, datasetName: dataset?.name || "scored_output", versionId, previewRows: preview.rows }));
      } else if (codeTab === "r") {
        setCodeResult(await runUserR({ code, context: { previewRows: preview.rows, datasetName: dataset?.name } }));
      } else {
        setCodeResult(await runUserSasCompatible({ code, context: { previewRows: preview.rows, datasetName: dataset?.name } }));
      }
    } catch (error) {
      setCodeResult({ ok: false, status: "error", stdout: "", stderr: error instanceof Error ? error.message : "Code execution failed.", runtimeMs: 0 });
    } finally {
      setRunningCode(false);
    }
  }

  const scoredDatasets = useMemo(() => datasets.filter(isScoredOutputDataset), [datasets]);
  const generatedCode = diagnostics?.generatedCode?.[codeTab] ?? "";
  const isRegressionScoredOutput = isRegressionDiagnostics(diagnostics, dataset);

  return (
    <div className="atlas-page-shell atlas-theme-diagnostics">
      <section className="atlas-studio-hero">
        <div className="atlas-studio-hero__band">
        <BrandLogo size="md" variant="dark" showSubtitle className="mb-3" />
        <div className="flex flex-col gap-4 xl:flex-row xl:items-end xl:justify-between">
          <div>
            <div className="flex items-center gap-2">
              <Activity size={22} className="text-orange-200" />
              <h1 className="text-2xl font-semibold text-white">Model Diagnostics</h1>
            </div>
            <p className="mt-2 max-w-4xl text-sm leading-6 text-orange-50/90">
              Review registered scored outputs with lift, calibration, residual, score distribution, and segment diagnostics before reporting or monitoring.
            </p>
          </div>
          <div className="grid gap-2 md:grid-cols-4 xl:min-w-[680px]">
            <Metric label="Rows reviewed" value={diagnostics?.rowCount?.toLocaleString() ?? "-"} />
            <Metric label="Mode" value={modeLabel(diagnostics?.diagnosticMode)} />
            <Metric label="Prediction column" value={diagnostics?.columnRoles.prediction || diagnostics?.columnRoles.score || "-"} />
            <Metric label="Actual column" value={diagnostics?.columnRoles.actual || "-"} />
            <Metric label="Status" value={diagnostics ? "Ready" : loading ? "Running" : "Select scored output"} />
          </div>
        </div>
        </div>
        {message && <div className="mx-5 my-4 rounded-lg border border-blue-200 bg-blue-50 px-3 py-2 text-sm text-blue-900">{message}</div>}
      </section>

      <section className="grid gap-4 xl:grid-cols-[320px_minmax(0,1fr)]">
        <aside className="space-y-4">
          <Panel title="Scored Dataset" icon={<DatabaseIcon />}>
            <label className="grid gap-1 text-xs font-semibold uppercase text-slate-500">
              Dataset
              <select className="rounded-lg border border-slate-300 px-3 py-2 text-sm font-normal normal-case text-slate-900" value={datasetId} onChange={(event) => { setDatasetId(event.target.value); setVersionId(""); }}>
                <option value="">Select scored output...</option>
                {scoredDatasets.map((item) => <option key={item.datasetId} value={item.datasetId}>{item.name}</option>)}
              </select>
            </label>
            <label className="mt-3 grid gap-1 text-xs font-semibold uppercase text-slate-500">
              Version
              <select className="rounded-lg border border-slate-300 px-3 py-2 text-sm font-normal normal-case text-slate-900" value={versionId} onChange={(event) => setVersionId(event.target.value)}>
                {(dataset?.versions ?? []).map((version) => <option key={version.versionId} value={version.versionId}>{version.versionId}</option>)}
              </select>
            </label>
            <button type="button" onClick={refreshDiagnostics} className="mt-3 inline-flex w-full items-center justify-center gap-2 rounded-lg bg-slate-950 px-3 py-2 text-sm font-semibold text-white" disabled={!datasetId || loading}>
              <RefreshCw size={15} className={loading ? "animate-spin" : ""} />
              Run Diagnostics
            </button>
            {!scoredDatasets.length && (
              <div className="mt-3 rounded-lg border border-amber-200 bg-amber-50 p-3 text-xs leading-5 text-amber-900">
                <div className="font-semibold">No scored-output datasets found.</div>
                <div>Register scored output from the Predictive Modeling Scoring step.</div>
                <div className="mt-3 flex flex-wrap gap-2">
                  <Link className="rounded-md bg-slate-950 px-3 py-2 text-xs font-semibold text-white" to="/step10">Go to Scoring</Link>
                  <Link className="rounded-md border border-amber-300 bg-white px-3 py-2 text-xs font-semibold text-amber-950" to="/datasets">Open Dataset Library</Link>
                </div>
              </div>
            )}
          </Panel>
          <Panel title="Actions" icon={<Download size={17} />}>
            <div className="grid gap-2">
              <button type="button" className="atlas-secondary-button" onClick={saveInsight} disabled={!diagnostics}><Save size={15} /> Save Diagnostics as Insight</button>
              <button
                type="button"
                className="atlas-secondary-button"
                onClick={async () => {
                  await refreshDiagnostics();
                  setMessage("Scored dataset diagnostics fields refreshed. ATLAS re-read the scored rows, field mapping, residual calculations, and available actual/prediction diagnostics.");
                }}
                disabled={!datasetId || loading}
              >
                <RefreshCw size={15} /> Refresh Diagnostics Fields
              </button>
              <button
                type="button"
                className="atlas-secondary-button"
                onClick={() => setMessage("ATLAS cannot rebuild this scored dataset because the original scoring input rows are not available. Re-run scoring and register the full scored output.")}
                disabled={!datasetId}
              >
                Re-register Full Scored Dataset
              </button>
              <button type="button" className="atlas-secondary-button" onClick={() => downloadExport("excel")} disabled={!diagnostics}>Export to Excel</button>
              <button type="button" className="atlas-secondary-button" onClick={() => downloadExport("word")} disabled={!diagnostics}>Export to Word</button>
              <button type="button" className="atlas-secondary-button" onClick={() => downloadExport("powerpoint")} disabled={!diagnostics}>Export to PowerPoint</button>
              <Link to={`/chart-studio${datasetId ? `?datasetId=${datasetId}` : ""}`} className="atlas-secondary-button">Open in Chart Studio</Link>
              <Link to="/model-document-studio" className="atlas-secondary-button">Add Diagnostic to Model Documentation</Link>
            </div>
          </Panel>
          <Panel title="Credit Risk Evidence Hooks" icon={<Sparkles size={17} />}>
            <p className="text-xs leading-5 text-slate-600">Save governed credit-risk evidence directly from diagnostics. These hooks feed Model Evidence Center, Model Documentation Studio, and monitoring documentation.</p>
            <div className="mt-2 grid gap-2">
              <button type="button" className="atlas-secondary-button" onClick={() => saveCreditRiskDiagnosticEvidence("psi")} disabled={!diagnostics}>Save PSI Evidence</button>
              <button type="button" className="atlas-secondary-button" onClick={() => saveCreditRiskDiagnosticEvidence("cutoff_optimization")} disabled={!diagnostics}>Save Cutoff Evidence</button>
              <button type="button" className="atlas-secondary-button" onClick={() => saveCreditRiskDiagnosticEvidence("fair_lending")} disabled={!diagnostics}>Save Fair Lending Review Note</button>
              <button type="button" className="atlas-secondary-button" onClick={() => saveCreditRiskDiagnosticEvidence("challenger_champion")} disabled={!diagnostics}>Save Challenger/Champion Evidence</button>
            </div>
          </Panel>
          <Panel title="Field Mapping" icon={<Activity size={17} />}>
            <FieldMappingControls
              columns={preview.columns}
              values={fieldOverrides}
              inferred={diagnostics?.columnRoles}
              onChange={setFieldOverrides}
              onApply={refreshDiagnostics}
              disabled={!datasetId || loading}
            />
          </Panel>
        </aside>

        <main className="space-y-5">
          {diagnostics ? (
            <>
              <section className="rounded-xl border border-emerald-200 bg-emerald-50 p-5 shadow-sm">
                <div className="flex items-start gap-3">
                  <Sparkles size={19} className="mt-0.5 text-emerald-700" />
                  <div>
                    <div className="text-xs font-semibold uppercase tracking-wide text-emerald-800">ATLAS diagnostics readout</div>
                    <p className="mt-2 text-sm leading-6 text-emerald-950">{diagnosticSummary(diagnostics)}</p>
                    <p className="mt-2 text-xs leading-5 text-emerald-900">{diagnostics.limitations}</p>
                  </div>
                </div>
              </section>

              {(diagnostics.mappingWarnings?.length || diagnostics.predictionSummary?.warnings?.length) ? (
                <section className="rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-950 shadow-sm">
                  <div className="font-semibold">Field Mapping and Prediction Quality Warnings</div>
                  <ul className="mt-2 list-disc space-y-1 pl-5 leading-6">
                    {[...(diagnostics.mappingWarnings ?? []), ...(diagnostics.predictionSummary?.warnings ?? [])].map((warning, index) => (
                      <li key={`${warning}-${index}`}>{warning}</li>
                    ))}
                  </ul>
                </section>
              ) : null}

              <section className="grid gap-4 xl:grid-cols-[1fr_0.9fr]">
                <Panel title="Predicted Value Summary" icon={<Activity size={17} />}>
                  <MetricGrid summary={diagnostics.predictionSummary?.summary ?? {}} />
                </Panel>
                <Panel title="Regression Fit Summary" icon={<Activity size={17} />}>
                  {diagnostics.regressionFitSummary?.available
                    ? <MetricGrid summary={diagnostics.regressionFitSummary.summary ?? {}} />
                    : <GuidancePanel message={diagnostics.regressionFitSummary?.warning || "Regression fit summary requires separate actual and prediction columns."} />}
                </Panel>
              </section>

              <section className="grid gap-4 xl:grid-cols-2">
                <Panel title={isRegressionScoredOutput ? "Prediction Distribution" : "Score Distribution"} icon={<BarChart3 size={17} />}>
                  <Histogram bins={diagnostics.scoreDistribution.bins} />
                </Panel>
                <Panel title="Actual Distribution" icon={<BarChart3 size={17} />}>
                  <Histogram bins={diagnostics.actualDistribution?.bins ?? []} />
                </Panel>
                <Panel title="Actual vs Predicted" icon={<BarChart3 size={17} />}>
                  <ScatterPlot points={diagnostics.actualVsPredicted.points} />
                </Panel>
                {isRegressionScoredOutput ? (
                  <Panel title="Classification Diagnostics Note" icon={<Activity size={17} />}>
                    <GuidancePanel message="Lift/Decile and Calibration require a binary outcome and probability score. This scored output appears to be regression, so ATLAS is showing regression diagnostics instead." />
                  </Panel>
                ) : (
                  <Panel title="Calibration" icon={<BarChart3 size={17} />}>
                    <CalibrationPlot rows={diagnostics.calibration} />
                  </Panel>
                )}
              </section>

              {!isRegressionScoredOutput && (
                <section className="grid gap-4">
                  <Panel title="Classification Summary Metrics" icon={<Activity size={17} />}>
                    {(diagnostics.classificationMetrics?.available === false)
                      ? <GuidancePanel message={String(diagnostics.classificationMetrics?.warning ?? "AUC/KS/Gini require binary actual outcome and score/probability.")} />
                      : <MetricGrid summary={diagnostics.classificationMetrics ?? {}} />}
                  </Panel>
                  <Panel title="Detailed Classification Lift Table" icon={<BarChart3 size={17} />}>
                    <SimpleTable rows={diagnostics.detailedLiftTable ?? []} empty="AUC/KS/Gini and detailed lift require binary actual outcome and score/probability." />
                  </Panel>
                </section>
              )}

              <section className="grid gap-4 xl:grid-cols-2">
                <Panel title="Top 10 Highest Predictions" icon={<Activity size={17} />}>
                  <SimpleTable rows={diagnostics.topPredictions ?? []} empty="No prediction column is available for ranking." />
                </Panel>
                <Panel title="Bottom 10 Lowest Predictions" icon={<Activity size={17} />}>
                  <SimpleTable rows={diagnostics.bottomPredictions ?? []} empty="No prediction column is available for ranking." />
                </Panel>
                <Panel title="Largest Absolute Errors" icon={<Activity size={17} />}>
                  <SimpleTable rows={diagnostics.largestAbsoluteErrors ?? []} empty="Actual and prediction columns are required to rank residual errors." />
                </Panel>
                <Panel title="Top Overpredictions" icon={<Activity size={17} />}>
                  <SimpleTable rows={diagnostics.topOverpredictions ?? []} empty="No overprediction rows were detected or actual/prediction mapping is incomplete." />
                </Panel>
                <Panel title="Top Underpredictions" icon={<Activity size={17} />}>
                  <SimpleTable rows={diagnostics.topUnderpredictions ?? []} empty="No underprediction rows were detected or actual/prediction mapping is incomplete." />
                </Panel>
                <Panel title="Prediction Band Summary" icon={<BarChart3 size={17} />}>
                  <SimpleTable rows={diagnostics.predictionBandSummary ?? []} empty="Prediction bands require a numeric prediction column." />
                </Panel>
              </section>

              <section className="grid gap-4 xl:grid-cols-[1fr_0.9fr]">
                <Panel title="Residual Diagnostics" icon={<Activity size={17} />}>
                  <div className="grid gap-2 md:grid-cols-5">
                    {Object.entries(diagnostics.residualDiagnostics.summary ?? {}).map(([key, value]) => <Metric key={key} label={key} value={format(value)} />)}
                  </div>
                  <Histogram bins={diagnostics.residualDiagnostics.histogram ?? []} />
                </Panel>
                <Panel title="Segment Performance" icon={<Activity size={17} />}>
                  <SimpleTable rows={diagnostics.segmentPerformance} empty="No low-cardinality segment column was detected." />
                </Panel>
              </section>

              <section>
                <Panel title="Scored Split Comparison" icon={<Activity size={17} />}>
                  <SimpleTable rows={diagnostics.splitComparison ?? []} empty="No related TRAIN, TEST, or OOT scored outputs were found for this model." />
                </Panel>
              </section>

              <section className="grid gap-4 xl:grid-cols-2">
                <Panel title="Population Waterfall" icon={<Activity size={17} />}>
                  <SimpleTable rows={diagnostics.populationWaterfall ?? []} empty="No population waterfall metadata is available yet." />
                </Panel>
                <Panel title="KPI Aggregation" icon={<Activity size={17} />}>
                  <SimpleTable rows={diagnostics.kpiAggregation?.rows ?? []} empty="No KPI aggregation rows are available." />
                  {diagnostics.kpiAggregation?.recommendation && <p className="mt-3 rounded-lg bg-blue-50 p-3 text-xs leading-5 text-blue-900">{diagnostics.kpiAggregation.recommendation}</p>}
                </Panel>
                <Panel title="VIF / Multicollinearity Analysis" icon={<Activity size={17} />}>
                  <div className="mb-3 rounded-lg bg-slate-50 p-3 text-sm font-semibold text-slate-800">{diagnostics.vifAnalysis?.formula ?? "VIF_j = 1 / (1 - R_j^2)"}</div>
                  <p className="mb-3 text-xs leading-5 text-slate-600">R_j^2 is from regressing predictor X_j on the other predictors. ATLAS recommends review, not automatic removal.</p>
                  <SimpleTable rows={diagnostics.vifAnalysis?.rows ?? []} empty={diagnostics.vifAnalysis?.warning ?? "VIF requires at least two numeric predictors with sufficient non-missing rows."} />
                </Panel>
                <Panel title="Pozzolo Prior Correction / Undersampling Calibration" icon={<Activity size={17} />}>
                  <div className="rounded-lg bg-slate-50 p-3 text-xs font-semibold leading-5 text-slate-800">
                    {String(diagnostics.pozzoloCalibration?.equation ?? "alpha = [pi / (1 - pi)] / [pi_s / (1 - pi_s)]; p_corrected = (alpha * p_s) / (1 - p_s + alpha * p_s)")}
                  </div>
                  <p className="mt-3 text-xs leading-5 text-slate-600">Pozzolo correction applies to classification probability calibration after sampling changes class priors. It does not apply to regression predictions.</p>
                  <MetricGrid summary={diagnostics.pozzoloCalibration ?? {}} />
                </Panel>
              </section>

              <section className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
                <div className="flex items-center justify-between gap-3">
                  <div className="flex items-center gap-2">
                    <Code2 size={18} className="text-blue-700" />
                    <h2 className="text-base font-semibold text-slate-950">Generated Diagnostics Code</h2>
                  </div>
                  <button type="button" className="atlas-secondary-button" onClick={runCode} disabled={runningCode || !generatedCode}>
                    {runningCode ? "Running..." : `Run ${codeTab.toUpperCase()}`}
                  </button>
                </div>
                <div className="mt-3 flex flex-wrap gap-2">
                  {(["python", "sql", "r", "sas"] as CodeTab[]).map((tab) => (
                    <button key={tab} type="button" onClick={() => setCodeTab(tab)} className={`rounded-lg border px-3 py-1.5 text-xs font-semibold ${codeTab === tab ? "border-blue-300 bg-blue-50 text-blue-800" : "border-slate-200 bg-white text-slate-600"}`}>{tab === "sas" ? "SAS-compatible" : tab.toUpperCase()}</button>
                  ))}
                </div>
                <pre className="mt-3 max-h-[260px] overflow-auto rounded-xl bg-slate-950 p-4 text-xs leading-5 text-slate-50">{generatedCode}</pre>
                {codeResult && <div className="mt-4"><CodeExecutionResult result={codeResult} /></div>}
              </section>
            </>
          ) : (
            <section className="rounded-xl border border-dashed border-slate-300 bg-white/80 p-10 text-center shadow-sm">
              <Activity size={40} className="mx-auto text-blue-700" />
              <h2 className="mt-3 text-lg font-semibold text-slate-950">Select a scored output to begin diagnostics</h2>
              <p className="mx-auto mt-2 max-w-2xl text-sm leading-6 text-slate-600">
                Scored outputs are created from the Predictive Modeling Scoring page and registered as governed Dataset Library assets.
              </p>
              {!scoredDatasets.length && (
                <div className="mt-5 flex justify-center gap-3">
                  <Link className="rounded-lg bg-slate-950 px-4 py-2 text-sm font-semibold text-white" to="/step10">Go to Scoring</Link>
                  <Link className="rounded-lg border border-slate-300 bg-white px-4 py-2 text-sm font-semibold text-slate-800" to="/datasets">Open Dataset Library</Link>
                </div>
              )}
            </section>
          )}
        </main>
      </section>
    </div>
  );
}

function diagnosticSummary(result: ModelDiagnosticsResult) {
  const scoreMean = result.scoreDistribution.summary?.mean;
  const bestLift = result.liftDecile?.[0]?.lift;
  const residual = result.residualDiagnostics.summary?.mae;
  const task = String(result.dataset.sourceInfo?.task ?? "").toLowerCase();
  const scoreLabel = task === "regression" ? "Mean prediction" : "Mean score";
  return `ATLAS reviewed ${result.rowCount.toLocaleString()} scored row(s). ${scoreLabel} is ${format(scoreMean)}${bestLift ? ` and top-decile lift is ${format(bestLift)}` : ""}${residual ? ` with mean absolute residual ${format(residual)}` : ""}. Review diagnostics before promoting this output into monitoring.`;
}

function isRegressionDiagnostics(result: ModelDiagnosticsResult | null, dataset: DatasetDetail | null) {
  if (result?.diagnosticMode === "regression") return true;
  const sourceInfo = (result?.dataset.sourceInfo ?? dataset?.sourceInfo ?? {}) as Record<string, unknown>;
  return String(sourceInfo.task ?? "").toLowerCase() === "regression" || Boolean(sourceInfo.columnRoles && typeof sourceInfo.columnRoles === "object" && "residual" in sourceInfo.columnRoles);
}

function FieldMappingControls({
  columns,
  values,
  inferred,
  onChange,
  onApply,
  disabled,
}: {
  columns: string[];
  values: { actual: string; prediction: string; score: string; residual: string; segment: string; positiveClass: string };
  inferred?: ModelDiagnosticsResult["columnRoles"];
  onChange: (values: { actual: string; prediction: string; score: string; residual: string; segment: string; positiveClass: string }) => void;
  onApply: () => void;
  disabled?: boolean;
}) {
  const update = (key: keyof typeof values, value: string) => onChange({ ...values, [key]: value });
  return (
    <div className="space-y-3">
      <p className="text-xs leading-5 text-slate-600">Override detected roles when a scored dataset uses project-specific target or prediction column names. Numeric segment columns with many distinct values are binned into quantiles for segment diagnostics.</p>
      <MappingSelect label="Actual column" value={values.actual} inferred={inferred?.actual} columns={columns} onChange={(value) => update("actual", value)} />
      <MappingSelect label="Prediction column" value={values.prediction} inferred={inferred?.prediction} columns={columns} onChange={(value) => update("prediction", value)} />
      <MappingSelect label="Score/probability column" value={values.score} inferred={inferred?.score} columns={columns} onChange={(value) => update("score", value)} />
      <MappingSelect label="Residual column" value={values.residual} inferred={inferred?.residual} columns={columns} onChange={(value) => update("residual", value)} />
      <MappingSelect label="Segment column" value={values.segment} inferred={inferred?.segment} columns={columns} onChange={(value) => update("segment", value)} />
      <label className="grid gap-1 text-xs font-semibold uppercase text-slate-500">
        Positive class value
        <input className="rounded-lg border border-slate-300 px-3 py-2 text-sm font-normal normal-case text-slate-900" value={values.positiveClass} onChange={(event) => update("positiveClass", event.target.value)} />
      </label>
      <button type="button" className="atlas-secondary-button w-full justify-center" onClick={onApply} disabled={disabled}>Apply Field Mapping</button>
    </div>
  );
}

function MappingSelect({ label, value, inferred, columns, onChange }: { label: string; value: string; inferred?: string | null; columns: string[]; onChange: (value: string) => void }) {
  return (
    <label className="grid gap-1 text-xs font-semibold uppercase text-slate-500">
      {label}
      <select className="rounded-lg border border-slate-300 px-3 py-2 text-sm font-normal normal-case text-slate-900" value={value} onChange={(event) => onChange(event.target.value)}>
        <option value="">{inferred ? `Auto: ${inferred}` : "Auto detect"}</option>
        {columns.map((column) => <option key={column} value={column}>{column}</option>)}
      </select>
    </label>
  );
}

function GuidancePanel({ message }: { message: string }) {
  return <div className="flex h-[220px] items-center justify-center rounded-lg border border-dashed border-slate-300 bg-slate-50 p-5 text-center text-sm leading-6 text-slate-600">{message}</div>;
}

function Panel({ title, icon, children }: { title: string; icon?: React.ReactNode; children: React.ReactNode }) {
  return (
    <section className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
      <div className="mb-3 flex items-center gap-2">
        {icon}
        <h2 className="text-sm font-semibold text-slate-950">{title}</h2>
      </div>
      {children}
    </section>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2">
      <div className="text-[10px] font-semibold uppercase tracking-wide text-slate-500">{label}</div>
      <div className="mt-1 truncate text-sm font-semibold text-slate-950" title={value}>{value}</div>
    </div>
  );
}

function MetricGrid({ summary }: { summary: Record<string, unknown> }) {
  const entries = Object.entries(summary);
  if (!entries.length) return <div className="rounded-lg bg-slate-50 p-6 text-center text-sm text-slate-500">No summary metrics available.</div>;
  return <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">{entries.map(([key, value]) => <Metric key={key} label={humanize(key)} value={format(value)} />)}</div>;
}

function Histogram({ bins }: { bins: Array<{ bin: string; count: number }> }) {
  if (!bins.length) return <div className="flex h-[180px] items-center justify-center rounded-lg bg-slate-50 text-sm text-slate-500">No distribution data available.</div>;
  const max = Math.max(...bins.map((bin) => bin.count), 1);
  return <div className="flex h-[220px] items-end gap-1 rounded-xl bg-slate-50 p-3">{bins.map((bin, index) => <div key={`${bin.bin}-${index}`} className="flex flex-1 flex-col items-center gap-1"><div className="w-full rounded-t bg-blue-600" style={{ height: `${Math.max(4, (bin.count / max) * 180)}px` }} title={`${bin.bin}: ${bin.count}`} /><span className="w-full truncate text-center text-[9px] text-slate-500">{index + 1}</span></div>)}</div>;
}

function LiftBars({ rows }: { rows: ModelDiagnosticsResult["liftDecile"] }) {
  if (!rows.length) return <div className="flex h-[220px] items-center justify-center rounded-lg bg-slate-50 text-sm text-slate-500">Lift requires score and actual columns.</div>;
  const max = Math.max(...rows.map((row) => Number(row.lift) || 0), 1);
  return <div className="space-y-2">{rows.map((row) => <div key={row.decile} className="grid grid-cols-[70px_minmax(0,1fr)_70px] items-center gap-2 text-xs"><div className="font-semibold">D{row.decile}</div><div className="h-3 rounded-full bg-slate-100"><div className="h-full rounded-full bg-emerald-600" style={{ width: `${Math.max(2, ((row.lift ?? 0) / max) * 100)}%` }} /></div><div className="text-right font-semibold">{format(row.lift)}</div></div>)}</div>;
}

function CalibrationPlot({ rows }: { rows: ModelDiagnosticsResult["calibration"] }) {
  if (!rows.length) return <div className="flex h-[220px] items-center justify-center rounded-lg bg-slate-50 text-sm text-slate-500">Calibration requires score and actual columns.</div>;
  return <div className="space-y-2">{rows.map((row) => <div key={row.bin} className="grid grid-cols-[54px_1fr_1fr] gap-2 text-xs"><div className="font-semibold">B{row.bin}</div><div><div className="mb-1 text-slate-500">Score {format(row.meanScore)}</div><div className="h-2 rounded-full bg-blue-100"><div className="h-full rounded-full bg-blue-600" style={{ width: `${Math.min(100, Math.max(2, (row.meanScore ?? 0) * 100))}%` }} /></div></div><div><div className="mb-1 text-slate-500">Actual {format(row.actualRate)}</div><div className="h-2 rounded-full bg-emerald-100"><div className="h-full rounded-full bg-emerald-600" style={{ width: `${Math.min(100, Math.max(2, (row.actualRate ?? 0) * 100))}%` }} /></div></div></div>)}</div>;
}

function ScatterPlot({ points }: { points: Array<{ actual: number | null; predicted: number | null }> }) {
  const usable = points.filter((point) => point.actual != null && point.predicted != null).slice(0, 180);
  if (!usable.length) return <div className="flex h-[220px] items-center justify-center rounded-lg bg-slate-50 text-sm text-slate-500">Actual vs predicted requires actual and prediction columns.</div>;
  const values = usable.flatMap((point) => [point.actual as number, point.predicted as number]);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const scale = (value: number, size: number) => ((value - min) / (max - min || 1)) * size;
  return <svg viewBox="0 0 420 220" className="h-[220px] w-full rounded-xl bg-slate-50"><line x1="40" y1="180" x2="390" y2="20" stroke="#94a3b8" strokeDasharray="4 4" />{usable.map((point, index) => <circle key={index} cx={40 + scale(point.predicted as number, 350)} cy={180 - scale(point.actual as number, 160)} r="3" fill="#2563eb" opacity="0.65" />)}<text x="210" y="210" textAnchor="middle" className="fill-slate-600 text-[11px]">Predicted</text><text x="12" y="110" textAnchor="middle" transform="rotate(-90 12 110)" className="fill-slate-600 text-[11px]">Actual</text></svg>;
}

function SimpleTable({ rows, empty }: { rows: Array<Record<string, unknown>>; empty: string }) {
  if (!rows.length) return <div className="rounded-lg bg-slate-50 p-6 text-center text-sm text-slate-500">{empty}</div>;
  const columns = Object.keys(rows[0]);
  return <div className="max-h-[320px] overflow-auto rounded-lg border border-slate-200"><table className="min-w-full text-xs"><thead className="sticky top-0 bg-slate-50 text-slate-500"><tr>{columns.map((column) => <th key={column} className="px-3 py-2 text-left">{column}</th>)}</tr></thead><tbody>{rows.map((row, index) => <tr key={index} className="border-t">{columns.map((column) => <td key={column} className="px-3 py-2">{String(row[column] ?? "-")}</td>)}</tr>)}</tbody></table></div>;
}

function format(value: unknown) {
  if (typeof value === "number" && Number.isFinite(value)) return Math.abs(value) >= 1000 ? value.toLocaleString(undefined, { maximumFractionDigits: 2 }) : value.toFixed(4);
  if (typeof value === "boolean") return value ? "Yes" : "No";
  if (typeof value === "string" && value.trim()) return value;
  return "-";
}

function humanize(value: string) {
  return value.replace(/([A-Z])/g, " $1").replace(/_/g, " ").replace(/\s+/g, " ").trim();
}

function modeLabel(mode?: string) {
  if (!mode) return "-";
  if (mode === "prediction_only") return "Prediction only";
  return humanize(mode);
}

function DatabaseIcon() {
  return <BarChart3 size={17} />;
}
