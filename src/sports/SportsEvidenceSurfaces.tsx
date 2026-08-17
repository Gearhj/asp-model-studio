import { useEffect, useMemo, useState, type ReactNode } from "react";
import { CircleDashed, Database, LockKeyhole, RefreshCw, Scale, ShieldCheck } from "lucide-react";
import { me } from "../lib/auth";
import {
  logicalExchangeUri,
  registerApprovedSportsDataset,
  type ActiveSportsDataset,
  type SportsEvidenceCoverage,
  useActiveSportsDataset,
} from "./sportsEvidenceApi";

function Page({ status, children }: { status: string; children: ReactNode }) {
  return (
    <div className="min-w-0 space-y-5 pb-10" data-sports-evidence-page="Data Warehouse">
      <header className="relative overflow-hidden rounded-2xl border border-slate-800 bg-slate-950 p-5 text-white shadow-xl sm:p-7">
        <div className="pointer-events-none absolute inset-0 opacity-60" aria-hidden="true" style={{ backgroundImage: "radial-gradient(circle at 84% 12%, rgba(34,211,238,.2), transparent 28%), linear-gradient(rgba(148,163,184,.055) 1px, transparent 1px), linear-gradient(90deg, rgba(148,163,184,.055) 1px, transparent 1px)", backgroundSize: "auto, 32px 32px, 32px 32px" }} />
        <div className="relative">
          <div className="flex flex-wrap items-center gap-3"><span className="text-xs font-semibold uppercase tracking-[0.18em] text-cyan-200">Sports evidence layer</span><Pill value={status} dark /></div>
          <h1 className="mt-4 text-3xl font-semibold tracking-tight sm:text-4xl">Data Warehouse</h1>
          <p className="mt-3 max-w-4xl text-sm leading-6 text-slate-300 sm:text-base sm:leading-7">Inspect the immutable, metadata-only evidence registration and analytical coverage used by sports research projects.</p>
        </div>
      </header>
      {children}
    </div>
  );
}

function Card({ title, description, children, className = "" }: { title: string; description?: string; children: ReactNode; className?: string }) {
  return <section className={`overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm ${className}`}><div className="border-b border-slate-100 px-5 py-4 sm:px-6"><h2 className="text-xl font-semibold tracking-tight text-slate-950">{title}</h2>{description ? <p className="mt-1 max-w-4xl text-sm leading-6 text-slate-600">{description}</p> : null}</div><div className="p-5 sm:p-6">{children}</div></section>;
}

function Pill({ value, dark = false }: { value: string; dark?: boolean }) {
  return <span className={`inline-flex max-w-full whitespace-normal break-words rounded-full border px-2.5 py-1 text-center text-[11px] font-semibold uppercase leading-4 tracking-wide ${dark ? "border-white/15 bg-white/5 text-slate-200" : "border-slate-200 bg-slate-50 text-slate-700"}`}>{value}</span>;
}

function StateMessage({ kind, title, detail, children }: { kind: "loading" | "empty" | "error"; title: string; detail: string; children?: ReactNode }) {
  return <div className={`rounded-2xl border border-dashed px-6 py-10 text-center ${kind === "error" ? "border-amber-300 bg-amber-50" : "border-slate-300 bg-gradient-to-br from-slate-50 to-cyan-50/40"}`} role={kind === "error" ? "alert" : "status"}>{kind === "loading" ? <CircleDashed className="mx-auto animate-spin text-cyan-700" /> : <Database className="mx-auto text-slate-500" />}<h2 className="mt-4 text-xl font-semibold text-slate-950">{title}</h2><p className="mx-auto mt-2 max-w-2xl text-sm leading-6 text-slate-600">{detail}</p>{children}</div>;
}

function number(value: number | undefined) {
  return typeof value === "number" && Number.isFinite(value) ? new Intl.NumberFormat("en-US").format(value) : "—";
}

function percentage(value: number | undefined) {
  if (typeof value !== "number" || !Number.isFinite(value)) return "—";
  const normalized = value <= 1 ? value * 100 : value;
  return `${normalized.toFixed(normalized === 100 ? 0 : 1)}%`;
}

function safeText(value: unknown) {
  if (value === null || value === undefined || value === "") return "—";
  const text = String(value);
  return /^[a-z]:[\\/]/i.test(text) || /^\\\\/.test(text) || /^file:/i.test(text) ? "Target-local reference withheld" : text;
}

