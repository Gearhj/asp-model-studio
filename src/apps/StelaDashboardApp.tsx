import { useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  CheckCircle2,
  ChevronRight,
  FileSearch,
  FlaskConical,
  History,
  Landmark,
  ListFilter,
  MessageSquareText,
  Send,
  ShieldCheck,
  SlidersHorizontal,
} from "lucide-react";
import {
  loadStelaAnalytics,
  loadStelaV04,
  simulateStela,
  SimulationRequest,
  SimulationResponse,
  StelaAnalytics,
  StelaDashboardData,
  StelaRow,
} from "../lib/stelaApi";

type Section =
  | "overview"
  | "holdout"
  | "analytics"
  | "simulator"
  | "comparison"
  | "queue"
  | "detail"
  | "history"
  | "pilot";

type SortMode = "row_count" | "worsened_rate" | "lift";

type DashboardMode = "Validation Evidence" | "Production Monitoring" | "Pilot Assessment";

type DashboardContextFilters = {
  mode: DashboardMode;
  evidenceDataset: string;
  dateRange: string;
  businessUnit: string;
  channel: string;
  agentModel: string;
  stelaVersion: string;
  governanceDirective: string;
  intentCategory: string;
  outcome: string;
};

type BacklogAnnotation = {
  failure_type: string;
  severity: string;
  fix_type: string;
  notes: string;
};

type IssueCluster = {
  cluster_name: string;
  row_count: number;
  average_compliance_delta?: number;
  worsened_count: number;
  average_token_delta?: number;
  example_conversation_id?: string;
  suggested_priority: "high" | "medium" | "low";
};

const sections: Array<{ id: Section; label: string; icon: typeof ShieldCheck }> = [
  { id: "overview", label: "Executive Overview", icon: ShieldCheck },
  { id: "analytics", label: "Chat Analytics", icon: MessageSquareText },
  { id: "simulator", label: "Counterfactual Simulator", icon: FlaskConical },
  { id: "queue", label: "Worsened Queue", icon: ListFilter },
  { id: "detail", label: "Investigation", icon: FileSearch },
  { id: "history", label: "Evidence History", icon: History },
];

const defaultDashboardContextFilters: DashboardContextFilters = {
  mode: "Validation Evidence",
  evidenceDataset: "v0.4 Frozen Holdout",
  dateRange: "Frozen validation run",
  businessUnit: "All",
  channel: "All",
  agentModel: "All",
  stelaVersion: "v0.4",
  governanceDirective: "All",
  intentCategory: "All",
  outcome: "All",
};

function fmt(value: number | undefined | null, digits = 3) {
  if (value === undefined || value === null || Number.isNaN(value)) return "n/a";
  return value.toFixed(digits);
}

function signed(value: number | undefined | null, digits = 3) {
  if (value === undefined || value === null || Number.isNaN(value)) return "n/a";
  return `${value > 0 ? "+" : ""}${value.toFixed(digits)}`;
}

function percent(value: number | undefined | null, digits = 1) {
  if (value === undefined || value === null || Number.isNaN(value)) return "n/a";
  return `${(value * 100).toFixed(digits)}%`;
}

function shortText(value: string | undefined, length = 112) {
  if (!value) return "";
  return value.length > length ? `${value.slice(0, length - 1)}...` : value;
}

function labelForRow(row: StelaRow) {
  return row.intent || row.category || "Unlabeled";
}

function outcomeForRow(row: StelaRow) {
  if (row.outcome) return row.outcome;
  const delta = row.compliance_delta ?? 0;
  if (delta > 0) return "improved";
  if (delta < 0) return "worsened";
  return "unchanged";
}

function boolLabel(value: boolean | undefined) {
  if (value === undefined || value === null) return "n/a";
  return value ? "true" : "false";
}

function averageNumbers(values: Array<number | undefined | null>) {
  const filtered = values.filter((value): value is number => value !== undefined && value !== null && !Number.isNaN(value));
  if (!filtered.length) return undefined;
  return filtered.reduce((sum, value) => sum + value, 0) / filtered.length;
}

function priorityForCluster(worsenedCount: number, averageDelta?: number): IssueCluster["suggested_priority"] {
  if (worsenedCount >= 3 || (averageDelta ?? 0) <= -0.75) return "high";
  if (worsenedCount >= 1) return "medium";
  return "low";
}

function makeCluster(name: string, rows: StelaRow[]): IssueCluster {
  const averageDelta = averageNumbers(rows.map((row) => row.compliance_delta));
  const worsenedCount = rows.filter((row) => outcomeForRow(row) === "worsened").length;
  return {
    cluster_name: name,
    row_count: rows.length,
    average_compliance_delta: averageDelta,
    worsened_count: worsenedCount,
    average_token_delta: averageNumbers(rows.map((row) => row.token_delta)),
    example_conversation_id: rows[0]?.conversation_id,
    suggested_priority: priorityForCluster(worsenedCount, averageDelta),
  };
}

function buildIssueClusters(rows: StelaRow[]): IssueCluster[] {
  const clusters: IssueCluster[] = [];
  const worsenedRows = rows.filter((row) => outcomeForRow(row) === "worsened");

  const byLabel = new Map<string, StelaRow[]>();
  const byFailedCriteria = new Map<string, StelaRow[]>();
  const byFrictionCause = new Map<string, StelaRow[]>();

  for (const row of worsenedRows) {
    const label = labelForRow(row);
    byLabel.set(label, [...(byLabel.get(label) ?? []), row]);
    for (const criterion of row.failed_criteria_stela ?? []) {
      byFailedCriteria.set(criterion, [...(byFailedCriteria.get(criterion) ?? []), row]);
    }
    const causes = (row.stela_audit.friction_cause ?? []) as string[];
    for (const cause of causes) {
      byFrictionCause.set(cause, [...(byFrictionCause.get(cause) ?? []), row]);
    }
  }

  for (const [label, group] of byLabel) clusters.push(makeCluster(`Worsened intent/category: ${label}`, group));
  for (const [criterion, group] of byFailedCriteria) clusters.push(makeCluster(`Worsened STELA criterion: ${criterion}`, group));
  for (const [cause, group] of byFrictionCause) clusters.push(makeCluster(`Worsened friction cause: ${cause}`, group));

  const allByLabel = new Map<string, StelaRow[]>();
  for (const row of rows) {
    const label = labelForRow(row);
    allByLabel.set(label, [...(allByLabel.get(label) ?? []), row]);
  }
  const labelGroups = Array.from(allByLabel.entries()).map(([label, group]) => ({ label, group, avgDelta: averageNumbers(group.map((row) => row.compliance_delta)) ?? 0, avgToken: averageNumbers(group.map((row) => row.token_delta)) ?? 0 }));
  labelGroups
    .filter((item) => item.avgDelta < 0)
    .sort((a, b) => a.avgDelta - b.avgDelta)
    .slice(0, 5)
    .forEach((item) => clusters.push(makeCluster(`Largest negative delta: ${item.label}`, item.group)));
  labelGroups
    .sort((a, b) => a.avgToken - b.avgToken)
    .slice(0, 5)
    .forEach((item) => clusters.push(makeCluster(`Largest token reduction: ${item.label}`, item.group)));
  labelGroups
    .filter((item) => item.avgDelta > 0)
    .sort((a, b) => b.avgDelta - a.avgDelta)
    .slice(0, 5)
    .forEach((item) => clusters.push(makeCluster(`Highest lift intent/category: ${item.label}`, item.group)));

  return clusters
    .filter((cluster) => cluster.row_count > 0)
    .sort((a, b) => {
      const priorityOrder = { high: 3, medium: 2, low: 1 };
      return priorityOrder[b.suggested_priority] - priorityOrder[a.suggested_priority] || b.worsened_count - a.worsened_count || b.row_count - a.row_count;
    });
}

export default function StelaDashboardApp() {
  const [data, setData] = useState<StelaDashboardData | null>(null);
  const [analytics, setAnalytics] = useState<StelaAnalytics | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [section, setSection] = useState<Section>("overview");
  const [returnSection, setReturnSection] = useState<Section>("analytics");
  const [selectedDataset, setSelectedDataset] = useState("all");
  const [selectedRowId, setSelectedRowId] = useState<string | null>(null);
  const [annotations, setAnnotations] = useState<Record<string, BacklogAnnotation>>({});

  useEffect(() => {
    Promise.all([loadStelaV04(), loadStelaAnalytics()])
      .then(([payload, analyticsPayload]) => {
        setData(payload);
        setAnalytics(analyticsPayload);
        setSelectedRowId(payload.worsened_rows[0]?.id ?? payload.rows[0]?.id ?? null);
      })
      .catch((err: Error) => setError(err.message));
  }, []);

  const rows = data?.rows ?? [];
  const selectedRow = rows.find((row) => row.id === selectedRowId) ?? rows[0];

  const openRow = (row: StelaRow, source: Section = "analytics") => {
    setSelectedRowId(row.id);
    setReturnSection(source);
    setSection("detail");
  };

  const openSimulator = (row?: StelaRow) => {
    if (row) setSelectedRowId(row.id);
    setSection("simulator");
  };

  if (error) {
    return (
      <Shell section={section} setSection={setSection}>
        <div className="rounded-lg border border-red-200 bg-red-50 p-5 text-red-800">
          STELA data failed to load: {error}
        </div>
      </Shell>
    );
  }

  if (!data || !analytics) {
    return (
      <Shell section={section} setSection={setSection}>
        <div className="rounded-lg border border-slate-200 bg-white p-6">Loading STELA validation data...</div>
      </Shell>
    );
  }

  return (
    <Shell section={section} setSection={setSection}>
      {section === "overview" && <ExecutiveOverview data={data} setSection={setSection} />}
      {section === "holdout" && (
        <HoldoutResults data={data} selectedDataset={selectedDataset} setSelectedDataset={setSelectedDataset} setSection={setSection} />
      )}
      {section === "analytics" && (
        <ChatAnalytics
          data={data}
          analytics={analytics}
          selectedDataset={selectedDataset}
          setSelectedDataset={setSelectedDataset}
          setSection={setSection}
          onSelect={(row) => openRow(row, "analytics")}
          onSimulate={openSimulator}
        />
      )}
      {section === "simulator" && <CounterfactualSimulator data={data} selectedRow={selectedRow} />}
      {section === "comparison" && <DatasetComparison data={data} />}
      {section === "queue" && (
        <WorsenedQueue
          data={data}
          selectedDataset={selectedDataset}
          setSelectedDataset={setSelectedDataset}
          onSelect={(row) => openRow(row, "queue")}
        />
      )}
      {section === "detail" && (
        <InvestigationView
          row={selectedRow}
          returnSection={returnSection}
          setSection={setSection}
          openSimulator={openSimulator}
          annotation={selectedRow ? annotations[selectedRow.id] : undefined}
          setAnnotation={(annotation) => {
            if (!selectedRow) return;
            setAnnotations((current) => ({ ...current, [selectedRow.id]: annotation }));
          }}
        />
      )}
      {section === "history" && <EvidenceHistory data={data} />}
      {section === "pilot" && <PilotReadiness />}
    </Shell>
  );
}

function Shell({
  children,
  section,
  setSection,
}: {
  children: React.ReactNode;
  section: Section;
  setSection: (section: Section) => void;
}) {
  return (
    <div className="min-h-screen bg-slate-100 text-slate-950">
      <div className="flex min-h-screen">
        <aside className="hidden w-72 shrink-0 bg-slate-950 text-white lg:block">
          <div className="border-b border-white/10 px-6 py-6">
            <div className="flex items-center gap-3">
              <div className="grid h-10 w-10 place-items-center rounded-lg bg-emerald-500 text-slate-950">
                <Landmark size={22} />
              </div>
              <div>
                <div className="text-sm font-semibold">STELA</div>
                <div className="text-xs text-slate-400">AI Behavior Digital Twin</div>
              </div>
            </div>
          </div>
          <nav className="grid gap-1 px-3 py-4">
            {sections.map((item) => {
              const Icon = item.icon;
              const active = item.id === section;
              return (
                <button
                  key={item.id}
                  className={[
                    "flex min-h-11 items-center gap-3 rounded-md px-3 text-left text-sm font-medium",
                    active ? "bg-white text-slate-950" : "text-slate-300 hover:bg-white/10 hover:text-white",
                  ].join(" ")}
                  onClick={() => setSection(item.id)}
                >
                  <Icon size={17} />
                  <span>{item.label}</span>
                </button>
              );
            })}
          </nav>
        </aside>
        <div className="min-w-0 flex-1">
          <header className="border-b border-slate-200 bg-white">
            <div className="flex flex-col gap-3 px-5 py-4 md:px-8 lg:flex-row lg:items-center lg:justify-between">
              <div>
                <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Frozen unseen holdout</p>
                <h1 className="mt-1 text-2xl font-semibold text-slate-950">STELA AI Governance Dashboard</h1>
              </div>
              <div className="flex flex-wrap items-center gap-3">
                <div className="inline-flex w-fit items-center gap-2 rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-sm font-medium text-amber-900">
                  <AlertTriangle size={16} />
                  v0.4 evidence is read-only. Simulations are local previews, not scored reruns.
                </div>
              </div>
            </div>
          </header>
          <AskStelaBar setSection={setSection} />
          <main className="min-w-0 px-4 py-6 md:px-8">{children}</main>
        </div>
      </div>
    </div>
  );
}

type ChatMessage = {
  role: "user" | "assistant";
  content: string;
};

const starterQuestions = [
  "What does compliance lift mean?",
  "Why did STELA pass but not strong pass?",
  "Which issue cluster should I review first?",
  "How many rows worsened?",
  "Did STELA reduce token cost?",
  "What is the difference between v0.4 and v0.5?",
  "How do I use the Counterfactual Simulator?",
  "Show me the top risk intents.",
  "What does Task Completion First mean?",
  "How do I use Chat Analytics?",
  "What should I investigate first?",
];

function answerAskStela(question: string) {
  const q = question.toLowerCase();
  if (q.includes("investigate first") || q.includes("review first") || q.includes("start with")) {
    return "Start with the top issue cluster: 'answers the actual question directly.' It affects 17 worsened rows and is marked high priority. Open the issue cluster, review matching rows, and inspect the first example.";
  }
  if ((q.includes("strong") && q.includes("pass")) || q.includes("not strong")) {
    return "STELA passed because compliance lift was positive, friction was reduced, errors were zero, and the worsened-row rate was below the 5% pass threshold. It did not receive Strong Pass because the worsened-row rate was 3.6%, which is above the under-2% strong-result threshold.";
  }
  if (q.includes("pass") || q.includes("validation") || q.includes("status") || q.includes("overall result")) {
    return "STELA passed the frozen v0.4 unseen holdout validation. It evaluated 500 rows, improved 282, left 200 unchanged, worsened 18, achieved +0.375 compliance lift, reduced friction by -0.200, reduced average output length by 143.250 tokens, and had zero errors.";
  }
  if (q.includes("lift") || q.includes("37.5")) {
    return "Compliance lift measures the improvement from the original assistant response to the STELA-governed response. In v0.4, average compliance improved by +0.375, or +37.5 percentage points.";
  }
  if (q.includes("cluster") || q.includes("review first")) {
    return "Start with the highest-priority issue cluster: answers the actual question directly. It has 17 worsened rows and is a Task Completion First concern because it indicates missed direct task completion.";
  }
  if (q.includes("summary") || q.includes("metrics") || q.includes("v0.4 pass")) {
    return "v0.4 PASS summary: 500 rows evaluated, 282 improved, 200 unchanged, 18 worsened, compliance lift +0.375, friction change -0.200, token change -143.250, and worsened-row rate 3.6%.";
  }
  if (q.includes("worsened") || q.includes("worse")) {
    return "18 of 500 rows worsened, which is a 3.6% worsened-row rate. Use Worsened Queue or filter Chat Analytics to inspect those rows.";
  }
  if (q.includes("token") || q.includes("cost") || q.includes("shorter")) {
    return "STELA reduced average output length by 143.250 tokens. 478 rows had shorter STELA responses, 21 were longer, and 1 was the same length. This suggests STELA improved behavior while reducing average response cost.";
  }
  if (q.includes("v0.4") || q.includes("v0.5")) {
    return "v0.4 is the frozen unseen holdout validation result. It measures whether STELA improved banking and lending responses on unseen data. v0.5 is a separate governance-directive audit layer focused on Task Completion First. v0.5 does not replace or modify v0.4.";
  }
  if (q.includes("counterfactual") || q.includes("digital twin") || q.includes("simulator")) {
    return "The AI Behavior Digital Twin lets you preview how behavior would change under different governance conditions such as higher customer distress, higher fraud risk, authenticated session context, or lower-friction objectives. In this prototype, simulations are local previews and do not modify v0.4 evidence.";
  }
  if (q.includes("risk intent") || q.includes("top risk") || q.includes("intent")) {
    return "The top risk intents to review first are split_payment, find_branch, find_ATM, close_account, and make_transfer. Use Top Risk Intents to filter matching rows, inspect examples, or open a row in the AI Behavior Digital Twin.";
  }
  if (q.includes("task completion")) {
    return "Task Completion First is the v0.5 governance directive requiring the agent to provide procedural task-completion steps before redirecting the user to human support, unless escalation is genuinely required.";
  }
  if (q.includes("analytics") || q.includes("chat analytics")) {
    return "Use Chat Analytics to identify patterns, prioritize issue clusters, and drill into examples. Start with the Top Findings and Top Risk Intents, then review matching rows and open examples in Investigation or the AI Behavior Digital Twin.";
  }
  if (q.includes("investigation")) {
    return "Use Investigation to compare the original response and the STELA response side by side, review audit results, failed criteria, metadata, token impact, and state/context information.";
  }
  if (q.includes("friction")) {
    return "Average friction change is -0.200. Lower friction is better when task completion remains compliant; v0.5 focuses on avoiding unnecessary friction while preserving banking controls.";
  }
  return "I can answer questions about v0.4 validation metrics, v0.5 governance directives, issue clusters, risk intents, Chat Analytics, Investigation, and the AI Behavior Digital Twin. Try asking: 'What should I investigate first?' or 'Why did STELA pass but not strong pass?'";
}

