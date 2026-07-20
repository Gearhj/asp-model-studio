import { useMemo } from "react";
import { useNavigate } from "react-router-dom";
import StepShell from "../../components/StepShell";
import { getWorkflowDefinition } from "../../config/workflows";
import { saveActiveProjectBeforeNavigation } from "../../lib/localProjects";
import { useWorkflowStore } from "../../state/useWorkflowStore";
import { getTimeSeriesPageByStep } from "./timeSeriesDemoData";
import type { TimeSeriesPageDefinition, TimeSeriesPageKey } from "./timeSeriesTypes";

type Props = {
  pageKey?: TimeSeriesPageKey;
};

const badgeClass = {
  good: "border-emerald-200 bg-emerald-50 text-emerald-900",
  warn: "border-amber-200 bg-amber-50 text-amber-900",
  info: "border-blue-200 bg-blue-50 text-blue-900",
} as const;

function StatGrid({ page }: { page: TimeSeriesPageDefinition }) {
  return (
    <div className="grid gap-3 md:grid-cols-4">
      {page.stats.map(([label, value, tone]) => (
        <div key={label} className={`rounded-xl border px-4 py-3 ${badgeClass[tone]}`}>
          <div className="text-[11px] font-semibold uppercase tracking-wide opacity-70">{label}</div>
          <div className="mt-1 text-xl font-semibold">{value}</div>
        </div>
      ))}
    </div>
  );
}

function PanelGrid({ page }: { page: TimeSeriesPageDefinition }) {
  return (
    <div className="grid gap-4 lg:grid-cols-3">
      {page.panels.map((panel) => (
        <section key={panel.title} className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
          <h3 className="text-base font-semibold text-slate-950">{panel.title}</h3>
          <p className="mt-2 text-sm leading-6 text-slate-600">{panel.body}</p>
          <div className="mt-4 flex flex-wrap gap-2">
            {panel.items.map((item) => (
              <span key={item} className="rounded-full border border-slate-200 bg-slate-50 px-3 py-1 text-xs font-medium text-slate-700">
                {item}
              </span>
            ))}
          </div>
        </section>
      ))}
    </div>
  );
}

function CodePanel({ page }: { page: TimeSeriesPageDefinition }) {
  return (
    <section className="rounded-2xl border border-slate-200 bg-slate-950 p-5 text-slate-100 shadow-sm">
      <div className="text-xs font-semibold uppercase tracking-wide text-cyan-200">Code & Reproducibility</div>
      <pre className="mt-3 overflow-auto rounded-xl bg-black/25 p-4 text-xs leading-6 text-slate-100">
        <code>{page.code.join("\n")}</code>
      </pre>
    </section>
  );
}

function LineChartMock({ title, fan = false }: { title: string; fan?: boolean }) {
  const points = [28, 38, 34, 47, 52, 49, 62, 68, 65, 76, 82, 88];
  return (
    <section className="rounded-2xl border border-blue-200 bg-white p-5 shadow-sm">
      <div className="flex items-center justify-between">
        <h3 className="text-base font-semibold text-slate-950">{title}</h3>
        <span className="rounded-full bg-blue-50 px-3 py-1 text-xs font-semibold text-blue-700">interactive preview</span>
      </div>
      <div className="mt-5 h-64 rounded-xl bg-gradient-to-b from-blue-50 to-white p-4">
        <div className="relative h-full">
          {fan ? <div className="absolute right-0 top-6 h-40 w-1/3 rounded-xl bg-cyan-100/70" /> : null}
          <svg viewBox="0 0 360 180" className="h-full w-full">
            <polyline
              fill="none"
              stroke="#2563eb"
              strokeWidth="4"
              points={points.map((point, index) => `${index * 32 + 4},${170 - point * 1.5}`).join(" ")}
            />
            {points.map((point, index) => (
              <circle key={index} cx={index * 32 + 4} cy={170 - point * 1.5} r="4" fill="#0f766e" />
            ))}
          </svg>
        </div>
      </div>
    </section>
  );
}

function Heatmap({ title }: { title: string }) {
  return (
    <section className="rounded-2xl border border-emerald-200 bg-emerald-50 p-5 shadow-sm">
      <h3 className="text-base font-semibold text-slate-950">{title}</h3>
      <div className="mt-4 grid grid-cols-8 gap-1">
        {Array.from({ length: 48 }).map((_, index) => (
          <div
            key={index}
            className="h-8 rounded-md"
            style={{ backgroundColor: `rgba(13, 148, 136, ${0.18 + (index % 7) * 0.1})` }}
            title={`period ${index + 1}`}
          />
        ))}
      </div>
    </section>
  );
}

