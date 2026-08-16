import type { ReactNode } from "react";
import type { LucideIcon } from "lucide-react";
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

function DisabledAction({ children }: { children: ReactNode }) {
  return (
    <button
      type="button"
      disabled
      className="inline-flex min-h-10 cursor-not-allowed items-center justify-center gap-2 rounded-lg border border-slate-200 bg-slate-100 px-3.5 py-2 text-sm font-semibold text-slate-400"
      title="Connection planned for Phase 2"
    >
      {children}
    </button>
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

function ContractGrid({ items }: { items: string[] }) {
  return (
    <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-5">
      {items.map((item, index) => (
        <div key={item} className="flex min-h-16 items-start gap-3 rounded-xl border border-slate-200 bg-slate-50 px-3 py-3">
          <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-md bg-slate-900 text-xs font-semibold tabular-nums text-cyan-200">
            {String(index + 1).padStart(2, "0")}
          </span>
          <span className="text-xs font-semibold leading-5 text-slate-700">{item}</span>
        </div>
      ))}
    </div>
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
  const manifestSections = [
    "Sport and league",
    "Seasons",
    "Populations",
    "Source versions",
    "Source rights",
    "Parquet partitions",
    "Checksums",
    "Identity coverage",
    "Temporal cutoffs and exclusions",
    "Target definitions",
  ];
  return (
    <StudioPageFrame
      eyebrow="Sports evidence layer"
      title="Data Warehouse"
      description="Register the immutable evidence boundary for every sport, season, population, and forecast target before model development begins."
      icon={Database}
      facts={[
        { label: "Registered datasets", value: "0" },
        { label: "Manifest", value: "Not registered" },
        { label: "Warehouse access", value: "Not connected" },
      ]}
    >
      <SectionCard
        eyebrow="Target-local state"
        title="Sports data registration"
        description="ASP Model Studio consumes immutable sports dataset manifests. The source warehouse remains external and read-only."
        icon={Fingerprint}
        action={<StatusPill label="Connection planned" tone="amber" />}
      >
        <EmptyState
          icon={Database}
          title="No Sports Dataset Registered"
          description="No sports evidence is available to projects in this workspace. Registering a manifest will be enabled only after the isolated Phase 2 connection is configured."
          detail="Arbitrary filesystem browsing and direct warehouse mutation are intentionally unavailable."
          contract="SPORTS_DATASET_MANIFEST_V1"
        />
        <div className="mt-5 flex flex-wrap justify-center gap-2">
          <DisabledAction><Database size={16} /> Register Manifest</DisabledAction>
          <DisabledAction><ShieldCheck size={16} /> Validate Manifest</DisabledAction>
          <DisabledAction><FileSearch2 size={16} /> Preview Schema</DisabledAction>
          <DisabledAction><Search size={16} /> Inspect Coverage</DisabledAction>
        </div>
        <p className="mt-3 text-center text-xs font-semibold uppercase tracking-wide text-amber-700">Connection planned for Phase 2</p>
      </SectionCard>

      <SectionCard title="Immutable manifest anatomy" description="Every registration must make the evidence, timing, identity, and rights boundary inspectable." icon={FileCheck2}>
        <ContractGrid items={manifestSections} />
      </SectionCard>

      <div className="grid gap-4 lg:grid-cols-3">
        <FeatureTile icon={LockKeyhole} title="Read-only source boundary" description="Source warehouse assets remain external. A manifest references governed partitions without copying or mutating the source." tag="GUARDRAIL" />
        <FeatureTile icon={Clock3} title="Point-in-time integrity" description="Temporal cutoffs and exclusions travel with the dataset version so future evidence cannot leak into development." tag="REQUIRED" />
        <FeatureTile icon={Scale} title="Rights-aware evidence" description="Source rights and permitted analytical uses are explicit components of registration, not hidden metadata." tag="REQUIRED" />
      </div>
    </StudioPageFrame>
  );
}

export function ModelLaboratoryPage() {
  const metricFamilies = [
    ["Probability", "Brier score · log loss · calibration error"],
    ["Score", "MAE · RMSE · distribution score"],
    ["Reliability", "Probability bands · subgroup stability · OOD"],
  ];
  return (
    <StudioPageFrame
      eyebrow="Candidate research"
      title="Model Laboratory"
      description="Run governed sports experiments, compare component candidates across temporal folds, and preserve artifact lineage from evidence to decision."
      icon={FlaskConical}
      tone="violet"
      facts={[
        { label: "Experiments", value: "0" },
        { label: "Candidates", value: "0" },
        { label: "Active runs", value: "0" },
      ]}
    >
      <MetricStrip items={[
        { label: "Experiments", value: "0", detail: "No Experiment Run" },
        { label: "Candidate models", value: "0", detail: "No registered candidate" },
        { label: "Temporal folds", value: "0", detail: "No validation plan" },
        { label: "Research challengers", value: "0", detail: "No selection decision" },
      ]} />

      <div className="grid gap-4 xl:grid-cols-[minmax(0,1.45fr)_minmax(300px,.55fr)]">
        <SectionCard title="Experiment ledger" description="Target, sport, dataset, fold, status, metrics, and lineage remain visible together." icon={Beaker}>
          <PlaceholderTable columns={["Experiment", "Sport", "Target", "Dataset", "Fold", "Status", "Key metrics", "Artifact lineage"]} title="Sports model experiments" />
        </SectionCard>
        <SectionCard title="No Experiment Run" description="A registered sports dataset and forecast contract are required before a candidate can run." icon={TimerReset}>
          <div className="space-y-3">
            {["Forecast contract", "Immutable dataset", "Temporal validation plan"].map((item, index) => (
              <div key={item} className="flex items-center gap-3 rounded-xl border border-slate-200 bg-slate-50 px-3 py-3">
                <span className="flex h-7 w-7 items-center justify-center rounded-full border border-slate-300 bg-white text-xs font-semibold tabular-nums text-slate-500">{index + 1}</span>
                <div className="min-w-0 flex-1 text-sm font-semibold text-slate-700">{item}</div>
                <StatusPill label="Pending" />
              </div>
            ))}
          </div>
        </SectionCard>
      </div>

      <SectionCard title="Sports evaluation vocabulary" description="Metrics are declared now; values remain empty until evidence-producing runs complete." icon={BarChart3}>
        <div className="grid gap-3 md:grid-cols-3">
          {metricFamilies.map(([title, metrics]) => (
            <div key={title} className="rounded-xl border border-slate-200 bg-gradient-to-br from-slate-50 to-white p-4">
              <div className="text-sm font-semibold text-slate-950">{title}</div>
              <div className="mt-2 text-xs leading-5 text-slate-600">{metrics}</div>
              <div className="mt-4 border-t border-slate-200 pt-3 text-xs font-semibold text-slate-400">No measured values</div>
            </div>
          ))}
        </div>
      </SectionCard>

      <SectionCard title="Artifact lineage" description="Each experiment will trace its forecast contract, immutable dataset, code, fold, model artifact, and evaluation evidence." icon={GitBranch}>
        <LineageRail labels={["Forecast contract", "Dataset version", "Experiment run", "Candidate artifact", "Validation evidence", "Decision"]} />
      </SectionCard>
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

export function EvaluationCalibrationPage() {
  const scorecards = [
    { title: "Brier score", group: "Probability accuracy", icon: Target },
    { title: "Log loss", group: "Probability sharpness", icon: Gauge },
    { title: "Calibration error", group: "Reliability", icon: SlidersHorizontal },
    { title: "Calibration slope", group: "Reliability", icon: LineChart },
    { title: "AUC", group: "Secondary discrimination", icon: BarChart3 },
    { title: "Score MAE / RMSE", group: "Score accuracy", icon: Goal },
    { title: "Distribution score", group: "Full-distribution quality", icon: ChartNoAxesCombined },
    { title: "Subgroup stability", group: "Team · player · venue · lifecycle", icon: Layers3 },
    { title: "OOD", group: "Out-of-distribution", icon: RadioTower },
  ];
  return (
    <StudioPageFrame
      eyebrow="Forward-looking evidence"
      title="Evaluation & Calibration"
      description="Judge sports forecasts on temporal holdouts, probability reliability, score distributions, subgroup stability, missingness, and uncertainty."
      icon={Gauge}
      tone="blue"
      facts={[
        { label: "Evaluations", value: "0" },
        { label: "Calibration artifacts", value: "0" },
        { label: "Status", value: "No evidence" },
      ]}
    >
      <MetricStrip items={[
        { label: "Completed evaluations", value: "0", detail: "No Evaluation Evidence" },
        { label: "Temporal folds", value: "0", detail: "No holdout evaluated" },
        { label: "Probability bands", value: "0", detail: "No calibrated forecasts" },
        { label: "Approved candidates", value: "0", detail: "No model decision" },
      ]} />

      <SectionCard title="Sports evaluation scorecard" description="Metric definitions are visible before results exist. Empty values are intentional." icon={BarChart3}>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {scorecards.map(({ title, group, icon: Icon }) => (
            <article key={title} className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
              <div className="flex items-start justify-between gap-3">
                <span className="inline-flex h-9 w-9 items-center justify-center rounded-lg bg-slate-100 text-slate-700"><Icon size={17} aria-hidden="true" /></span>
                <span className="text-xl font-semibold tabular-nums text-slate-300">—</span>
              </div>
              <h3 className="mt-4 text-sm font-semibold text-slate-950">{title}</h3>
              <p className="mt-1 text-xs leading-5 text-slate-500">{group}</p>
              <div className="mt-3 border-t border-slate-100 pt-3 text-xs font-semibold uppercase tracking-wide text-slate-400">Awaiting evaluation</div>
            </article>
          ))}
        </div>
      </SectionCard>

      <div className="grid gap-4 xl:grid-cols-2">
        <SectionCard title="Calibration bands" description="Observed frequency versus forecast probability will render by temporal fold and selected subgroup." icon={LineChart}>
          <div className="relative min-h-72 rounded-xl border border-dashed border-slate-300 bg-slate-50 p-5">
            <div className="absolute bottom-12 left-14 top-5 w-px bg-slate-300" aria-hidden="true" />
            <div className="absolute bottom-12 left-14 right-5 h-px bg-slate-300" aria-hidden="true" />
            <div className="absolute bottom-12 left-14 right-5 border-t border-dashed border-slate-300 [transform:rotate(-26deg)] [transform-origin:left_center]" aria-hidden="true" />
            <div className="flex min-h-56 items-center justify-center text-center">
              <div><CircleDashed size={24} className="mx-auto text-slate-400" /><div className="mt-2 text-sm font-semibold text-slate-700">No calibration observations</div></div>
            </div>
            <div className="text-center text-xs font-medium text-slate-500">Forecast probability</div>
          </div>
        </SectionCard>
        <SectionCard title="Reliability lenses" description="Every candidate is evaluated beyond a single aggregate score." icon={Search}>
          <div className="grid gap-2 sm:grid-cols-2">
            {["Probability bands", "Team and player", "Venue", "Forecast lifecycle", "Missingness pattern", "Strict vs enhanced evidence", "In-distribution vs OOD", "Prospective period"].map((item) => (
              <div key={item} className="flex items-center gap-2 rounded-lg border border-slate-200 bg-slate-50 px-3 py-3 text-sm font-medium text-slate-700"><CircleDashed size={15} className="text-slate-400" />{item}</div>
            ))}
          </div>
        </SectionCard>
      </div>
    </StudioPageFrame>
  );
}

const MODEL_GRAPH_NODES = [
  { label: "Player State", icon: BrainCircuit },
  { label: "Participation", icon: Users },
  { label: "Event Model", icon: Binary },
  { label: "Usage Model", icon: Activity },
  { label: "Simulator", icon: Workflow },
  { label: "Calibration", icon: Gauge },
  { label: "Forecast Bundle", icon: Box },
] as const;

export function ModelGraphPage() {
  return (
    <StudioPageFrame
      eyebrow="Component decision system"
      title="Model Graph"
      description="Inspect the governed dependency graph from player state through simulation, calibration, and the executable sports forecast bundle."
      icon={Network}
      tone="emerald"
      facts={[
        { label: "Graphs", value: "0" },
        { label: "Components", value: "0" },
        { label: "Decision", value: "No decision" },
      ]}
    >
      <SectionCard title="No Model Graph" description="This blueprint shows the required DAG shape only. It does not represent trained, approved, or deployed components." icon={GitBranch} action={<StatusPill label="Blueprint only" tone="amber" />}>
        <div className="relative rounded-2xl border border-slate-800 bg-slate-950 p-4 sm:p-6">
          <div className="pointer-events-none absolute inset-0 opacity-30" style={{ backgroundImage: "radial-gradient(rgba(103,232,249,.24) 1px, transparent 1px)", backgroundSize: "22px 22px" }} aria-hidden="true" />
          <div className="relative flex flex-col items-stretch gap-2 xl:flex-row xl:items-center" aria-label="Future sports model directed acyclic graph">
            {MODEL_GRAPH_NODES.map(({ label, icon: Icon }, index) => (
              <div key={label} className="contents">
                <div className="flex min-h-24 min-w-0 flex-1 items-center gap-3 rounded-xl border border-white/10 bg-white/[0.055] px-3 py-3 backdrop-blur-sm xl:flex-col xl:justify-center xl:text-center">
                  <span className="inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-cyan-400/10 text-cyan-200 ring-1 ring-cyan-300/15"><Icon size={18} aria-hidden="true" /></span>
                  <div className="min-w-0">
                    <div className="text-sm font-semibold text-white">{label}</div>
                    <div className="mt-1 text-xs text-slate-400">Not configured</div>
                  </div>
                </div>
                {index < MODEL_GRAPH_NODES.length - 1 ? (
                  <><ArrowDown size={18} className="mx-auto text-cyan-400/60 xl:hidden" aria-hidden="true" /><ArrowRight size={18} className="hidden shrink-0 text-cyan-400/60 xl:block" aria-hidden="true" /></>
                ) : null}
              </div>
            ))}
          </div>
        </div>
      </SectionCard>

      <SectionCard title="Governed lifecycle" description="Lifecycle labels describe review state; they never substitute for validation evidence." icon={ShieldCheck}>
        <div className="flex flex-wrap gap-2">
          {["DEVELOPMENT", "RESEARCH CHALLENGER", "RESEARCH CANDIDATE", "SHADOW", "OPERATIONAL", "RETIRED"].map((status, index) => (
            <span key={status} className={`rounded-full border px-3 py-2 text-xs font-semibold tracking-wide ${index === 0 ? "border-cyan-200 bg-cyan-50 text-cyan-800" : "border-slate-200 bg-slate-50 text-slate-600"}`}>{status}</span>
          ))}
        </div>
      </SectionCard>

      <div className="grid gap-4 lg:grid-cols-3">
        <FeatureTile icon={Fingerprint} title="Immutable identity" description="Each node will resolve to a versioned artifact, schema, code reference, and checksum." />
        <FeatureTile icon={GitBranch} title="Explicit dependencies" description="Inputs and downstream consumers remain visible before a graph can advance through review." />
        <FeatureTile icon={BookOpenCheck} title="Decision evidence" description="Temporal validation and calibration evidence travel with every selection decision." />
      </div>
    </StudioPageFrame>
  );
}

export function RegistryDeploymentPage() {
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
      description="Promote reviewed components into an immutable sports forecasting graph and package it for isolated execution by ASP."
      icon={PackageCheck}
      tone="emerald"
      facts={[
        { label: "Registered components", value: "0" },
        { label: "Approved graphs", value: "0" },
        { label: "Exported bundles", value: "0" },
      ]}
    >
      <MetricStrip items={[
        { label: "Components", value: "0", detail: "No registered artifact" },
        { label: "Graphs", value: "0", detail: "No Model Graph" },
        { label: "Bundles", value: "0", detail: "No Bundle Exported" },
        { label: "Target environments", value: "0", detail: "No deployment target" },
      ]} />

      <SectionCard title="Component registry" description="Component, graph, bundle, lifecycle, training time, validation state, and target environment belong in one evidence ledger." icon={Boxes}>
        <PlaceholderTable columns={["Component", "Graph", "Bundle", "Status", "Lifecycle", "Last trained", "Validation status", "Target environment"]} title="Sports model registry" />
      </SectionCard>

      <SectionCard
        eyebrow="Future export contract"
        title="ASP model bundle"
        description="A model bundle is an immutable, self-contained sports forecasting graph that ASP can load and execute without ASP Model Studio being online."
        icon={Box}
        action={<StatusPill label="No Bundle Exported" tone="slate" />}
      >
        <EmptyState
          icon={PackageCheck}
          title="No sports model bundle has been exported."
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

      <SectionCard title="Export gates" description="Deployment remains unavailable until every governance gate is supported by evidence." icon={LockKeyhole}>
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

      <SectionCard title="Future ASP evidence loop" description="The connection is explanatory in Phase 1. ASP is not connected and no forecasts or outcomes have been imported." icon={RadioTower} action={<StatusPill label="Connection planned" tone="amber" />}>
        <LineageRail labels={["ASP forecasts", "Probabilities", "Scores & outcomes", "Calibration", "Drift", "Challenger comparison"]} />
      </SectionCard>

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        <FeatureTile icon={Target} title="Forecast integrity" description="Track forecast timestamps, intended lifecycle, population, graph version, and target definition." />
        <FeatureTile icon={Gauge} title="Calibration" description="Compare forecast probability bands with realized outcomes once the observation window matures." />
        <FeatureTile icon={Activity} title="Data and concept drift" description="Monitor input coverage, distribution shift, missingness, usage state, and model behavior." />
        <FeatureTile icon={Goal} title="Scores and outcomes" description="Join finalized game and player outcomes to the exact forecast evidence available at prediction time." />
        <FeatureTile icon={Beaker} title="Challenger comparison" description="Evaluate research challengers prospectively beside the operational graph without promoting them." />
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