function MetricGrid({ dataset }: { dataset: ActiveSportsDataset }) {
  const totals = dataset.totals;
  const items = [
    { label: "Seasons", value: dataset.seasons?.length ? `${Math.min(...dataset.seasons)}–${Math.max(...dataset.seasons)}` : "—", detail: dataset.league },
    { label: "Games", value: number(totals.games), detail: "Registered manifest evidence" },
    { label: "Plate appearances", value: number(totals.plateAppearances), detail: "Registered manifest evidence" },
    { label: "Transitions", value: number(totals.transitions), detail: "Registered manifest evidence" },
    { label: "Starter targets", value: number(totals.starterTargets), detail: "Registered manifest evidence" },
    { label: "Bullpen appearances", value: number(totals.bullpenAppearances), detail: "Registered manifest evidence" },
    { label: "Player priors", value: number(totals.playerPriors), detail: "Registered manifest evidence" },
    { label: "Partitions", value: number(totals.partitions), detail: `${percentage(totals.playerIdentityCoverage)} primary player identity-reference coverage; canonical cross-family bridge absent` },
  ];
  return <section className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4" aria-label="Dataset evidence summary">{items.map((item) => <article key={item.label} className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm"><div className="text-xs font-semibold uppercase tracking-wide text-slate-500">{item.label}</div><div className="mt-2 break-words text-2xl font-semibold tabular-nums text-slate-950">{item.value}</div><div className="mt-1 text-xs leading-5 text-slate-500">{item.detail}</div></article>)}</section>;
}

function FamilyChart({ dataset }: { dataset: ActiveSportsDataset }) {
  const maximum = Math.max(1, ...dataset.families.map((item) => item.rows));
  return <div className="space-y-3" role="img" aria-label="Family volume chart">{dataset.families.map((row) => <div key={row.family} className="grid gap-2 sm:grid-cols-[190px_minmax(0,1fr)_100px] sm:items-center"><div className="break-words text-xs font-semibold text-slate-700">{row.family.replaceAll("_", " ")}</div><div className="h-3 overflow-hidden rounded-full bg-slate-100"><div className="h-full rounded-full bg-gradient-to-r from-cyan-600 to-blue-500" style={{ width: `${Math.max(1, row.rows / maximum * 100)}%` }} /></div><div className="text-right font-mono text-xs tabular-nums text-slate-600">{number(row.rows)}</div></div>)}</div>;
}

function SeasonCoverage({ dataset }: { dataset: ActiveSportsDataset }) {
  return <div className="overflow-x-auto"><table className="w-full min-w-[720px] text-left text-xs"><thead><tr className="border-b border-slate-200 text-slate-500">{["Season", "Games", "Plate appearances", "Transitions", "Starter targets", "Bullpen"].map((label) => <th key={label} className="px-3 py-3 font-semibold uppercase tracking-wide">{label}</th>)}</tr></thead><tbody>{dataset.seasonCoverage.map((row) => <tr key={row.season} className="border-b border-slate-100 last:border-0"><td className="px-3 py-3 font-semibold text-slate-900">{row.season}</td><td className="px-3 py-3 tabular-nums">{number(row.games)}</td><td className="px-3 py-3 tabular-nums">{number(row.plateAppearances)}</td><td className="px-3 py-3 tabular-nums">{number(row.transitions)}</td><td className="px-3 py-3 tabular-nums">{number(row.starterTargets)}</td><td className="px-3 py-3 tabular-nums">{number(row.bullpenAppearances)}</td></tr>)}</tbody></table></div>;
}

function Populations({ dataset }: { dataset: ActiveSportsDataset }) {
  const total = Math.max(1, dataset.populations.reduce((sum, item) => sum + item.rows, 0));
  return <><div className="flex h-6 overflow-hidden rounded-full bg-slate-100" role="img" aria-label="Dataset population composition">{dataset.populations.map((item, index) => <div key={item.populationId} className={index % 3 === 0 ? "bg-cyan-600" : index % 3 === 1 ? "bg-violet-500" : "bg-slate-500"} style={{ width: `${item.rows / total * 100}%` }} title={`${item.populationId}: ${number(item.rows)}`} />)}</div><div className="mt-4 grid gap-3 md:grid-cols-3">{dataset.populations.map((item) => <article key={item.populationId} className="rounded-xl border border-slate-200 bg-slate-50 p-4"><h3 className="text-sm font-semibold text-slate-950">{item.populationId.replaceAll("_", " ")}</h3><div className="mt-1 text-xl font-semibold tabular-nums">{number(item.rows)}</div><p className="mt-2 break-words font-mono text-[11px] leading-5 text-slate-500">{item.predicate}</p>{item.uses?.length ? <p className="mt-2 text-xs leading-5 text-emerald-800">Uses: {item.uses.join("; ")}</p> : null}{item.prohibitions?.length ? <p className="mt-1 text-xs leading-5 text-amber-800">Prohibited: {item.prohibitions.join("; ")}</p> : null}</article>)}</div></>;
}