function AskStelaBar({ setSection }: { setSection: (section: Section) => void }) {
  const [input, setInput] = useState("");
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const sendMessage = (text: string) => {
    const trimmed = text.trim();
    if (!trimmed) return;
    setMessages((current) => [...current, { role: "user", content: trimmed }, { role: "assistant", content: answerAskStela(trimmed) }]);
    setInput("");
  };
  return (
    <div className="sticky top-0 z-30 border-b border-sky-200 bg-sky-50/95 px-4 py-3 backdrop-blur md:px-8">
      <div className="flex flex-wrap items-center gap-2">
        <div className="flex shrink-0 items-center gap-1.5 text-sm font-semibold text-sky-800">
          <MessageSquareText size={16} />
          Ask STELA
        </div>
        <form className="flex min-w-[220px] flex-1 gap-2" onSubmit={(event) => { event.preventDefault(); sendMessage(input); }}>
          <input
            className="min-h-9 flex-1 rounded-md border border-sky-300 bg-white px-3 text-sm outline-none focus:border-sky-500"
            value={input}
            onChange={(event) => setInput(event.target.value)}
            placeholder="Ask about STELA metrics or workflows"
          />
          <button className="inline-flex min-h-9 items-center gap-1 rounded-md bg-sky-600 px-3 text-sm font-semibold text-white hover:bg-sky-700" type="submit">
            <Send size={15} />
            Send
          </button>
        </form>
        <span className="shrink-0 text-[11px] font-medium text-sky-700">Local dashboard assistant. No model call is made in this prototype.</span>
      </div>
      <div className="mt-2 flex flex-wrap gap-1.5">
        {starterQuestions.map((question) => (
          <button key={question} className="rounded-full border border-sky-200 bg-white px-2.5 py-1 text-[11px] font-semibold text-slate-700 hover:border-sky-400 hover:bg-sky-50" onClick={() => sendMessage(question)}>
            {question}
          </button>
        ))}
      </div>
      {messages.length > 0 && (
        <div className="mt-2 max-h-44 space-y-2 overflow-auto rounded-md border border-sky-200 bg-white p-3">
          {messages.map((message, index) => (
            <div key={`${message.role}-${index}`} className={`max-w-[90%] rounded-lg px-3 py-2 text-xs leading-5 ${message.role === "user" ? "ml-auto bg-slate-950 text-white" : "border border-sky-100 bg-sky-50 text-slate-700"}`}>
              {message.content}
            </div>
          ))}
          <div className="flex flex-wrap gap-1.5 pt-1">
            <button className="rounded-md border border-sky-200 bg-white px-2.5 py-1 text-[11px] font-semibold text-slate-600 hover:bg-sky-50" onClick={() => setMessages([])}>Clear</button>
            <button className="rounded-md border border-sky-200 bg-white px-2.5 py-1 text-[11px] font-semibold text-slate-600 hover:bg-sky-50" onClick={() => setSection("analytics")}>Chat Analytics</button>
            <button className="rounded-md border border-sky-200 bg-white px-2.5 py-1 text-[11px] font-semibold text-slate-600 hover:bg-sky-50" onClick={() => setSection("simulator")}>Digital Twin</button>
          </div>
        </div>
      )}
    </div>
  );
}

function ExecutiveOverview({ data, setSection }: { data: StelaDashboardData; setSection: (section: Section) => void }) {
  const combined = data.combined;
  const [contextFilters, setContextFilters] = useState<DashboardContextFilters>(defaultDashboardContextFilters);
  return (
    <div className="space-y-6">
      <DashboardContextBar filters={contextFilters} setFilters={setContextFilters} />

      <section className="grid gap-4 xl:grid-cols-[1.1fr_1.9fr]">
        <div className="rounded-lg border border-emerald-200 bg-white p-6">
          <div className="flex items-center justify-between gap-4">
            <div>
              <p className="text-xs font-semibold uppercase tracking-wide text-emerald-700">Holdout status</p>
              <div className="mt-3 text-6xl font-semibold tracking-tight text-emerald-700">PASS</div>
            </div>
            <CheckCircle2 className="text-emerald-600" size={58} />
          </div>
          <p className="mt-5 text-sm leading-6 text-slate-600">
            STELA passed a frozen 500-row unseen holdout evaluation on structured public banking and lending chatbot data.
          </p>
          <div className="mt-5 flex flex-wrap gap-2">
            <button className="inline-flex items-center gap-2 rounded-md bg-slate-950 px-4 py-2 text-sm font-semibold text-white" onClick={() => setSection("analytics")}>
              Open chat analytics
              <ChevronRight size={16} />
            </button>
            <button className="inline-flex items-center gap-2 rounded-md border border-slate-300 bg-white px-4 py-2 text-sm font-semibold text-slate-800" onClick={() => setSection("simulator")}>
              Open AI Behavior Digital Twin
              <FlaskConical size={16} />
            </button>
            <button className="inline-flex items-center gap-2 rounded-md border border-slate-300 bg-white px-4 py-2 text-sm font-semibold text-slate-800" onClick={() => setSection("history")}>
              View validation evidence
              <History size={16} />
            </button>
          </div>
        </div>
        <div className="grid gap-3 md:grid-cols-5">
          <Kpi label="Compliance Lift" value="+37.5 pts" tone="emerald" />
          <Kpi label="Friction Change" value="-20.0 pts" tone="emerald" />
          <Kpi label="Worsened Rate" value="3.6%" tone="amber" />
          <Kpi label="Token Change" value="-143.25" tone="emerald" />
          <Kpi label="Errors" value="0" tone="emerald" />
        </div>
      </section>

      <DatasetTable datasets={combined.datasets} />

      <section className="grid gap-4 lg:grid-cols-2">
        <CriteriaCard title="Pass criteria" items={[
          ["Compliance lift > 0", true],
          ["Worsened-row rate under 5%", true],
          ["Generation errors = 0", true],
          ["Original audit errors = 0", true],
          ["STELA audit errors = 0", true],
          ["Friction change neutral or negative", true],
        ]} />
        <CriteriaCard title="Strong result criteria" items={[
          ["Compliance lift >= +0.10", true],
          ["Worsened-row rate under 2%", false],
          ["Generation errors = 0", true],
          ["Audit errors = 0", true],
          ["Friction change negative", true],
          ["Token change neutral or negative", true],
        ]} note="PASS, not STRONG PASS, because worsened-row rate was 3.6%, above the under-2% strong threshold." />
      </section>
    </div>
  );
}

function DashboardContextBar({
  filters,
  setFilters,
}: {
  filters: DashboardContextFilters;
  setFilters: (filters: DashboardContextFilters) => void;
}) {
  const validationMode = filters.mode === "Validation Evidence";
  const [expanded, setExpanded] = useState(false);

  const updateFilter = <Key extends keyof DashboardContextFilters>(key: Key, value: DashboardContextFilters[Key]) => {
    if (key === "mode") {
      setFilters({
        ...filters,
        mode: value as DashboardMode,
        dateRange: value === "Validation Evidence" ? "Frozen validation run" : "Last 30 days",
      });
      return;
    }
    setFilters({ ...filters, [key]: value });
  };

  const filterFields: Array<{
    id: keyof DashboardContextFilters;
    label: string;
    options: string[];
    disabled?: boolean;
  }> = [
    { id: "mode", label: "Mode", options: ["Validation Evidence", "Production Monitoring", "Pilot Assessment"] },
    { id: "evidenceDataset", label: "Evidence / Dataset", options: ["v0.4 Frozen Holdout", "v0.5 Governance Directive", "All Evidence"] },
    {
      id: "dateRange",
      label: "Date Range",
      options: validationMode ? ["Frozen validation run"] : ["Last 24 hours", "Last 7 days", "Last 30 days", "Quarter", "Year", "Custom"],
      disabled: validationMode,
    },
    { id: "businessUnit", label: "Business Unit", options: ["All", "Retail Banking", "Mortgage / Loans", "Credit Cards", "Deposits", "Fraud"] },
    { id: "channel", label: "Channel", options: ["All", "Chatbot", "Voice Agent", "Email Assistant", "Internal Agent"] },
    { id: "agentModel", label: "Agent / Model", options: ["All", "Agent v1", "Agent v2", "Custom"] },
    { id: "stelaVersion", label: "STELA Version", options: ["All", "v0.4", "v0.5"] },
    { id: "governanceDirective", label: "Governance Directive", options: ["All", "Task Completion First", "None / General"] },
    { id: "intentCategory", label: "Intent / Category", options: ["All", "Account", "Payment", "Personal Information", "Loan Application", "Card Servicing"] },
    { id: "outcome", label: "Outcome", options: ["All", "Improved", "Unchanged", "Worsened"] },
  ];

  return (
    <section className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
        <div>
          <div className="inline-flex items-center gap-2 rounded-md border border-slate-200 bg-slate-50 px-2.5 py-1 text-xs font-semibold uppercase tracking-wide text-slate-600">
            <SlidersHorizontal size={14} />
            Dashboard Context
          </div>
          <p className="mt-2 text-sm leading-6 text-slate-600">
            {validationMode
              ? "Current view: frozen v0.4 unseen holdout validation. Date range does not apply."
              : "Production and pilot monitoring filters are UI-ready placeholders. Current metrics are from the frozen v0.4 validation evidence package."}
          </p>
          <div className="mt-3 flex flex-wrap gap-2 text-xs font-semibold text-slate-600">
            <span className="rounded-md bg-slate-100 px-2.5 py-1">{filters.mode}</span>
            <span className="rounded-md bg-slate-100 px-2.5 py-1">{filters.evidenceDataset}</span>
            <span className="rounded-md bg-slate-100 px-2.5 py-1">{filters.stelaVersion}</span>
            <span className="rounded-md bg-slate-100 px-2.5 py-1">Outcome: {filters.outcome}</span>
          </div>
        </div>
        <div className="flex flex-wrap gap-2">
          {expanded && (
            <button
              className="inline-flex min-h-9 w-fit items-center justify-center rounded-md border border-slate-300 bg-white px-3 text-sm font-semibold text-slate-700 hover:border-slate-500"
              onClick={() => setFilters(defaultDashboardContextFilters)}
            >
              Reset Filters
            </button>
          )}
          <button
            className="inline-flex min-h-9 w-fit items-center justify-center rounded-md bg-slate-950 px-3 text-sm font-semibold text-white hover:bg-slate-800"
            onClick={() => setExpanded((current) => !current)}
            aria-expanded={expanded}
          >
            {expanded ? "Hide Filters" : "Show Filters"}
          </button>
        </div>
      </div>

      {expanded && (
        <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-3 2xl:grid-cols-5">
          {filterFields.map((field) => (
            <label key={field.id} className="grid gap-1 text-sm font-medium text-slate-700">
              <span>{field.label}</span>
              <select
                className={[
                  "min-h-10 rounded-md border px-3 py-2 text-sm font-medium",
                  field.disabled ? "border-slate-200 bg-slate-100 text-slate-500" : "border-slate-300 bg-white text-slate-900",
                ].join(" ")}
                value={filters[field.id]}
                disabled={field.disabled}
                onChange={(event) => updateFilter(field.id, event.target.value)}
              >
                {field.options.map((option) => (
                  <option key={option} value={option}>
                    {option}
                  </option>
                ))}
              </select>
            </label>
          ))}
        </div>
      )}
    </section>
  );
}