function Timeline() {
  return (
    <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
      <h3 className="text-base font-semibold text-slate-950">Rolling-origin timeline</h3>
      <div className="mt-5 space-y-3">
        {["Fold 1", "Fold 2", "Fold 3", "Fold 4", "Fold 5", "Fold 6"].map((fold, index) => (
          <div key={fold} className="grid grid-cols-[80px_1fr] items-center gap-3">
            <div className="text-xs font-semibold text-slate-600">{fold}</div>
            <div className="flex h-7 overflow-hidden rounded-full bg-slate-100">
              <div className="bg-slate-800" style={{ width: `${40 + index * 6}%` }} />
              <div className="w-5 bg-amber-300" />
              <div className="w-20 bg-blue-500" />
              <div className="w-12 bg-emerald-500" />
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}

function TableCard({ title, columns, rows }: { title: string; columns: string[]; rows: string[][] }) {
  return (
    <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
      <h3 className="text-base font-semibold text-slate-950">{title}</h3>
      <div className="mt-4 overflow-hidden rounded-xl border border-slate-200">
        <table className="w-full text-left text-sm">
          <thead className="bg-slate-50 text-xs uppercase tracking-wide text-slate-500">
            <tr>{columns.map((column) => <th key={column} className="px-3 py-2">{column}</th>)}</tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {rows.map((row) => (
              <tr key={row.join("-")} className="hover:bg-blue-50/50">
                {row.map((cell) => <td key={cell} className="px-3 py-2 text-slate-700">{cell}</td>)}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function TimeSeriesVisualCenter({ page }: { page: TimeSeriesPageDefinition }) {
  switch (page.layout) {
    case "profile":
      return (
        <div className="grid gap-4 xl:grid-cols-[1.5fr_1fr]">
          <LineChartMock title="Target over time with rolling mean and anomaly markers" />
          <Heatmap title="Seasonality and lag signal" />
        </div>
      );
    case "feature-builder":
      return (
        <div className="grid gap-4 xl:grid-cols-[1fr_1fr]">
          <Heatmap title="Lag correlation heatmap" />
          <TableCard title="Future-known driver gate" columns={["Feature", "Known at forecast time", "Action"]} rows={[["promo_flag", "Yes", "Allow"], ["future_balance", "No", "Block"], ["holiday", "Yes", "Allow"]]} />
        </div>
      );
    case "timeline":
      return <Timeline />;
    case "model-cards":
      return (
        <div className="grid gap-4 md:grid-cols-2">
          {["Naive baseline", "Seasonal naive", "Exponential smoothing", "ARIMA/SARIMA-style template", "Gradient boosting with lag features", "Anomaly detection baseline"].map((model) => (
            <section key={model} className="rounded-2xl border border-blue-200 bg-blue-50 p-5 shadow-sm">
              <div className="text-base font-semibold text-slate-950">{model}</div>
              <p className="mt-2 text-sm text-slate-600">Best used when its assumptions match the history length, seasonality, and interpretability requirements.</p>
            </section>
          ))}
        </div>
      );
    case "run-results":
      return (
        <div className="space-y-4">
          <div className="rounded-2xl border border-amber-200 bg-amber-50 p-4 text-sm font-semibold text-amber-900">Backtest preview mode - backend execution has not been connected for this local run.</div>
          <TableCard title="Fold table - fold-by-fold metrics" columns={["Model", "Fold", "WAPE", "Bias", "Coverage"]} rows={[["Seasonal naive", "1", "8.2%", "-1.1%", "90%"], ["ETS", "2", "7.6%", "0.4%", "91%"], ["Lag boosting", "3", "6.9%", "0.8%", "88%"]]} />
        </div>
      );
    case "forecast":
      return (
        <div className="grid gap-4 xl:grid-cols-[1.4fr_1fr]">
          <LineChartMock title="Actual plus forecast fan chart" fan />
          <TableCard title="Forecast horizon table" columns={["Period", "Forecast", "Lower", "Upper"]} rows={[["2026-08", "18,420", "17,100", "19,880"], ["2026-09", "18,910", "17,500", "20,230"], ["2026-10", "19,240", "17,640", "20,900"]]} />
        </div>
      );
    case "diagnostics":
      return (
        <div className="grid gap-4 xl:grid-cols-[1fr_1fr]">
          <LineChartMock title="Residuals over time" />
          <Heatmap title="Segment error heatmap" />
        </div>
      );
    case "scenario":
      return (
        <div className="grid gap-4 xl:grid-cols-[1.4fr_1fr]">
          <LineChartMock title="Base vs scenario forecast" fan />
          <TableCard title="Stress comparison table" columns={["Scenario", "Delta", "Risk"]} rows={[["Fraud spike", "+18%", "Review"], ["Downturn", "-9%", "Monitor"], ["Outage", "+12%", "Escalate"]]} />
        </div>
      );
    default:
      return <PanelGrid page={page} />;
  }
}

function SelectField({ label, options }: { label: string; options: string[] }) {
  return (
    <label className="rounded-xl border border-slate-200 bg-white p-3 text-sm shadow-sm">
      <span className="block text-xs font-semibold uppercase tracking-wide text-slate-600">{label}</span>
      <select className="mt-2 w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm text-slate-900">
        {options.map((option) => (
          <option key={option}>{option}</option>
        ))}
      </select>
    </label>
  );
}

function TimeSeriesPlanningWorkspace({ page }: { page: TimeSeriesPageDefinition }) {
  switch (page.layout) {
    case "charter":
      return (
        <section className="rounded-2xl border border-emerald-200 bg-emerald-50 p-5 shadow-sm">
          <div className="text-xs font-semibold uppercase tracking-wide text-emerald-700">Forecast charter</div>
          <div className="mt-4 grid gap-3 md:grid-cols-3">
            <SelectField label="Study goal" options={["Forecast future values", "Detect anomalies", "Monitor trend/stability", "Backtest forecast accuracy", "Compare time-aware models"]} />
            <SelectField label="Forecast horizon" options={["7 days", "30 days", "90 days", "12 months", "Custom"]} />
            <SelectField label="Forecast frequency" options={["Hourly", "Daily", "Weekly", "Monthly", "Quarterly"]} />
            <SelectField label="Entity grain" options={["Portfolio", "Product", "Branch", "Customer segment", "Account"]} />
            <SelectField label="Governance context" options={["Operational planning", "Financial reporting", "Customer-impacting", "Regulated decision support"]} />
            <SelectField label="Intended use" options={["Planning estimate", "Risk monitoring", "Staffing forecast", "Liquidity planning", "Management reporting"]} />
          </div>
        </section>
      );
    case "mapping":
      return (
        <section className="rounded-2xl border border-blue-200 bg-blue-50 p-5 text-sm text-blue-950 shadow-sm">
          The Time Series Data Acquisition page now owns dataset registration, schema-driven mapping, profiling, and evidence capture.
        </section>
      );
    case "profile":
      return (
        <section className="rounded-2xl border border-cyan-200 bg-cyan-50 p-5 shadow-sm">
          <div className="text-xs font-semibold uppercase tracking-wide text-cyan-700">Diagnostic view controls</div>
          <div className="mt-4 grid gap-3 md:grid-cols-6">
            <SelectField label="Entity selector" options={["All entities", "Top volume entity", "Highest error entity", "Custom entity"]} />
            <SelectField label="Date range" options={["Full history", "Last 12 periods", "Last 24 periods", "Custom"]} />
            <SelectField label="Rolling window" options={["7 periods", "14 periods", "30 periods", "Custom"]} />
            <SelectField label="Seasonality view" options={["Month of year", "Day of week", "Hour of day", "Quarter"]} />
            <SelectField label="Decomposition mode" options={["Additive", "Multiplicative", "STL preview"]} />
            <SelectField label="Anomaly sensitivity" options={["Low", "Medium", "High", "Reviewer threshold"]} />
          </div>
        </section>
      );
    case "timeline":
      return (
        <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
          <div className="text-xs font-semibold uppercase tracking-wide text-slate-600">Temporal validation design</div>
          <div className="mt-4 grid gap-3 md:grid-cols-4">
            <SelectField label="Split strategy" options={["Holdout by date", "Rolling origin", "Expanding window", "Sliding window"]} />
            <SelectField label="Initial training window" options={["12 periods", "24 periods", "36 periods", "Custom"]} />
            <SelectField label="Number of folds" options={["3", "5", "6", "10"]} />
            <SelectField label="Gap period" options={["None", "1 period", "2 periods", "Custom"]} />
          </div>
        </section>
      );
    case "model-cards":
      return null;
    case "run-results":
      return <section className="rounded-2xl border border-amber-200 bg-amber-50 p-4 text-sm font-semibold text-amber-900">Preview configuration - run controls are shown for workflow planning. Backend execution is not claimed unless the training service returns a run record.</section>;
    case "forecast":
      return (
        <section className="rounded-2xl border border-blue-200 bg-blue-50 p-5 shadow-sm">
          <div className="text-xs font-semibold uppercase tracking-wide text-blue-700">Forecast review controls</div>
          <div className="mt-4 grid gap-3 md:grid-cols-5">
            <SelectField label="Select entity" options={["All entities", "Top increasing", "Top decreasing", "Custom entity"]} />
            <SelectField label="Select horizon" options={["Next 7 days", "Next 30 days", "Next 90 days", "Next 12 months"]} />
            <SelectField label="Show intervals" options={["80%", "90%", "95%", "Hide intervals"]} />
            <SelectField label="Compare forecasts" options={["Champion only", "Champion vs baseline", "All candidates"]} />
            <SelectField label="Export format" options={["CSV", "Governed JSON", "Excel-ready CSV"]} />
          </div>
        </section>
      );
    case "scenario":
      return (
        <section className="rounded-2xl border border-rose-200 bg-rose-50 p-5 shadow-sm">
          <div className="text-xs font-semibold uppercase tracking-wide text-rose-700">Scenario builder</div>
          <div className="mt-4 grid gap-3 md:grid-cols-4">
            <SelectField label="Volume shock" options={["None", "+10%", "+25%", "-10%", "Custom"]} />
            <SelectField label="Seasonality shock" options={["None", "Holiday surge", "Seasonality fade", "Custom"]} />
            <SelectField label="Fraud spike" options={["None", "Moderate", "Severe", "Custom"]} />
            <SelectField label="Outage" options={["None", "1 period", "3 periods", "Custom"]} />
          </div>
        </section>
      );
    default:
      return null;
  }
}

export default function TimeSeriesWorkflowShell({ pageKey }: Props) {
  const navigate = useNavigate();
  const workflow = getWorkflowDefinition("time_series_forecasting");
  const resolvedPage = useMemo(() => {
    if (!pageKey) return getTimeSeriesPageByStep(1);
    const pageIndex = workflow.steps.findIndex((_, index) => getTimeSeriesPageByStep(index + 1).key === pageKey);
    return getTimeSeriesPageByStep(pageIndex + 1);
  }, [pageKey, workflow.steps]);
  const stepIndex = resolvedPage.stepNumber - 1;
  const currentStep = workflow.steps[stepIndex];
  const nextStep = workflow.steps[stepIndex + 1];

  const handleNext = () => {
    const store = useWorkflowStore.getState();
    if (currentStep) store.markWorkflowStepComplete(currentStep.id);
    if (nextStep) {
      store.setWorkflowStepStatus(nextStep.id, "in_progress");
      store.setCurrentStepId(nextStep.id);
    }
    saveActiveProjectBeforeNavigation(useWorkflowStore.getState());
    navigate(nextStep?.route ?? "/project-overview");
    window.requestAnimationFrame(() => window.scrollTo({ top: 0, left: 0, behavior: "auto" }));
  };

  return (
    <StepShell
      title=""
      hideHeader
      nextLabel={nextStep ? `Continue to ${nextStep.label}` : "Save Time Series Package"}
      onNextClick={handleNext}
      nextStatusLine={`Save ${resolvedPage.evidenceType} evidence and continue.`}
    >
      <div className="space-y-5">
        <section className="overflow-hidden rounded-2xl border border-slate-800 bg-slate-950 text-white shadow-xl">
          <div className="p-6">
            <div className="text-xs font-semibold uppercase tracking-wide text-cyan-200">{resolvedPage.eyebrow}</div>
            <h1 className="mt-2 text-3xl font-semibold">{resolvedPage.title}</h1>
            <p className="mt-3 max-w-4xl text-sm leading-6 text-slate-200">{resolvedPage.summary}</p>
          </div>
          <div className="grid border-t border-white/10 bg-white/5 md:grid-cols-4">
            <div className="p-4"><div className="text-xs uppercase text-slate-400">Step</div><div className="font-semibold">{resolvedPage.stepNumber} of 12</div></div>
            <div className="p-4"><div className="text-xs uppercase text-slate-400">Evidence</div><div className="font-semibold">{resolvedPage.evidenceType}</div></div>
            <div className="p-4"><div className="text-xs uppercase text-slate-400">Validation</div><div className="font-semibold">Time-aware</div></div>
            <div className="p-4"><div className="text-xs uppercase text-slate-400">Mode</div><div className="font-semibold">Financial services</div></div>
          </div>
        </section>

        <StatGrid page={resolvedPage} />

        <TimeSeriesPlanningWorkspace page={resolvedPage} />

        <TimeSeriesVisualCenter page={resolvedPage} />
        <PanelGrid page={resolvedPage} />
        <CodePanel page={resolvedPage} />
      </div>
    </StepShell>
  );
}