function Folds({ dataset }: { dataset: ActiveSportsDataset }) {
  return <div className="space-y-3">{dataset.folds.map((fold) => <article key={fold.foldId} className="rounded-xl border border-slate-200 p-4"><div className="flex flex-wrap justify-between gap-2"><h3 className="font-semibold text-slate-950">{fold.foldId}</h3><Pill value={`Validate ${fold.validationSeason}`} /></div><div className="mt-3 grid gap-2 sm:grid-cols-2"><div className="rounded-lg bg-cyan-50 p-3 text-sm"><strong>Development {fold.trainingSeasons.join("–")}</strong><div className="mt-1 tabular-nums text-slate-600">{number(fold.trainingRows)} PA</div></div><div className="rounded-lg bg-blue-50 p-3 text-sm"><strong>Validation {fold.validationSeason}</strong><div className="mt-1 tabular-nums text-slate-600">{number(fold.validationRows)} PA</div></div></div></article>)}</div>;
}

function Coverage({ dataset }: { dataset: ActiveSportsDataset }) {
  const rows: SportsEvidenceCoverage[] = Array.isArray(dataset.evidenceCoverage) ? dataset.evidenceCoverage : Object.entries(dataset.evidenceCoverage ?? {}).map(([evidence, status]) => ({ evidence, status: String(status) }));
  return <div className="grid gap-2 sm:grid-cols-2">{rows.map((item) => <div key={item.evidence} className="flex items-start justify-between gap-3 rounded-xl border border-slate-200 bg-slate-50 p-3"><div><div className="text-sm font-semibold text-slate-900">{item.evidence.replaceAll("_", " ")}</div>{item.detail ? <div className="mt-1 text-xs text-slate-500">{item.detail}</div> : null}</div><Pill value={String(item.status)} /></div>)}</div>;
}

function Rights({ dataset }: { dataset: ActiveSportsDataset }) {
  return <div className="space-y-3">{dataset.rights.map((right) => <article key={right.source} className="rounded-xl border border-slate-200 p-4"><div className="flex flex-wrap items-center justify-between gap-2"><h3 className="font-semibold text-slate-950">{right.source}</h3>{right.status ? <Pill value={right.status} /> : null}</div>{right.attribution ? <p className="mt-2 text-xs leading-5 text-slate-600">{right.attribution}</p> : null}{right.allowedUses?.length ? <p className="mt-2 text-xs text-emerald-800">Allowed: {right.allowedUses.join("; ")}</p> : null}{right.prohibitedUses?.length ? <p className="mt-1 text-xs text-amber-800">Prohibited: {right.prohibitedUses.join("; ")}</p> : null}</article>)}</div>;
}