function ChatAnalytics({
  data,
  analytics,
  selectedDataset,
  setSelectedDataset,
  setSection,
  onSelect,
  onSimulate,
}: {
  data: StelaDashboardData;
  analytics: StelaAnalytics;
  selectedDataset: string;
  setSelectedDataset: (value: string) => void;
  setSection: (section: Section) => void;
  onSelect: (row: StelaRow) => void;
  onSimulate: (row?: StelaRow) => void;
}) {
  const [outcomeFilter, setOutcomeFilter] = useState("all");
  const [intentFilter, setIntentFilter] = useState("all");
  const [deltaMin, setDeltaMin] = useState(-1);
  const [deltaMax, setDeltaMax] = useState(1);
  const [frictionFilter, setFrictionFilter] = useState("all");
  const [tokenFilter, setTokenFilter] = useState("all");
  const [originalMin, setOriginalMin] = useState(0);
  const [originalMax, setOriginalMax] = useState(1);
  const [stelaMin, setStelaMin] = useState(0);
  const [stelaMax, setStelaMax] = useState(1);
  const [criteriaSearch, setCriteriaSearch] = useState("");
  const [messageSearch, setMessageSearch] = useState("");
  const [sortMode, setSortMode] = useState<SortMode>("row_count");
  const [filtersExpanded, setFiltersExpanded] = useState(false);
  const [activeCluster, setActiveCluster] = useState<IssueCluster | null>(null);
  const [issueTableExpanded, setIssueTableExpanded] = useState(false);
  const [failureCriteriaExpanded, setFailureCriteriaExpanded] = useState(false);

  const intentOptions = useMemo(() => {
    const values = new Set<string>();
    data.rows.forEach((row) => values.add(labelForRow(row)));
    return Array.from(values).sort();
  }, [data.rows]);

  const resetFilters = () => {
    setSelectedDataset("all");
    setOutcomeFilter("all");
    setIntentFilter("all");
    setDeltaMin(-1);
    setDeltaMax(1);
    setFrictionFilter("all");
    setTokenFilter("all");
    setOriginalMin(0);
    setOriginalMax(1);
    setStelaMin(0);
    setStelaMax(1);
    setCriteriaSearch("");
    setMessageSearch("");
    setActiveCluster(null);
  };

  const filteredRows = useMemo(() => {
    const criteriaNeedle = criteriaSearch.trim().toLowerCase();
    const messageNeedle = messageSearch.trim().toLowerCase();
    return data.rows.filter((row) => {
      const outcome = outcomeForRow(row);
      const delta = row.compliance_delta ?? 0;
      const friction = row.friction_delta ?? 0;
      const token = row.token_delta ?? 0;
      const failedText = [...(row.failed_criteria_original ?? []), ...(row.failed_criteria_stela ?? [])].join(" ").toLowerCase();
      if (selectedDataset !== "all" && row.dataset_id !== selectedDataset) return false;
      if (outcomeFilter !== "all" && outcome !== outcomeFilter) return false;
      if (intentFilter !== "all" && labelForRow(row) !== intentFilter) return false;
      if (delta < deltaMin || delta > deltaMax) return false;
      if (frictionFilter === "increased" && friction <= 0) return false;
      if (frictionFilter === "decreased" && friction >= 0) return false;
      if (frictionFilter === "unchanged" && friction !== 0) return false;
      if (tokenFilter === "increased" && token <= 0) return false;
      if (tokenFilter === "decreased" && token >= 0) return false;
      if (tokenFilter === "unchanged" && token !== 0) return false;
      if ((row.original_compliance ?? 0) < originalMin || (row.original_compliance ?? 0) > originalMax) return false;
      if ((row.stela_compliance ?? 0) < stelaMin || (row.stela_compliance ?? 0) > stelaMax) return false;
      if (criteriaNeedle && !failedText.includes(criteriaNeedle)) return false;
      if (messageNeedle && !(row.user_message ?? "").toLowerCase().includes(messageNeedle)) return false;
      if (activeCluster && !rowMatchesIssueCluster(row, activeCluster)) return false;
      return true;
    });
  }, [activeCluster, criteriaSearch, data.rows, deltaMax, deltaMin, frictionFilter, intentFilter, messageSearch, originalMax, originalMin, outcomeFilter, selectedDataset, stelaMax, stelaMin, tokenFilter]);

  const sortedIntentPerformance = useMemo(() => {
    const rows = [...analytics.intent_category_performance];
    rows.sort((a, b) => {
      if (sortMode === "worsened_rate") return b.worsened_rate - a.worsened_rate;
      if (sortMode === "lift") return (b.average_lift ?? 0) - (a.average_lift ?? 0);
      return b.row_count - a.row_count;
    });
    return rows;
  }, [analytics.intent_category_performance, sortMode]);
  const allIssueClusters = useMemo(() => buildIssueClusters(data.rows), [data.rows]);
  const issueClusters = useMemo(() => buildIssueClusters(filteredRows), [filteredRows]);
  const topIssueClusters = allIssueClusters.slice(0, 5);
  const topCluster = topIssueClusters[0];
  const rowPreview = filteredRows.slice(0, 8);
  const activeClusterFocus = useMemo(() => {
    if (!activeCluster) return null;
    const clusterRows = data.rows.filter((row) => rowMatchesIssueCluster(row, activeCluster));
    return buildSelectedFocus("Issue cluster", activeCluster.cluster_name, clusterRows, activeCluster.suggested_priority);
  }, [activeCluster, data.rows]);
  const activeIntentFocus = useMemo(() => {
    if (intentFilter !== "all") {
      const intentRows = data.rows.filter((row) => labelForRow(row) === intentFilter);
      return buildSelectedFocus("Intent/category", intentFilter, intentRows);
    }
    return null;
  }, [data.rows, intentFilter]);

  return (
    <div className="space-y-6">
      <section className="grid gap-4 xl:grid-cols-2">
        <PerformanceSummary combined={data.combined} />
        <TopFindings
          combined={data.combined}
          tokenEfficiency={analytics.token_efficiency}
          topCluster={topCluster}
          onWorsened={() => {
            setOutcomeFilter("worsened");
            document.getElementById("filtered-row-preview")?.scrollIntoView({ behavior: "smooth", block: "start" });
          }}
          onToken={() => {
            setTokenFilter("decreased");
            document.getElementById("token-efficiency-detail")?.scrollIntoView({ behavior: "smooth", block: "start" });
          }}
          onCluster={(cluster) => {
            setActiveCluster(cluster);
            document.getElementById("issue-cluster-priority")?.scrollIntoView({ behavior: "smooth", block: "start" });
          }}
          onFriction={() => {
            setFrictionFilter("increased");
            document.getElementById("visual-summary-charts")?.scrollIntoView({ behavior: "smooth", block: "start" });
          }}
          onEvidence={() => setSection("history")}
        />
      </section>

      <section id="visual-summary-charts" className="grid gap-4 xl:grid-cols-3">
        <OutcomeDistributionCard
          rows={data.combined.rows}
          improved={data.combined.improved}
          unchanged={data.combined.unchanged}
          worsened={data.combined.worsened}
          onSelect={setOutcomeFilter}
        />
        <FrictionMovementCard analytics={analytics} onSelect={setFrictionFilter} />
        <TokenEfficiencySummaryCard analytics={analytics} onSelect={setTokenFilter} />
      </section>

      <section className="grid gap-4 lg:grid-cols-2">
        <TopRiskIntents
          rows={analytics.intent_category_performance}
          allRows={data.rows}
          selectedIntent={intentFilter}
          onSelectIntent={(intent) => {
            setIntentFilter(intent);
            setActiveCluster(null);
            document.getElementById("filtered-row-preview")?.scrollIntoView({ behavior: "smooth", block: "start" });
          }}
          onInspect={(intent) => {
            const row = data.rows.find((candidate) => labelForRow(candidate) === intent);
            if (row) onSelect(row);
          }}
          onSimulate={(intent) => {
            const row = data.rows.find((candidate) => labelForRow(candidate) === intent);
            if (row) onSimulate(row);
          }}
        />
        <IssueClusterPriorityChart
          rows={topIssueClusters}
          activeCluster={activeCluster}
          focus={activeClusterFocus}
          onSelect={(cluster) => setActiveCluster(cluster)}
          onInspect={(cluster) => {
            const row = data.rows.find((candidate) => rowMatchesIssueCluster(candidate, cluster));
            if (row) onSelect(row);
          }}
          onViewRows={() => document.getElementById("filtered-row-preview")?.scrollIntoView({ behavior: "smooth", block: "start" })}
          onInvestigate={() => {
            if (activeClusterFocus?.firstRow) onSelect(activeClusterFocus.firstRow);
          }}
          onSimulate={() => {
            if (activeClusterFocus?.firstRow) onSimulate(activeClusterFocus.firstRow);
          }}
        />
      </section>

      <AdvancedFiltersPanel
        expanded={filtersExpanded}
        setExpanded={setFiltersExpanded}
        activeCluster={activeCluster}
        clearCluster={() => setActiveCluster(null)}
        resetFilters={resetFilters}
        selectedDataset={selectedDataset}
        setSelectedDataset={setSelectedDataset}
        datasets={data.combined.datasets}
        outcomeFilter={outcomeFilter}
        setOutcomeFilter={setOutcomeFilter}
        intentFilter={intentFilter}
        setIntentFilter={setIntentFilter}
        intentOptions={intentOptions}
        frictionFilter={frictionFilter}
        setFrictionFilter={setFrictionFilter}
        tokenFilter={tokenFilter}
        setTokenFilter={setTokenFilter}
        deltaMin={deltaMin}
        setDeltaMin={setDeltaMin}
        deltaMax={deltaMax}
        setDeltaMax={setDeltaMax}
        originalMin={originalMin}
        setOriginalMin={setOriginalMin}
        originalMax={originalMax}
        setOriginalMax={setOriginalMax}
        stelaMin={stelaMin}
        setStelaMin={setStelaMin}
        stelaMax={stelaMax}
        setStelaMax={setStelaMax}
        criteriaSearch={criteriaSearch}
        setCriteriaSearch={setCriteriaSearch}
        messageSearch={messageSearch}
        setMessageSearch={setMessageSearch}
      />

      <IntentPerformanceTable
        rows={sortedIntentPerformance}
        sortMode={sortMode}
        setSortMode={setSortMode}
        selectedIntent={intentFilter}
        focus={activeIntentFocus}
        onSelectIntent={(intent) => {
          setIntentFilter(intent);
          setActiveCluster(null);
        }}
        onViewRows={() => document.getElementById("filtered-row-preview")?.scrollIntoView({ behavior: "smooth", block: "start" })}
        onInvestigate={() => {
          if (activeIntentFocus?.firstRow) onSelect(activeIntentFocus.firstRow);
        }}
        onSimulate={() => {
          if (activeIntentFocus?.firstRow) onSimulate(activeIntentFocus.firstRow);
        }}
      />

      <FilteredRowPreview rows={rowPreview} totalRows={filteredRows.length} onSelect={onSelect} onSimulate={onSimulate} />

      <section>
        <div className="mb-3">
          <h3 className="font-semibold text-slate-950">Efficiency and Failure Signals</h3>
          <p className="mt-1 text-sm text-slate-600">Token impact and highest-priority failed criteria in the current validation view.</p>
        </div>
        <div className="grid gap-4 xl:grid-cols-2">
          <TokenEfficiency analytics={analytics} />

          <FailureCriteriaSummary
            rows={analytics.failure_criteria}
            expanded={failureCriteriaExpanded}
            setExpanded={setFailureCriteriaExpanded}
            selectedCriterion={criteriaSearch}
            onSelectCriterion={(criterion) => {
              setCriteriaSearch(criterion);
              setActiveCluster(null);
            }}
            onInspect={(conversationId) => {
              const row = data.rows.find((candidate) => candidate.conversation_id === conversationId);
              if (row) onSelect(row);
            }}
          />
        </div>
      </section>

      <CollapsibleIssueClustersTable
        rows={issueClusters}
        expanded={issueTableExpanded}
        setExpanded={setIssueTableExpanded}
        onSelectCluster={setActiveCluster}
        onInspect={(cluster) => {
          const row = data.rows.find((candidate) => rowMatchesIssueCluster(candidate, cluster));
          if (row) onSelect(row);
        }}
      />

      <RowExplorer rows={filteredRows} onSelect={onSelect} />
    </div>
  );
}

function rowMatchesIssueCluster(row: StelaRow, cluster: IssueCluster) {
  const label = labelForRow(row);
  const failedCriteria = [...(row.failed_criteria_original ?? []), ...(row.failed_criteria_stela ?? [])];
  const frictionCauses = (row.stela_audit.friction_cause ?? []) as string[];
  if (cluster.cluster_name.startsWith("Worsened intent/category: ")) {
    return label === cluster.cluster_name.replace("Worsened intent/category: ", "");
  }
  if (cluster.cluster_name.startsWith("Largest negative delta: ")) {
    return label === cluster.cluster_name.replace("Largest negative delta: ", "");
  }
  if (cluster.cluster_name.startsWith("Largest token reduction: ")) {
    return label === cluster.cluster_name.replace("Largest token reduction: ", "");
  }
  if (cluster.cluster_name.startsWith("Highest lift intent/category: ")) {
    return label === cluster.cluster_name.replace("Highest lift intent/category: ", "");
  }
  if (cluster.cluster_name.startsWith("Worsened STELA criterion: ")) {
    return failedCriteria.includes(cluster.cluster_name.replace("Worsened STELA criterion: ", ""));
  }
  if (cluster.cluster_name.startsWith("Worsened friction cause: ")) {
    return frictionCauses.includes(cluster.cluster_name.replace("Worsened friction cause: ", ""));
  }
  return false;
}

function mostCommonFrictionCause(rows: StelaRow[]) {
  const counts = new Map<string, number>();
  rows.forEach((row) => {
    ((row.stela_audit.friction_cause ?? []) as string[]).forEach((cause) => {
      counts.set(cause, (counts.get(cause) ?? 0) + 1);
    });
  });
  return Array.from(counts.entries()).sort((a, b) => b[1] - a[1])[0];
}

function buildSelectedFocus(type: "Intent/category" | "Issue cluster", name: string, rows: StelaRow[], priority?: IssueCluster["suggested_priority"]) {
  const worsenedCount = rows.filter((row) => outcomeForRow(row) === "worsened").length;
  const averageOriginal = averageNumbers(rows.map((row) => row.original_compliance));
  const averageStela = averageNumbers(rows.map((row) => row.stela_compliance));
  const averageDelta = averageNumbers(rows.map((row) => row.compliance_delta));
  const averageToken = averageNumbers(rows.map((row) => row.token_delta));
  const action =
    worsenedCount >= 3
      ? "High priority backlog review"
      : worsenedCount >= 1
        ? "Review examples"
        : (averageDelta ?? 0) > 0 && (averageToken ?? 0) < -100
          ? "Potential efficiency win"
          : (averageDelta ?? 0) > 0
            ? "Monitor as strong performer"
            : "Review examples";
  return {
    type,
    name,
    rowsAffected: rows.length,
    worsenedCount,
    worsenedRate: rows.length ? worsenedCount / rows.length : 0,
    averageOriginal,
    averageStela,
    averageDelta,
    averageToken,
    priority,
    action,
    firstRow: rows[0],
  };
}

function OutcomeDistributionCard({
  rows,
  improved,
  unchanged,
  worsened,
  onSelect,
}: {
  rows: number;
  improved: number;
  unchanged: number;
  worsened: number;
  onSelect: (outcome: string) => void;
}) {
  const segments = [
    { label: "Improved", value: improved, outcome: "improved", color: "bg-emerald-500" },
    { label: "Unchanged", value: unchanged, outcome: "unchanged", color: "bg-slate-400" },
    { label: "Worsened", value: worsened, outcome: "worsened", color: "bg-amber-500" },
  ];
  const max = Math.max(...segments.map((segment) => segment.value), 1);
  return (
    <div className="rounded-lg border border-slate-200 bg-white p-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h3 className="font-semibold text-slate-950">Outcome Distribution</h3>
          <p className="mt-1 text-xs text-slate-600">Click a segment to filter matching rows.</p>
        </div>
        <button className="text-xs font-semibold text-slate-500 hover:text-slate-900" onClick={() => onSelect("all")}>Clear</button>
      </div>
      <div className="mt-3 grid gap-2.5">
        {segments.map((segment) => (
          <button
            key={segment.outcome}
            className="text-left"
            title={`${segment.label}: ${segment.value} (${percent(segment.value / rows)})`}
            onClick={() => onSelect(segment.outcome)}
            aria-label={`Filter ${segment.label}`}
          >
            <div className="mb-1 flex justify-between text-xs font-medium text-slate-600">
              <span>{segment.label}</span>
              <span>{segment.value} ({percent(segment.value / rows)})</span>
            </div>
            <div className="h-2.5 overflow-hidden rounded-full bg-slate-100">
              <div className={`h-full rounded-full ${segment.color}`} style={{ width: `${Math.max((segment.value / max) * 100, 2)}%` }} />
            </div>
          </button>
        ))}
      </div>
    </div>
  );
}

function FrictionMovementCard({ analytics, onSelect }: { analytics: StelaAnalytics; onSelect: (value: string) => void }) {
  const bars = [
    { label: "Friction reduced", value: analytics.friction_movement.reduced, filter: "decreased", tone: "bg-emerald-500" },
    { label: "Friction unchanged", value: analytics.friction_movement.unchanged, filter: "unchanged", tone: "bg-slate-400" },
    { label: "Friction increased", value: analytics.friction_movement.increased, filter: "increased", tone: "bg-amber-500" },
  ];
  const max = Math.max(...bars.map((bar) => bar.value), 1);
  return (
    <div className="rounded-lg border border-slate-200 bg-white p-4">
      <h3 className="font-semibold text-slate-950">Friction Movement</h3>
      <p className="mt-1 text-xs text-slate-600">STELA almost never increased friction.</p>
      <div className="mt-3 grid gap-2.5">
        {bars.map((bar) => (
          <button key={bar.filter} className="text-left" onClick={() => onSelect(bar.filter)}>
            <div className="mb-1 flex justify-between text-xs font-medium text-slate-600"><span>{bar.label}</span><span>{bar.value}</span></div>
            <div className="h-2.5 overflow-hidden rounded-full bg-slate-100">
              <div className={`h-full rounded-full ${bar.tone}`} style={{ width: `${Math.max((bar.value / max) * 100, 2)}%` }} />
            </div>
          </button>
        ))}
      </div>
    </div>
  );
}

function TokenEfficiencySummaryCard({ analytics, onSelect }: { analytics: StelaAnalytics; onSelect: (value: string) => void }) {
  const shorter = analytics.token_efficiency.stela_shorter_count;
  const longer = analytics.token_efficiency.stela_longer_count;
  const same = analytics.token_efficiency.stela_same_count;
  const max = Math.max(shorter, longer, same, 1);
  return (
    <div className="rounded-lg border border-slate-200 bg-white p-4">
      <h3 className="font-semibold text-slate-950">Token Efficiency</h3>
      <p className="mt-1 text-xs text-slate-600">Negative token change indicates shorter STELA output.</p>
      <div className="mt-3 grid gap-2.5">
        {[
          ["Shorter STELA responses", shorter, "decreased", "bg-emerald-500"],
          ["Longer STELA responses", longer, "increased", "bg-amber-500"],
          ["Same length", same, "unchanged", "bg-slate-400"],
        ].map(([label, value, filter, color]) => (
          <button key={String(label)} className="text-left" onClick={() => onSelect(String(filter))}>
            <div className="mb-1 flex justify-between text-xs font-medium text-slate-600"><span>{label}</span><span>{String(value)}</span></div>
            <div className="h-2.5 overflow-hidden rounded-full bg-slate-100">
              <div className={`h-full rounded-full ${color}`} style={{ width: `${Math.max((Number(value) / max) * 100, 2)}%` }} />
            </div>
          </button>
        ))}
      </div>
      <div className="mt-3 rounded-md bg-emerald-50 px-3 py-2 text-sm font-semibold text-emerald-800">Average token change: {signed(analytics.token_efficiency.average_token_change)}</div>
    </div>
  );
}

function PerformanceSummary({ combined }: { combined: StelaDashboardData["combined"] }) {
  const metrics = [
    { label: "Total rows", value: String(combined.rows), tone: "slate" },
    { label: "Improved", value: String(combined.improved), tone: "emerald" },
    { label: "Unchanged", value: String(combined.unchanged), tone: "slate" },
    { label: "Worsened", value: String(combined.worsened), tone: "amber" },
    { label: "Avg lift", value: signed(combined.average_compliance_lift), tone: "emerald" },
    { label: "Friction", value: signed(combined.average_friction_change), tone: "emerald" },
    { label: "Token", value: signed(combined.average_token_change), tone: "emerald" },
  ] as const;
  return (
    <section className="rounded-lg border border-slate-200 bg-white p-4">
      <div className="flex items-center justify-between gap-3">
        <div>
          <h3 className="font-semibold text-slate-950">Performance Summary</h3>
          <p className="mt-1 text-sm text-slate-600">Frozen v0.4 holdout metrics.</p>
        </div>
        <Badge tone="emerald">PASS</Badge>
      </div>
      <div className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-3 xl:grid-cols-4">
        {metrics.map((metric) => (
          <CompactMetric key={metric.label} label={metric.label} value={metric.value} tone={metric.tone} />
        ))}
      </div>
    </section>
  );
}

