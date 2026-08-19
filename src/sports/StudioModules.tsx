import type { ReactNode } from "react";
import type { LucideIcon } from "lucide-react";
import {
  DataWarehouseEvidencePage,
} from "./SportsEvidenceSurfaces";
import {
  ParticipationUsagePage,
  BaseOutTransitionSection,
  GameReplaySection,
  SimulationInputSection,
  WholeGameMonteCarloSection,
  ParticipationAblationSection,
  StarterIdentitySection,
  Phase4EvaluationSection,
  Phase4GraphSection,
  Phase4ModelLaboratorySection,
  Phase4RegistrySection,
  Phase4SimulationStatus,
  PlayerTeamStatePage,
} from "./Phase4Surfaces";
export { ParticipationUsagePage, PlayerTeamStatePage } from "./Phase4Surfaces";
import {
  logicalSportsEvidenceUri,
  sportsPaDecisionStatus,
  useActiveSportsDataset,
  type SportsPaEvidenceRecord,
  type SportsPaMetrics,
  type SportsPaTerminalStatus,
} from "./sportsEvidenceApi";
import {
  Activity,
  ArrowDown,
  ArrowRight,
  BarChart3,
  Beaker,
  Binary,
  BookOpenCheck,
  Box,
  Boxes,
  BrainCircuit,
  ChartNoAxesCombined,
  CheckCircle2,
  ChevronRight,
  CircleDashed,
  Clock3,
  CloudCog,
  Code2,
  Database,
  FileCheck2,
  FileClock,
  FileKey2,
  FileSearch2,
  Fingerprint,
  FlaskConical,
  Gauge,
  GitBranch,
  Goal,
  Layers3,
  LineChart,
  LockKeyhole,
  MonitorDot,
  Network,
  PackageCheck,
  RadioTower,
  Scale,
  Search,
  ServerCog,
  Settings2,
  ShieldCheck,
  SlidersHorizontal,
  Sparkles,
  Target,
  Telescope,
  TimerReset,
  Users,
  Workflow,
} from "lucide-react";

type Tone = "cyan" | "blue" | "violet" | "emerald" | "amber" | "slate";

const toneClasses: Record<Tone, { icon: string; wash: string; border: string; text: string }> = {
  cyan: {
    icon: "bg-cyan-400/15 text-cyan-200 ring-cyan-300/20",
    wash: "from-cyan-50 to-white",
    border: "border-cyan-200",
    text: "text-cyan-800",
  },
  blue: {
    icon: "bg-blue-400/15 text-blue-200 ring-blue-300/20",
    wash: "from-blue-50 to-white",
    border: "border-blue-200",
    text: "text-blue-800",
  },
  violet: {
    icon: "bg-violet-400/15 text-violet-200 ring-violet-300/20",
    wash: "from-violet-50 to-white",
    border: "border-violet-200",
    text: "text-violet-800",
  },
  emerald: {
    icon: "bg-emerald-400/15 text-emerald-200 ring-emerald-300/20",
    wash: "from-emerald-50 to-white",
    border: "border-emerald-200",
    text: "text-emerald-800",
  },
  amber: {
    icon: "bg-amber-400/15 text-amber-100 ring-amber-300/20",
    wash: "from-amber-50 to-white",
    border: "border-amber-200",
    text: "text-amber-800",
  },
  slate: {
    icon: "bg-white/10 text-slate-200 ring-white/15",
    wash: "from-slate-50 to-white",
    border: "border-slate-200",
    text: "text-slate-700",
  },
};

type StudioPageFrameProps = {
  eyebrow: string;
  title: string;
  description: string;
  icon: LucideIcon;
  tone?: Tone;
  status?: string;
  facts?: Array<{ label: string; value: string }>;
  children: ReactNode;
};

function StudioPageFrame({
  eyebrow,
  title,
  description,
  icon: Icon,
  tone = "cyan",
  status = "NOT CONFIGURED",
  facts = [],
  children,
}: StudioPageFrameProps) {
  const toneClass = toneClasses[tone];
  return (
    <div className="min-w-0 space-y-5 pb-10" data-sports-module={title}>
      <header className="relative isolate overflow-hidden rounded-2xl border border-slate-800 bg-slate-950 text-white shadow-xl shadow-slate-950/10">
        <div
          className="pointer-events-none absolute inset-0 opacity-70"
          aria-hidden="true"
          style={{
            backgroundImage:
              "radial-gradient(circle at 82% 15%, rgba(34,211,238,.18), transparent 26%), linear-gradient(rgba(148,163,184,.055) 1px, transparent 1px), linear-gradient(90deg, rgba(148,163,184,.055) 1px, transparent 1px)",
            backgroundSize: "auto, 32px 32px, 32px 32px",
          }}
        />
        <div className="relative grid gap-8 p-5 sm:p-7 lg:grid-cols-[minmax(0,1fr)_minmax(280px,0.46fr)] lg:items-end">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-3">
              <span className={`inline-flex h-11 w-11 items-center justify-center rounded-xl ring-1 ${toneClass.icon}`}>
                <Icon size={22} aria-hidden="true" />
              </span>
              <span className="text-xs font-semibold uppercase tracking-[0.18em] text-cyan-200">{eyebrow}</span>
              <StatusPill label={status} dark />
            </div>
            <h1 className="mt-5 max-w-4xl text-3xl font-semibold tracking-tight text-white sm:text-4xl">{title}</h1>
            <p className="mt-3 max-w-3xl text-sm leading-6 text-slate-300 sm:text-base sm:leading-7">{description}</p>
          </div>
          {facts.length > 0 ? (
            <dl className="grid grid-cols-2 gap-px overflow-hidden rounded-xl border border-white/10 bg-white/10 sm:grid-cols-3 lg:grid-cols-1 xl:grid-cols-3">
              {facts.map((fact) => (
                <div key={fact.label} className="min-w-0 bg-slate-950/70 px-4 py-3 backdrop-blur-sm">
                  <dt className="text-xs font-medium text-slate-400">{fact.label}</dt>
                  <dd className="mt-1 break-words text-sm font-semibold tabular-nums text-white">{fact.value}</dd>
                </div>
              ))}
            </dl>
          ) : null}
        </div>
      </header>
      {children}
    </div>
  );
}

