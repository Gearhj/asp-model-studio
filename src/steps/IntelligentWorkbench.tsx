import React, { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import {
  BrainCircuit,
  ClipboardCheck,
  Code2,
  Download,
  FileText,
  FlaskConical,
  NotebookTabs,
  Plus,
  Scale,
} from "lucide-react";
import { logDecision } from "../lib/decisionJournal";
import { inferLocalProblemType, loadLocalDataset } from "../lib/localDataset";
import { USER_PYTHON_CODE_KEY } from "../lib/notebookExport";
import { useWorkflowStore } from "../state/useWorkflowStore";
import { BRAND } from "../config/brand";

const API_BASE =
  (import.meta.env.VITE_API_BASE as string | undefined)?.replace(/\/$/, "") ||
  "http://127.0.0.1:8001/api";

const EXPERIMENT_KEY = "modeling-tool-experiments";
const DECISION_KEY = "modeling-tool-decisions";

type RankedModel = {
  key: string;
  name: string;
  task?: "classification" | "regression" | "anomaly";
  auc?: number;
  pr_auc?: number;
  f1?: number;
  rmse?: number;
  mae?: number;
  r2?: number;
  adjusted_r2?: number;
};

type Experiment = {
  id: string;
  name: string;
  model: string;
  metric: string;
  outcome: string;
  notes: string;
  createdAt: string;
};

type Decision = {
  id: string;
  area: string;
  decision: string;
  rationale: string;
  evidence: string;
  owner: string;
  createdAt: string;
};

function readList<T>(key: string): T[] {
  try {
    const parsed = JSON.parse(localStorage.getItem(key) || "[]");
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

function writeList<T>(key: string, rows: T[]) {
  localStorage.setItem(key, JSON.stringify(rows));
}

function downloadText(filename: string, content: string, type = "text/plain") {
  const blob = new Blob([content], { type });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  URL.revokeObjectURL(url);
}

function todayStamp() {
  return new Date().toISOString().slice(0, 10);
}

export default function IntelligentWorkbench() {
  const steps = useWorkflowStore((state) => state.steps);
  const [ranked, setRanked] = useState<RankedModel[]>([]);
  const [experiments, setExperiments] = useState<Experiment[]>(() => readList<Experiment>(EXPERIMENT_KEY));
  const [decisions, setDecisions] = useState<Decision[]>(() => readList<Decision>(DECISION_KEY));
  const [experimentDraft, setExperimentDraft] = useState({
    name: "Champion challenger run",
    model: "",
    metric: "",
    outcome: "Promising",
    notes: "",
  });
  const [decisionDraft, setDecisionDraft] = useState({
    area: "Model Selection",
    decision: "",
    rationale: "",
    evidence: "",
    owner: "Model Developer",
  });

  const dataset = loadLocalDataset();
  const problemType = inferLocalProblemType(dataset);
  const completedCount = Object.entries(steps).filter(([key, status]) => key !== "dashboard" && status === "completed").length;
  const champion = ranked[0] ?? null;

  useEffect(() => {
    fetch(`${API_BASE}/train/last`, { credentials: "include" })
      .then((res) => res.json())
      .then((data) => {
        const rows = data?.summary?.ranked;
        if (Array.isArray(rows)) {
          setRanked(rows);
          setExperimentDraft((current) => ({
            ...current,
            model: current.model || rows[0]?.name || "",
            metric:
              current.metric ||
              (data?.summary?.problem_type === "regression"
                ? `RMSE ${rows[0]?.rmse?.toFixed?.(4) ?? "-"}`
                : `AUC ${rows[0]?.auc?.toFixed?.(4) ?? "-"}`),
          }));
        }
      })
      .catch(() => setRanked([]));
  }, []);

  useEffect(() => writeList(EXPERIMENT_KEY, experiments), [experiments]);
  useEffect(() => writeList(DECISION_KEY, decisions), [decisions]);

  const recommendations = useMemo(
    () => buildRecommendations({ problemType, completedCount, ranked, decisions }),
    [problemType, completedCount, ranked, decisions]
  );

  const notebookCode = useMemo(
    () => buildNotebookCode({
      target: dataset?.target ?? "target",
      problemType: problemType ?? "classification",
      championName: champion?.name ?? "Champion model",
    }),
    [dataset?.target, problemType, champion?.name]
  );

  const governanceMarkdown = useMemo(
    () =>
      buildGovernanceMemo({
        problemType,
        target: dataset?.target,
        rows: dataset?.rows.length ?? 0,
        selectedColumns: dataset?.selected_columns ?? [],
        champion,
        experiments,
        decisions,
        recommendations,
      }),
    [problemType, dataset?.target, dataset?.rows.length, dataset?.selected_columns, champion, experiments, decisions, recommendations]
  );

  const addExperiment = () => {
    const name = experimentDraft.name.trim();
    if (!name) return;
    setExperiments((current) => [
      {
        id: crypto.randomUUID(),
        createdAt: todayStamp(),
        ...experimentDraft,
        name,
      },
      ...current,
    ]);
    setExperimentDraft((current) => ({ ...current, notes: "" }));
  };

  const addDecision = () => {
    const decision = decisionDraft.decision.trim();
    if (!decision) return;
    logDecision({
      workflowStep: "AI Workbench",
      actionType: "workflow_setting_changed",
      subject: decision,
      previousValue: "-",
      newValue: decisionDraft,
      systemRecommendation: "Material modeling decisions should include rationale, alternatives considered, evidence, and accountable owner.",
      followStatus: decisionDraft.rationale.trim() ? "followed" : "unknown",
      userReason: decisionDraft.rationale,
    });
    setDecisions((current) => [
      {
        id: crypto.randomUUID(),
        createdAt: todayStamp(),
        ...decisionDraft,
        decision,
      },
      ...current,
    ]);
    setDecisionDraft((current) => ({ ...current, decision: "", rationale: "", evidence: "" }));
  };

  return (
    <div className="space-y-5">
      <section className="overflow-hidden rounded-lg border border-slate-200/80 bg-white shadow-sm">
        <div className="grid gap-5 p-5 lg:grid-cols-[minmax(0,1fr)_360px]">
          <div>
            <div className="inline-flex items-center gap-2 rounded-full border border-slate-200 bg-slate-50 px-3 py-1 text-xs font-semibold text-slate-600">
              <BrainCircuit size={14} />
              Intelligent modeling workbench
            </div>
            <h1 className="mt-4 text-2xl font-semibold tracking-tight text-slate-950">
              Senior-DS guidance layer for Consumer Lending AI/ML development
            </h1>
            <p className="mt-2 max-w-3xl text-sm leading-6 text-slate-600">
              Keep using the existing workflow, while this page consolidates recommendations, experiment history,
              notebook handoffs, decision rationale, and governance-ready outputs.
            </p>
            <div className="mt-4 flex flex-wrap gap-2">
              <Link className="rounded-lg bg-slate-950 px-3 py-2 text-sm font-medium text-white shadow-sm hover:bg-slate-800" to="/step07">
                Continue Modeling
              </Link>
              <button
                className="inline-flex items-center gap-2 rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-medium text-slate-700 shadow-sm hover:bg-slate-50"
                onClick={() => downloadText("model-governance-memo.md", governanceMarkdown, "text/markdown")}
              >
                <Download size={15} />
                Export Governance Memo
              </button>
            </div>
          </div>
          <div className="grid gap-3 rounded-lg border border-slate-200 bg-slate-50 p-4">
            <WorkbenchStat label="Workflow Complete" value={`${completedCount}/10`} />
            <WorkbenchStat label="Problem Type" value={problemType ?? "Not selected"} />
            <WorkbenchStat label="Target" value={dataset?.target ?? "Not selected"} />
            <WorkbenchStat label="Champion" value={champion?.name ?? "No trained model"} />
          </div>
        </div>
      </section>

      <section className="grid gap-5 xl:grid-cols-[minmax(0,1.15fr)_minmax(420px,0.85fr)]">
        <AdvisorPanel recommendations={recommendations} />
        <ExperimentPanel
          experiments={experiments}
          draft={experimentDraft}
          setDraft={setExperimentDraft}
          onAdd={addExperiment}
        />
      </section>

      <section className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
        <NotebookPanel code={notebookCode} />
        <DecisionPanel decisions={decisions} draft={decisionDraft} setDraft={setDecisionDraft} onAdd={addDecision} />
      </section>

      <GovernancePanel markdown={governanceMarkdown} decisions={decisions} experiments={experiments} ranked={ranked} />
    </div>
  );
}

function WorkbenchStat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-slate-200 bg-white px-3 py-2">
      <div className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">{label}</div>
      <div className="mt-1 truncate text-sm font-semibold text-slate-950" title={value}>
        {value}
      </div>
    </div>
  );
}

function AdvisorPanel({ recommendations }: { recommendations: { title: string; detail: string; severity: string }[] }) {
  return (
    <section className="rounded-lg border border-slate-200/80 bg-white p-4 shadow-sm">
      <div className="flex items-center gap-2">
        <BrainCircuit size={18} className="text-slate-700" />
        <h2 className="text-sm font-semibold text-slate-950">AI-Assisted Modeling Advisor</h2>
      </div>
      <div className="mt-4 grid gap-3">
        {recommendations.map((item) => (
          <article key={item.title} className="rounded-lg border border-slate-200 bg-slate-50 p-3">
            <div className="flex items-center justify-between gap-3">
              <h3 className="text-sm font-semibold text-slate-900">{item.title}</h3>
              <span className="rounded-full bg-white px-2 py-0.5 text-[11px] font-semibold text-slate-600 ring-1 ring-slate-200">
                {item.severity}
              </span>
            </div>
            <p className="mt-1 text-sm leading-5 text-slate-600">{item.detail}</p>
          </article>
        ))}
      </div>
    </section>
  );
}

function ExperimentPanel({
  experiments,
  draft,
  setDraft,
  onAdd,
}: {
  experiments: Experiment[];
  draft: Omit<Experiment, "id" | "createdAt">;
  setDraft: React.Dispatch<React.SetStateAction<Omit<Experiment, "id" | "createdAt">>>;
  onAdd: () => void;
}) {
  return (
    <section className="rounded-lg border border-slate-200/80 bg-white p-4 shadow-sm">
      <div className="flex items-center gap-2">
        <FlaskConical size={18} className="text-slate-700" />
        <h2 className="text-sm font-semibold text-slate-950">Experiment Tracking</h2>
      </div>
      <div className="mt-4 grid gap-3">
        <div className="grid gap-2 sm:grid-cols-2">
          <input className="rounded-lg border border-slate-300 px-3 py-2 text-sm" value={draft.name} onChange={(e) => setDraft((d) => ({ ...d, name: e.target.value }))} placeholder="Experiment name" />
          <input className="rounded-lg border border-slate-300 px-3 py-2 text-sm" value={draft.model} onChange={(e) => setDraft((d) => ({ ...d, model: e.target.value }))} placeholder="Model / challenger" />
          <input className="rounded-lg border border-slate-300 px-3 py-2 text-sm" value={draft.metric} onChange={(e) => setDraft((d) => ({ ...d, metric: e.target.value }))} placeholder="Metric result" />
          <select className="rounded-lg border border-slate-300 px-3 py-2 text-sm" value={draft.outcome} onChange={(e) => setDraft((d) => ({ ...d, outcome: e.target.value }))}>
            <option>Promising</option>
            <option>Champion</option>
            <option>Rejected</option>
            <option>Needs Review</option>
          </select>
        </div>
        <textarea className="min-h-20 rounded-lg border border-slate-300 px-3 py-2 text-sm" value={draft.notes} onChange={(e) => setDraft((d) => ({ ...d, notes: e.target.value }))} placeholder="What changed, why it matters, and what to test next." />
        <button className="inline-flex w-fit items-center gap-2 rounded-lg bg-slate-950 px-3 py-2 text-sm font-medium text-white shadow-sm hover:bg-slate-800" onClick={onAdd}>
          <Plus size={15} />
          Log Experiment
        </button>
      </div>
      <div className="mt-4 max-h-72 overflow-auto rounded-lg border border-slate-200">
        {experiments.length ? experiments.map((row) => (
          <div key={row.id} className="border-b border-slate-100 p-3 last:border-b-0">
            <div className="flex items-center justify-between gap-3">
              <strong className="text-sm text-slate-950">{row.name}</strong>
              <span className="text-xs text-slate-500">{row.createdAt}</span>
            </div>
            <div className="mt-1 text-xs font-medium text-slate-600">{row.model} · {row.metric} · {row.outcome}</div>
            {row.notes && <p className="mt-1 text-sm leading-5 text-slate-600">{row.notes}</p>}
          </div>
        )) : <div className="p-3 text-sm text-slate-500">No experiments logged yet.</div>}
      </div>
    </section>
  );
}

function NotebookPanel({ code }: { code: string }) {
  const [draftCode, setDraftCode] = useState(() => localStorage.getItem(USER_PYTHON_CODE_KEY) || code);
  const [lastLoggedCode, setLastLoggedCode] = useState(code);

  useEffect(() => {
    const saved = localStorage.getItem(USER_PYTHON_CODE_KEY);
    setDraftCode(saved || code);
    setLastLoggedCode(saved || code);
  }, [code]);

  const logCodeEdit = () => {
    if (draftCode === lastLoggedCode) return;
    logDecision({
      workflowStep: "AI Workbench",
      actionType: "custom_python_code_edited",
      subject: "Notebook starter code",
      previousValue: `${lastLoggedCode.length} characters`,
      newValue: `${draftCode.length} characters`,
    });
    localStorage.setItem(USER_PYTHON_CODE_KEY, draftCode);
    setLastLoggedCode(draftCode);
  };

  return (
    <section className="rounded-lg border border-slate-200/80 bg-white p-4 shadow-sm">
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <NotebookTabs size={18} className="text-slate-700" />
          <h2 className="text-sm font-semibold text-slate-950">Python Notebook / Code Integration</h2>
        </div>
        <button className="inline-flex items-center gap-2 rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-medium text-slate-700 shadow-sm hover:bg-slate-50" onClick={() => downloadText("modeling_workbench_starter.py", draftCode)}>
          <Code2 size={15} />
          Export .py
        </button>
      </div>
      <textarea
        className="mt-4 h-[430px] w-full resize-y rounded-lg bg-slate-950 p-4 font-mono text-xs leading-5 text-slate-100 outline-none ring-1 ring-slate-900 focus:ring-indigo-400"
        value={draftCode}
        onChange={(event) => {
          setDraftCode(event.target.value);
          localStorage.setItem(USER_PYTHON_CODE_KEY, event.target.value);
        }}
        onBlur={logCodeEdit}
        spellCheck={false}
      />
    </section>
  );
}

function DecisionPanel({
  decisions,
  draft,
  setDraft,
  onAdd,
}: {
  decisions: Decision[];
  draft: Omit<Decision, "id" | "createdAt">;
  setDraft: React.Dispatch<React.SetStateAction<Omit<Decision, "id" | "createdAt">>>;
  onAdd: () => void;
}) {
  return (
    <section className="rounded-lg border border-slate-200/80 bg-white p-4 shadow-sm">
      <div className="flex items-center gap-2">
        <ClipboardCheck size={18} className="text-slate-700" />
        <h2 className="text-sm font-semibold text-slate-950">Decision Documentation</h2>
      </div>
      <div className="mt-4 grid gap-3">
        <div className="grid gap-2 sm:grid-cols-2">
          <select className="rounded-lg border border-slate-300 px-3 py-2 text-sm" value={draft.area} onChange={(e) => setDraft((d) => ({ ...d, area: e.target.value }))}>
            <option>Data Selection</option>
            <option>Feature Engineering</option>
            <option>Model Selection</option>
            <option>Performance Tradeoff</option>
            <option>Fair Lending / Bias</option>
            <option>Deployment Readiness</option>
          </select>
          <input className="rounded-lg border border-slate-300 px-3 py-2 text-sm" value={draft.owner} onChange={(e) => setDraft((d) => ({ ...d, owner: e.target.value }))} placeholder="Owner" />
        </div>
        <input className="rounded-lg border border-slate-300 px-3 py-2 text-sm" value={draft.decision} onChange={(e) => setDraft((d) => ({ ...d, decision: e.target.value }))} placeholder="Decision made" />
        <textarea className="min-h-20 rounded-lg border border-slate-300 px-3 py-2 text-sm" value={draft.rationale} onChange={(e) => setDraft((d) => ({ ...d, rationale: e.target.value }))} placeholder="Rationale and alternatives considered" />
        <textarea className="min-h-16 rounded-lg border border-slate-300 px-3 py-2 text-sm" value={draft.evidence} onChange={(e) => setDraft((d) => ({ ...d, evidence: e.target.value }))} placeholder="Evidence: metrics, charts, tests, policy references" />
        <button className="inline-flex w-fit items-center gap-2 rounded-lg bg-slate-950 px-3 py-2 text-sm font-medium text-white shadow-sm hover:bg-slate-800" onClick={onAdd}>
          <Plus size={15} />
          Add Decision
        </button>
      </div>
      <div className="mt-4 max-h-72 overflow-auto rounded-lg border border-slate-200">
        {decisions.length ? decisions.map((row) => (
          <div key={row.id} className="border-b border-slate-100 p-3 last:border-b-0">
            <div className="flex items-center justify-between gap-3">
              <strong className="text-sm text-slate-950">{row.area}</strong>
              <span className="text-xs text-slate-500">{row.createdAt}</span>
            </div>
            <p className="mt-1 text-sm font-medium text-slate-800">{row.decision}</p>
            <p className="mt-1 text-sm leading-5 text-slate-600">{row.rationale}</p>
          </div>
        )) : <div className="p-3 text-sm text-slate-500">No model decisions documented yet.</div>}
      </div>
    </section>
  );
}

function GovernancePanel({
  markdown,
  decisions,
  experiments,
  ranked,
}: {
  markdown: string;
  decisions: Decision[];
  experiments: Experiment[];
  ranked: RankedModel[];
}) {
  const checklist = [
    { label: "Development sample and target documented", done: markdown.includes("Target:") },
    { label: "Candidate experiments logged", done: experiments.length > 0 },
    { label: "Champion or challenger results available", done: ranked.length > 0 },
    { label: "Material modeling decisions documented", done: decisions.length > 0 },
    { label: "Governance memo export ready", done: true },
  ];
  return (
    <section className="rounded-lg border border-slate-200/80 bg-white p-4 shadow-sm">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <Scale size={18} className="text-slate-700" />
          <h2 className="text-sm font-semibold text-slate-950">Model Governance Outputs</h2>
        </div>
        <button className="inline-flex items-center gap-2 rounded-lg bg-slate-950 px-3 py-2 text-sm font-medium text-white shadow-sm hover:bg-slate-800" onClick={() => downloadText("model-governance-memo.md", markdown, "text/markdown")}>
          <FileText size={15} />
          Download Memo
        </button>
      </div>
      <div className="mt-4 grid gap-3 md:grid-cols-5">
        {checklist.map((item) => (
          <div key={item.label} className={`rounded-lg border px-3 py-3 ${item.done ? "border-emerald-200 bg-emerald-50" : "border-amber-200 bg-amber-50"}`}>
            <div className={`text-xs font-semibold ${item.done ? "text-emerald-800" : "text-amber-900"}`}>
              {item.done ? "Ready" : "Needs input"}
            </div>
            <div className="mt-1 text-sm leading-5 text-slate-700">{item.label}</div>
          </div>
        ))}
      </div>
    </section>
  );
}

function buildRecommendations({
  problemType,
  completedCount,
  ranked,
  decisions,
}: {
  problemType: "classification" | "regression" | null;
  completedCount: number;
  ranked: RankedModel[];
  decisions: Decision[];
}) {
  const rows = [
    {
      title: "Keep the guided workflow as the source of record",
      detail:
        completedCount < 7
          ? "Finish preprocessing, split, and training before locking interpretation or governance artifacts."
          : "The core workflow is far enough along to begin documenting champion selection and governance rationale.",
      severity: completedCount < 7 ? "Next best action" : "On track",
    },
    {
      title: "Document model-purpose and lending-use constraints",
      detail:
        "For Consumer Lending, capture the intended use, prohibited uses, adverse-action explainability needs, and monitoring owner before production export.",
      severity: "Governance",
    },
  ];

  if (!problemType) {
    rows.unshift({
      title: "Load a dataset and select a target",
      detail: "The advisor can become more specific once it knows whether this is a classification or regression problem.",
      severity: "Required",
    });
  } else if (problemType === "classification") {
    rows.push({
      title: "Prioritize ranking metrics and calibration",
      detail: "For lending classification, compare AUC/PR-AUC, lift by decile, threshold precision/recall, probability calibration, PSI, and VSI before final model selection.",
      severity: "Model risk",
    });
  } else {
    rows.push({
      title: "Review residual structure before champion selection",
      detail: "For regression, inspect residual bias, outlier sensitivity, RMSE/MAE tradeoffs, R-squared, adjusted R-squared, prediction stability, and variable stability.",
      severity: "Model risk",
    });
  }

  if (ranked.length > 1) {
    rows.push({
      title: "Promote a champion/challenger narrative",
      detail: `You have ${ranked.length} trained candidate models. Record why the champion beats alternatives, including any interpretability or implementation tradeoffs.`,
      severity: "Documentation",
    });
  }

  if (!decisions.length) {
    rows.push({
      title: "Start the decision log now",
      detail: "Record data exclusions, imputation choices, feature transformations, final feature count, and champion rationale while the evidence is fresh.",
      severity: "Audit trail",
    });
  }

  return rows;
}

function buildNotebookCode({
  target,
  problemType,
  championName,
}: {
  target: string;
  problemType: "classification" | "regression";
  championName: string;
}) {
  return `# ${BRAND.productName} - Notebook Handoff
# ${BRAND.productSubtitle}
# Generated starter code for external Python review.

import pandas as pd
import numpy as np
from pathlib import Path

TARGET = "${target}"
PROBLEM_TYPE = "${problemType}"
CHAMPION_MODEL = "${championName}"

# 1. Load the same development data used in the UI.
# Replace this path with the CSV used on Step 1.
df = pd.read_csv("TRAIN.csv")

# 2. Recreate high-level checks expected by the regulated workflow.
print("Rows:", len(df))
print("Columns:", len(df.columns))
print("Target:", TARGET)
print(df[TARGET].describe())

# 3. Add custom model-development code here.
# Keep transformations reproducible and document every excluded variable.

# 4. Suggested validation checks:
if PROBLEM_TYPE == "classification":
    checks = ["AUC", "PR-AUC", "Lift by decile", "Calibration", "PSI", "VSI", "Fair lending review"]
else:
    checks = ["RMSE", "MAE", "R-squared", "Adjusted R-squared", "Residual bias", "PSI", "VSI"]

print("Required validation checks:", checks)
`;
}

function buildGovernanceMemo({
  problemType,
  target,
  rows,
  selectedColumns,
  champion,
  experiments,
  decisions,
  recommendations,
}: {
  problemType: "classification" | "regression" | null;
  target?: string | null;
  rows: number;
  selectedColumns: string[];
  champion: RankedModel | null;
  experiments: Experiment[];
  decisions: Decision[];
  recommendations: { title: string; detail: string; severity: string }[];
}) {
  return `# Consumer Lending AI/ML Model Development Memo

## Model Context
- Problem type: ${problemType ?? "Not selected"}
- Target: ${target ?? "Not selected"}
- Cached development rows: ${rows.toLocaleString()}
- Selected feature count: ${selectedColumns.length}
- Champion model: ${champion?.name ?? "Not selected"}

## Champion Metrics
${champion ? formatChampion(champion) : "- No trained champion available."}

## Experiment Log
${experiments.length ? experiments.map((row) => `- ${row.createdAt}: ${row.name} | ${row.model} | ${row.metric} | ${row.outcome} | ${row.notes}`).join("\n") : "- No experiments logged yet."}

## Decision Log
${decisions.length ? decisions.map((row) => `- ${row.createdAt} | ${row.area} | ${row.decision} | Owner: ${row.owner}\n  - Rationale: ${row.rationale || "Not documented"}\n  - Evidence: ${row.evidence || "Not documented"}`).join("\n") : "- No decisions documented yet."}

## Advisor Recommendations
${recommendations.map((row) => `- [${row.severity}] ${row.title}: ${row.detail}`).join("\n")}

## Governance Review Prompts
- Intended model use and decisioning context
- Data lineage and sample representativeness
- Feature exclusions and prohibited-variable review
- Performance, stability, sensitivity, and explainability evidence
- Fair lending / bias testing evidence
- Champion/challenger rationale
- Monitoring plan, retraining triggers, and owner
`;
}

function formatChampion(champion: RankedModel) {
  if (champion.task === "regression" || typeof champion.rmse === "number") {
    return `- RMSE: ${champion.rmse?.toFixed(4) ?? "-"}\n- MAE: ${champion.mae?.toFixed(4) ?? "-"}\n- R-squared: ${champion.r2?.toFixed(4) ?? "-"}`;
  }
  return `- AUC: ${champion.auc?.toFixed(4) ?? "-"}\n- PR-AUC: ${champion.pr_auc?.toFixed(4) ?? "-"}\n- F1: ${champion.f1?.toFixed(4) ?? "-"}`;
}