function CompactMetric({ label, value, tone }: { label: string; value: string; tone: "emerald" | "amber" | "slate" }) {
  const color = tone === "emerald" ? "text-emerald-700" : tone === "amber" ? "text-amber-700" : "text-slate-950";
  return (
    <div className="rounded-md bg-slate-50 px-3 py-2">
      <div className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">{label}</div>
      <div className={`mt-1 text-lg font-semibold ${color}`}>{value}</div>
    </div>
  );
}

function HowToUseChatAnalytics() {
  return (
    <div className="rounded-lg border border-slate-200 bg-white p-5">
      <h3 className="font-semibold text-slate-950">How to use Chat Analytics</h3>
      <p className="mt-2 text-sm leading-6 text-slate-600">
        Use this page to visually identify behavior patterns, prioritize issue clusters, and drill into row-level examples. Start with the visual summary, risk matrix, or issue clusters, then open examples in Investigation or the AI Behavior Digital Twin.
      </p>
    </div>
  );
}

function TopFindings({
  combined,
  tokenEfficiency,
  topCluster,
  onWorsened,
  onToken,
  onCluster,
  onFriction,
  onEvidence,
}: {
  combined: StelaDashboardData["combined"];
  tokenEfficiency: StelaAnalytics["token_efficiency"];
  topCluster?: IssueCluster;
  onWorsened: () => void;
  onToken: () => void;
  onCluster: (cluster: IssueCluster) => void;
  onFriction: () => void;
  onEvidence: () => void;
}) {
  const findings = [
    { title: "Review worsened rows", description: `${combined.worsened} rows worsened out of ${combined.rows}.`, action: "View rows", onClick: onWorsened },
    { title: "Token efficiency gain", description: `${tokenEfficiency.stela_shorter_count} rows had shorter STELA responses; average token change ${signed(tokenEfficiency.average_token_change)}.`, action: "Review token detail", onClick: onToken },
    topCluster ? { title: "Top issue cluster", description: `${topCluster.cluster_name.replace(/^Worsened STELA criterion: /, "")}, ${topCluster.worsened_count} worsened rows.`, action: "Open issue cluster", onClick: () => onCluster(topCluster) } : null,
    { title: "Friction stayed controlled", description: "Friction increased in only 1 row.", action: "Review friction", onClick: onFriction },
    { title: "Pass but not strong pass", description: "Worsened-row rate was 3.6%, below pass threshold but above strong-result threshold.", action: "View evidence", onClick: onEvidence },
  ].filter((item): item is { title: string; description: string; action: string; onClick: () => void } => Boolean(item)).slice(0, 5);
  return (
    <div className="rounded-lg border border-slate-200 bg-white p-4">
      <div>
        <h3 className="font-semibold text-slate-950">Top Findings</h3>
        <p className="mt-1 text-sm text-slate-600">Prioritized actions from the current view.</p>
      </div>
      <div className="mt-3 grid gap-2">
        {findings.map((finding) => (
          <button key={finding.title} className="grid gap-1 rounded-md border border-slate-200 bg-slate-50 px-3 py-2 text-left hover:border-emerald-300 hover:bg-emerald-50" onClick={finding.onClick}>
            <span className="flex items-center justify-between gap-3">
              <span className="text-sm font-semibold text-slate-950">{finding.title}</span>
              <span className="text-xs font-semibold text-emerald-700">{finding.action}</span>
            </span>
            <span className="text-xs leading-5 text-slate-600">{finding.description}</span>
            </button>
        ))}
      </div>
    </div>
  );
}