function StatusPill({ label, dark = false, tone = "slate" }: { label: string; dark?: boolean; tone?: Tone }) {
  const color = dark
    ? "border-white/10 bg-white/5 text-slate-300"
    : `${toneClasses[tone].border} bg-gradient-to-r ${toneClasses[tone].wash} ${toneClasses[tone].text}`;
  return (
    <span className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-semibold uppercase tracking-wide ${color}`}>
      <span className="h-1.5 w-1.5 rounded-full bg-current opacity-70" aria-hidden="true" />
      {label}
    </span>
  );
}

function MetricStrip({ items }: { items: Array<{ label: string; value: string; detail: string }> }) {
  return (
    <section className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4" aria-label="Module status">
      {items.map((item) => (
        <article key={item.label} className="rounded-xl border border-slate-200 bg-white px-4 py-4 shadow-sm">
          <div className="text-xs font-semibold uppercase tracking-[0.12em] text-slate-500">{item.label}</div>
          <div className="mt-2 text-2xl font-semibold tabular-nums tracking-tight text-slate-950">{item.value}</div>
          <div className="mt-1 text-xs leading-5 text-slate-500">{item.detail}</div>
        </article>
      ))}
    </section>
  );
}

type SectionCardProps = {
  title: string;
  description?: string;
  eyebrow?: string;
  icon?: LucideIcon;
  action?: ReactNode;
  children: ReactNode;
  className?: string;
};

function SectionCard({ title, description, eyebrow, icon: Icon, action, children, className = "" }: SectionCardProps) {
  return (
    <section className={`overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm ${className}`}>
      <div className="flex flex-col gap-4 border-b border-slate-100 px-5 py-4 sm:flex-row sm:items-start sm:justify-between sm:px-6">
        <div className="flex min-w-0 gap-3">
          {Icon ? (
            <span className="mt-0.5 inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-slate-900 text-cyan-200">
              <Icon size={18} aria-hidden="true" />
            </span>
          ) : null}
          <div className="min-w-0">
            {eyebrow ? <div className="text-xs font-semibold uppercase tracking-[0.14em] text-cyan-700">{eyebrow}</div> : null}
            <h2 className="text-xl font-semibold tracking-tight text-slate-950">{title}</h2>
            {description ? <p className="mt-1 max-w-3xl text-sm leading-6 text-slate-600">{description}</p> : null}
          </div>
        </div>
        {action ? <div className="shrink-0">{action}</div> : null}
      </div>
      <div className="p-5 sm:p-6">{children}</div>
    </section>
  );
}

function EmptyState({
  icon: Icon,
  title,
  description,
  detail,
  contract,
}: {
  icon: LucideIcon;
  title: string;
  description: string;
  detail?: string;
  contract?: string;
}) {
  return (
    <div className="relative overflow-hidden rounded-2xl border border-dashed border-slate-300 bg-gradient-to-br from-slate-50 via-white to-cyan-50/60 px-5 py-8 text-center sm:px-8">
      <div className="pointer-events-none absolute -right-12 -top-12 h-40 w-40 rounded-full border border-cyan-100 bg-cyan-100/30" aria-hidden="true" />
      <span className="relative mx-auto inline-flex h-14 w-14 items-center justify-center rounded-2xl bg-slate-950 text-cyan-200 shadow-lg shadow-slate-900/15">
        <Icon size={26} aria-hidden="true" />
      </span>
      <h3 className="relative mt-4 text-xl font-semibold tracking-tight text-slate-950">{title}</h3>
      <p className="relative mx-auto mt-2 max-w-2xl text-sm leading-6 text-slate-600">{description}</p>
      {detail ? <p className="relative mx-auto mt-2 max-w-2xl text-xs leading-5 text-slate-500">{detail}</p> : null}
      {contract ? (
        <div className="relative mt-4 inline-flex items-center gap-2 rounded-lg border border-slate-200 bg-white px-3 py-2 font-mono text-xs font-semibold text-slate-700 shadow-sm">
          <FileKey2 size={15} className="text-cyan-700" aria-hidden="true" />
          {contract}
        </div>
      ) : null}
    </div>
  );
}

function FeatureTile({ icon: Icon, title, description, tag }: { icon: LucideIcon; title: string; description: string; tag?: string }) {
  return (
    <article className="group rounded-xl border border-slate-200 bg-slate-50/70 p-4 transition-colors hover:border-cyan-200 hover:bg-cyan-50/50">
      <div className="flex items-start justify-between gap-3">
        <span className="inline-flex h-9 w-9 items-center justify-center rounded-lg border border-slate-200 bg-white text-slate-700 shadow-sm group-hover:text-cyan-700">
          <Icon size={18} aria-hidden="true" />
        </span>
        {tag ? <StatusPill label={tag} /> : null}
      </div>
      <h3 className="mt-4 text-sm font-semibold text-slate-950">{title}</h3>
      <p className="mt-1 text-xs leading-5 text-slate-600">{description}</p>
    </article>
  );
}

function PlaceholderTable({ columns, title }: { columns: string[]; title: string }) {
  return (
    <div className="overflow-x-auto rounded-xl border border-slate-200">
      <table className="w-full min-w-[760px] table-fixed" aria-label={title}>
        <thead className="bg-slate-900">
          <tr>
            {columns.map((column) => (
              <th key={column} scope="col" className="px-3 py-3 text-left text-xs font-semibold uppercase tracking-wide text-slate-300">
                {column}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          <tr>
            <td colSpan={columns.length} className="bg-white px-4 py-7 text-center">
              <CircleDashed size={22} className="mx-auto text-slate-400" aria-hidden="true" />
              <div className="mt-2 text-sm font-semibold text-slate-700">No rows to display</div>
              <div className="mt-1 text-xs text-slate-500">Records appear only after governed evidence is created.</div>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  );
}

export function DataWarehousePage() {
  return <DataWarehouseEvidencePage />;
}

function terminalTone(status: SportsPaTerminalStatus | null): Tone {
  if (status === "RESEARCH_CHALLENGER") return "violet";
  if (status === "RESEARCH_BASELINE") return "cyan";
  if (status === "REJECTED_BASELINE" || status === "BLOCKED") return "amber";
  return "slate";
}

function formatInteger(value: number | undefined) {
  return value === undefined ? "—" : value.toLocaleString("en-US");
}

function formatMetric(value: number | undefined) {
  if (value === undefined) return "—";
  return value.toLocaleString("en-US", { maximumFractionDigits: 6 });
}

function formatDuration(value: number | undefined) {
  if (value === undefined) return "—";
  return value < 120 ? `${value.toLocaleString("en-US", { maximumFractionDigits: 1 })}s` : `${(value / 60).toLocaleString("en-US", { maximumFractionDigits: 1 })}m`;
}

function evidenceString(record: SportsPaEvidenceRecord | undefined, ...keys: string[]) {
  for (const key of keys) {
    if (typeof record?.[key] === "string" && record[key]) return String(record[key]);
  }
  return "";
}

function evidenceNumber(record: SportsPaEvidenceRecord | undefined, ...keys: string[]) {
  for (const key of keys) {
    const value = record?.[key];
    if (typeof value === "number" && Number.isFinite(value)) return value;
  }
  return undefined;
}

function evidenceSummary(value: unknown) {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "boolean") return value ? "Yes" : "No";
  if (typeof value === "number") return value.toLocaleString("en-US", { maximumFractionDigits: 6 });
  if (typeof value === "string") return value;
  return JSON.stringify(value);
}

function EvidenceRecordList({ records, empty }: { records: SportsPaEvidenceRecord[]; empty: string }) {
  if (!records.length) return <p className="text-sm text-slate-500">{empty}</p>;
  return (
    <div className="space-y-2">
      {records.map((record, index) => (
        <dl key={`${evidenceString(record, "artifactId", "id", "name") || "evidence"}-${index}`} className="grid gap-2 rounded-lg border border-slate-200 bg-slate-50 p-3 sm:grid-cols-2">
          {Object.entries(record).map(([key, value]) => (
            <div key={key} className="min-w-0">
              <dt className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">{key.replaceAll(/([A-Z])/g, " $1")}</dt>
              <dd className="mt-0.5 break-words text-xs font-medium text-slate-800">{evidenceSummary(value)}</dd>
            </div>
          ))}
        </dl>
      ))}
    </div>
  );
}

export function ModelLaboratoryPage() {
  const datasetEvidence = useActiveSportsDataset();
  const dataset = datasetEvidence.status === "ready" ? datasetEvidence.data : null;
  const baseline = dataset?.paBaseline;
  const phase4 = dataset?.phase4;
  const featureAudit = dataset?.featureAudit;
  const decision = sportsPaDecisionStatus(baseline?.decision) || sportsPaDecisionStatus(baseline?.status) || (baseline ? "BLOCKED" : null);
  const candidates = baseline?.candidates ?? [];
  const foldCount = candidates.reduce((total, candidate) => total + candidate.folds.length, 0);
  const selected = candidates.find((candidate) => candidate.candidateId === baseline?.selectedCandidateId || candidate.selected);
  const prerequisiteStates: Array<{ label: string; status: string; tone: Tone }> = [
    { label: "Forecast contract", status: dataset?.project ? "REGISTERED" : "PENDING", tone: dataset?.project ? "emerald" : "slate" },
    { label: "Immutable dataset", status: dataset?.validationStatus || "PENDING", tone: dataset ? "emerald" : "slate" },
    { label: "Temporal validation plan", status: dataset?.folds.length ? `${dataset.folds.length} FOLDS` : "PENDING", tone: dataset?.folds.length ? "emerald" : "slate" },
    { label: "MLB_PA_FEATURE_VIEW_V1", status: baseline?.featureView ? "MATERIALIZED" : featureAudit?.status || "NOT AUDITED", tone: baseline?.featureView ? "emerald" : featureAudit?.status === "BLOCKED" ? "amber" : "slate" },
  ];
  return (
    <StudioPageFrame
      eyebrow="Candidate research"
      title="Model Laboratory"
      description="Run governed sports experiments, compare component candidates across temporal folds, and preserve artifact lineage from evidence to decision."
      icon={FlaskConical}
      tone="violet"
      status={decision || baseline?.status || featureAudit?.status || "NOT CONFIGURED"}
      facts={[
        { label: "Experiments", value: baseline?.experiment ? "1" : "0" },
        { label: "Candidates", value: String(candidates.length) },
        { label: "Dataset", value: dataset?.validationStatus || (datasetEvidence.status === "error" ? "Unavailable" : "None") },
      ]}
    >
      <MetricStrip items={[
        { label: "Experiments", value: baseline?.experiment ? "1" : "0", detail: baseline?.experiment?.status || "No Experiment Run" },
        { label: "Candidate models", value: String(candidates.length), detail: candidates.length ? `${candidates.filter((candidate) => candidate.selected).length} selected by evidence` : "No registered candidate" },
        { label: "Candidate folds", value: String(foldCount), detail: foldCount ? "Recorded frozen rolling-origin evaluations" : "No validation fold evaluated" },
        { label: "Research decision", value: baseline ? decision || "BLOCKED" : "NOT CONFIGURED", detail: selected?.name || baseline?.decisionReason || "No selection decision" },
      ]} />

      {baseline ? <>
        <div className="grid gap-4 xl:grid-cols-[minmax(0,1.3fr)_minmax(300px,.7fr)]">
          <SectionCard title="Experiment evidence" description="The active dataset binds this run, its feature view, timing, tuning policy, and terminal research decision." icon={Beaker} action={<StatusPill label={decision || "BLOCKED"} tone={terminalTone(decision)} />}>
            <dl className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
              {[
                ["Run", baseline.runId],
                ["Run SHA", baseline.runSha || "Not recorded"],
                ["Project", baseline.projectId || dataset?.project?.projectId || "Not recorded"],
                ["Experiment", baseline.experiment?.experimentId || "Not recorded"],
                ["Experiment status", baseline.experiment?.status || "Not recorded"],
                ["Runtime", formatDuration(baseline.experiment?.durationSeconds)],
                ["Feature view", baseline.featureView?.featureViewId || "Not recorded"],
                ["Rows", formatInteger(baseline.featureView?.rowCount)],
              ].map(([label, value]) => <div key={label} className="rounded-lg border border-slate-200 bg-slate-50 p-3"><dt className="text-xs font-semibold uppercase text-slate-500">{label}</dt><dd className="mt-1 break-words text-sm font-semibold text-slate-900">{value}</dd></div>)}
            </dl>
            {baseline.experiment?.tuningPolicy !== undefined ? <div className="mt-3 rounded-lg border border-slate-200 p-3"><div className="text-xs font-semibold uppercase text-slate-500">Tuning policy</div><div className="mt-1 break-words text-xs text-slate-700">{evidenceSummary(baseline.experiment.tuningPolicy)}</div></div> : null}
          </SectionCard>
          <SectionCard title="Feature-view lineage" description="Only the logical exchange reference is shown; target-local paths remain suppressed." icon={Layers3}>
            {baseline.featureView ? <div className="space-y-3 text-sm">
              <div><div className="text-xs font-semibold uppercase text-slate-500">Contract authority</div><div className="mt-1 break-words font-semibold text-slate-900">{baseline.featureView.contractVersion || "Not recorded"} · {baseline.featureView.contractSha || "Contract SHA unavailable"}</div></div>
              <div><div className="text-xs font-semibold uppercase text-slate-500">Feature-view content SHA</div><div className="mt-1 break-all font-mono text-xs text-slate-700">{baseline.featureView.contentSha || "Not recorded"}</div></div>
              <div><div className="text-xs font-semibold uppercase text-slate-500">Logical root</div><div className="mt-1 break-all font-mono text-xs text-slate-700">{logicalSportsEvidenceUri(baseline.featureView.logicalRoot)}</div></div>
              <div><div className="text-xs font-semibold uppercase text-slate-500">Classes / features</div><div className="mt-1 text-slate-800">{baseline.featureView.classOrder.join(" · ") || "No class order"} · {baseline.featureView.features.length} features</div></div>
            </div> : <p className="text-sm text-slate-500">No feature-view artifact was returned.</p>}
          </SectionCard>
        </div>

        <SectionCard title="Candidate model ledger" description="Candidate definitions, fold metrics, runtimes, convergence evidence, and prediction lineage are rendered from the registered run." icon={FlaskConical}>
          {candidates.length ? <div className="space-y-4">
            {candidates.map((candidate) => (
              <article key={candidate.candidateId} className="overflow-hidden rounded-xl border border-slate-200">
                <div className="flex flex-wrap items-start justify-between gap-3 bg-slate-50 px-4 py-3">
                  <div><h3 className="font-semibold text-slate-950">{candidate.name}</h3><p className="mt-1 text-xs text-slate-600">{candidate.candidateId} · {candidate.definition || "Definition not recorded"}</p></div>
                  <div className="flex gap-2"><StatusPill label={candidate.status || "UNKNOWN"} />{candidate.selected ? <StatusPill label="SELECTED" tone="violet" /> : null}</div>
                </div>
                <div className="grid gap-3 border-t border-slate-200 p-4 lg:grid-cols-[minmax(0,1fr)_260px]">
                  <div className="overflow-x-auto">
                    <table className="w-full min-w-[680px] text-left text-xs" aria-label={`${candidate.name} temporal folds`}>
                      <thead><tr className="text-slate-500">{["Fold", "Status", "Train", "Validation", "Train / validation rows", "Log loss", "Brier", "ECE", "Prediction artifact"].map((label) => <th key={label} className="border-b border-slate-200 px-2 py-2 font-semibold">{label}</th>)}</tr></thead>
                      <tbody>{candidate.folds.map((fold) => {
                        const metrics = fold.calibratedMetrics || fold.metrics || fold.rawMetrics;
                        const predictionId = evidenceString(fold.predictionArtifact, "artifactId", "id", "logicalUri") || "Not recorded";
                        return <tr key={fold.foldId} className="align-top"><td className="border-b border-slate-100 px-2 py-2 font-semibold text-slate-900">{fold.foldId}</td><td className="border-b border-slate-100 px-2 py-2">{fold.status}</td><td className="border-b border-slate-100 px-2 py-2">{fold.trainSeasons.join(", ") || "—"}</td><td className="border-b border-slate-100 px-2 py-2">{fold.validationSeason ?? "—"}</td><td className="border-b border-slate-100 px-2 py-2">{formatInteger(fold.trainingRows)} / {formatInteger(fold.validationRows ?? fold.rowCount ?? metrics?.rowCount)}</td><td className="border-b border-slate-100 px-2 py-2">{formatMetric(metrics?.logLoss)}</td><td className="border-b border-slate-100 px-2 py-2">{formatMetric(metrics?.brierScore)}</td><td className="border-b border-slate-100 px-2 py-2">{formatMetric(metrics?.topLabelEce)}</td><td className="max-w-48 break-words border-b border-slate-100 px-2 py-2">{predictionId}</td></tr>;
                      })}</tbody>
                    </table>
                    {!candidate.folds.length ? <p className="py-4 text-center text-sm text-slate-500">No fold evidence was returned for this candidate.</p> : null}
                  </div>
                  <dl className="space-y-3 rounded-lg bg-slate-50 p-3 text-xs">
                    <div><dt className="font-semibold uppercase text-slate-500">Runtime</dt><dd className="mt-1 font-semibold text-slate-900">{formatDuration(candidate.runtimeSeconds)}</dd></div>
                    <div><dt className="font-semibold uppercase text-slate-500">Aggregate selection metrics (2024)</dt><dd className="mt-1 space-y-1 text-slate-700"><div>Log loss: {formatMetric(candidate.aggregateMetrics?.logLoss)}</div><div>Brier: {formatMetric(candidate.aggregateMetrics?.brierScore)}</div><div>ECE: {formatMetric(candidate.aggregateMetrics?.topLabelEce)}</div></dd></div>
                    <div><dt className="font-semibold uppercase text-slate-500">Hyperparameters</dt><dd className="mt-1 break-words text-slate-700">{evidenceSummary(candidate.hyperparameters)}</dd></div>
                    <div><dt className="font-semibold uppercase text-slate-500">Convergence</dt><dd className="mt-1 break-words text-slate-700">{evidenceSummary(candidate.convergence)}</dd></div>
                    {candidate.eligible !== undefined ? <div><dt className="font-semibold uppercase text-slate-500">Eligible</dt><dd className="mt-1 text-slate-700">{candidate.eligible ? "Yes" : "No"}{candidate.rejectionReasons.length ? ` · ${candidate.rejectionReasons.join(" · ")}` : ""}</dd></div> : null}
                  </dl>
                </div>
              </article>
            ))}
          </div> : <EmptyState icon={TimerReset} title="No Experiment Run" description="The run record contains no candidate evidence. Candidate counts and metrics remain empty." />}
        </SectionCard>

        <SectionCard title="Feature artifacts and season lineage" description="Materialized feature artifacts and season-row evidence are carried with the active dataset." icon={GitBranch}>
          <div className="grid gap-4 lg:grid-cols-3"><EvidenceRecordList records={baseline.featureView?.seasonRows ?? []} empty="No season-row evidence was returned." /><EvidenceRecordList records={baseline.featureView?.artifacts ?? []} empty="No feature artifact lineage was returned." /><EvidenceRecordList records={[...(baseline.parent ? [baseline.parent] : []), ...(baseline.identityBridge ? [baseline.identityBridge] : []), ...baseline.artifacts]} empty="No parent or run artifact lineage was returned." /></div>
        </SectionCard>
      </> : <>
        <SectionCard title="No Experiment Run" description={featureAudit?.status === "BLOCKED" ? "The registered evidence currently blocks candidate fitting." : "A registered sports dataset and forecast contract are required before a candidate can run."} icon={TimerReset}>
          <div className="space-y-3">{prerequisiteStates.map((item, index) => <div key={item.label} className="flex flex-wrap items-center gap-3 rounded-xl border border-slate-200 bg-slate-50 px-3 py-3"><span className="flex h-7 w-7 items-center justify-center rounded-full border border-slate-300 bg-white text-xs font-semibold text-slate-500">{index + 1}</span><div className="min-w-0 flex-1 text-sm font-semibold text-slate-700">{item.label}</div><StatusPill label={item.status} tone={item.tone} /></div>)}</div>
        </SectionCard>
        <SectionCard title="Sports evaluation vocabulary" description="Metrics remain empty until evidence-producing runs complete." icon={BarChart3}><div className="grid gap-3 md:grid-cols-3">{[["Probability", "Brier score · log loss · calibration error"], ["Classification", "Accuracy · macro F1 · confusion matrix"], ["Reliability", "Provided probability bands · prevalence"]].map(([title, metrics]) => <div key={title} className="rounded-xl border border-slate-200 bg-slate-50 p-4"><div className="text-sm font-semibold text-slate-950">{title}</div><div className="mt-2 text-xs text-slate-600">{metrics}</div><div className="mt-4 border-t border-slate-200 pt-3 text-xs font-semibold text-slate-400">No measured values</div></div>)}</div></SectionCard>
      </>}
      <Phase4ModelLaboratorySection study={phase4} />
    </StudioPageFrame>
  );
}

function LineageRail({ labels }: { labels: string[] }) {
  return (
    <div className="flex flex-col gap-2 lg:flex-row lg:items-center" aria-label="Artifact lineage">
      {labels.map((label, index) => (
        <div key={label} className="contents">
          <div className="flex min-h-16 flex-1 items-center gap-3 rounded-xl border border-dashed border-slate-300 bg-slate-50 px-3 py-3">
            <span className="h-2.5 w-2.5 shrink-0 rounded-full border-2 border-slate-400 bg-white" aria-hidden="true" />
            <span className="text-xs font-semibold leading-5 text-slate-600">{label}</span>
          </div>
          {index < labels.length - 1 ? (
            <><ArrowDown size={16} className="mx-auto text-slate-400 lg:hidden" aria-hidden="true" /><ArrowRight size={16} className="hidden shrink-0 text-slate-400 lg:block" aria-hidden="true" /></>
          ) : null}
        </div>
      ))}
    </div>
  );
}

export function SimulationStudioPage() {
  const datasetEvidence = useActiveSportsDataset();
  const phase4 = datasetEvidence.status === "ready" ? datasetEvidence.data.phase4 : undefined;
  return (
    <StudioPageFrame
      eyebrow="Probabilistic game engine"
      title="Simulation Studio"
      description="Compose player, team, participation, event, and usage uncertainty into inspectable game-state simulations and outcome distributions."
      icon={Binary}
      tone="cyan"
      facts={[
        { label: "Simulation runs", value: "0" },
        { label: "Scenarios", value: "0" },
        { label: "Engine", value: "Not configured" },
      ]}
    >
      <MetricStrip items={[
        { label: "Game simulations", value: "0", detail: "No Simulation Run" },
        { label: "Score distributions", value: "0", detail: "No result artifacts" },
        { label: "Player distributions", value: "0", detail: "No result artifacts" },
        { label: "Scenario sets", value: "0", detail: "No scenarios defined" },
      ]} />

      <GameReplaySection replay={phase4?.gameReplay} />
      <BaseOutTransitionSection transition={phase4?.baseOutTransition} />
      <SimulationInputSection input={phase4?.simulationInput} />
      <WholeGameMonteCarloSection mc={phase4?.wholeGameMonteCarlo} />
      <ParticipationAblationSection ablation={phase4?.participationAblation} />
      <StarterIdentitySection starter={phase4?.starterIdentity} />
      <Phase4SimulationStatus study={phase4} />

      <SectionCard title="Sports simulation architecture" description="The studio is reserved for sports-native state propagation; inherited experimental-design simulation is not presented as a game simulator." icon={Workflow}>
        <LineageRail labels={["Player & team state", "Participation & usage", "Event / drive model", "Game-state engine", "Outcome distributions"]} />
      </SectionCard>

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <FeatureTile icon={Goal} title="Game-state simulation" description="Advance innings, base-out states, drives, field position, clock, or score state through sport-specific transitions." />
        <FeatureTile icon={BarChart3} title="Score distributions" description="Produce joint home and away scores, margin or run differential, and totals only from executed simulations." />
        <FeatureTile icon={Users} title="Player outcomes" description="Carry uncertain participation, usage, and event opportunity into coherent player-level distributions." />
        <FeatureTile icon={SlidersHorizontal} title="Scenario analysis" description="Compare confirmed and uncertain lineups, availability, weather, usage, and coaching assumptions." />
      </div>

      <div className="grid gap-4 xl:grid-cols-[minmax(0,1.2fr)_minmax(320px,.8fr)]">
        <SectionCard title="Distribution canvas" description="Charts appear here only after a governed simulation run." icon={ChartNoAxesCombined}>
          <div className="flex min-h-64 flex-col items-center justify-center rounded-xl border border-dashed border-slate-300 bg-slate-50 px-6 text-center">
            <LineChart size={32} className="text-slate-400" aria-hidden="true" />
            <div className="mt-3 text-base font-semibold text-slate-800">No Simulation Run</div>
            <p className="mt-1 max-w-lg text-sm leading-6 text-slate-500">No score, player, or scenario distribution has been generated.</p>
          </div>
        </SectionCard>
        <SectionCard title="Run prerequisites" description="A simulation cannot start until each upstream artifact is versioned." icon={CheckCircle2}>
          <PrerequisiteList items={["Approved forecast contract", "Registered dataset manifest", "Player or team state artifact", "Event or drive model", "Usage and participation model"]} />
        </SectionCard>
      </div>
    </StudioPageFrame>
  );
}

function PrerequisiteList({ items }: { items: string[] }) {
  return (
    <div className="space-y-2">
      {items.map((item) => (
        <div key={item} className="flex items-center gap-3 rounded-lg border border-slate-200 bg-slate-50 px-3 py-2.5">
          <CircleDashed size={16} className="shrink-0 text-slate-400" aria-hidden="true" />
          <span className="min-w-0 flex-1 text-sm font-medium text-slate-700">{item}</span>
          <span className="text-xs font-semibold uppercase text-slate-400">Pending</span>
        </div>
      ))}
    </div>
  );
}

function MetricsComparison({ rows }: { rows: Array<{ label: string; metrics: SportsPaMetrics }> }) {
  return (
    <div className="overflow-x-auto rounded-xl border border-slate-200">
      <table className="w-full min-w-[720px] text-left text-sm" aria-label="Temporal evaluation metric comparison">
        <thead className="bg-slate-900 text-xs uppercase text-slate-300"><tr><th className="px-3 py-3">Evidence</th>{["Rows", "Log loss", "Brier", "Top-label ECE", "Accuracy", "Balanced accuracy", "Macro F1"].map((label) => <th key={label} className="px-3 py-3">{label}</th>)}</tr></thead>
        <tbody>{rows.map(({ label, metrics }) => <tr key={label} className="border-t border-slate-100"><th scope="row" className="px-3 py-3 font-semibold text-slate-900">{label}</th><td className="px-3 py-3">{formatInteger(metrics.rowCount)}</td><td className="px-3 py-3">{formatMetric(metrics.logLoss)}</td><td className="px-3 py-3">{formatMetric(metrics.brierScore)}</td><td className="px-3 py-3">{formatMetric(metrics.topLabelEce)}</td><td className="px-3 py-3">{formatMetric(metrics.top1Accuracy)}</td><td className="px-3 py-3">{formatMetric(metrics.balancedAccuracy)}</td><td className="px-3 py-3">{formatMetric(metrics.macroF1)}</td></tr>)}</tbody>
      </table>
    </div>
  );
}

function MetricEvidenceChart({ rows }: { rows: Array<{ label: string; metrics: SportsPaMetrics }> }) {
  const series = [
    { label: "Log loss", color: "#0e7490", values: rows.map((row) => row.metrics.logLoss) },
    { label: "Summed Brier", color: "#2563eb", values: rows.map((row) => row.metrics.brierScore) },
    { label: "Top-label ECE", color: "#7c3aed", values: rows.map((row) => row.metrics.topLabelEce) },
  ];
  if (!rows.length || !series.some((item) => item.values.some((value) => value !== undefined))) {
    return <div className="flex min-h-44 items-center justify-center rounded-xl border border-dashed border-slate-300 bg-slate-50 text-sm font-semibold text-slate-600">No comparison chart evidence</div>;
  }
  return (
    <div className="space-y-3">
      <svg viewBox="0 0 720 245" role="img" aria-label={`${rows.length} registered evaluation rows compared across log loss, Brier score, and top-label calibration error`} className="w-full rounded-xl border border-slate-200 bg-slate-50">
        <title>Registered probability-metric comparison</title>
        {series.map((item, panelIndex) => {
          const supplied = item.values.filter((value): value is number => value !== undefined);
          const minimum = supplied.length ? Math.min(...supplied) : 0;
          const maximum = supplied.length ? Math.max(...supplied) : 1;
          const span = maximum - minimum || 1;
          const panelLeft = 18 + panelIndex * 238;
          const pointRows = item.values.flatMap((value, rowIndex) => value === undefined ? [] : [{
            rowIndex,
            value,
            x: panelLeft + 24 + ((rowIndex + 0.5) / rows.length) * 184,
            y: 184 - ((value - minimum) / span) * 118,
          }]);
          return <g key={item.label}>
            <text x={panelLeft + 116} y="24" textAnchor="middle" fontSize="12" fontWeight="600" fill="#334155">{item.label}</text>
            <line x1={panelLeft + 24} y1="184" x2={panelLeft + 208} y2="184" stroke="#94a3b8" />
            <line x1={panelLeft + 24} y1="60" x2={panelLeft + 24} y2="184" stroke="#94a3b8" />
            <text x={panelLeft + 20} y="64" textAnchor="end" fontSize="9" fill="#64748b">{formatMetric(maximum)}</text>
            <text x={panelLeft + 20} y="184" textAnchor="end" fontSize="9" fill="#64748b">{formatMetric(minimum)}</text>
            {pointRows.length > 1 ? <polyline points={pointRows.map((point) => `${point.x},${point.y}`).join(" ")} fill="none" stroke={item.color} strokeWidth="2" /> : null}
            {pointRows.map((point) => <g key={point.rowIndex}><circle cx={point.x} cy={point.y} r="4" fill={item.color}><title>{`${rows[point.rowIndex].label}: ${formatMetric(point.value)}`}</title></circle><text x={point.x} y="202" textAnchor="middle" fontSize="9" fill="#64748b">{point.rowIndex + 1}</text></g>)}
          </g>;
        })}
      </svg>
      <ol className="grid gap-1 text-xs text-slate-600 sm:grid-cols-2">{rows.map((row, index) => <li key={row.label}><span className="font-mono font-semibold text-slate-900">{index + 1}</span> · {row.label}</li>)}</ol>
    </div>
  );
}

function ReliabilityEvidence({ metrics }: { metrics: SportsPaMetrics }) {
  const bins = metrics.topLabelReliability.flatMap((bin, index) => {
    const forecast = evidenceNumber(bin, "meanConfidence", "meanPredictedProbability", "averageConfidence", "forecastProbability", "binCenter");
    const observed = evidenceNumber(bin, "accuracy", "observedFrequency", "empiricalFrequency", "eventRate");
    return forecast === undefined || observed === undefined ? [] : [{ bin, index, forecast, observed }];
  });
  if (!bins.length) return <div className="flex min-h-56 items-center justify-center rounded-xl border border-dashed border-slate-300 bg-slate-50 text-sm font-semibold text-slate-600">No calibration observations</div>;
  return (
    <div className="space-y-4">
      <svg viewBox="0 0 420 260" role="img" aria-label={`${bins.length} provided reliability bins`} className="w-full rounded-xl border border-slate-200 bg-slate-50">
        <title>Provided top-label reliability bins</title>
        <line x1="42" y1="220" x2="388" y2="220" stroke="#94a3b8" /><line x1="42" y1="220" x2="42" y2="22" stroke="#94a3b8" /><line x1="42" y1="220" x2="388" y2="22" stroke="#cbd5e1" strokeDasharray="5 5" />
        {bins.map(({ index, forecast, observed }) => <circle key={index} cx={42 + Math.max(0, Math.min(1, forecast)) * 346} cy={220 - Math.max(0, Math.min(1, observed)) * 198} r="5" fill="#0891b2"><title>{`Bin ${index + 1}: forecast ${formatMetric(forecast)}, observed ${formatMetric(observed)}`}</title></circle>)}
        <text x="215" y="248" textAnchor="middle" fontSize="11" fill="#64748b">Forecast probability</text><text x="13" y="125" textAnchor="middle" fontSize="11" fill="#64748b" transform="rotate(-90 13 125)">Observed frequency</text>
      </svg>
      <div className="overflow-x-auto"><table className="w-full text-left text-xs" aria-label="Provided reliability bin evidence"><thead><tr className="text-slate-500"><th className="border-b px-2 py-2">Bin</th><th className="border-b px-2 py-2">Forecast</th><th className="border-b px-2 py-2">Observed</th><th className="border-b px-2 py-2">Rows</th></tr></thead><tbody>{bins.map(({ bin, index, forecast, observed }) => <tr key={index}><td className="border-b px-2 py-2">{evidenceString(bin, "binId", "label") || index + 1}</td><td className="border-b px-2 py-2">{formatMetric(forecast)}</td><td className="border-b px-2 py-2">{formatMetric(observed)}</td><td className="border-b px-2 py-2">{formatInteger(evidenceNumber(bin, "rowCount", "count", "n"))}</td></tr>)}</tbody></table></div>
    </div>
  );
}

const RELIABILITY_COLORS = ["#0e7490", "#2563eb", "#7c3aed", "#c2410c", "#047857", "#be123c", "#4f46e5", "#a16207"];

function ClasswiseReliabilityEvidence({ metrics }: { metrics: SportsPaMetrics }) {
  const classes = (metrics.classOrder.length ? metrics.classOrder : Object.keys(metrics.classwiseReliability)).flatMap((label, classIndex) => {
    const bins = (metrics.classwiseReliability[label] || []).flatMap((bin, binIndex) => {
      const forecast = evidenceNumber(bin, "meanProbability", "meanPredictedProbability", "forecastProbability", "binCenter");
      const observed = evidenceNumber(bin, "realizedFrequency", "observedFrequency", "empiricalFrequency", "eventRate");
      return forecast === undefined || observed === undefined ? [] : [{ forecast, observed, binIndex }];
    });
    return bins.length ? [{ label, classIndex, bins }] : [];
  });
  if (!classes.length) return <div className="flex min-h-56 items-center justify-center rounded-xl border border-dashed border-slate-300 bg-slate-50 text-sm font-semibold text-slate-600">No classwise reliability observations</div>;
  return (
    <div className="space-y-3">
      <svg viewBox="0 0 420 260" role="img" aria-label={`${classes.length} supplied classwise reliability curves`} className="w-full rounded-xl border border-slate-200 bg-slate-50">
        <title>Final 2025 classwise reliability curves</title>
        <line x1="42" y1="220" x2="388" y2="220" stroke="#94a3b8" /><line x1="42" y1="220" x2="42" y2="22" stroke="#94a3b8" /><line x1="42" y1="220" x2="388" y2="22" stroke="#cbd5e1" strokeDasharray="5 5" />
        {classes.map(({ label, classIndex, bins }) => { const color = RELIABILITY_COLORS[classIndex % RELIABILITY_COLORS.length]; const points = bins.map((bin) => `${42 + Math.max(0, Math.min(1, bin.forecast)) * 346},${220 - Math.max(0, Math.min(1, bin.observed)) * 198}`).join(" "); return <g key={label}>{bins.length > 1 ? <polyline points={points} fill="none" stroke={color} strokeWidth="1.5" opacity="0.85" /> : null}{bins.map((bin) => <circle key={bin.binIndex} cx={42 + Math.max(0, Math.min(1, bin.forecast)) * 346} cy={220 - Math.max(0, Math.min(1, bin.observed)) * 198} r="3" fill={color}><title>{`${label} bin ${bin.binIndex + 1}: forecast ${formatMetric(bin.forecast)}, observed ${formatMetric(bin.observed)}`}</title></circle>)}</g>; })}
        <text x="215" y="248" textAnchor="middle" fontSize="11" fill="#64748b">Forecast probability</text><text x="13" y="125" textAnchor="middle" fontSize="11" fill="#64748b" transform="rotate(-90 13 125)">Observed frequency</text>
      </svg>
      <div className="flex flex-wrap gap-2">{classes.map(({ label, classIndex, bins }) => <span key={label} className="inline-flex items-center gap-1.5 rounded-md border border-slate-200 bg-white px-2 py-1 text-[11px] font-semibold text-slate-700"><span className="h-2 w-2 rounded-full" style={{ backgroundColor: RELIABILITY_COLORS[classIndex % RELIABILITY_COLORS.length] }} />{label} · {bins.length} bins</span>)}</div>
    </div>
  );
}

function ProbabilityHistogramEvidence({ metrics }: { metrics: SportsPaMetrics }) {
  const classes = (metrics.classOrder.length ? metrics.classOrder : Object.keys(metrics.probabilityHistograms)).flatMap((label, classIndex) => {
    const bins = (metrics.probabilityHistograms[label] || []).flatMap((bin, binIndex) => {
      const share = evidenceNumber(bin, "populationShare");
      const lower = evidenceNumber(bin, "lowerBound");
      const upper = evidenceNumber(bin, "upperBound");
      return share === undefined || lower === undefined || upper === undefined ? [] : [{ share, midpoint: (lower + upper) / 2, binIndex }];
    });
    return bins.length ? [{ label, classIndex, bins }] : [];
  });
  const maximum = Math.max(0, ...classes.flatMap((item) => item.bins.map((bin) => bin.share)));
  if (!classes.length || maximum <= 0) return <div className="flex min-h-56 items-center justify-center rounded-xl border border-dashed border-slate-300 bg-slate-50 text-sm font-semibold text-slate-600">No probability histogram observations</div>;
  return (
    <div className="space-y-3">
      <svg viewBox="0 0 420 260" role="img" aria-label={`${classes.length} supplied predicted-probability histograms`} className="w-full rounded-xl border border-slate-200 bg-slate-50">
        <title>Final 2025 predicted-probability histograms</title>
        <line x1="42" y1="220" x2="388" y2="220" stroke="#94a3b8" /><line x1="42" y1="220" x2="42" y2="22" stroke="#94a3b8" />
        {classes.map(({ label, classIndex, bins }) => { const color = RELIABILITY_COLORS[classIndex % RELIABILITY_COLORS.length]; const points = bins.map((bin) => `${42 + Math.max(0, Math.min(1, bin.midpoint)) * 346},${220 - (bin.share / maximum) * 188}`).join(" "); return <polyline key={label} points={points} fill="none" stroke={color} strokeWidth="1.75"><title>{`${label} probability-bin population shares`}</title></polyline>; })}
        <text x="215" y="248" textAnchor="middle" fontSize="11" fill="#64748b">Predicted probability bin</text><text x="13" y="125" textAnchor="middle" fontSize="11" fill="#64748b" transform="rotate(-90 13 125)">Population share</text>
      </svg>
      <div className="flex flex-wrap gap-2">{classes.map(({ label, classIndex }) => <span key={label} className="inline-flex items-center gap-1.5 rounded-md border border-slate-200 bg-white px-2 py-1 text-[11px] font-semibold text-slate-700"><span className="h-2 w-2 rounded-full" style={{ backgroundColor: RELIABILITY_COLORS[classIndex % RELIABILITY_COLORS.length] }} />{label}</span>)}</div>
    </div>
  );
}

function PrevalenceAndConfusion({ metrics }: { metrics: SportsPaMetrics }) {
  const classes = metrics.classOrder.length ? metrics.classOrder : Object.keys(metrics.realizedPrevalence);
  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <div className="overflow-x-auto"><table className="w-full text-left text-xs" aria-label="Realized and predicted prevalence"><thead><tr className="text-slate-500"><th className="border-b px-2 py-2">Class</th><th className="border-b px-2 py-2">Realized</th><th className="border-b px-2 py-2">Predicted</th><th className="border-b px-2 py-2">Argmax</th></tr></thead><tbody>{classes.map((label) => <tr key={label}><th scope="row" className="border-b px-2 py-2 font-semibold">{label}</th><td className="border-b px-2 py-2">{formatMetric(metrics.realizedPrevalence[label])}</td><td className="border-b px-2 py-2">{formatMetric(metrics.predictedPrevalence[label])}</td><td className="border-b px-2 py-2">{formatMetric(metrics.argmaxPrevalence[label])}</td></tr>)}</tbody></table>{!classes.length ? <p className="py-5 text-center text-sm text-slate-500">No prevalence evidence returned.</p> : null}</div>
      <div className="overflow-x-auto">{metrics.confusionMatrix.length ? <table className="w-full text-center text-xs" aria-label="Final 2025 confusion matrix"><thead><tr><th className="border-b p-2 text-left text-slate-500">Actual \ predicted</th>{classes.map((label) => <th key={label} className="border-b p-2 text-slate-500">{label}</th>)}</tr></thead><tbody>{metrics.confusionMatrix.map((row, rowIndex) => <tr key={classes[rowIndex] || rowIndex}><th scope="row" className="border-b p-2 text-left font-semibold">{classes[rowIndex] || rowIndex + 1}</th>{row.map((value, columnIndex) => <td key={columnIndex} className="border-b p-2 tabular-nums">{formatInteger(value)}</td>)}</tr>)}</tbody></table> : <p className="py-5 text-center text-sm text-slate-500">No confusion matrix returned.</p>}</div>
    </div>
  );
}

export function EvaluationCalibrationPage() {
  const datasetEvidence = useActiveSportsDataset();
  const baseline = datasetEvidence.status === "ready" ? datasetEvidence.data.paBaseline : undefined;
  const phase4 = datasetEvidence.status === "ready" ? datasetEvidence.data.phase4 : undefined;
  const calibration = baseline?.calibration;
  const decision = sportsPaDecisionStatus(baseline?.decision) || sportsPaDecisionStatus(baseline?.status) || (baseline ? "BLOCKED" : null);
  const calibrationRows = [
    calibration?.raw2024 ? { label: "2024 raw", metrics: calibration.raw2024 } : null,
    calibration?.scaled2024 ? { label: "2024 scaled", metrics: calibration.scaled2024 } : null,
    calibration?.raw2025 ? { label: "2025 raw", metrics: calibration.raw2025 } : null,
    calibration?.scaled2025 ? { label: "2025 scaled", metrics: calibration.scaled2025 } : null,
    calibration?.final2025 ? { label: "2025 final", metrics: calibration.final2025 } : null,
  ].filter((item): item is { label: string; metrics: SportsPaMetrics } => Boolean(item));
  const candidateComparisonIds = [...new Set(["C0", "C1", baseline?.selectedCandidateId]
    .filter((candidateId): candidateId is string => Boolean(candidateId)))];
  const candidateFoldRows = candidateComparisonIds.flatMap((candidateId) => {
    const candidate = baseline?.candidates.find((item) => item.candidateId === candidateId);
    if (!candidate) return [];
    const role = candidateId === "C0" ? "C0 global" : candidateId === "C1" ? "C1 context" : "Selected candidate";
    return candidate.folds.flatMap((fold) => {
      const metrics = fold.metrics || fold.rawMetrics || fold.calibratedMetrics;
      if (!metrics || (fold.validationSeason !== 2024 && fold.validationSeason !== 2025)) return [];
      return [{ label: `${role} · ${fold.validationSeason} · ${candidate.name}`, metrics }];
    });
  });
  const evaluationViewCount = candidateFoldRows.length + calibrationRows.length;
  const finalMetrics = calibration?.final2025;
  const reliabilityBins = calibrationRows.reduce((total, item) => total + item.metrics.topLabelReliability.length, 0);
  return (
    <StudioPageFrame
      eyebrow="Forward-looking evidence"
      title="Evaluation & Calibration"
      description="Judge sports forecasts on frozen rolling-origin validation, probability reliability, subgroup stability, missingness, and uncertainty."
      icon={Gauge}
      tone="blue"
      status={decision || calibration?.status || "NOT CONFIGURED"}
      facts={[
        { label: "Evaluation views", value: String(evaluationViewCount) },
        { label: "Calibration", value: calibration?.status || "No evidence" },
        { label: "Decision", value: baseline ? decision || "BLOCKED" : "NOT CONFIGURED" },
      ]}
    >
      <MetricStrip items={[
        { label: "Evaluation views", value: String(evaluationViewCount), detail: evaluationViewCount ? "Cross-candidate and calibration evidence" : "No Evaluation Evidence" },
        { label: "Final validation rows", value: formatInteger(finalMetrics?.rowCount), detail: finalMetrics ? "2025 frozen validation fold" : "No validation fold evaluated" },
        { label: "Provided reliability bins", value: String(reliabilityBins), detail: reliabilityBins ? "No interpolated or invented bins" : "No calibrated forecasts" },
        { label: "Research decision", value: baseline ? decision || "BLOCKED" : "NOT CONFIGURED", detail: baseline?.decisionReason || "No model decision" },
      ]} />

      {evaluationViewCount ? <>
        {candidateFoldRows.length ? <SectionCard title="Frozen 2024 / 2025 candidate fold comparison" description="C0 global, C1 context, and the selected candidate are compared from their registered rolling-origin fold metrics; a selected C1 row is shown once." icon={Scale}><div className="space-y-4"><MetricEvidenceChart rows={candidateFoldRows} /><MetricsComparison rows={candidateFoldRows} /></div></SectionCard> : null}
        {calibrationRows.length ? <SectionCard title="2024 calibration and 2025 final comparison" description="Raw and scaled evidence is shown only when supplied by the registered run." icon={BarChart3}><div className="space-y-4"><MetricEvidenceChart rows={calibrationRows} /><MetricsComparison rows={calibrationRows} /></div></SectionCard> : null}
        {finalMetrics ? <SectionCard title="Final 2025 prevalence and confusion" description="Class prevalence and confusion counts use the frozen 2025 rolling-origin validation evidence." icon={Target}><PrevalenceAndConfusion metrics={finalMetrics} /></SectionCard> : null}
        <div className="grid gap-4 xl:grid-cols-2">
          <SectionCard title="Provided final reliability bins" description="The chart draws only bins present in final 2025 evidence." icon={LineChart}>{finalMetrics ? <ReliabilityEvidence metrics={finalMetrics} /> : <div className="text-sm text-slate-500">No final 2025 reliability evidence returned.</div>}</SectionCard>
          <SectionCard title="Calibration decision" description="Temperature fitting and retention remain separate from the terminal research decision." icon={SlidersHorizontal}>
            <dl className="grid gap-3 sm:grid-cols-2">{[["Status", calibration?.status || "NOT_RUN"], ["Source season", calibration?.sourceSeason ?? "—"], ["Fitted temperature", formatMetric(calibration?.fittedTemperature)], ["Retained temperature", formatMetric(calibration?.retainedTemperature)], ["Retained", calibration?.retained === undefined ? "Not recorded" : calibration.retained ? "Yes" : "No"], ["Reason", calibration?.reason || "Not recorded"]].map(([label, value]) => <div key={String(label)} className="rounded-lg border border-slate-200 bg-slate-50 p-3"><dt className="text-xs font-semibold uppercase text-slate-500">{label}</dt><dd className="mt-1 break-words text-sm font-semibold text-slate-900">{String(value)}</dd></div>)}</dl>
          </SectionCard>
        </div>
        <div className="grid gap-4 xl:grid-cols-2">
          <SectionCard title="Final 2025 classwise reliability" description="Each curve uses only supplied per-class bins; no interpolation or missing bin is invented." icon={LineChart}>{finalMetrics ? <ClasswiseReliabilityEvidence metrics={finalMetrics} /> : <div className="text-sm text-slate-500">No final classwise reliability evidence returned.</div>}</SectionCard>
          <SectionCard title="Final 2025 probability histograms" description="Per-class population shares show where the frozen model placed probability mass." icon={BarChart3}>{finalMetrics ? <ProbabilityHistogramEvidence metrics={finalMetrics} /> : <div className="text-sm text-slate-500">No final probability histogram evidence returned.</div>}</SectionCard>
        </div>
        <SectionCard title="Paired bootstrap comparisons" description="Point estimates, intervals, resample counts, and seeds are displayed; individual replicate arrays are intentionally withheld from the surface." icon={Scale}>
          {baseline?.bootstrapComparisons.length ? <div className="grid gap-3 lg:grid-cols-2">{baseline.bootstrapComparisons.map((comparison, index) => <article key={`${comparison.comparatorCandidateId}-${comparison.foldId || index}`} className="rounded-xl border border-slate-200 p-4"><div className="flex flex-wrap items-center justify-between gap-2"><h3 className="font-semibold text-slate-950">{comparison.comparatorName}</h3><StatusPill label={comparison.validationSeason ? String(comparison.validationSeason) : comparison.foldId || "COMPARISON"} /></div><p className="mt-1 text-xs text-slate-500">{comparison.comparatorCandidateId} · {formatInteger(comparison.resampleCount)} resamples · seed {comparison.seed ?? "—"}</p><div className="mt-3 grid gap-2 sm:grid-cols-2">{[["Log-loss difference", comparison.logLossDifference], ["Brier-score difference", comparison.brierScoreDifference]].map(([label, evidence]) => { const record = evidence as SportsPaEvidenceRecord; const interval = record.percentileInterval as SportsPaEvidenceRecord | undefined; return <dl key={String(label)} className="rounded-lg bg-slate-50 p-3 text-xs"><dt className="font-semibold text-slate-800">{String(label)}</dt><dd className="mt-2 space-y-1 text-slate-600"><div>Point: {formatMetric(evidenceNumber(record, "pointEstimate"))}</div><div>Mean: {formatMetric(evidenceNumber(record, "bootstrapMean"))}</div><div>Interval: {formatMetric(evidenceNumber(interval, "lower"))} to {formatMetric(evidenceNumber(interval, "upper"))}</div><div>P(selected better): {formatMetric(evidenceNumber(record, "probabilitySelectedBetter"))}</div></dd></dl>; })}</div></article>)}</div> : <p className="text-sm text-slate-500">No bootstrap comparison evidence was returned.</p>}
        </SectionCard>
      </> : <EmptyState icon={Gauge} title="No Evaluation Evidence" description="No 2024 calibration or frozen 2025 rolling-origin metrics were returned by the active dataset." detail={baseline?.decisionReason} />}
      <Phase4EvaluationSection study={phase4} />
    </StudioPageFrame>
  );
}

const FUTURE_MODEL_GRAPH_NODES = ["Confirmed-lineup feed", "Probable-starter feed", "Injury and transaction feed", "Handedness / platoon (E6)", "Batter archetypes", "Pitcher archetypes", "SVM challenger", "Random forest / extra trees challenger", "Boosting challenger", "Neural challenger", "Premium Statcast ablation", "Catcher state", "Pitcher-catcher battery interaction", "Catcher-batter archetype interaction", "Pitch selection and sequencing", "Catcher framing", "Catcher blocking", "Catcher throwing / running control", "ABS challenge decision model", "Base-out transition model", "Game simulator", "Residual model", "Forecast bundle", "Forward monitoring"];

function graphNodeId(node: SportsPaEvidenceRecord, index: number) {
  return evidenceString(node, "nodeId", "id", "artifactId", "key") || `node-${index + 1}`;
}

function graphNodeLabel(node: SportsPaEvidenceRecord, index: number) {
  return evidenceString(node, "displayName", "label", "name", "nodeType", "artifactId") || `Research node ${index + 1}`;
}

export function ModelGraphPage() {
  const datasetEvidence = useActiveSportsDataset();
  const dataset = datasetEvidence.status === "ready" ? datasetEvidence.data : null;
  const baseline = dataset?.paBaseline;
  const phase4 = dataset?.phase4;
  const graph = baseline?.graph;
  const decision = sportsPaDecisionStatus(baseline?.decision) || sportsPaDecisionStatus(baseline?.status) || (baseline ? "BLOCKED" : null);
  const hasResearchGraph = Boolean(graph?.nodes.length);
  return (
    <StudioPageFrame
      eyebrow="Component decision system"
      title="Model Graph"
      description="Inspect the governed PA research lineage from feature authority through candidates, calibration, evaluation, and terminal decision."
      icon={Network}
      tone={terminalTone(decision)}
      status={decision || "NOT CONFIGURED"}
      facts={[
        { label: "Research graphs", value: hasResearchGraph ? "1" : "0" },
        { label: "Evidence nodes", value: String(graph?.nodes.length ?? 0) },
        { label: "Decision", value: baseline ? decision || "BLOCKED" : "NOT CONFIGURED" },
      ]}
    >
      <SectionCard title={hasResearchGraph ? "Registered research evidence graph" : "No Model Graph"} description={hasResearchGraph ? "Nodes and directed edges are projected from the registered PA baseline. This graph grants no bundle or delivery authority." : "No research graph evidence is bound to the active dataset."} icon={GitBranch} action={<StatusPill label={decision || graph?.status || "NOT_CONFIGURED"} tone={terminalTone(decision)} />}>
        {hasResearchGraph ? <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_360px]">
          <ol className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3" aria-label="Research model graph nodes">
            {graph!.nodes.map((node, index) => <li key={graphNodeId(node, index)} className="rounded-xl border border-slate-200 bg-slate-50 p-4"><div className="flex items-center gap-3"><span className="inline-flex h-9 w-9 items-center justify-center rounded-lg bg-slate-950 text-cyan-200"><Network size={17} aria-hidden="true" /></span><div className="min-w-0"><div className="break-words text-sm font-semibold text-slate-950">{graphNodeLabel(node, index)}</div><div className="mt-1 break-words font-mono text-[11px] text-slate-500">{graphNodeId(node, index)}</div></div></div><div className="mt-3"><StatusPill label={evidenceString(node, "status", "state") || "RECORDED"} /></div></li>)}
          </ol>
          <div><h3 className="text-xs font-semibold uppercase tracking-wide text-slate-500">Directed edges</h3><ul className="mt-2 space-y-2" aria-label="Research model graph edges">{graph!.edges.map((edge, index) => { const source = evidenceString(edge, "sourceNodeId", "source", "from") || "Unknown source"; const target = evidenceString(edge, "targetNodeId", "target", "to") || "Unknown target"; return <li key={`${source}-${target}-${index}`} className="rounded-lg border border-slate-200 p-3 text-xs"><div className="flex items-center gap-2 font-semibold text-slate-800"><span className="break-all">{source}</span><ArrowRight size={14} className="shrink-0 text-cyan-700" aria-hidden="true" /><span className="break-all">{target}</span></div><div className="mt-1 text-slate-500">{evidenceString(edge, "relation", "relationship", "edgeType", "type") || "depends on"}</div></li>; })}</ul>{!graph!.edges.length ? <p className="mt-2 text-sm text-slate-500">No directed edges were returned.</p> : null}</div>
        </div> : <EmptyState icon={Network} title="No Model Graph" description="The active evidence does not include a completed PA research graph." detail={baseline?.decisionReason} />}
      </SectionCard>

      <Phase4GraphSection study={phase4} />

      {phase4?.incrementalSignalStudy ? (() => {
        const s = phase4.incrementalSignalStudy!;
        const dec = (s.decision ?? {}) as Record<string, unknown>;
        const e1 = (dec.e1 ?? {}) as Record<string, unknown>;
        const e2 = (dec.e2 ?? {}) as Record<string, unknown>;
        const ns = (s.nextStep ?? {}) as Record<string, unknown>;
        return (
          <SectionCard title="E1/E2 incremental-signal research study" description="Completed feature-ablation decision node (D3 vs D3+E1 vs D3+E1+E2). Research only — grants no promotion, bundle, or champion change." icon={GitBranch} action={<StatusPill label="FEATURE_ABLATION_COMPLETE" tone="cyan" />}>
            <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
              <div className="flex items-center justify-between gap-2 rounded-lg border border-slate-200 bg-slate-50 px-3 py-2.5"><span className="text-xs font-semibold text-slate-700">E1 predictive value</span><span className="text-[11px] font-semibold uppercase text-slate-500">{String(e1.decision ?? "—")}</span></div>
              <div className="flex items-center justify-between gap-2 rounded-lg border border-slate-200 bg-slate-50 px-3 py-2.5"><span className="text-xs font-semibold text-slate-700">E2 incremental value</span><span className="text-[11px] font-semibold uppercase text-slate-500">{String(e2.decision ?? "—")}</span></div>
              <div className="flex items-center justify-between gap-2 rounded-lg border border-slate-200 bg-slate-50 px-3 py-2.5"><span className="text-xs font-semibold text-slate-700">Recommended next</span><span className="text-[11px] font-semibold uppercase text-slate-500">{String(ns.recommendedPath ?? "—")}</span></div>
            </div>
          </SectionCard>
        );
      })() : null}

      <SectionCard title="Terminal research vocabulary" description="Only the terminal statuses supported by PA baseline evidence are shown." icon={ShieldCheck}>
        <div className="flex flex-wrap gap-2">
          {["RESEARCH_CHALLENGER", "RESEARCH_BASELINE", "REJECTED_BASELINE", "BLOCKED"].map((status) => (
            <span key={status} className={`rounded-full border px-3 py-2 text-xs font-semibold tracking-wide ${status === decision ? "border-cyan-200 bg-cyan-50 text-cyan-800" : "border-slate-200 bg-slate-50 text-slate-600"}`}>{status}</span>
          ))}
        </div>
      </SectionCard>

      <SectionCard title="Remaining Gen-2 components" description="These future nodes remain explicitly not configured; no simulation or forecast bundle is implied." icon={CircleDashed}>
        <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4">{FUTURE_MODEL_GRAPH_NODES.map((label) => <div key={label} className="flex items-center justify-between gap-2 rounded-lg border border-slate-200 bg-slate-50 px-3 py-2.5"><span className="text-xs font-semibold text-slate-700">{label}</span><span className="text-[11px] font-semibold uppercase text-slate-400">NOT_CONFIGURED</span></div>)}</div>
      </SectionCard>
    </StudioPageFrame>
  );
}

export function RegistryDeploymentPage() {
  const datasetEvidence = useActiveSportsDataset();
  const baseline = datasetEvidence.status === "ready" ? datasetEvidence.data.paBaseline : undefined;
  const phase4 = datasetEvidence.status === "ready" ? datasetEvidence.data.phase4 : undefined;
  const registry = baseline?.registry;
  const decision = sportsPaDecisionStatus(baseline?.decision) || sportsPaDecisionStatus(baseline?.status) || (baseline ? "BLOCKED" : null);
  const selected = baseline?.candidates.find((candidate) => candidate.candidateId === baseline.selectedCandidateId || candidate.selected);
  const artifactEvidence = registry?.artifacts.length ? registry.artifacts : baseline?.artifacts ?? [];
  const bundleContents = [
    "Player-state artifacts",
    "Event or drive models",
    "Usage models",
    "Simulator",
    "Calibration",
    "Ensemble",
    "Schemas",
    "Dependencies",
    "OOD policy",
    "Checksums",
    "Validation evidence",
  ];
  return (
    <StudioPageFrame
      eyebrow="Governed model delivery"
      title="Registry & Deployment"
      description="Inspect registered PA research artifacts and their lineage while graph approval, bundle export, and deployment targets remain unavailable."
      icon={PackageCheck}
      tone={terminalTone(decision)}
      status={baseline ? decision || "BLOCKED" : "NOT CONFIGURED"}
      facts={[
        { label: "Research artifacts", value: String(artifactEvidence.length) },
        { label: "Approved graphs", value: "0" },
        { label: "Exported bundles", value: "0" },
      ]}
    >
      <MetricStrip items={[
        { label: "Research registry records", value: registry ? "1" : "0", detail: baseline?.runId || "No registered run" },
        { label: "Approved graphs", value: "0", detail: baseline?.graph ? "Research graph evidence only" : "No Model Graph" },
        { label: "Bundles", value: "0", detail: "No Bundle Exported" },
        { label: "Target environments", value: "0", detail: "No deployment target" },
      ]} />

      <Phase4RegistrySection study={phase4} />

      <SectionCard title="Research artifact registry" description="The terminal PA research status and immutable artifact references come from the active dataset; no delivery state is inferred." icon={Boxes} action={<StatusPill label={baseline ? decision || "BLOCKED" : "NOT CONFIGURED"} tone={terminalTone(decision)} />}>
        {registry || artifactEvidence.length ? <div className="space-y-4">
          <div className="overflow-x-auto rounded-xl border border-slate-200"><table className="w-full min-w-[760px] text-left text-sm" aria-label="PA research model registry"><thead className="bg-slate-900 text-xs uppercase text-slate-300"><tr>{["Research run", "Selected candidate", "Artifact references", "Terminal research status", "Approved graph", "Bundle", "Target"].map((label) => <th key={label} className="px-3 py-3">{label}</th>)}</tr></thead><tbody><tr><td className="max-w-80 break-all px-3 py-3 font-mono text-xs font-semibold text-slate-900">{baseline?.runId || "Not recorded"}</td><td className="px-3 py-3">{selected?.name || baseline?.selectedCandidateId || "Not selected"}</td><td className="px-3 py-3">{artifactEvidence.length}</td><td className="px-3 py-3"><StatusPill label={decision || "BLOCKED"} tone={terminalTone(decision)} /></td><td className="px-3 py-3">0</td><td className="px-3 py-3">0</td><td className="px-3 py-3">0</td></tr></tbody></table></div>
          <div><h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">Artifact lineage</h3><EvidenceRecordList records={artifactEvidence} empty="No artifact lineage records were returned." /></div>
          {baseline?.decisionReason ? <div className="rounded-lg border border-slate-200 bg-slate-50 p-3 text-sm text-slate-700"><span className="font-semibold">Decision rationale:</span> {baseline.decisionReason}</div> : null}
        </div> : <PlaceholderTable columns={["Component", "Graph", "Bundle", "Status", "Lifecycle", "Last trained", "Validation status", "Target environment"]} title="Sports model registry" />}
      </SectionCard>

      <SectionCard
        eyebrow="Future export contract"
        title="ASP model bundle"
        description="A model bundle is an immutable, self-contained sports forecasting graph that ASP can load and execute without ASP Model Studio being online."
        icon={Box}
        action={<div className="flex items-center gap-2"><StatusPill label="EXPORT DISABLED" tone="slate" /><button type="button" disabled className="cursor-not-allowed rounded-lg bg-slate-200 px-3 py-2 text-xs font-semibold text-slate-500">Export unavailable</button></div>}
      >
        <EmptyState
          icon={PackageCheck}
          title="No standalone ASP model bundle has been approved or exported."
          description="An approved model graph, complete validation evidence, dependency lock, schemas, and checksums are required before export becomes available."
          contract="SPORTS_MODEL_BUNDLE_V1"
        />
        <div className="mt-5">
          <h3 className="text-sm font-semibold text-slate-950">Expected bundle contents</h3>
          <div className="mt-3 grid gap-2 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
            {bundleContents.map((item) => (
              <div key={item} className="flex items-center gap-2 rounded-lg border border-slate-200 bg-slate-50 px-3 py-2.5 text-xs font-semibold text-slate-700"><CircleDashed size={15} className="shrink-0 text-slate-400" />{item}</div>
            ))}
          </div>
        </div>
      </SectionCard>

      <SectionCard title="Export gates" description="Export and deployment remain unavailable; a terminal research status is not delivery authority." icon={LockKeyhole}>
        <PrerequisiteList items={["Approved component DAG", "Temporal validation complete", "Calibration evidence accepted", "OOD and missingness policy defined", "Schemas and dependencies locked", "Checksums produced"]} />
      </SectionCard>
    </StudioPageFrame>
  );
}

export function ForwardMonitoringPage() {
  return (
    <StudioPageFrame
      eyebrow="Prospective evidence"
      title="Forward Monitoring"
      description="Evaluate forecasts when future ASP evidence arrives, then compare calibration, drift, outcomes, and research challengers without changing the source system."
      icon={MonitorDot}
      tone="amber"
      facts={[
        { label: "Monitoring plans", value: "0" },
        { label: "Incoming feeds", value: "0" },
        { label: "ASP connection", value: "Planned" },
      ]}
    >
      <MetricStrip items={[
        { label: "Monitoring plans", value: "0", detail: "No Monitoring Plan" },
        { label: "Forecast batches", value: "0", detail: "No prospective evidence" },
        { label: "Drift signals", value: "0", detail: "No evidence window" },
        { label: "Challenger comparisons", value: "0", detail: "No forward comparison" },
      ]} />

      <SectionCard title="Future ASP evidence loop" description="The connection remains explanatory in Phase 3. ASP is not connected and no forecasts or outcomes have been imported." icon={RadioTower} action={<StatusPill label="Connection planned" tone="amber" />}>
        <LineageRail labels={["ASP forecasts", "Probabilities", "Scores & outcomes", "Calibration", "Drift", "Challenger comparison"]} />
      </SectionCard>

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        <FeatureTile icon={Target} title="Forecast integrity" description="Track forecast timestamps, intended lifecycle, population, graph version, and target definition." />
        <FeatureTile icon={Gauge} title="Calibration" description="Compare forecast probability bands with realized outcomes once the observation window matures." />
        <FeatureTile icon={Activity} title="Data and concept drift" description="Monitor input coverage, distribution shift, missingness, usage state, and model behavior." />
        <FeatureTile icon={Goal} title="Scores and outcomes" description="Join finalized game and player outcomes to the exact forecast evidence available at prediction time." />
        <FeatureTile icon={Beaker} title="Challenger comparison" description="Evaluate research challengers prospectively beside any future approved graph without promoting them." />
        <FeatureTile icon={FileClock} title="Evidence maturity" description="Keep incomplete games, stat corrections, and delayed labels distinct from mature monitoring windows." />
      </div>

      <SectionCard title="No Monitoring Plan" description="Create a monitoring plan only after a bundle and its target outcomes have been approved." icon={MonitorDot}>
        <PrerequisiteList items={["Exported model bundle", "Forecast evidence contract", "Outcome maturity policy", "Monitoring cohorts", "Alert and review policy"]} />
      </SectionCard>
    </StudioPageFrame>
  );
}

export function ResearchToolsPage() {
  const tools = [
    { icon: BarChart3, title: "Analytics Workbench", description: "Interrogate governed sports datasets with reproducible analytical views and exported evidence." },
    { icon: Code2, title: "SQL Lab", description: "Author read-only analytical queries against project-scoped registered data." },
    { icon: ChartNoAxesCombined, title: "Visualization Studio", description: "Build publication-quality sports research charts without implying unobserved results." },
    { icon: Beaker, title: "Experiment Workspace", description: "Prototype candidate specifications before they enter the governed Model Laboratory." },
    { icon: Telescope, title: "Challenger Research", description: "Track hypotheses and research candidates separately from operational model decisions." },
    { icon: BookOpenCheck, title: "Methodology Evidence", description: "Collect assumptions, tests, limitations, and decision rationale alongside analytical artifacts." },
  ];
  return (
    <StudioPageFrame
      eyebrow="Reproducible exploration"
      title="Research Tools"
      description="Explore sports evidence, test hypotheses, and shape research challengers while preserving the boundary between discovery and approved model artifacts."
      icon={Telescope}
      tone="violet"
      facts={[
        { label: "Research sessions", value: "0" },
        { label: "Saved analyses", value: "0" },
        { label: "Challengers", value: "0" },
      ]}
    >
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        {tools.map((tool) => <FeatureTile key={tool.title} {...tool} tag="GENERIC CAPABILITY" />)}
      </div>

      <div className="grid gap-4 xl:grid-cols-[minmax(0,1.3fr)_minmax(320px,.7fr)]">
        <SectionCard title="Research activity" description="Saved target-local work will appear with its project, dataset version, author, and evidence status." icon={FileClock}>
          <EmptyState icon={Telescope} title="No Research Session" description="No sports research work has been saved in this workspace." />
        </SectionCard>
        <SectionCard title="Research boundary" description="Exploration can inform a challenger, but cannot silently become operational." icon={ShieldCheck}>
          <PrerequisiteList items={["Project-scoped evidence", "Reproducible query or code", "Saved analytical artifact", "Candidate registration", "Independent validation"]} />
        </SectionCard>
      </div>
    </StudioPageFrame>
  );
}

type ResearchSurfaceSpec = {
  title: string;
  eyebrow: string;
  description: string;
  icon: LucideIcon;
  capabilities: Array<{ icon: LucideIcon; title: string; description: string }>;
  emptyTitle: string;
  emptyDescription: string;
  evidence: string[];
};

const researchSurfaces: Record<"analytics" | "sql" | "visualization" | "documentation", ResearchSurfaceSpec> = {
  analytics: {
    title: "Analytics Workbench",
    eyebrow: "Reproducible sports analysis",
    description: "Profile registered sports evidence, engineer candidate features, run project-scoped Python, and preserve analytical lineage without overstating results.",
    icon: Beaker,
    capabilities: [
      { icon: BarChart3, title: "Sports data profiling", description: "Review identity, missingness, distributions, coverage, and temporal availability at the registered grain." },
      { icon: Code2, title: "Python execution", description: "Run reproducible project-scoped analysis with saved code, parameters, outputs, and environment evidence." },
      { icon: Layers3, title: "Feature research", description: "Develop player, team, usage, event, drive, and game-state candidate features." },
    ],
    emptyTitle: "No Sports Dataset Registered",
    emptyDescription: "The workbench will activate after a SPORTS_DATASET_MANIFEST_V1 is validated for this workspace.",
    evidence: ["Dataset version", "Analysis code", "Runtime identity", "Saved findings", "Artifact lineage"],
  },
  sql: {
    title: "SQL Lab",
    eyebrow: "Version-pinned query workspace",
    description: "Author read-only sports research queries against immutable, project-scoped dataset versions and retain query evidence with every result.",
    icon: Code2,
    capabilities: [
      { icon: Database, title: "Registered tables", description: "Query only schemas exposed by an approved sports dataset manifest." },
      { icon: FileSearch2, title: "Sports query patterns", description: "Explore games, players, events, drives, participation, usage, and temporal coverage." },
      { icon: FileCheck2, title: "Query lineage", description: "Save SQL text, dataset identity, execution time, result schema, and export evidence." },
    ],
    emptyTitle: "No Query Context",
    emptyDescription: "SQL execution is waiting for a registered sports dataset manifest; no external warehouse is browsed from this page.",
    evidence: ["Read-only SQL", "Dataset checksum", "Query parameters", "Result schema", "Export record"],
  },
  visualization: {
    title: "Visualization Studio",
    eyebrow: "Sports analytical graphics",
    description: "Build clear, publication-quality views of registered sports evidence, forecast distributions, calibration, and stability without fabricating observations.",
    icon: ChartNoAxesCombined,
    capabilities: [
      { icon: BarChart3, title: "Evidence charts", description: "Profile coverage, player and team state, event distributions, and temporal behavior." },
      { icon: LineChart, title: "Reliability views", description: "Visualize calibration, score error, probability bands, fold stability, and uncertainty." },
      { icon: FileCheck2, title: "Chart evidence", description: "Preserve data identity, filters, chart specification, annotations, and export lineage." },
    ],
    emptyTitle: "No Visualization Context",
    emptyDescription: "No sports dataset, experiment result, forecast distribution, or calibration artifact is available to visualize.",
    evidence: ["Chart specification", "Data version", "Filters", "Annotations", "Export artifact"],
  },
  documentation: {
    title: "Model Documentation",
    eyebrow: "Methodology & validation package",
    description: "Assemble a governed sports methodology package from forecast contracts, evidence manifests, experiments, temporal validation, calibration, model-graph decisions, and limitations.",
    icon: BookOpenCheck,
    capabilities: [
      { icon: FileCheck2, title: "Methodology package", description: "Document targets, populations, assumptions, component methods, simulation, and uncertainty." },
      { icon: ShieldCheck, title: "Validation evidence", description: "Link temporal folds, reliability diagnostics, subgroup stability, OOD policy, and reviewer decisions." },
      { icon: GitBranch, title: "Graph decision record", description: "Explain selected components, research challengers, dependencies, lifecycle status, and export readiness." },
    ],
    emptyTitle: "No Documentation Workspace",
    emptyDescription: "Create a sports project and collect workflow evidence before generating its methodology and validation package.",
    evidence: ["Forecast contract", "Manifest identity", "Experiment evidence", "Validation package", "Model graph decision"],
  },
};

export function AnalyticsWorkbenchPage() { return <ResearchToolSurface spec={researchSurfaces.analytics} />; }
export function SqlLabPage() { return <ResearchToolSurface spec={researchSurfaces.sql} />; }
export function VisualizationStudioPage() { return <ResearchToolSurface spec={researchSurfaces.visualization} />; }
export function ModelDocumentationPage() { return <ResearchToolSurface spec={researchSurfaces.documentation} />; }

function ResearchToolSurface({ spec }: { spec: ResearchSurfaceSpec }) {
  return (
    <StudioPageFrame
      eyebrow={spec.eyebrow}
      title={spec.title}
      description={spec.description}
      icon={spec.icon}
      tone="violet"
      status="NOT CONFIGURED"
      facts={[
        { label: "Dataset context", value: "Not loaded" },
        { label: "Artifact context", value: "Not loaded" },
        { label: "Evidence state", value: "Awaiting context" },
      ]}
    >
      <div className="grid gap-4 md:grid-cols-3">
        {spec.capabilities.map((capability) => <FeatureTile key={capability.title} {...capability} tag="GENERIC CAPABILITY" />)}
      </div>
      <div className="grid gap-4 xl:grid-cols-[minmax(0,1.25fr)_minmax(320px,.75fr)]">
        <SectionCard title="Workspace state" description="This module activates only from target-local, registered sports evidence." icon={spec.icon}>
          <EmptyState icon={CircleDashed} title={spec.emptyTitle} description={spec.emptyDescription} detail="No historical sports data or performance result is inferred." />
        </SectionCard>
        <SectionCard title="Evidence captured" description="Every saved output carries its analytical identity." icon={Fingerprint}>
          <PrerequisiteList items={spec.evidence} />
        </SectionCard>
      </div>
    </StudioPageFrame>
  );
}

export function DataSourcesRightsPage() {
  const rightsChecks = [
    { icon: Scale, title: "Permitted use", description: "Document modeling, validation, display, and redistribution permissions for each source." },
    { icon: Clock3, title: "Temporal availability", description: "Record when evidence became available relative to every forecast cutoff." },
    { icon: Fingerprint, title: "Source identity", description: "Pin provider, product, delivery, version, partition, and checksum identity." },
    { icon: FileCheck2, title: "Coverage and exclusions", description: "Declare eligible sports, leagues, seasons, populations, and excluded records." },
  ];
  return (
    <StudioPageFrame
      eyebrow="Evidence governance"
      title="Data Sources & Rights"
      description="Make source ownership, permitted use, version identity, timing, and exclusions visible before evidence can enter a sports modeling workflow."
      icon={Scale}
      tone="amber"
      facts={[
        { label: "Registered sources", value: "0" },
        { label: "Rights records", value: "0" },
        { label: "Open reviews", value: "0" },
      ]}
    >
      <SectionCard title="Source and rights ledger" description="No external sports warehouse is connected in Phase 1." icon={Database} action={<StatusPill label="Read-only contract" tone="amber" />}>
        <EmptyState
          icon={FileKey2}
          title="No Data Source Registered"
          description="Source registrations and rights attestations will arrive through the immutable sports dataset manifest."
          detail="This workspace does not browse, copy, or alter the external ASP warehouse."
          contract="SPORTS_DATASET_MANIFEST_V1"
        />
      </SectionCard>

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        {rightsChecks.map((check) => <FeatureTile key={check.title} {...check} tag="REQUIRED" />)}
      </div>

      <SectionCard title="Rights review matrix" description="Source-level permissions will be evaluated against intended modeling and export uses." icon={ShieldCheck}>
        <PlaceholderTable columns={["Source", "Sport", "Version", "Use", "Export", "Review"]} title="Sports data source rights" />
      </SectionCard>
    </StudioPageFrame>
  );
}

export function AdministrationPage() {
  const controls = [
    { icon: ShieldCheck, title: "Workspace governance", description: "Project isolation, authentication, permissions, and evidence boundaries." },
    { icon: ServerCog, title: "Runtime isolation", description: "Target-local storage, backend services, ports, and execution environments." },
    { icon: FileCheck2, title: "Audit evidence", description: "Project events, approvals, exports, and administrative changes." },
    { icon: CloudCog, title: "Integration policy", description: "Future source and deployment connections remain explicitly configured and least-privileged." },
  ];
  return (
    <StudioPageFrame
      eyebrow="Platform control center"
      title="Administration"
      description="Govern the isolated ASP Model Studio workspace, its project boundaries, integrations, runtime controls, and audit evidence."
      icon={ServerCog}
      tone="slate"
      status="TARGET-LOCAL"
      facts={[
        { label: "Admin event feed", value: "Not loaded" },
        { label: "Integration policy", value: "Explicit" },
        { label: "Workspace", value: "Isolated" },
      ]}
    >
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        {controls.map((control) => <FeatureTile key={control.title} {...control} />)}
      </div>

      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_minmax(320px,.72fr)]">
        <SectionCard title="Administrative activity" description="Only target-local administrative events belong in this workspace." icon={FileClock}>
          <EmptyState icon={CircleDashed} title="Administrative Activity Not Loaded" description="This surface does not infer whether administrative actions are pending." detail="Runtime health and user-directory data are shown only when connected to their target-local services." />
        </SectionCard>
        <SectionCard title="Isolation posture" description="Phase 1 keeps sports modeling independent from other products and source systems." icon={LockKeyhole}>
          <div className="space-y-2">
            {["Target-local runtime", "Target-local project storage", "Authentication preserved", "External warehouse not connected", "Public registration unavailable"].map((item) => (
              <div key={item} className="flex items-center gap-3 rounded-lg border border-emerald-200 bg-emerald-50/60 px-3 py-2.5 text-sm font-medium text-emerald-950"><ShieldCheck size={16} className="shrink-0 text-emerald-700" />{item}</div>
            ))}
          </div>
        </SectionCard>
      </div>
    </StudioPageFrame>
  );
}

export function UsersSettingsPage() {
  const preferences = [
    { title: "Workspace identity", detail: "ASP Model Studio · Sports Forecasting, Simulation & Model Intelligence", icon: Sparkles },
    { title: "Display", detail: "Professional analytical interface · responsive density", icon: MonitorDot },
    { title: "Evidence defaults", detail: "Immutable versions · point-in-time integrity", icon: ShieldCheck },
    { title: "Notifications", detail: "No monitoring or review notifications configured", icon: Activity },
  ];
  return (
    <StudioPageFrame
      eyebrow="Access and workspace preferences"
      title="Users & Settings"
      description="Manage target-local access posture and analytical workspace preferences without weakening authentication or project isolation."
      icon={Settings2}
      tone="blue"
      status="AUTHENTICATION PRESERVED"
      facts={[
        { label: "Directory", value: "Target-local" },
        { label: "Public registration", value: "Disabled" },
        { label: "Project isolation", value: "Required" },
      ]}
    >
      <div className="grid gap-4 xl:grid-cols-[minmax(0,1.05fr)_minmax(340px,.95fr)]">
        <SectionCard title="User directory" description="Account details are loaded only from the isolated ASP Model Studio authentication service." icon={Users}>
          <EmptyState icon={Users} title="No User Directory Loaded" description="This static workspace view does not invent user counts, roles, or identities." detail="Sign in and target-local directory services remain authoritative." />
        </SectionCard>
        <SectionCard title="Workspace settings" description="Visible defaults communicate the product posture; service-backed changes remain unavailable here." icon={Settings2}>
          <div className="space-y-2">
            {preferences.map(({ title, detail, icon: Icon }) => (
              <div key={title} className="flex gap-3 rounded-xl border border-slate-200 bg-slate-50 p-3">
                <span className="inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-lg border border-slate-200 bg-white text-slate-700"><Icon size={17} /></span>
                <div className="min-w-0"><div className="text-sm font-semibold text-slate-950">{title}</div><div className="mt-1 text-xs leading-5 text-slate-600">{detail}</div></div>
              </div>
            ))}
          </div>
        </SectionCard>
      </div>

      <SectionCard title="Access principles" description="Authentication and project isolation remain core platform machinery." icon={LockKeyhole}>
        <div className="grid gap-3 md:grid-cols-3">
          <FeatureTile icon={LockKeyhole} title="Authenticated access" description="Normal application routes remain behind supported authentication." tag="REQUIRED" />
          <FeatureTile icon={Users} title="Private onboarding" description="Public self-registration is not exposed by the sports studio." tag="DISABLED" />
          <FeatureTile icon={Fingerprint} title="Project isolation" description="Projects, datasets, experiments, and artifacts retain scoped identity." tag="REQUIRED" />
        </div>
      </SectionCard>
    </StudioPageFrame>
  );
}

export function LegacyWorkflowUnavailablePage() {
  return (
    <div className="flex min-h-[68vh] items-center justify-center px-4 py-10" data-sports-module="Legacy workflow unavailable">
      <section className="relative w-full max-w-3xl overflow-hidden rounded-3xl border border-slate-800 bg-slate-950 px-6 py-12 text-center text-white shadow-2xl shadow-slate-950/20 sm:px-12">
        <div className="pointer-events-none absolute inset-0 opacity-60" style={{ backgroundImage: "radial-gradient(circle at 50% -10%, rgba(34,211,238,.24), transparent 40%), radial-gradient(rgba(103,232,249,.16) 1px, transparent 1px)", backgroundSize: "auto, 28px 28px" }} aria-hidden="true" />
        <div className="relative">
          <span className="mx-auto inline-flex h-16 w-16 items-center justify-center rounded-2xl bg-white/5 text-cyan-200 ring-1 ring-white/10"><LockKeyhole size={29} aria-hidden="true" /></span>
          <div className="mt-5 text-xs font-semibold uppercase tracking-[0.18em] text-cyan-200">Sports-native route boundary</div>
          <h1 className="mt-3 text-3xl font-semibold tracking-tight sm:text-4xl">Legacy workflow unavailable in ASP Model Studio</h1>
          <p className="mx-auto mt-4 max-w-2xl text-sm leading-7 text-slate-300">This route belongs to an inherited workflow that is not part of the sports modeling experience. No obsolete product screen is exposed here.</p>
          <a href="/" className="mt-7 inline-flex min-h-11 items-center justify-center gap-2 rounded-xl bg-cyan-300 px-5 py-2.5 text-sm font-semibold text-slate-950 shadow-lg shadow-cyan-950/20 transition hover:bg-cyan-200 focus:outline-none focus:ring-2 focus:ring-cyan-200 focus:ring-offset-2 focus:ring-offset-slate-950">
            Return to Studio Home <ChevronRight size={17} aria-hidden="true" />
          </a>
        </div>
      </section>
    </div>
  );
}

export const STUDIO_MODULE_PAGES = {
  DataWarehousePage,
  PlayerTeamStatePage,
  ParticipationUsagePage,
  ModelLaboratoryPage,
  SimulationStudioPage,
  EvaluationCalibrationPage,
  ModelGraphPage,
  RegistryDeploymentPage,
  ForwardMonitoringPage,
  ResearchToolsPage,
  AnalyticsWorkbenchPage,
  SqlLabPage,
  VisualizationStudioPage,
  ModelDocumentationPage,
  DataSourcesRightsPage,
  AdministrationPage,
  UsersSettingsPage,
  LegacyWorkflowUnavailablePage,
} as const;