function FeatureAuthority({ dataset }: { dataset: ActiveSportsDataset }) {
  const audit = dataset.featureAudit;
  if (!audit) return null;
  return <Card title="Plate-appearance feature authority" description="Package-only identity evidence for MLB_PA_FEATURE_VIEW_V1. Zero joins are reported as a governed blocker, not filled or inferred.">
    <div className="flex flex-wrap items-start justify-between gap-3 rounded-xl border border-amber-200 bg-amber-50 p-4">
      <div className="min-w-0"><div className="break-words font-mono text-xs font-semibold text-amber-950">{audit.contractVersion}</div><p className="mt-1 text-sm leading-6 text-amber-950">{audit.missingBridge.reason}</p></div><Pill value={audit.status} />
    </div>
    <dl className="mt-4 grid gap-3 sm:grid-cols-2">
      <Detail label="Plate-appearance namespace" value={audit.observedNamespaces.plateAppearance.join(", ")} />
      <Detail label="Player-prior namespaces" value={audit.observedNamespaces.playerPrior.join(", ")} />
    </dl>
    <div className="mt-4 overflow-x-auto"><table className="w-full min-w-[680px] text-left text-xs"><thead><tr className="border-b border-slate-200 text-slate-500">{["Season", "Plate appearances", "Eligible batting priors", "Batter Y-1 joins", "Eligible pitching priors", "Pitcher Y-1 joins"].map((label) => <th key={label} className="px-3 py-3 font-semibold uppercase tracking-wide">{label}</th>)}</tr></thead><tbody>{audit.perSeasonRows.map((row) => <tr key={row.season} className="border-b border-slate-100 last:border-0"><td className="px-3 py-3 font-semibold text-slate-900">{row.season}</td><td className="px-3 py-3 tabular-nums">{number(row.plateAppearanceRows)}</td><td className="px-3 py-3 tabular-nums">{number(row.eligibleBattingPriorRows)}</td><td className="px-3 py-3 font-semibold tabular-nums text-amber-900">{number(row.batterYMinus1JoinMatches)} / {number(row.batterYMinus1JoinDenominator)}</td><td className="px-3 py-3 tabular-nums">{number(row.eligiblePitchingPriorRows)}</td><td className="px-3 py-3 font-semibold tabular-nums text-amber-900">{number(row.pitcherYMinus1JoinMatches)} / {number(row.pitcherYMinus1JoinDenominator)}</td></tr>)}</tbody></table></div>
    <p className="mt-4 break-words text-xs leading-5 text-slate-600">Required authority: <span className="font-mono font-semibold">{audit.missingBridge.requiredArtifact}</span>. Fuzzy or inferred identity matching used: <strong>{audit.joinEvidence.inferenceOrFuzzyMatchingUsed ? "yes" : "no"}</strong>.</p>
  </Card>;
}

function Detail({ label, value }: { label: string; value: string }) {
  return <div className="min-w-0 rounded-lg border border-slate-200 bg-slate-50 p-3"><dt className="text-xs font-semibold uppercase tracking-wide text-slate-500">{label}</dt><dd className="mt-1 break-all font-mono text-xs leading-5 text-slate-800">{safeText(value)}</dd></div>;
}

function DatasetDetails({ dataset }: { dataset: ActiveSportsDataset }) {
  return <>
    <MetricGrid dataset={dataset} />
    <div className="grid gap-5 xl:grid-cols-2"><Card title="Family volume" description="Declared rows by logical data family."><FamilyChart dataset={dataset} /></Card><Card title="Season coverage" description="Registered evidence by season and target family."><SeasonCoverage dataset={dataset} /></Card></div>
    <Card title="Population composition" description="Governed population precedence, permitted research uses, and prohibitions."><Populations dataset={dataset} /></Card>
    <div className="grid gap-5 xl:grid-cols-2"><Card title="Temporal fold timeline" description="Frozen retrospective rolling-origin validation folds."><Folds dataset={dataset} /></Card><Card title="Evidence coverage matrix" description="Only coverage states returned by the registered dataset service are shown."><Coverage dataset={dataset} /></Card></div>
    <FeatureAuthority dataset={dataset} />
    <div className="grid gap-5 xl:grid-cols-2"><Card title="Source rights" description="Approved uses and prohibited redistribution remain part of the registration."><Rights dataset={dataset} /></Card><Card title="Known limitations" description="Retrospective evidence is not prospective proof."><ul className="space-y-2">{dataset.limitations.map((limitation) => <li key={limitation} className="flex gap-3 rounded-lg border border-amber-100 bg-amber-50 px-3 py-2 text-sm leading-6 text-amber-950"><Scale size={16} className="mt-1 shrink-0" />{limitation}</li>)}</ul></Card></div>
    <Card title="Technical registration details" description="Checksums remain inspectable without exposing the administrator-controlled physical exchange path."><details><summary className="cursor-pointer text-sm font-semibold text-cyan-800">Show immutable identifiers</summary><dl className="mt-4 grid gap-3 sm:grid-cols-2"><Detail label="Registration ID" value={dataset.registrationId} /><Detail label="Dataset ID" value={dataset.datasetId} /><Detail label="Dataset version" value={dataset.datasetVersionId} /><Detail label="Manifest ID" value={dataset.manifestId} /><Detail label="Manifest SHA-256" value={dataset.manifestSha} /><Detail label="Partition authority SHA-256" value={dataset.partitionAuthoritySha || "Unavailable"} /><Detail label="Package ID" value={dataset.packageId} /><Detail label="Logical root" value={logicalExchangeUri(dataset.logicalRoot)} /><Detail label="Evidence cutoff" value={dataset.evidenceCutoff} /></dl></details></Card>
  </>;
}