function TopRiskIntents({
  rows,
  allRows,
  selectedIntent,
  onSelectIntent,
  onInspect,
  onSimulate,
}: {
  rows: StelaAnalytics["intent_category_performance"];
  allRows: StelaRow[];
  selectedIntent: string;
  onSelectIntent: (intent: string) => void;
  onInspect: (intent: string) => void;
  onSimulate: (intent: string) => void;
}) {
  const topRows = [...rows]
    .sort((a, b) => b.worsened_count - a.worsened_count || b.worsened_rate - a.worsened_rate || b.row_count - a.row_count)
    .slice(0, 8);
  const maxRate = Math.max(...topRows.map((row) => row.worsened_rate), 0.01);
  const firstConversationByIntent = new Map<string, string>();
  for (const row of allRows) {
    const label = labelForRow(row);
    if (!firstConversationByIntent.has(label)) firstConversationByIntent.set(label, row.conversation_id);
  }
  const riskLabel = (row: StelaAnalytics["intent_category_performance"][number]) => {
    if (row.worsened_count >= 2 || row.worsened_rate >= 0.05) return "High";
    if (row.worsened_count === 1) return "Medium";
    if ((row.average_lift ?? 0) > 0) return "Low";
    return "Medium";
  };
  return (
    <div className="rounded-lg border border-slate-200 bg-white">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="px-4 pt-4">
          <h3 className="font-semibold text-slate-950">Top Risk Intents</h3>
          <p className="mt-1 text-sm text-slate-600">Ranked by worsened rows, worsened rate, then row count.</p>
        </div>
        {selectedIntent !== "all" && <button className="mr-4 mt-4 text-sm font-semibold text-slate-600 hover:text-slate-950" onClick={() => onSelectIntent("all")}>Clear intent</button>}
      </div>
      <div className="mt-3 overflow-auto px-3 pb-3">
        <table className="min-w-[900px] w-full table-fixed text-left text-sm">
          <colgroup>
            <col className="w-[220px]" />
            <col className="w-[58px]" />
            <col className="w-[78px]" />
            <col className="w-[140px]" />
            <col className="w-[84px]" />
            <col className="w-[94px]" />
            <col className="w-[78px]" />
            <col className="w-[230px]" />
          </colgroup>
          <thead className="border-b border-slate-200 bg-slate-50 text-xs uppercase tracking-wide text-slate-500">
            <tr>
              <th className="px-2 py-2">Intent/category</th>
              <th className="px-2 py-2">Rows</th>
              <th className="px-2 py-2">Worsened</th>
              <th className="px-2 py-2">Worsened rate</th>
              <th className="px-2 py-2">Avg lift</th>
              <th className="px-2 py-2">Token</th>
              <th className="px-2 py-2">Risk</th>
              <th className="px-2 py-2 text-right">Actions</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {topRows.map((row) => {
            const selected = selectedIntent === row.label;
            const risk = riskLabel(row);
            const example = firstConversationByIntent.get(row.label);
            return (
              <tr key={row.label} className={selected ? "bg-emerald-50" : "bg-white hover:bg-slate-50"}>
                <td className="px-2 py-2">
                  <button className="max-w-full truncate text-left font-semibold text-slate-950 hover:text-emerald-700" title={row.label} onClick={() => onSelectIntent(row.label)}>{row.label}</button>
                </td>
                <td className="px-2 py-2">{row.row_count}</td>
                <td className="px-2 py-2">{row.worsened_count}</td>
                <td className="px-2 py-2">
                  <div className="flex items-center gap-2">
                    <div className="h-2 w-16 overflow-hidden rounded-full bg-slate-100">
                      <div className="h-full rounded-full bg-amber-500" style={{ width: `${Math.max((row.worsened_rate / maxRate) * 100, row.worsened_rate > 0 ? 6 : 0)}%` }} />
                    </div>
                    <span>{percent(row.worsened_rate)}</span>
                  </div>
                </td>
                <td className={`px-2 py-2 font-semibold ${(row.average_lift ?? 0) < 0 ? "text-red-700" : "text-emerald-700"}`}>{signed(row.average_lift)}</td>
                <td className="px-2 py-2">{signed(row.average_token_change)}</td>
                <td className="px-2 py-2"><Badge tone={risk === "High" ? "red" : risk === "Medium" ? "amber" : "emerald"}>{risk}</Badge></td>
                <td className="px-2 py-2">
                  <div className="flex justify-end gap-1.5">
                    <button className="rounded-md border border-slate-300 bg-white px-2 py-1 text-xs font-semibold text-slate-800" onClick={() => onSelectIntent(row.label)}>View rows</button>
                    <button className="rounded-md border border-slate-300 bg-white px-2 py-1 text-xs font-semibold text-slate-800 disabled:opacity-40" onClick={() => onInspect(row.label)} disabled={!example}>Inspect</button>
                    <button className="rounded-md bg-slate-950 px-2 py-1 text-xs font-semibold text-white disabled:opacity-40" onClick={() => onSimulate(row.label)} disabled={!example}>Digital Twin</button>
                  </div>
                </td>
              </tr>
            );
          })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function IssueClusterPriorityChart({
  rows,
  activeCluster,
  focus,
  onSelect,
  onInspect,
  onViewRows,
  onInvestigate,
  onSimulate,
}: {
  rows: IssueCluster[];
  activeCluster: IssueCluster | null;
  focus: ReturnType<typeof buildSelectedFocus> | null;
  onSelect: (cluster: IssueCluster) => void;
  onInspect: (cluster: IssueCluster) => void;
  onViewRows: () => void;
  onInvestigate: () => void;
  onSimulate: () => void;
}) {
  const max = Math.max(...rows.map((row) => row.worsened_count || row.row_count), 1);
  return (
    <div id="issue-cluster-priority" className="rounded-lg border border-slate-200 bg-white p-5">
      <h3 className="font-semibold text-slate-950">Issue Cluster Priority</h3>
      <p className="mt-1 text-sm text-slate-600">Ranked by v0.5 priority and worsened count.</p>
      <div className="mt-4 grid gap-2">
        {rows.map((row) => {
          const active = activeCluster?.cluster_name === row.cluster_name;
          return (
            <button key={`${row.cluster_name}-${row.example_conversation_id}`} className={`rounded-md border px-3 py-2 text-left ${active ? "border-emerald-400 bg-emerald-50" : "border-slate-200 bg-slate-50 hover:border-slate-300"}`} onClick={() => onSelect(row)}>
              <div className="flex items-start justify-between gap-3">
                <span className="text-sm font-semibold leading-5 text-slate-900">{row.cluster_name}</span>
                <Badge tone={row.suggested_priority === "high" ? "red" : row.suggested_priority === "medium" ? "amber" : "slate"}>{row.suggested_priority}</Badge>
              </div>
              <div className="mt-2 h-2 overflow-hidden rounded-full bg-white">
                <div className="h-full rounded-full bg-emerald-500" style={{ width: `${Math.max(((row.worsened_count || row.row_count) / max) * 100, 3)}%` }} />
              </div>
              <div className="mt-1.5 flex items-center justify-between gap-3 text-xs text-slate-600">
                <span>{row.worsened_count} worsened rows | avg delta {signed(row.average_compliance_delta)}</span>
                <span className="font-semibold text-slate-950" onClick={(event) => { event.stopPropagation(); onInspect(row); }}>Inspect example</span>
              </div>
            </button>
          );
        })}
      </div>
      {focus && (
        <div className="mt-4">
          <SelectedFocusCard focus={focus} onViewRows={onViewRows} onInvestigate={onInvestigate} onSimulate={onSimulate} compact />
        </div>
      )}
    </div>
  );
}

function SelectedFocusCard({
  focus,
  onViewRows,
  onInvestigate,
  onSimulate,
  compact = false,
}: {
  focus: ReturnType<typeof buildSelectedFocus> | null;
  onViewRows: () => void;
  onInvestigate: () => void;
  onSimulate: () => void;
  compact?: boolean;
}) {
  if (!focus) {
    return (
      <section className="rounded-lg border border-slate-200 bg-white p-5">
        <h3 className="font-semibold text-slate-950">Selected Focus</h3>
        <p className="mt-2 text-sm leading-6 text-slate-600">No focus selected. Select an intent, issue cluster, or finding to review matching rows.</p>
      </section>
    );
  }
  return (
    <section className={`rounded-lg border border-emerald-200 bg-white ${compact ? "p-4" : "p-5"}`}>
      <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
        <div>
          <div className="text-xs font-semibold uppercase tracking-wide text-emerald-700">{focus.type}</div>
          <h3 className="mt-1 text-lg font-semibold text-slate-950">{focus.name}</h3>
          <p className="mt-2 text-sm leading-6 text-slate-600">{focus.action}</p>
        </div>
        <div className="flex flex-wrap gap-2">
          <button className="rounded-md border border-slate-300 bg-white px-3 py-2 text-sm font-semibold text-slate-800" onClick={onViewRows}>View matching rows</button>
          <button className="rounded-md bg-slate-950 px-3 py-2 text-sm font-semibold text-white disabled:opacity-40" onClick={onInvestigate} disabled={!focus.firstRow}>Open first investigation</button>
          <button className="rounded-md border border-slate-300 bg-white px-3 py-2 text-sm font-semibold text-slate-800 disabled:opacity-40" onClick={onSimulate} disabled={!focus.firstRow}>Open in AI Behavior Digital Twin</button>
        </div>
      </div>
      <div className={`mt-4 grid gap-3 sm:grid-cols-2 ${compact ? "lg:grid-cols-3" : "lg:grid-cols-4 xl:grid-cols-8"}`}>
        <MiniMetric label="Rows affected" value={String(focus.rowsAffected)} />
        <MiniMetric label="Original" value={fmt(focus.averageOriginal)} />
        <MiniMetric label="STELA" value={fmt(focus.averageStela)} />
        <MiniMetric label="Lift" value={signed(focus.averageDelta)} />
        <MiniMetric label="Worsened" value={String(focus.worsenedCount)} />
        <MiniMetric label="Worsened rate" value={percent(focus.worsenedRate)} />
        <MiniMetric label="Token change" value={signed(focus.averageToken)} />
        <MiniMetric label="v0.5 priority" value={focus.priority ?? "n/a"} />
      </div>
    </section>
  );
}

function AdvancedFiltersPanel(props: {
  expanded: boolean;
  setExpanded: (expanded: boolean) => void;
  activeCluster: IssueCluster | null;
  clearCluster: () => void;
  resetFilters: () => void;
  selectedDataset: string;
  setSelectedDataset: (value: string) => void;
  datasets: StelaDashboardData["combined"]["datasets"];
  outcomeFilter: string;
  setOutcomeFilter: (value: string) => void;
  intentFilter: string;
  setIntentFilter: (value: string) => void;
  intentOptions: string[];
  frictionFilter: string;
  setFrictionFilter: (value: string) => void;
  tokenFilter: string;
  setTokenFilter: (value: string) => void;
  deltaMin: number;
  setDeltaMin: (value: number) => void;
  deltaMax: number;
  setDeltaMax: (value: number) => void;
  originalMin: number;
  setOriginalMin: (value: number) => void;
  originalMax: number;
  setOriginalMax: (value: number) => void;
  stelaMin: number;
  setStelaMin: (value: number) => void;
  stelaMax: number;
  setStelaMax: (value: number) => void;
  criteriaSearch: string;
  setCriteriaSearch: (value: string) => void;
  messageSearch: string;
  setMessageSearch: (value: string) => void;
}) {
  const datasetLabel = props.selectedDataset === "all" ? "All" : props.datasets.find((dataset) => dataset.id === props.selectedDataset)?.label ?? props.selectedDataset;
  const chips = [
    `Dataset: ${datasetLabel}`,
    `Outcome: ${props.outcomeFilter}`,
    `Intent/category: ${props.intentFilter}`,
    `Friction: ${props.frictionFilter}`,
    `Token delta: ${props.tokenFilter}`,
    props.activeCluster ? `Cluster: ${shortText(props.activeCluster.cluster_name, 44)}` : null,
  ].filter((chip): chip is string => Boolean(chip));
  return (
    <section className="rounded-lg border border-slate-200 bg-white p-4">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
        <div>
          <h3 className="font-semibold text-slate-950">Advanced Filters</h3>
          <div className="mt-2 flex flex-wrap gap-2 text-xs font-semibold text-slate-600">
            {chips.map((chip) => <span key={chip} className="rounded-md bg-slate-100 px-2.5 py-1">{chip}</span>)}
          </div>
        </div>
        <div className="flex flex-wrap gap-2">
          {props.activeCluster && <button className="rounded-md border border-slate-300 bg-white px-3 py-2 text-sm font-semibold text-slate-700" onClick={props.clearCluster}>Clear Cluster</button>}
          <button className="rounded-md border border-slate-300 bg-white px-3 py-2 text-sm font-semibold text-slate-700" onClick={props.resetFilters}>Reset Filters</button>
          <button className="rounded-md bg-slate-950 px-3 py-2 text-sm font-semibold text-white" onClick={() => props.setExpanded(!props.expanded)}>{props.expanded ? "Hide Filters" : "Show Filters"}</button>
        </div>
      </div>
      {props.expanded && (
        <div className="mt-4 grid gap-3 lg:grid-cols-4 xl:grid-cols-5">
          <FilterHeader selectedDataset={props.selectedDataset} setSelectedDataset={props.setSelectedDataset} datasets={props.datasets} compact />
          <SelectFilter label="Outcome" value={props.outcomeFilter} onChange={props.setOutcomeFilter} options={["all", "improved", "unchanged", "worsened"]} />
          <SelectFilter label="Intent/category" value={props.intentFilter} onChange={props.setIntentFilter} options={["all", ...props.intentOptions]} />
          <SelectFilter label="Friction" value={props.frictionFilter} onChange={props.setFrictionFilter} options={["all", "increased", "decreased", "unchanged"]} />
          <SelectFilter label="Token delta" value={props.tokenFilter} onChange={props.setTokenFilter} options={["all", "increased", "decreased", "unchanged"]} />
          <NumberFilter label="Delta min" value={props.deltaMin} onChange={props.setDeltaMin} step={0.05} />
          <NumberFilter label="Delta max" value={props.deltaMax} onChange={props.setDeltaMax} step={0.05} />
          <NumberFilter label="Original min" value={props.originalMin} onChange={props.setOriginalMin} step={0.05} />
          <NumberFilter label="Original max" value={props.originalMax} onChange={props.setOriginalMax} step={0.05} />
          <NumberFilter label="STELA min" value={props.stelaMin} onChange={props.setStelaMin} step={0.05} />
          <NumberFilter label="STELA max" value={props.stelaMax} onChange={props.setStelaMax} step={0.05} />
          <label className="grid gap-1 text-sm font-medium text-slate-700">
            Failed criteria contains
            <input className="min-h-10 rounded-md border border-slate-300 px-3" value={props.criteriaSearch} onChange={(event) => props.setCriteriaSearch(event.target.value)} />
          </label>
          <label className="grid gap-1 text-sm font-medium text-slate-700 lg:col-span-2">
            User message search
            <input className="min-h-10 rounded-md border border-slate-300 px-3" value={props.messageSearch} onChange={(event) => props.setMessageSearch(event.target.value)} />
          </label>
        </div>
      )}
    </section>
  );
}

function FilteredRowPreview({
  rows,
  totalRows,
  onSelect,
  onSimulate,
}: {
  rows: StelaRow[];
  totalRows: number;
  onSelect: (row: StelaRow) => void;
  onSimulate: (row?: StelaRow) => void;
}) {
  return (
    <div className="rounded-lg border border-slate-200 bg-white">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-200 px-4 py-3">
        <div>
          <h3 className="font-semibold text-slate-950">Filtered Row Preview</h3>
          <p className="mt-1 text-sm text-slate-600">Showing {rows.length} of {totalRows} matching rows. Full Row Explorer remains below.</p>
        </div>
        <span className="rounded-md bg-slate-100 px-3 py-1 text-sm font-semibold text-slate-600">Jump to Row Explorer</span>
      </div>
      <div className="overflow-auto">
        <table className="min-w-[980px] w-full text-left text-sm">
          <thead className="bg-slate-50 text-xs uppercase tracking-wide text-slate-500">
            <tr>
              {["Outcome", "Intent/category", "User message", "Original", "STELA", "Delta", "Token", "Actions"].map((head) => <th key={head} className="px-3 py-3">{head}</th>)}
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {rows.map((row) => {
              const outcome = outcomeForRow(row);
              return (
                <tr key={row.id}>
                  <td className="px-3 py-3"><Badge tone={outcome === "worsened" ? "red" : outcome === "improved" ? "emerald" : "slate"}>{outcome}</Badge></td>
                  <td className="px-3 py-3 font-medium text-slate-900">{labelForRow(row)}</td>
                  <td className="max-w-[420px] truncate px-3 py-3" title={row.user_message}>{row.user_message}</td>
                  <td className="px-3 py-3">{fmt(row.original_compliance)}</td>
                  <td className="px-3 py-3">{fmt(row.stela_compliance)}</td>
                  <td className={`px-3 py-3 font-semibold ${(row.compliance_delta ?? 0) < 0 ? "text-red-700" : "text-emerald-700"}`}>{signed(row.compliance_delta)}</td>
                  <td className="px-3 py-3">{signed(row.token_delta, 0)}</td>
                  <td className="px-3 py-3">
                    <div className="flex flex-wrap gap-2">
                      <button className="rounded-md bg-slate-950 px-3 py-1.5 text-xs font-semibold text-white" onClick={() => onSelect(row)}>Investigate</button>
                      <button className="rounded-md border border-slate-300 bg-white px-3 py-1.5 text-xs font-semibold text-slate-800" onClick={() => onSimulate(row)}>Digital Twin</button>
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function CounterfactualSimulator({ data, selectedRow }: { data: StelaDashboardData; selectedRow?: StelaRow }) {
  const [mode, setMode] = useState<"selected" | "freeform">("selected");
  const [freeform, setFreeform] = useState({
    user_message: "",
    original_response: "",
    dataset: "custom scenario",
    intent: "",
    category: "",
    notes: "",
  });
  const [request, setRequest] = useState<SimulationRequest>({
    row_id: selectedRow?.id ?? null,
    state_vector: {
      compliance_risk: 0.2,
      customer_distress: 0.05,
      fraud_risk: 0.1,
      account_sensitivity: 0.25,
    },
    toggles: {
      authenticated_session: true,
      account_info_available: false,
      transfer_action: false,
      customer_distressed: false,
      high_regulatory_sensitivity: false,
      minimize_friction: true,
      require_human_escalation: false,
    },
    behavioral_objective: "balanced",
  });
  const [result, setResult] = useState<SimulationResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setRequest((current) => ({ ...current, row_id: selectedRow?.id ?? null }));
  }, [selectedRow?.id]);

  useEffect(() => {
    const body: SimulationRequest = {
      ...request,
      row_id: mode === "selected" ? selectedRow?.id ?? null : null,
      user_message: mode === "freeform" ? freeform.user_message : undefined,
      original_response: mode === "freeform" ? freeform.original_response : undefined,
      dataset: mode === "freeform" ? freeform.dataset : undefined,
      intent: mode === "freeform" ? freeform.intent : undefined,
      category: mode === "freeform" ? freeform.category : undefined,
      notes: mode === "freeform" ? freeform.notes : undefined,
    };
    simulateStela(body)
      .then((payload) => {
        setResult(payload);
        setError(null);
      })
      .catch((err: Error) => setError(err.message));
  }, [freeform, mode, request, selectedRow?.id]);

  const currentRow = mode === "selected" ? selectedRow : undefined;

  return (
    <div className="space-y-5">
      <div className="rounded-lg border border-violet-200 bg-white p-5">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
          <div>
            <p className="text-xs font-semibold uppercase tracking-wide text-violet-700">Counterfactual Simulator</p>
            <h2 className="mt-2 text-2xl font-semibold text-slate-950">AI Behavior Digital Twin</h2>
            <p className="mt-2 max-w-3xl text-sm leading-6 text-slate-600">
              Rule-based simulation preview. Not a scored model rerun. This local prototype does not modify frozen v0.4 evidence or make paid model calls.
            </p>
          </div>
          <button
            className="inline-flex min-h-10 items-center gap-2 rounded-md border border-slate-300 bg-slate-100 px-4 text-sm font-semibold text-slate-500"
            disabled
            title="Future feature. This will generate and audit a counterfactual STELA response using the model. Disabled in this local prototype to avoid modifying the frozen validation evidence or making paid API calls."
          >
            Future feature. Disabled in this prototype. No model calls are made.
          </button>
        </div>
      </div>

      <div className="grid gap-4 xl:grid-cols-[1fr_1.1fr]">
        <div className="space-y-4">
          <div className="rounded-lg border border-slate-200 bg-white p-4">
            <div className="inline-flex rounded-md border border-slate-300 bg-slate-50 p-1">
              <button className={`rounded px-3 py-2 text-sm font-semibold ${mode === "selected" ? "bg-slate-950 text-white" : "text-slate-700"}`} onClick={() => setMode("selected")}>Selected row</button>
              <button className={`rounded px-3 py-2 text-sm font-semibold ${mode === "freeform" ? "bg-slate-950 text-white" : "text-slate-700"}`} onClick={() => setMode("freeform")}>Freeform scenario</button>
            </div>
            {mode === "selected" && currentRow && <SelectedRowSimulation row={currentRow} />}
            {mode === "freeform" && <FreeformScenario value={freeform} onChange={setFreeform} datasets={data.combined.datasets.map((dataset) => dataset.label)} />}
          </div>
          <SimulationControls request={request} setRequest={setRequest} />
        </div>

        <div className="space-y-4">
          {error && <div className="rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-800">{error}</div>}
          {result && (
            <>
              <SimulatedPlan result={result} />
              <BeforeAfterDeltaStrip row={currentRow} result={result} />
              <CounterfactualComparison row={currentRow} result={result} />
              <DeltaSummary result={result} />
            </>
          )}
        </div>
      </div>
    </div>
  );
}

function SelectedRowSimulation({ row }: { row: StelaRow }) {
  return (
    <div className="mt-4 grid gap-4">
      <div>
        <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">{row.dataset} / {row.conversation_id} / Turn {row.turn_id}</div>
        <h3 className="mt-2 text-lg font-semibold text-slate-950">{row.user_message}</h3>
      </div>
      <ResponsePanel title="Original response" compliance={row.original_compliance} text={row.original_assistant_response} />
      <ResponsePanel title="Current STELA response" compliance={row.stela_compliance} text={row.stela_assistant_response} />
      <div className="grid gap-4 md:grid-cols-2">
        <JsonPanel title="Metadata" value={row.metadata ?? {}} />
        <JsonPanel title="State/context" value={{ state_vector: row.stela_state_vector_seed, stela_context_packet: row.stela_context_packet }} />
      </div>
    </div>
  );
}

function FreeformScenario({
  value,
  onChange,
  datasets,
}: {
  value: { user_message: string; original_response: string; dataset: string; intent: string; category: string; notes: string };
  onChange: (value: { user_message: string; original_response: string; dataset: string; intent: string; category: string; notes: string }) => void;
  datasets: string[];
}) {
  const set = (key: keyof typeof value, next: string) => onChange({ ...value, [key]: next });
  return (
    <div className="mt-4 grid gap-3">
      <SelectFilter label="Dataset/domain" value={value.dataset} onChange={(next) => set("dataset", next)} options={["custom scenario", ...datasets]} />
      <label className="grid gap-1 text-sm font-medium text-slate-700">
        User message
        <textarea className="min-h-24 rounded-md border border-slate-300 px-3 py-2" value={value.user_message} onChange={(event) => set("user_message", event.target.value)} />
      </label>
      <label className="grid gap-1 text-sm font-medium text-slate-700">
        Original response
        <textarea className="min-h-24 rounded-md border border-slate-300 px-3 py-2" value={value.original_response} onChange={(event) => set("original_response", event.target.value)} />
      </label>
      <div className="grid gap-3 md:grid-cols-2">
        <label className="grid gap-1 text-sm font-medium text-slate-700">
          Intent
          <input className="min-h-10 rounded-md border border-slate-300 px-3" value={value.intent} onChange={(event) => set("intent", event.target.value)} />
        </label>
        <label className="grid gap-1 text-sm font-medium text-slate-700">
          Category
          <input className="min-h-10 rounded-md border border-slate-300 px-3" value={value.category} onChange={(event) => set("category", event.target.value)} />
        </label>
      </div>
      <label className="grid gap-1 text-sm font-medium text-slate-700">
        Notes
        <textarea className="min-h-20 rounded-md border border-slate-300 px-3 py-2" value={value.notes} onChange={(event) => set("notes", event.target.value)} />
      </label>
    </div>
  );
}

function SimulationControls({ request, setRequest }: { request: SimulationRequest; setRequest: (request: SimulationRequest) => void }) {
  const setState = (key: keyof SimulationRequest["state_vector"], value: number) => {
    setRequest({ ...request, state_vector: { ...request.state_vector, [key]: value } });
  };
  const setToggle = (key: keyof SimulationRequest["toggles"], value: boolean) => {
    setRequest({ ...request, toggles: { ...request.toggles, [key]: value } });
  };
  const applyPreset = (preset: string) => {
    const presets: Record<string, Partial<SimulationRequest>> = {
      "Routine servicing": {
        state_vector: { compliance_risk: 0.2, customer_distress: 0.05, fraud_risk: 0.1, account_sensitivity: 0.25 },
        toggles: { authenticated_session: true, account_info_available: false, transfer_action: false, customer_distressed: false, high_regulatory_sensitivity: false, minimize_friction: true, require_human_escalation: false },
        behavioral_objective: "balanced",
      },
      "Lower friction": {
        state_vector: { compliance_risk: 0.15, customer_distress: 0.05, fraud_risk: 0.08, account_sensitivity: 0.2 },
        toggles: { authenticated_session: true, account_info_available: true, transfer_action: false, customer_distressed: false, high_regulatory_sensitivity: false, minimize_friction: true, require_human_escalation: false },
        behavioral_objective: "minimize_friction",
      },
      "Security-first": {
        state_vector: { compliance_risk: 0.55, customer_distress: 0.1, fraud_risk: 0.75, account_sensitivity: 0.8 },
        toggles: { authenticated_session: false, account_info_available: false, transfer_action: false, customer_distressed: false, high_regulatory_sensitivity: true, minimize_friction: false, require_human_escalation: false },
        behavioral_objective: "maximize_compliance",
      },
      "Distressed customer": {
        state_vector: { compliance_risk: 0.35, customer_distress: 0.8, fraud_risk: 0.2, account_sensitivity: 0.35 },
        toggles: { authenticated_session: true, account_info_available: false, transfer_action: false, customer_distressed: true, high_regulatory_sensitivity: false, minimize_friction: true, require_human_escalation: false },
        behavioral_objective: "customer_retention_sensitive",
      },
      "Escalation required": {
        state_vector: { compliance_risk: 0.75, customer_distress: 0.55, fraud_risk: 0.65, account_sensitivity: 0.75 },
        toggles: { authenticated_session: true, account_info_available: false, transfer_action: false, customer_distressed: true, high_regulatory_sensitivity: true, minimize_friction: false, require_human_escalation: true },
        behavioral_objective: "escalation_first",
      },
      "Regulatory sensitivity": {
        state_vector: { compliance_risk: 0.85, customer_distress: 0.15, fraud_risk: 0.3, account_sensitivity: 0.65 },
        toggles: { authenticated_session: true, account_info_available: false, transfer_action: false, customer_distressed: false, high_regulatory_sensitivity: true, minimize_friction: false, require_human_escalation: false },
        behavioral_objective: "maximize_compliance",
      },
    };
    const selected = presets[preset];
    setRequest({
      ...request,
      ...selected,
      row_id: request.row_id,
      state_vector: selected.state_vector ?? request.state_vector,
      toggles: selected.toggles ?? request.toggles,
      behavioral_objective: selected.behavioral_objective ?? request.behavioral_objective,
    });
  };
  return (
    <div className="rounded-lg border border-slate-200 bg-white p-5">
      <div className="flex items-center gap-2">
        <SlidersHorizontal size={18} />
        <h3 className="font-semibold text-slate-950">Simulation controls</h3>
      </div>
      <div className="mt-4">
        <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Scenario presets</div>
        <div className="mt-2 flex flex-wrap gap-2">
          {["Routine servicing", "Lower friction", "Security-first", "Distressed customer", "Escalation required", "Regulatory sensitivity"].map((preset) => (
            <button key={preset} className="rounded-md border border-slate-300 bg-white px-3 py-2 text-sm font-semibold text-slate-700 hover:border-slate-500" onClick={() => applyPreset(preset)}>
              {preset}
            </button>
          ))}
        </div>
      </div>
      <div className="mt-4 grid gap-4">
        {Object.entries(request.state_vector).map(([key, value]) => (
          <label key={key} className="grid gap-2 text-sm font-medium text-slate-700">
            <span className="flex justify-between"><span>{key.replace(/_/g, " ")}</span><span>{value.toFixed(2)}</span></span>
            <input type="range" min="0" max="1" step="0.01" value={value} onChange={(event) => setState(key as keyof SimulationRequest["state_vector"], Number(event.target.value))} />
          </label>
        ))}
      </div>
      <div className="mt-5 grid gap-2 md:grid-cols-2">
        {Object.entries(request.toggles).map(([key, value]) => (
          <label key={key} className="flex items-center gap-2 rounded-md bg-slate-50 px-3 py-2 text-sm text-slate-700">
            <input type="checkbox" checked={value} onChange={(event) => setToggle(key as keyof SimulationRequest["toggles"], event.target.checked)} />
            {key.replace(/_/g, " ")}
          </label>
        ))}
      </div>
      <SelectFilter
        label="Behavioral objective"
        value={request.behavioral_objective}
        onChange={(next) => setRequest({ ...request, behavioral_objective: next as SimulationRequest["behavioral_objective"] })}
        options={["maximize_compliance", "minimize_friction", "balanced", "shortest_acceptable_response", "escalation_first", "customer_retention_sensitive"]}
      />
    </div>
  );
}

function BeforeAfterDeltaStrip({ row, result }: { row?: StelaRow; result: SimulationResponse }) {
  const currentFrame = (row?.stela_context_packet?.active_intent as string | undefined) || row?.intent || "current";
  const currentFriction = row?.stela_friction ? "high" : "low";
  const currentRisk = (row?.stela_compliance ?? 1) < 0.5 ? "high" : (row?.stela_compliance ?? 1) < 0.8 ? "medium" : "low";
  const currentEscalation = "unchanged";
  const currentExperience = outcomeForRow(row ?? ({ compliance_delta: 0 } as StelaRow));
  const tokenImpact = result.expected_friction === "low" ? "likely shorter" : "likely longer";
  const items = [
    ["planning frame", currentFrame, result.planning_frame],
    ["friction", currentFriction, result.expected_friction],
    ["compliance risk", currentRisk, result.expected_compliance_risk],
    ["escalation likelihood", currentEscalation, result.delta_summary.escalation_likelihood],
    ["customer experience", currentExperience, result.delta_summary.customer_experience],
    ["token impact", String(row?.token_delta ?? "n/a"), tokenImpact],
  ];
  return (
    <div className="rounded-lg border border-slate-200 bg-white p-4">
      <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Before/after delta strip</div>
      <div className="mt-3 grid gap-2 md:grid-cols-2 xl:grid-cols-3">
        {items.map(([label, current, simulated]) => (
          <div key={label} className="rounded-md bg-slate-50 p-3 text-sm">
            <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">{label}</div>
            <div className="mt-2 flex items-center justify-between gap-2">
              <span className="truncate text-slate-600" title={current}>{current}</span>
              <ChevronRight size={14} className="shrink-0 text-slate-400" />
              <strong className="truncate text-slate-950" title={simulated}>{simulated}</strong>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function SimulatedPlan({ result }: { result: SimulationResponse }) {
  return (
    <div className="rounded-lg border border-violet-200 bg-white p-5">
      <p className="text-xs font-semibold uppercase tracking-wide text-violet-700">Rule-based simulation preview</p>
      <h3 className="mt-2 text-lg font-semibold text-slate-950">Simulated behavioral plan</h3>
      <div className="mt-4 grid gap-3 md:grid-cols-3">
        <MiniMetric label="Risk posture" value={result.risk_posture} />
        <MiniMetric label="Planning frame" value={result.planning_frame} />
        <MiniMetric label="Response style" value={result.response_style} />
        <MiniMetric label="Expected friction" value={result.expected_friction} />
        <MiniMetric label="Compliance risk" value={result.expected_compliance_risk} />
      </div>
      <div className="mt-4">
        <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Behavioral imperatives</div>
        <div className="mt-2 flex flex-wrap gap-2">
          {result.behavioral_imperatives.map((item) => (
            <span key={item} className="rounded-md bg-slate-100 px-3 py-1 text-sm font-medium text-slate-700">{item}</span>
          ))}
        </div>
      </div>
      <div className="mt-4 rounded-md bg-violet-50 p-4 text-sm leading-6 text-violet-950">
        <strong>Response sketch:</strong> {result.response_sketch}
      </div>
      <p className="mt-3 text-xs font-semibold uppercase tracking-wide text-slate-500">{result.note}</p>
    </div>
  );
}

function CounterfactualComparison({ row, result }: { row?: StelaRow; result: SimulationResponse }) {
  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <div className="rounded-lg border border-slate-200 bg-white p-5">
        <h3 className="font-semibold text-slate-950">Current STELA Behavior</h3>
        <div className="mt-4 grid gap-2 text-sm text-slate-700">
          <div>Current planning frame: <strong>{row?.stela_context_packet?.active_intent as string || row?.intent || "n/a"}</strong></div>
          <div>Current compliance: <strong>{fmt(row?.stela_compliance)}</strong></div>
          <div>Current friction: <strong>{boolLabel(row?.stela_friction)}</strong></div>
          <div>Current token estimate: <strong>{String(row?.comparison?.stela_estimated_output_tokens ?? "n/a")}</strong></div>
        </div>
        <p className="mt-4 whitespace-pre-wrap text-sm leading-6 text-slate-700">{row?.stela_assistant_response ?? "No selected row in freeform mode."}</p>
      </div>
      <div className="rounded-lg border border-violet-200 bg-white p-5">
        <h3 className="font-semibold text-slate-950">Simulated Behavior</h3>
        <div className="mt-4 grid gap-2 text-sm text-slate-700">
          <div>Simulated frame: <strong>{result.planning_frame}</strong></div>
          <div>Expected compliance impact: <strong>{result.delta_summary.compliance_risk}</strong></div>
          <div>Expected friction impact: <strong>{result.delta_summary.friction}</strong></div>
          <div>Expected token impact: <strong>{result.expected_friction === "low" ? "likely shorter" : "likely longer"}</strong></div>
        </div>
        <p className="mt-4 whitespace-pre-wrap text-sm leading-6 text-slate-700">{result.response_sketch}</p>
      </div>
    </div>
  );
}

function DeltaSummary({ result }: { result: SimulationResponse }) {
  return (
    <div className="rounded-lg border border-slate-200 bg-white p-5">
      <h3 className="font-semibold text-slate-950">Scenario delta summary</h3>
      <div className="mt-4 grid gap-3 md:grid-cols-4">
        <MiniMetric label="Compliance risk" value={result.delta_summary.compliance_risk} />
        <MiniMetric label="Friction" value={result.delta_summary.friction} />
        <MiniMetric label="Escalation" value={result.delta_summary.escalation_likelihood} />
        <MiniMetric label="Customer XP" value={result.delta_summary.customer_experience} />
      </div>
      <p className="mt-4 text-sm leading-6 text-slate-600">{result.delta_summary.reason}</p>
    </div>
  );
}

function HoldoutResults({
  data,
  selectedDataset,
  setSelectedDataset,
  setSection,
}: {
  data: StelaDashboardData;
  selectedDataset: string;
  setSelectedDataset: (value: string) => void;
  setSection: (section: Section) => void;
}) {
  const datasets = selectedDataset === "all" ? data.combined.datasets : data.combined.datasets.filter((dataset) => dataset.id === selectedDataset);
  return (
    <div className="space-y-5">
      <FilterHeader selectedDataset={selectedDataset} setSelectedDataset={setSelectedDataset} datasets={data.combined.datasets} />
      <DatasetTable datasets={datasets} />
      <div className="grid gap-4 lg:grid-cols-3">
        {datasets.map((dataset) => (
          <button key={dataset.id} className="rounded-lg border border-slate-200 bg-white p-5 text-left hover:border-slate-400" onClick={() => {
            setSelectedDataset(dataset.id);
            setSection("analytics");
          }}>
            <div className="text-sm font-semibold text-slate-950">{dataset.label}</div>
            <div className="mt-4 grid grid-cols-3 gap-3 text-center">
              <MiniMetric label="Improved" value={String(dataset.improved)} />
              <MiniMetric label="Unchanged" value={String(dataset.unchanged)} />
              <MiniMetric label="Worsened" value={String(dataset.worsened)} />
            </div>
            <div className="mt-4 flex items-center justify-between text-sm text-slate-600">
              <span>Lift {signed(dataset.average_compliance_lift)}</span>
              <span>Friction {signed(dataset.average_friction_change)}</span>
              <span>Token {signed(dataset.average_token_change)}</span>
            </div>
          </button>
        ))}
      </div>
    </div>
  );
}

function DatasetComparison({ data }: { data: StelaDashboardData }) {
  return (
    <div className="space-y-5">
      <DatasetTable datasets={data.combined.datasets} />
      <div className="rounded-lg border border-slate-200 bg-white p-5">
        <h2 className="text-lg font-semibold text-slate-950">Development Evidence Is Separate</h2>
        <p className="mt-2 text-sm leading-6 text-slate-600">
          v0.4 is the primary validation result because it is a frozen unseen holdout. v0.2 and v0.3 remain useful history, but they are not the headline proof.
        </p>
      </div>
    </div>
  );
}

function WorsenedQueue(props: {
  data: StelaDashboardData;
  selectedDataset: string;
  setSelectedDataset: (value: string) => void;
  onSelect: (row: StelaRow) => void;
}) {
  const [intentFilter, setIntentFilter] = useState("all");
  const [frictionFilter, setFrictionFilter] = useState("all");
  const [tokenFilter, setTokenFilter] = useState("all");
  const [maxDelta, setMaxDelta] = useState(0);
  const intentOptions = useMemo(() => {
    const values = new Set<string>();
    props.data.worsened_rows.forEach((row) => values.add(labelForRow(row)));
    return Array.from(values).sort();
  }, [props.data.worsened_rows]);
  const rows = useMemo(() => {
    return props.data.worsened_rows.filter((row) => {
      const tokenDelta = row.token_delta ?? 0;
      const frictionDelta = row.friction_delta ?? 0;
      if (props.selectedDataset !== "all" && row.dataset_id !== props.selectedDataset) return false;
      if (intentFilter !== "all" && labelForRow(row) !== intentFilter) return false;
      if ((row.compliance_delta ?? 0) > maxDelta) return false;
      if (frictionFilter === "increased" && frictionDelta <= 0) return false;
      if (frictionFilter === "decreased" && frictionDelta >= 0) return false;
      if (tokenFilter === "increased" && tokenDelta <= 0) return false;
      if (tokenFilter === "decreased" && tokenDelta >= 0) return false;
      return true;
    });
  }, [frictionFilter, intentFilter, maxDelta, props.data.worsened_rows, props.selectedDataset, tokenFilter]);
  return (
    <div className="space-y-4">
      <div className="rounded-lg border border-slate-200 bg-white p-4">
        <div className="flex flex-col gap-3 lg:flex-row lg:items-end">
          <FilterHeader selectedDataset={props.selectedDataset} setSelectedDataset={props.setSelectedDataset} datasets={props.data.combined.datasets} compact />
          <SelectFilter label="Intent/category" value={intentFilter} onChange={setIntentFilter} options={["all", ...intentOptions]} />
          <NumberFilter label="Compliance delta max" value={maxDelta} onChange={setMaxDelta} step={0.1} />
          <SelectFilter label="Friction" value={frictionFilter} onChange={setFrictionFilter} options={["all", "increased", "decreased"]} />
          <SelectFilter label="Token delta" value={tokenFilter} onChange={setTokenFilter} options={["all", "increased", "decreased"]} />
        </div>
      </div>
      <RowExplorer rows={rows} onSelect={props.onSelect} />
      <p className="text-sm text-slate-500">Manual analysis is v0.5 backlog only. The v0.4 holdout result remains frozen.</p>
    </div>
  );
}

function defaultAnnotation(): BacklogAnnotation {
  return {
    failure_type: "unclear",
    severity: "medium",
    fix_type: "unknown",
    notes: "",
  };
}

function evidenceBundleMarkdown(row: StelaRow, annotation?: BacklogAnnotation) {
  return [
    "# STELA v0.4 Evidence Bundle",
    "",
    "v0.4 evidence is frozen. This bundle is for v0.5 backlog analysis only.",
    "",
    `- Dataset: ${row.dataset}`,
    `- Conversation ID: ${row.conversation_id}`,
    `- Turn ID: ${row.turn_id}`,
    `- Intent/category: ${labelForRow(row)}`,
    `- Original compliance: ${fmt(row.original_compliance)}`,
    `- STELA compliance: ${fmt(row.stela_compliance)}`,
    `- Compliance delta: ${signed(row.compliance_delta)}`,
    `- Original friction: ${boolLabel(row.original_friction)}`,
    `- STELA friction: ${boolLabel(row.stela_friction)}`,
    `- Token delta: ${signed(row.token_delta, 0)}`,
    "",
    "## User Message",
    "",
    row.user_message || "",
    "",
    "## Original Response",
    "",
    row.original_assistant_response || "",
    "",
    "## STELA Response",
    "",
    row.stela_assistant_response || "",
    "",
    "## Failed Original Criteria",
    "",
    (row.failed_criteria_original ?? []).map((item) => `- ${item}`).join("\n") || "- None",
    "",
    "## Failed STELA Criteria",
    "",
    (row.failed_criteria_stela ?? []).map((item) => `- ${item}`).join("\n") || "- None",
    "",
    "## v0.5 Backlog Classification",
    "",
    `- Failure type: ${annotation?.failure_type ?? "unclear"}`,
    `- Severity: ${annotation?.severity ?? "medium"}`,
    `- Fix type: ${annotation?.fix_type ?? "unknown"}`,
    `- Notes: ${annotation?.notes ?? ""}`,
  ].join("\n");
}

function InvestigationView({
  row,
  returnSection,
  setSection,
  openSimulator,
  annotation,
  setAnnotation,
}: {
  row?: StelaRow;
  returnSection: Section;
  setSection: (section: Section) => void;
  openSimulator: (row?: StelaRow) => void;
  annotation?: BacklogAnnotation;
  setAnnotation: (annotation: BacklogAnnotation) => void;
}) {
  const [bundleText, setBundleText] = useState<string | null>(null);
  if (!row) {
    return <div className="rounded-lg border border-slate-200 bg-white p-5">No row selected.</div>;
  }
  const outcome = outcomeForRow(row);
  const activeAnnotation = annotation ?? defaultAnnotation();
  const updateAnnotation = (key: keyof BacklogAnnotation, value: string) => {
    setAnnotation({ ...activeAnnotation, [key]: value });
  };
  const openBundle = async () => {
    const text = evidenceBundleMarkdown(row, activeAnnotation);
    setBundleText(text);
    try {
      await navigator.clipboard.writeText(text);
    } catch {
      // Clipboard availability varies by browser context; modal still provides copyable text.
    }
  };
  return (
    <div className="space-y-5">
      <div className="rounded-lg border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900">
        Manual classification is for v0.5 backlog only. The v0.4 holdout result remains frozen.
      </div>
      <div className="rounded-lg border border-slate-200 bg-white p-5">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex flex-wrap items-center gap-2 text-xs font-semibold uppercase tracking-wide text-slate-500">
            <span>{row.dataset}</span>
            <span>{row.conversation_id}</span>
            <span>Turn {row.turn_id}</span>
            <span>{labelForRow(row)}</span>
          </div>
          <div className="flex flex-wrap gap-2">
            <Badge tone={outcome === "worsened" ? "red" : outcome === "improved" ? "emerald" : "slate"}>{outcome}</Badge>
            <Badge tone={(row.compliance_delta ?? 0) < 0 ? "red" : "emerald"}>{signed(row.compliance_delta)} compliance delta</Badge>
          </div>
        </div>
        <h2 className="mt-3 text-xl font-semibold text-slate-950">{row.user_message}</h2>
        <div className="mt-4 flex flex-wrap gap-2">
          <button className="rounded-md bg-slate-950 px-4 py-2 text-sm font-semibold text-white" onClick={() => openSimulator(row)}>Open in Counterfactual Simulator</button>
          <button className="rounded-md border border-emerald-300 bg-emerald-50 px-4 py-2 text-sm font-semibold text-emerald-900" onClick={openBundle}>Evidence Bundle</button>
          <button className="rounded-md border border-slate-300 bg-white px-4 py-2 text-sm font-semibold text-slate-800" onClick={() => setSection("queue")}>Back to Worsened Queue</button>
          <button className="rounded-md border border-slate-300 bg-white px-4 py-2 text-sm font-semibold text-slate-800" onClick={() => setSection(returnSection === "queue" ? "analytics" : returnSection)}>Back to Chat Analytics</button>
        </div>
      </div>
      <WhyThisMatters outcome={outcome} />
      <div className="grid gap-4 lg:grid-cols-2">
        <ResponsePanel title="Original response" compliance={row.original_compliance} text={row.original_assistant_response} />
        <ResponsePanel title="STELA response" compliance={row.stela_compliance} text={row.stela_assistant_response} />
      </div>
      <div className="grid gap-4 lg:grid-cols-2">
        <AuditPanel title="Original audit" audit={row.original_audit} />
        <AuditPanel title="STELA audit" audit={row.stela_audit} />
      </div>
      <div className="grid gap-4 lg:grid-cols-3">
        <JsonPanel title="Token comparison" value={{ token_delta: row.token_delta, comparison: row.comparison }} />
        <JsonPanel title="Metadata" value={row.metadata ?? {}} />
        <JsonPanel title="State/context" value={{ state_vector: row.stela_state_vector_seed, stela_context_packet: row.stela_context_packet }} />
      </div>
      <div className="rounded-lg border border-slate-200 bg-white p-5">
        <h3 className="font-semibold text-slate-950">v0.5 Backlog Classification</h3>
        <p className="mt-2 text-sm text-slate-600">Local UI state only. The v0.4 holdout result remains frozen.</p>
        <div className="mt-4 grid gap-3 md:grid-cols-3">
          <SelectFilter label="Failure type" value={activeAnnotation.failure_type} onChange={(value) => updateAnnotation("failure_type", value)} options={["over-control", "under-answering", "template mismatch", "judge artifact", "missing context", "legitimate tradeoff", "unclear"]} />
          <SelectFilter label="Severity" value={activeAnnotation.severity} onChange={(value) => updateAnnotation("severity", value)} options={["low", "medium", "high"]} />
          <SelectFilter label="Fix type" value={activeAnnotation.fix_type} onChange={(value) => updateAnnotation("fix_type", value)} options={["template", "audit rubric", "context packet", "data issue", "no fix", "unknown"]} />
          <label className="grid gap-1 text-sm font-medium text-slate-700 md:col-span-3">
            Notes
            <textarea className="min-h-24 rounded-md border border-slate-300 px-3 py-2" value={activeAnnotation.notes} onChange={(event) => updateAnnotation("notes", event.target.value)} />
          </label>
        </div>
      </div>
      {bundleText && (
        <div className="fixed inset-0 z-50 grid place-items-center bg-slate-950/50 p-4">
          <div className="max-h-[85vh] w-full max-w-4xl overflow-auto rounded-lg bg-white p-5 shadow-xl">
            <div className="flex items-center justify-between gap-3">
              <h3 className="text-lg font-semibold text-slate-950">Evidence Bundle</h3>
              <button className="rounded-md border border-slate-300 px-3 py-2 text-sm font-semibold" onClick={() => setBundleText(null)}>Close</button>
            </div>
            <p className="mt-2 text-sm text-slate-600">This markdown block was copied when clipboard access was available. It is also selectable below.</p>
            <textarea className="mt-4 min-h-[420px] w-full rounded-md border border-slate-300 bg-slate-50 p-3 font-mono text-xs leading-5" value={bundleText} readOnly />
          </div>
        </div>
      )}
    </div>
  );
}

function WhyThisMatters({ outcome }: { outcome: string }) {
  const text =
    outcome === "worsened"
      ? "STELA underperformed the original response on this row."
      : outcome === "improved"
        ? "STELA improved compliance on this row."
        : "STELA matched the original response on compliance.";
  return (
    <div className="rounded-lg border border-slate-200 bg-white p-5">
      <h3 className="font-semibold text-slate-950">Why this matters</h3>
      <p className="mt-2 text-sm leading-6 text-slate-600">{text}</p>
    </div>
  );
}

function EvidenceHistory({ data }: { data: StelaDashboardData }) {
  const pilotInputs = ["anonymized chatbot transcripts", "original assistant responses", "institution policy requirements", "authentication/session metadata", "product/account context", "service-result metadata where available"];
  const pilotOutputs = ["compliance lift", "friction reduction", "worsened-row queue", "audit evidence", "executive summary", "remediation backlog", "counterfactual simulation scenarios"];
  return (
    <div className="grid gap-4">
      {data.history.map((item) => (
        <div key={item.version} className={`rounded-lg border p-5 ${item.version === "v0.4" ? "border-emerald-200 bg-emerald-50" : "border-slate-200 bg-white"}`}>
          <div className="flex items-center justify-between gap-4">
            <div>
              <div className="text-sm font-semibold text-slate-950">{item.version} - {item.title}</div>
              <div className="mt-1 text-xs font-semibold uppercase tracking-wide text-slate-500">{item.role}</div>
            </div>
            {item.version === "v0.4" && <span className="rounded-md bg-emerald-600 px-3 py-1 text-sm font-semibold text-white">Primary</span>}
          </div>
          <p className="mt-3 text-sm leading-6 text-slate-600">{item.summary}</p>
        </div>
      ))}
      <div className="rounded-lg border border-slate-200 bg-white p-5">
        <div className="text-sm font-semibold text-slate-950">v0.5 - Governance Directive: Task Completion First</div>
        <div className="mt-1 text-xs font-semibold uppercase tracking-wide text-slate-500">Audit-layer governance milestone</div>
        <p className="mt-3 text-sm leading-6 text-slate-600">
          v0.5 operationalizes the Task Completion First governance directive as an audit-layer check. It does not replace the frozen v0.4 unseen holdout validation result.
        </p>
        <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <MiniMetric label="Baseline alignment" value="0.425" />
          <MiniMetric label="Implemented alignment" value="0.800" />
          <MiniMetric label="Compliance accuracy" value="0.90" />
          <MiniMetric label="Status" value="Implemented" />
        </div>
      </div>
      <div className="rounded-lg border border-slate-200 bg-white p-5">
        <div className="text-sm font-semibold text-slate-950">v0.4 Dataset-Level Validation Detail</div>
        <div className="mt-1 text-xs font-semibold uppercase tracking-wide text-slate-500">Validation documentation</div>
        <p className="mt-3 text-sm leading-6 text-slate-600">
          Dataset-level validation remains available here as supporting evidence. The Executive Overview retains the dataset table, while detailed comparison stays out of the primary workflow navigation.
        </p>
        <div className="mt-4">
          <DatasetTable datasets={data.combined.datasets} />
        </div>
      </div>
      <div className="rounded-lg border border-slate-200 bg-white p-5">
        <div className="text-sm font-semibold text-slate-950">Pilot Readiness Documentation</div>
        <div className="mt-1 text-xs font-semibold uppercase tracking-wide text-slate-500">Preserved documentation</div>
        <p className="mt-3 text-sm leading-6 text-slate-600">
          This public dataset validates the offline assessment workflow. A pilot with anonymized production transcripts would apply the same process to real customer conversations, with production system state mapped into STELA context packets.
        </p>
        <div className="mt-4 grid gap-4 lg:grid-cols-2">
          <Checklist title="Pilot inputs" items={pilotInputs} />
          <Checklist title="Pilot outputs" items={pilotOutputs} />
        </div>
      </div>
    </div>
  );
}

function PilotReadiness() {
  const inputs = ["anonymized chatbot transcripts", "original assistant responses", "institution policy requirements", "authentication/session metadata", "product/account context", "service-result metadata where available"];
  const outputs = ["compliance lift", "friction reduction", "worsened-row queue", "audit evidence", "executive summary", "remediation backlog", "counterfactual simulation scenarios"];
  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <Checklist title="Pilot inputs" items={inputs} />
      <Checklist title="Pilot outputs" items={outputs} />
      <div className="rounded-lg border border-slate-200 bg-white p-5 lg:col-span-2">
        <h2 className="text-lg font-semibold text-slate-950">Positioning</h2>
        <p className="mt-2 text-sm leading-6 text-slate-600">
          This public dataset validates the offline assessment workflow. A pilot with anonymized production transcripts would apply the same process to real customer conversations, with production system state mapped into STELA context packets.
        </p>
      </div>
    </div>
  );
}

function RowExplorer({ rows, onSelect }: { rows: StelaRow[]; onSelect: (row: StelaRow) => void }) {
  return (
    <div className="rounded-lg border border-slate-200 bg-white">
      <div className="border-b border-slate-200 px-4 py-3 text-sm font-semibold text-slate-950">Row explorer ({rows.length} rows)</div>
      <div className="max-h-[560px] overflow-auto">
      <table className="min-w-[1500px] w-full text-left text-sm">
        <thead className="sticky top-0 z-10 bg-slate-50 text-xs uppercase tracking-wide text-slate-500 shadow-sm">
          <tr>
            {["Dataset", "Conversation", "Turn", "Intent/category", "User message", "Original", "STELA", "Delta", "Orig friction", "STELA friction", "Token", "Outcome"].map((head) => <th key={head} className="px-3 py-3">{head}</th>)}
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {rows.map((row) => {
            const outcome = outcomeForRow(row);
            return (
              <tr key={row.id} className="cursor-pointer hover:bg-slate-50" onClick={() => onSelect(row)}>
                <td className="px-3 py-3 font-medium text-slate-900">{row.dataset}</td>
                <td className="px-3 py-3">{row.conversation_id}</td>
                <td className="px-3 py-3">{row.turn_id}</td>
                <td className="px-3 py-3">{labelForRow(row)}</td>
                <td className="max-w-[340px] truncate px-3 py-3" title={row.user_message}>{row.user_message}</td>
                <td className="px-3 py-3">{fmt(row.original_compliance)}</td>
                <td className="px-3 py-3">{fmt(row.stela_compliance)}</td>
                <td className={`px-3 py-3 font-semibold ${(row.compliance_delta ?? 0) < 0 ? "text-red-700" : "text-emerald-700"}`}>{signed(row.compliance_delta)}</td>
                <td className="px-3 py-3">{boolLabel(row.original_friction)}</td>
                <td className="px-3 py-3">{boolLabel(row.stela_friction)}</td>
                <td className="px-3 py-3">{signed(row.token_delta, 0)}</td>
                <td className="px-3 py-3"><Badge tone={outcome === "worsened" ? "red" : outcome === "improved" ? "emerald" : "slate"}>{outcome}</Badge></td>
              </tr>
            );
          })}
        </tbody>
      </table>
      </div>
    </div>
  );
}

function IntentPerformanceTable({
  rows,
  sortMode,
  setSortMode,
  selectedIntent,
  focus,
  onSelectIntent,
  onViewRows,
  onInvestigate,
  onSimulate,
}: {
  rows: StelaAnalytics["intent_category_performance"];
  sortMode: SortMode;
  setSortMode: (mode: SortMode) => void;
  selectedIntent: string;
  focus: ReturnType<typeof buildSelectedFocus> | null;
  onSelectIntent: (intent: string) => void;
  onViewRows: () => void;
  onInvestigate: () => void;
  onSimulate: () => void;
}) {
  return (
    <div className="rounded-lg border border-slate-200 bg-white">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-200 px-4 py-3">
        <h3 className="font-semibold text-slate-950">Intent/category performance</h3>
        <div className="flex flex-wrap items-center gap-2">
          {selectedIntent !== "all" && <button className="rounded-md border border-slate-300 bg-white px-3 py-2 text-sm font-semibold text-slate-700" onClick={() => onSelectIntent("all")}>Clear intent</button>}
          <SelectFilter label="Sort" value={sortMode} onChange={(value) => setSortMode(value as SortMode)} options={["row_count", "worsened_rate", "lift"]} />
        </div>
      </div>
      <div className="overflow-auto" style={{ maxHeight: 380 }}>
      <table className="min-w-[860px] w-full text-left text-sm">
        <thead className="sticky top-0 z-10 bg-slate-50 text-xs uppercase tracking-wide text-slate-500 shadow-sm">
          <tr>
            {["Intent/category", "Rows", "Original", "STELA", "Lift", "Worsened", "Rate", "Token"].map((head) => <th key={head} className="bg-slate-50 px-3 py-3">{head}</th>)}
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {rows.map((row) => (
            <tr key={row.label} className={`cursor-pointer hover:bg-slate-50 ${selectedIntent === row.label ? "bg-emerald-50" : ""}`} onClick={() => onSelectIntent(row.label)}>
              <td className="px-3 py-3 font-medium text-slate-900">{row.label}</td>
              <td className="px-3 py-3">{row.row_count}</td>
              <td className="px-3 py-3">{fmt(row.average_original_compliance)}</td>
              <td className="px-3 py-3">{fmt(row.average_stela_compliance)}</td>
              <td className="px-3 py-3 font-semibold text-emerald-700">{signed(row.average_lift)}</td>
              <td className="px-3 py-3">{row.worsened_count}</td>
              <td className="px-3 py-3">{percent(row.worsened_rate)}</td>
              <td className="px-3 py-3">{signed(row.average_token_change)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      </div>
      {focus && (
        <div className="border-t border-slate-200 p-4">
          <SelectedFocusCard focus={focus} onViewRows={onViewRows} onInvestigate={onInvestigate} onSimulate={onSimulate} compact />
        </div>
      )}
    </div>
  );
}

function TokenEfficiency({ analytics }: { analytics: StelaAnalytics }) {
  return (
    <div id="token-efficiency-detail" className="rounded-lg border border-slate-200 bg-white p-5">
      <h3 className="font-semibold text-slate-950">Token efficiency</h3>
      <div className="mt-4 grid gap-3 md:grid-cols-3">
        <MiniMetric label="Avg change" value={signed(analytics.token_efficiency.average_token_change)} />
        <MiniMetric label="Shorter" value={String(analytics.token_efficiency.stela_shorter_count)} />
        <MiniMetric label="Longer" value={String(analytics.token_efficiency.stela_longer_count)} />
      </div>
      <div className="mt-4 grid gap-3">
        {analytics.token_efficiency.by_dataset.map((item) => (
          <div key={item.dataset_id} className="flex items-center justify-between rounded-md bg-slate-50 px-3 py-2 text-sm">
            <span>{item.dataset}</span>
            <strong>{signed(item.average_token_change)}</strong>
          </div>
        ))}
        {analytics.token_efficiency.by_outcome.map((item) => (
          <div key={item.outcome} className="flex items-center justify-between rounded-md bg-slate-50 px-3 py-2 text-sm">
            <span>{item.outcome}</span>
            <strong>{signed(item.average_token_change)}</strong>
          </div>
        ))}
      </div>
    </div>
  );
}

function IssueClustersTable({
  rows,
  onSelectCluster,
  onInspect,
}: {
  rows: IssueCluster[];
  onSelectCluster: (cluster: IssueCluster) => void;
  onInspect: (cluster: IssueCluster) => void;
}) {
  return (
    <div className="rounded-lg border border-slate-200 bg-white">
      <div className="flex flex-col gap-2 border-b border-slate-200 px-4 py-3">
        <h3 className="font-semibold text-slate-950">Issue Clusters</h3>
        <p className="text-sm text-slate-600">
          Issue clusters are for v0.5 backlog analysis only. The v0.4 holdout result remains frozen.
        </p>
      </div>
      <div className="max-h-[420px] overflow-auto">
        <table className="min-w-[980px] w-full text-left text-sm">
          <thead className="sticky top-0 z-10 bg-slate-50 text-xs uppercase tracking-wide text-slate-500 shadow-sm">
            <tr>
              {["Cluster", "Rows", "Avg delta", "Worsened", "Avg token", "Example", "v0.5 priority"].map((head) => <th key={head} className="px-3 py-3">{head}</th>)}
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {rows.map((row) => (
              <tr key={`${row.cluster_name}-${row.example_conversation_id}`} className="cursor-pointer hover:bg-slate-50" onClick={() => onSelectCluster(row)}>
                <td className="px-3 py-3 font-medium text-slate-900">{row.cluster_name}</td>
                <td className="px-3 py-3">{row.row_count}</td>
                <td className={`px-3 py-3 font-semibold ${(row.average_compliance_delta ?? 0) < 0 ? "text-red-700" : "text-emerald-700"}`}>{signed(row.average_compliance_delta)}</td>
                <td className="px-3 py-3">{row.worsened_count}</td>
                <td className="px-3 py-3">{signed(row.average_token_delta)}</td>
                <td className="px-3 py-3">
                  <button className="text-sm font-semibold text-slate-950 hover:text-emerald-700" onClick={(event) => { event.stopPropagation(); onInspect(row); }}>
                    {row.example_conversation_id}
                  </button>
                </td>
                <td className="px-3 py-3">
                  <Badge tone={row.suggested_priority === "high" ? "red" : row.suggested_priority === "medium" ? "amber" : "slate"}>{row.suggested_priority}</Badge>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function CollapsibleIssueClustersTable({
  rows,
  expanded,
  setExpanded,
  onSelectCluster,
  onInspect,
}: {
  rows: IssueCluster[];
  expanded: boolean;
  setExpanded: (expanded: boolean) => void;
  onSelectCluster: (cluster: IssueCluster) => void;
  onInspect: (cluster: IssueCluster) => void;
}) {
  const topIssue = rows[0];
  const highPriorityCount = rows.filter((row) => row.suggested_priority === "high").length;
  return (
    <section className="rounded-lg border border-slate-200 bg-white">
      <div className="flex flex-col gap-3 border-b border-slate-200 px-4 py-3 lg:flex-row lg:items-center lg:justify-between">
        <div>
          <h3 className="font-semibold text-slate-950">Full Issue Cluster Table</h3>
          <p className="mt-1 text-sm text-slate-600">
            {topIssue
              ? `Top issue: ${topIssue.cluster_name}, ${topIssue.worsened_count} worsened rows. ${highPriorityCount} high-priority clusters detected. ${rows.length} total clusters.`
              : "No issue clusters match the current filters."}
          </p>
        </div>
        <button className="w-fit rounded-md bg-slate-950 px-3 py-2 text-sm font-semibold text-white" onClick={() => setExpanded(!expanded)}>
          {expanded ? "Hide full issue cluster table" : "Show full issue cluster table"}
        </button>
      </div>
      {expanded && <IssueClustersTable rows={rows} onSelectCluster={onSelectCluster} onInspect={onInspect} />}
    </section>
  );
}

function FailureCriteriaSummary({
  rows,
  expanded,
  setExpanded,
  selectedCriterion,
  onSelectCriterion,
  onInspect,
}: {
  rows: StelaAnalytics["failure_criteria"];
  expanded: boolean;
  setExpanded: (expanded: boolean) => void;
  selectedCriterion: string;
  onSelectCriterion: (criterion: string) => void;
  onInspect: (conversationId: string) => void;
}) {
  const sortedRows = [...rows].sort((a, b) => b.worsened_row_count - a.worsened_row_count || b.stela_count - a.stela_count);
  const topRows = sortedRows.slice(0, 5);
  const renderRows = (visibleRows: StelaAnalytics["failure_criteria"]) => visibleRows.map((row) => {
    const selected = selectedCriterion === row.failed_criterion;
    return (
      <tr key={row.failed_criterion} className={selected ? "bg-emerald-50" : "bg-white hover:bg-slate-50"}>
        <td className="px-3 py-2">
          <button className="max-w-full truncate text-left font-medium text-slate-950 hover:text-emerald-700" title={row.failed_criterion} onClick={() => onSelectCriterion(selected ? "" : row.failed_criterion)}>
            {row.failed_criterion}
          </button>
        </td>
        <td className="px-3 py-2">{row.original_count}</td>
        <td className="px-3 py-2">{row.stela_count}</td>
        <td className="px-3 py-2"><WorsenedCountBadge value={row.worsened_row_count} /></td>
        <td className="px-3 py-2">
          <span className="block truncate text-xs font-medium text-slate-600" title={row.example_conversation_id}>{row.example_conversation_id}</span>
        </td>
        <td className="px-3 py-2">
          <div className="flex justify-end gap-1.5">
            <button className="rounded-md border border-slate-300 bg-white px-2 py-1 text-xs font-semibold text-slate-800" onClick={() => onSelectCriterion(selected ? "" : row.failed_criterion)}>
              {selected ? "Clear" : "View rows"}
            </button>
            <button className="rounded-md bg-slate-950 px-2 py-1 text-xs font-semibold text-white disabled:opacity-40" onClick={() => {
              if (row.example_conversation_id) onInspect(row.example_conversation_id);
            }} disabled={!row.example_conversation_id}>
              Inspect
            </button>
          </div>
        </td>
      </tr>
    );
  });
  return (
    <div className="rounded-lg border border-slate-200 bg-white">
      <div className="flex flex-col gap-2 border-b border-slate-200 px-4 py-3 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <h3 className="font-semibold text-slate-950">Failure Criteria Summary</h3>
          <p className="mt-1 text-sm text-slate-600">Top failed criteria ranked by worsened rows.</p>
        </div>
        {selectedCriterion && (
          <button className="text-sm font-semibold text-slate-600 hover:text-slate-950" onClick={() => onSelectCriterion("")}>
            Clear selected criterion
          </button>
        )}
      </div>
      <div className="overflow-auto px-3 py-3">
        <table className="min-w-[860px] w-full table-fixed text-left text-sm">
          <colgroup>
            <col />
            <col className="w-[110px]" />
            <col className="w-[100px]" />
            <col className="w-[130px]" />
            <col className="w-[190px]" />
            <col className="w-[150px]" />
          </colgroup>
          <thead className="border-b border-slate-200 bg-slate-50 text-xs uppercase tracking-wide text-slate-500">
            <tr>
              <th className="px-3 py-2">Failed criterion</th>
              <th className="px-3 py-2">Original count</th>
              <th className="px-3 py-2">STELA count</th>
              <th className="px-3 py-2">Worsened rows</th>
              <th className="px-3 py-2">Example</th>
              <th className="px-3 py-2 text-right">Actions</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {renderRows(topRows)}
          </tbody>
        </table>
      </div>
      <div className="border-t border-slate-200 px-4 py-3">
        <button className="rounded-md bg-slate-950 px-3 py-2 text-sm font-semibold text-white" onClick={() => setExpanded(!expanded)}>
          {expanded ? "Hide full failure criteria table" : "Show full failure criteria table"}
        </button>
        {expanded && (
          <div className="mt-3 max-h-[520px] overflow-auto">
            <table className="min-w-[860px] w-full table-fixed text-left text-sm">
              <colgroup>
                <col />
                <col className="w-[110px]" />
                <col className="w-[100px]" />
                <col className="w-[130px]" />
                <col className="w-[190px]" />
                <col className="w-[150px]" />
              </colgroup>
              <tbody className="divide-y divide-slate-100">
                {renderRows(sortedRows)}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}

function CompactCount({ label, value, tone = "slate" }: { label: string; value: number; tone?: "amber" | "slate" }) {
  const color = tone === "amber" ? "text-amber-700" : "text-slate-950";
  return (
    <div className="flex items-center justify-between gap-2 rounded bg-white/70 px-2 py-1 lg:block lg:bg-transparent lg:px-0 lg:py-0">
      <span className="text-[11px] font-semibold uppercase text-slate-500 lg:hidden">{label}</span>
      <span className={`font-semibold ${color}`}>{value}</span>
    </div>
  );
}

function WorsenedCountBadge({ value }: { value: number }) {
  const classes = value > 0 ? "bg-amber-50 text-amber-800 ring-1 ring-amber-200" : "bg-slate-100 text-slate-600";
  return (
    <div className="flex items-center justify-between gap-2 lg:block">
      <span className="text-[11px] font-semibold uppercase text-slate-500 lg:hidden">Worsened</span>
      <span className={`inline-flex rounded-md px-2 py-1 text-xs font-semibold ${classes}`}>{value} worsened</span>
    </div>
  );
}

function FailureCriteriaTable({
  rows,
  selectedCriterion,
  onSelectCriterion,
}: {
  rows: StelaAnalytics["failure_criteria"];
  selectedCriterion: string;
  onSelectCriterion: (criterion: string) => void;
}) {
  const maxOriginal = Math.max(...rows.map((row) => row.original_count), 1);
  const maxStela = Math.max(...rows.map((row) => row.stela_count), 1);
  const maxWorsened = Math.max(...rows.map((row) => row.worsened_row_count), 1);
  return (
    <div className="rounded-lg border border-slate-200 bg-white">
      <div className="flex flex-col gap-2 border-b border-slate-200 px-4 py-3 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <h3 className="text-sm font-semibold text-slate-950">Failure Criteria Detail</h3>
          <p className="mt-1 text-sm text-slate-600">Click a criterion to filter the row preview and explorer. Darker bars indicate higher count.</p>
        </div>
        {selectedCriterion && (
          <button className="text-sm font-semibold text-slate-600 hover:text-slate-950" onClick={() => onSelectCriterion("")}>
            Clear selected criterion
          </button>
        )}
      </div>
      <div className="max-h-[520px] overflow-auto p-3">
        <div className="grid gap-2">
          {rows.map((row) => {
            const selected = selectedCriterion === row.failed_criterion;
            return (
              <button
                key={row.failed_criterion}
                className={`rounded-md border p-3 text-left transition ${selected ? "border-emerald-400 bg-emerald-50" : "border-slate-200 bg-white hover:border-slate-300 hover:bg-slate-50"}`}
                onClick={() => onSelectCriterion(selected ? "" : row.failed_criterion)}
              >
                <div className="flex flex-col gap-2 lg:flex-row lg:items-start lg:justify-between">
                  <div className="min-w-0">
                    <div className="font-medium leading-5 text-slate-950">{row.failed_criterion}</div>
                    <div className="mt-1 text-xs text-slate-500">Example: {row.example_conversation_id}</div>
                  </div>
                  <div className="flex shrink-0 flex-wrap gap-2">
                    {selected && <Badge tone="emerald">selected</Badge>}
                    {row.worsened_row_count > 0 && <Badge tone="amber">{row.worsened_row_count} worsened</Badge>}
                  </div>
                </div>
                <div className="mt-3 grid gap-2 lg:grid-cols-3">
                  <HeatCell label="Original" value={row.original_count} max={maxOriginal} tone="slate" />
                  <HeatCell label="STELA" value={row.stela_count} max={maxStela} tone="emerald" />
                  <HeatCell label="Worsened" value={row.worsened_row_count} max={maxWorsened} tone="amber" />
                </div>
              </button>
            );
          })}
        </div>
      </div>
    </div>
  );
}

function HeatCell({ label, value, max, tone }: { label: string; value: number; max: number; tone: "slate" | "emerald" | "amber" }) {
  const toneClass = tone === "emerald" ? "bg-emerald-500" : tone === "amber" ? "bg-amber-500" : "bg-slate-500";
  return (
    <div className="rounded-md bg-slate-50 px-2 py-2">
      <div className="flex items-center justify-between gap-2 text-xs font-semibold text-slate-600">
        <span>{label}</span>
        <span>{value}</span>
      </div>
      <div className="mt-1.5 h-2 overflow-hidden rounded-full bg-slate-200">
        <div className={`h-full rounded-full ${toneClass}`} style={{ width: `${Math.max((value / max) * 100, value > 0 ? 5 : 0)}%` }} />
      </div>
    </div>
  );
}

function BarSection({ title, bars }: { title: string; bars: Array<{ label: string; value: number }> }) {
  const max = Math.max(...bars.map((bar) => bar.value), 1);
  return (
    <div className="rounded-lg border border-slate-200 bg-white p-5">
      <h3 className="font-semibold text-slate-950">{title}</h3>
      <div className="mt-4 grid gap-3">
        {bars.map((bar) => (
          <div key={bar.label}>
            <div className="mb-1 flex justify-between gap-3 text-xs font-medium text-slate-600">
              <span>{bar.label}</span>
              <span>{bar.value}</span>
            </div>
            <div className="h-3 overflow-hidden rounded-full bg-slate-100">
              <div className="h-full rounded-full bg-emerald-500" style={{ width: `${(bar.value / max) * 100}%` }} />
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function DatasetTable({ datasets }: { datasets: StelaDashboardData["combined"]["datasets"] }) {
  return (
    <div className="overflow-auto rounded-lg border border-slate-200 bg-white">
      <table className="min-w-[980px] w-full text-left text-sm">
        <thead className="bg-slate-50 text-xs uppercase tracking-wide text-slate-500">
          <tr>
            {["Dataset", "Rows", "Original", "STELA", "Lift", "Friction", "Improved", "Unchanged", "Worsened", "Token"].map((head) => <th key={head} className="px-4 py-3">{head}</th>)}
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {datasets.map((dataset) => (
            <tr key={dataset.id}>
              <td className="px-4 py-3 font-medium text-slate-950">{dataset.label}</td>
              <td className="px-4 py-3">{dataset.rows}</td>
              <td className="px-4 py-3">{fmt(dataset.original_average_compliance)}</td>
              <td className="px-4 py-3">{fmt(dataset.stela_average_compliance)}</td>
              <td className="px-4 py-3 font-semibold text-emerald-700">{signed(dataset.average_compliance_lift)}</td>
              <td className="px-4 py-3 font-semibold text-emerald-700">{signed(dataset.average_friction_change)}</td>
              <td className="px-4 py-3">{dataset.improved}</td>
              <td className="px-4 py-3">{dataset.unchanged}</td>
              <td className="px-4 py-3">{dataset.worsened}</td>
              <td className="px-4 py-3">{signed(dataset.average_token_change)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function FilterHeader({ selectedDataset, setSelectedDataset, datasets, compact = false }: { selectedDataset: string; setSelectedDataset: (value: string) => void; datasets: StelaDashboardData["combined"]["datasets"]; compact?: boolean }) {
  return (
    <label className={`grid gap-1 text-sm font-medium text-slate-700 ${compact ? "" : "w-full max-w-sm"}`}>
      Dataset
      <select className="min-h-10 rounded-md border border-slate-300 px-3" value={selectedDataset} onChange={(e) => setSelectedDataset(e.target.value)}>
        <option value="all">All datasets</option>
        {datasets.map((dataset) => <option key={dataset.id} value={dataset.id}>{dataset.label}</option>)}
      </select>
    </label>
  );
}

function SelectFilter({ label, value, onChange, options }: { label: string; value: string; onChange: (value: string) => void; options: string[] }) {
  return (
    <label className="grid gap-1 text-sm font-medium text-slate-700">
      {label}
      <select className="min-h-10 rounded-md border border-slate-300 px-3" value={value} onChange={(event) => onChange(event.target.value)}>
        {options.map((option) => <option key={option} value={option}>{option}</option>)}
      </select>
    </label>
  );
}

function NumberFilter({ label, value, onChange, step }: { label: string; value: number; onChange: (value: number) => void; step: number }) {
  return (
    <label className="grid gap-1 text-sm font-medium text-slate-700">
      {label}
      <input className="min-h-10 rounded-md border border-slate-300 px-3" type="number" step={step} value={value} onChange={(event) => onChange(Number(event.target.value))} />
    </label>
  );
}

function Kpi({ label, value, tone }: { label: string; value: string; tone: "emerald" | "amber" | "slate" }) {
  const color = tone === "emerald" ? "text-emerald-700" : tone === "amber" ? "text-amber-700" : "text-slate-950";
  return (
    <div className="rounded-lg border border-slate-200 bg-white p-4">
      <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">{label}</div>
      <div className={`mt-3 text-2xl font-semibold ${color}`}>{value}</div>
    </div>
  );
}

function CriteriaCard({ title, items, note }: { title: string; items: Array<[string, boolean]>; note?: string }) {
  return (
    <div className="rounded-lg border border-slate-200 bg-white p-5">
      <h2 className="text-lg font-semibold text-slate-950">{title}</h2>
      <div className="mt-4 grid gap-3">
        {items.map(([label, met]) => (
          <div key={label} className="flex items-center justify-between gap-3 rounded-md bg-slate-50 px-3 py-2">
            <span className="text-sm text-slate-700">{label}</span>
            <span className={`text-sm font-semibold ${met ? "text-emerald-700" : "text-amber-700"}`}>{met ? "Met" : "Not met"}</span>
          </div>
        ))}
      </div>
      {note && <p className="mt-4 text-sm leading-6 text-slate-600">{note}</p>}
    </div>
  );
}

function MiniMetric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md bg-slate-50 p-3">
      <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">{label}</div>
      <div className="mt-2 text-lg font-semibold text-slate-950">{value}</div>
    </div>
  );
}

function Badge({ children, tone }: { children: React.ReactNode; tone: "emerald" | "amber" | "red" | "slate" }) {
  const classes = {
    emerald: "bg-emerald-50 text-emerald-800",
    amber: "bg-amber-50 text-amber-800",
    red: "bg-red-50 text-red-800",
    slate: "bg-slate-100 text-slate-700",
  };
  return <span className={`rounded-md px-2 py-1 text-xs font-semibold uppercase tracking-wide ${classes[tone]}`}>{children}</span>;
}

function ResponsePanel({ title, compliance, text }: { title: string; compliance?: number; text?: string }) {
  return (
    <div className="rounded-lg border border-slate-200 bg-white p-5">
      <div className="flex items-center justify-between gap-3">
        <h3 className="font-semibold text-slate-950">{title}</h3>
        <span className="rounded-md bg-slate-100 px-2 py-1 text-sm font-semibold text-slate-700">Compliance {fmt(compliance)}</span>
      </div>
      <p className="mt-4 whitespace-pre-wrap text-sm leading-6 text-slate-700">{text || "No response text available."}</p>
    </div>
  );
}

function AuditPanel({ title, audit }: { title: string; audit: Record<string, unknown> }) {
  const failed = (audit.failed_criteria as string[] | undefined) ?? [];
  const causes = (audit.friction_cause as string[] | undefined) ?? [];
  return (
    <div className="rounded-lg border border-slate-200 bg-white p-5">
      <h3 className="font-semibold text-slate-950">{title}</h3>
      <div className="mt-4 grid gap-2 text-sm text-slate-700">
        <div>Compliance: <strong>{fmt(audit.compliance as number | undefined)}</strong></div>
        <div>Friction: <strong>{String(Boolean(audit.friction_detected))}</strong></div>
        <div>Friction cause: <strong>{causes.length ? causes.join(", ") : "none"}</strong></div>
      </div>
      <div className="mt-4">
        <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Failed criteria</div>
        <ul className="mt-2 grid gap-2 text-sm text-slate-700">
          {failed.length ? failed.map((item) => <li key={item} className="rounded-md bg-red-50 px-3 py-2 text-red-800">{item}</li>) : <li className="rounded-md bg-emerald-50 px-3 py-2 text-emerald-800">None</li>}
        </ul>
      </div>
      {typeof audit.note === "string" && <p className="mt-4 text-sm leading-6 text-slate-600">{audit.note}</p>}
    </div>
  );
}

function JsonPanel({ title, value }: { title: string; value: unknown }) {
  return (
    <div className="rounded-lg border border-slate-200 bg-white p-5">
      <h3 className="font-semibold text-slate-950">{title}</h3>
      <pre className="mt-4 max-h-80 overflow-auto rounded-md bg-slate-950 p-3 text-xs leading-5 text-slate-100">{JSON.stringify(value, null, 2)}</pre>
    </div>
  );
}

function Checklist({ title, items }: { title: string; items: string[] }) {
  return (
    <div className="rounded-lg border border-slate-200 bg-white p-5">
      <h2 className="text-lg font-semibold text-slate-950">{title}</h2>
      <div className="mt-4 grid gap-2">
        {items.map((item) => (
          <div key={item} className="flex items-center gap-3 rounded-md bg-slate-50 px-3 py-2 text-sm text-slate-700">
            <CheckCircle2 size={16} className="text-emerald-600" />
            {item}
          </div>
        ))}
      </div>
    </div>
  );
}
