import { useMemo } from "react";
import { useNavigate } from "react-router-dom";
import StepShell from "../../components/StepShell";
import { getWorkflowDefinition } from "../../config/workflows";
import { saveActiveProjectBeforeNavigation } from "../../lib/localProjects";
import { useWorkflowStore } from "../../state/useWorkflowStore";
import { getLlmPageByStep } from "./llmDemoData";
import type { LlmPageDefinition, LlmPageKey } from "./llmTypes";

type Props = {
  pageKey?: LlmPageKey;
};

const toneClass = {
  good: "border-emerald-200 bg-emerald-50 text-emerald-900",
  warn: "border-amber-200 bg-amber-50 text-amber-900",
  info: "border-blue-200 bg-blue-50 text-blue-900",
} as const;

function MetricStrip({ page }: { page: LlmPageDefinition }) {
  return (
    <div className="grid gap-3 md:grid-cols-4">
      {page.stats.map(([label, value, tone]) => (
        <div key={label} className={`rounded-xl border px-4 py-3 ${toneClass[tone]}`}>
          <div className="text-[11px] font-semibold uppercase tracking-wide opacity-70">{label}</div>
          <div className="mt-1 text-xl font-semibold">{value}</div>
        </div>
      ))}
    </div>
  );
}

function PanelGrid({ page }: { page: LlmPageDefinition }) {
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

function CodePanel({ page }: { page: LlmPageDefinition }) {
  return (
    <section className="rounded-2xl border border-slate-200 bg-slate-950 p-5 text-slate-100 shadow-sm">
      <div className="text-xs font-semibold uppercase tracking-wide text-violet-200">Code & Reproducibility</div>
      <pre className="mt-3 overflow-auto rounded-xl bg-black/25 p-4 text-xs leading-6 text-slate-100">
        <code>{page.code.join("\n")}</code>
      </pre>
    </section>
  );
}

function LlmPipeline() {
  return (
    <section className="rounded-2xl border border-blue-200 bg-blue-50 p-5 shadow-sm">
      <h3 className="text-base font-semibold text-slate-950">RAG pipeline graphic</h3>
      <div className="mt-5 grid gap-3 md:grid-cols-5">
        {["Source", "Chunk", "Embed", "Retrieve", "Cite & answer"].map((item, index) => (
          <div key={item} className="rounded-xl border border-blue-200 bg-white p-4 text-center">
            <div className="mx-auto flex h-9 w-9 items-center justify-center rounded-full bg-blue-600 text-sm font-semibold text-white">{index + 1}</div>
            <div className="mt-3 text-sm font-semibold text-slate-900">{item}</div>
          </div>
        ))}
      </div>
    </section>
  );
}

function RiskHeatmap({ title }: { title: string }) {
  const items = ["Injection", "Leakage", "Hallucination", "Privacy", "Fair lending", "UDAAP", "No source", "Toxicity", "Confidentiality"];
  return (
    <section className="rounded-2xl border border-amber-200 bg-amber-50 p-5 shadow-sm">
      <h3 className="text-base font-semibold text-slate-950">{title}</h3>
      <div className="mt-4 grid grid-cols-3 gap-2">
        {items.map((item, index) => (
          <div key={item} className="rounded-xl border border-white/70 bg-white p-3">
            <div className="text-xs font-semibold text-slate-600">{item}</div>
            <div className={`mt-2 h-2 rounded-full ${index % 3 === 0 ? "bg-red-400" : index % 3 === 1 ? "bg-amber-400" : "bg-emerald-400"}`} />
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
              <tr key={row.join("-")} className="hover:bg-violet-50/50">
                {row.map((cell) => <td key={cell} className="px-3 py-2 text-slate-700">{cell}</td>)}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function PromptEditor() {
  return (
    <section className="rounded-2xl border border-violet-200 bg-violet-50 p-5 shadow-sm">
      <h3 className="text-base font-semibold text-slate-950">Prompt editor sections</h3>
      <div className="mt-4 grid gap-3 md:grid-cols-2">
        {["System instruction editor", "Developer instruction editor", "User prompt template editor", "Few-shot examples"].map((label) => (
          <textarea key={label} className="min-h-28 rounded-xl border border-violet-200 bg-white p-3 text-sm" defaultValue={`${label}: document the rule, boundary, and example here.`} />
        ))}
      </div>
    </section>
  );
}

function LlmVisualCenter({ page }: { page: LlmPageDefinition }) {
  switch (page.layout) {
    case "risk":
    case "safety":
      return <RiskHeatmap title={page.layout === "risk" ? "Use-case risk matrix" : "Safety and red-team risk heatmap"} />;
    case "sources":
      return <TableCard title="Source inventory table" columns={["Source", "Owner", "Freshness", "Sensitivity", "Coverage"]} rows={[["Policy manual", "Compliance", "Current", "Restricted", "High"], ["Call transcripts", "Ops", "Review", "PII", "Medium"], ["FAQ corpus", "Product", "Current", "Internal", "High"]]} />;
    case "schema":
      return <TableCard title="JSON schema preview" columns={["Field", "Type", "Required", "Rule"]} rows={[["answer", "string", "Yes", "Cited"], ["citations", "array", "Yes", "Source ID"], ["confidence", "number", "Yes", "0 to 1"]]} />;
    case "prompt":
      return <PromptEditor />;
    case "rag":
      return <LlmPipeline />;
    case "eval-run":
      return <TableCard title="Evaluation scorecard" columns={["Metric", "Value", "Threshold", "Status"]} rows={[["Groundedness", "86%", "80%", "Pass"], ["Citation accuracy", "82%", "85%", "Review"], ["Hallucination rate", "4.1%", "3%", "Review"], ["Refusal correctness", "91%", "90%", "Pass"]]} />;
    case "review":
      return <TableCard title="Human review workflow" columns={["Stage", "Owner", "Decision", "Evidence"]} rows={[["Sample", "QA", "Risk based", "Queue"], ["Review", "Analyst", "Override allowed", "Reason code"], ["Escalate", "Manager", "Required", "Ticket"]]} />;
    case "deployment":
      return <TableCard title="Monitoring threshold table" columns={["Metric", "Threshold", "Owner", "Action"]} rows={[["Groundedness", "< 80%", "Model owner", "Rollback"], ["Overrides", "> 12%", "QA", "Review"], ["Incidents", "> 0 high", "Risk", "Escalate"]]} />;
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

function LlmPlanningWorkspace({ page }: { page: LlmPageDefinition }) {
  switch (page.layout) {
    case "risk":
      return (
        <section className="rounded-2xl border border-violet-200 bg-violet-50 p-5 shadow-sm">
          <div className="text-xs font-semibold uppercase tracking-wide text-violet-700">Risk boundary controls</div>
          <div className="mt-4 grid gap-3 md:grid-cols-3">
            <SelectField label="LLM workflow mode" options={["RAG question answering", "Extraction", "Classification", "Summarization", "Analyst copilot"]} />
            <SelectField label="Customer impact" options={["No customer impact", "Internal advisory", "Customer-facing draft", "Customer-impacting decision support"]} />
            <SelectField label="Human review" options={["Always required", "Risk-based", "Low-confidence only", "Not allowed to bypass review"]} />
          </div>
        </section>
      );
    case "sources":
      return (
        <section className="rounded-2xl border border-blue-200 bg-blue-50 p-5 shadow-sm">
          <div className="text-xs font-semibold uppercase tracking-wide text-blue-700">Source upload and registration</div>
          <div className="mt-4 grid gap-3 md:grid-cols-4">
            <SelectField label="Source type" options={["Policy document", "Procedure", "Knowledge base", "Call transcript", "Case notes"]} />
            <SelectField label="Permitted use" options={["Internal analysis", "Customer response draft", "Training only", "Restricted"]} />
            <SelectField label="Freshness" options={["Current", "Review within 30 days", "Stale", "Unknown"]} />
            <SelectField label="Sensitivity" options={["Public", "Internal", "Confidential", "PII present"]} />
          </div>
        </section>
      );
    case "schema":
      return (
        <section className="rounded-2xl border border-emerald-200 bg-emerald-50 p-5 shadow-sm">
          <div className="text-xs font-semibold uppercase tracking-wide text-emerald-700">Output contract design</div>
          <div className="mt-4 grid gap-3 md:grid-cols-4">
            <SelectField label="Task type" options={["Classification", "Extraction", "Summarization", "Question answering", "Draft generation"]} />
            <SelectField label="Citation requirement" options={["Required for every answer", "Required for regulated topics", "Optional", "Not allowed"]} />
            <SelectField label="Refusal behavior" options={["Refuse unsupported", "Ask clarifying question", "Escalate to reviewer"]} />
            <SelectField label="Escalation rule" options={["No source", "Low confidence", "Sensitive topic", "Policy conflict"]} />
          </div>
        </section>
      );
    case "prompt":
      return <section className="rounded-2xl border border-violet-200 bg-violet-50 p-4 text-sm font-semibold text-violet-900">Planning control - prompt variables, examples, conflicts, and token limits are edited in the prompt component editor below.</section>;
    case "rag":
      return (
        <section className="rounded-2xl border border-cyan-200 bg-cyan-50 p-5 shadow-sm">
          <div className="text-xs font-semibold uppercase tracking-wide text-cyan-700">Retrieval configuration</div>
          <div className="mt-4 grid gap-3 md:grid-cols-5">
            <SelectField label="Chunking strategy" options={["Fixed length", "Paragraph", "Section", "Page", "Semantic"]} />
            <SelectField label="Embedding model label" options={["Local embedding", "Enterprise approved", "Domain tuned", "Reviewer supplied"]} />
            <SelectField label="Top-k" options={["3", "5", "8", "10"]} />
            <SelectField label="Reranking" options={["None", "Cross-encoder", "Metadata priority", "Hybrid"]} />
            <SelectField label="No-source fallback" options={["Refuse", "Ask clarifying question", "Escalate"]} />
          </div>
        </section>
      );
    case "eval-data":
      return <section className="rounded-2xl border border-slate-200 bg-white p-4 text-sm font-semibold text-slate-800">Golden test set builder - add expected answers, required citations, adversarial cases, and rubric criteria in the evaluation workspace.</section>;
    case "eval-run":
      return <section className="rounded-2xl border border-amber-200 bg-amber-50 p-4 text-sm font-semibold text-amber-900">Manual evaluation template - no real LLM evaluation is claimed until an approved backend run record is returned.</section>;
    case "review":
      return (
        <section className="rounded-2xl border border-indigo-200 bg-indigo-50 p-5 shadow-sm">
          <div className="text-xs font-semibold uppercase tracking-wide text-indigo-700">Quality control policy</div>
          <div className="mt-4 grid gap-3 md:grid-cols-4">
            <SelectField label="Sampling strategy" options={["Random", "Risk-based", "Low-confidence", "All customer-impacting outputs"]} />
            <SelectField label="Review rate" options={["5%", "10%", "25%", "100%"]} />
            <SelectField label="Override process" options={["Reason code required", "Manager approval", "Two-reviewer consensus"]} />
            <SelectField label="Quality threshold" options={["90%", "95%", "98%", "Custom"]} />
          </div>
        </section>
      );
    case "deployment":
      return (
        <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
          <div className="text-xs font-semibold uppercase tracking-wide text-slate-600">Deployment boundary</div>
          <div className="mt-4 grid gap-3 md:grid-cols-4">
            <SelectField label="Deployment mode" options={["Offline analysis", "Internal assistant", "Reviewer draft", "Customer-facing controlled pilot"]} />
            <SelectField label="Change control" options={["Prompt only", "Prompt and sources", "Full model review", "Emergency rollback"]} />
            <SelectField label="Monitoring cadence" options={["Daily", "Weekly", "Monthly", "After each release"]} />
            <SelectField label="Incident escalation" options={["Model owner", "Risk owner", "Compliance owner", "Executive escalation"]} />
          </div>
        </section>
      );
    default:
      return null;
  }
}

export default function LlmWorkflowShell({ pageKey }: Props) {
  const navigate = useNavigate();
  const workflow = getWorkflowDefinition("llm_generative_ai");
  const page = useMemo(() => {
    if (!pageKey) return getLlmPageByStep(1);
    const pageIndex = workflow.steps.findIndex((_, index) => getLlmPageByStep(index + 1).key === pageKey);
    return getLlmPageByStep(pageIndex + 1);
  }, [pageKey, workflow.steps]);
  const currentStep = workflow.steps[page.stepNumber - 1];
  const nextStep = workflow.steps[page.stepNumber];

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
      nextLabel={nextStep ? `Continue to ${nextStep.label}` : "Save LLM Governance Package"}
      onNextClick={handleNext}
      nextStatusLine={`Save ${page.evidenceType} evidence and continue.`}
    >
      <div className="space-y-5">
        <section className="overflow-hidden rounded-2xl border border-slate-800 bg-slate-950 text-white shadow-xl">
          <div className="p-6">
            <div className="text-xs font-semibold uppercase tracking-wide text-violet-200">{page.eyebrow}</div>
            <h1 className="mt-2 text-3xl font-semibold">{page.title}</h1>
            <p className="mt-3 max-w-4xl text-sm leading-6 text-slate-200">{page.summary}</p>
          </div>
          <div className="grid border-t border-white/10 bg-white/5 md:grid-cols-4">
            <div className="p-4"><div className="text-xs uppercase text-slate-400">Step</div><div className="font-semibold">{page.stepNumber} of 12</div></div>
            <div className="p-4"><div className="text-xs uppercase text-slate-400">Evidence</div><div className="font-semibold">{page.evidenceType}</div></div>
            <div className="p-4"><div className="text-xs uppercase text-slate-400">Governance</div><div className="font-semibold">LLM controls</div></div>
            <div className="p-4"><div className="text-xs uppercase text-slate-400">Review</div><div className="font-semibold">Human accountable</div></div>
          </div>
        </section>

        <MetricStrip page={page} />

        <LlmPlanningWorkspace page={page} />

        <LlmVisualCenter page={page} />
        <PanelGrid page={page} />
        <CodePanel page={page} />
      </div>
    </StepShell>
  );
}