function RegistrationAction({ onRegistered }: { onRegistered: () => void }) {
  const [role, setRole] = useState<string | null>(null);
  const [status, setStatus] = useState<"idle" | "validating" | "success" | "error">("idle");
  const [message, setMessage] = useState("");
  useEffect(() => {
    let current = true;
    void me().then((response) => { if (current) setRole(String(response.user.role).toLowerCase()); }).catch(() => { if (current) setRole(""); });
    return () => { current = false; };
  }, []);
  const isAdmin = role === "admin";
  const buttonLabel = status === "validating" ? "Validating approved exchange…" : "Register approved MLB exchange";
  async function register() {
    if (!isAdmin || status === "validating") return;
    setStatus("validating");
    setMessage("Validating package inventory, hashes, schemas, row counts, rights, and temporal contracts.");
    try {
      await registerApprovedSportsDataset();
      setStatus("success");
      setMessage("The approved exchange passed registration. Refreshing governed evidence.");
      onRegistered();
    } catch (error) {
      setStatus("error");
      setMessage(error instanceof Error ? error.message : "Registration failed closed.");
    }
  }
  return <div className="mt-5"><button type="button" disabled={!isAdmin || status === "validating" || role === null} onClick={() => void register()} className="inline-flex min-h-11 items-center gap-2 rounded-xl bg-slate-950 px-4 py-2 text-sm font-semibold text-white hover:bg-slate-800 disabled:cursor-not-allowed disabled:bg-slate-300"><ShieldCheck size={16} />{buttonLabel}</button>{role !== null && !isAdmin ? <p className="mt-2 text-xs font-semibold text-slate-500">Administrator permission is required to register the approved exchange.</p> : null}{message ? <p className={`mx-auto mt-3 max-w-2xl rounded-lg border px-3 py-2 text-xs font-semibold ${status === "error" ? "border-amber-300 bg-amber-100 text-amber-950" : "border-cyan-200 bg-cyan-50 text-cyan-950"}`} role="status">{message}</p> : null}<p className="mt-3 text-xs leading-5 text-slate-500"><LockKeyhole size={13} className="mr-1 inline" />The browser submits no filesystem path. The backend resolves only its administrator-controlled exchange root.</p></div>;
}

export function DataWarehouseEvidencePage() {
  const evidence = useActiveSportsDataset();
  const status = evidence.status === "ready" ? evidence.data.validationStatus : evidence.status === "loading" ? "Loading" : "Not registered";
  const summary = useMemo(() => evidence.status === "ready" ? `${evidence.data.datasetId} · ${evidence.data.registrationId}` : "", [evidence]);
  return <Page status={status}>
    {evidence.status === "loading" ? <StateMessage kind="loading" title="Loading governed dataset evidence" detail="Reading the target-local registration service." /> : evidence.status === "error" ? <StateMessage kind="error" title="Dataset evidence unavailable" detail={evidence.error}><button type="button" onClick={evidence.refresh} className="mt-5 inline-flex items-center gap-2 rounded-lg border border-amber-300 bg-white px-3 py-2 text-sm font-semibold text-amber-950"><RefreshCw size={15} /> Retry</button></StateMessage> : evidence.status === "empty" ? <StateMessage kind="empty" title="No Sports Dataset Registered" detail="No governed sports manifest is registered in this workspace. No warehouse values are inferred or prefilled."><div className="mt-4 inline-flex rounded-lg border border-slate-200 bg-white px-3 py-2 font-mono text-xs font-semibold text-slate-700">SPORTS_DATASET_MANIFEST_V1</div><RegistrationAction onRegistered={evidence.refresh} /></StateMessage> : <><div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-950"><span className="flex items-center gap-2 font-semibold"><ShieldCheck size={17} /> Registered evidence is {evidence.data.validationStatus}</span><span className="break-all font-mono text-xs">{summary}</span></div><DatasetDetails dataset={evidence.data} /></>}
  </Page>;
}
