import { useEffect, useMemo, useState, type ReactNode } from "react";
import { CheckCircle2, CircleDashed, Database, Fingerprint, LockKeyhole, RefreshCw, Scale, ShieldCheck } from "lucide-react";
import { me } from "../lib/auth";
import Gen3CatalogSection from "./cockpit/Gen3CatalogSection";
import {
  logicalExchangeUri,
  logicalSportsEvidenceUri,
  activateSportsDataset,
  registerApprovedSportsDataset,
  type ActiveSportsDataset,
  type SportsEvidenceCoverage,
  type SportsIdentityBridgeEvidenceRow,
  useSportsDatasetCatalog,
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

function safeText(value: unknown): string {
  if (value === null || value === undefined || value === "") return "—";
  if (Array.isArray(value)) return value.length ? value.map(safeText).join("; ") : "—";
  if (typeof value === "boolean") return value ? "Yes" : "No";
  if (typeof value === "object") return "Structured evidence recorded";
  const text = String(value);
  return /^[a-z]:[\\/]/i.test(text) || /^\\\\/.test(text) || /^file:/i.test(text) || /^\//.test(text) ? "Target-local reference withheld" : text;
}

function isValidatedStatus(value: string | undefined) {
  return ["VALID", "VALIDATED", "PASS", "PASSED", "COMPLETE"].includes(String(value || "").trim().toUpperCase());
}

function hasValidatedIdentityBridge(dataset: ActiveSportsDataset) {
  const bridge = dataset.identityBridge;
  return Boolean(
    bridge?.active
    && bridge.noNamesOrFuzzyMatching
    && isValidatedStatus(bridge.validationStatus)
    && isValidatedStatus(bridge.joinAudit.status),
  );
}

function humanizeEvidenceKey(value: string) {
  return value
    .replaceAll("_", " ")
    .replace(/([a-z0-9])([A-Z])/g, "$1 $2")
    .replace(/^./, (character) => character.toUpperCase());
}

function evidenceValue(key: string, value: unknown) {
  if (/logical(?:uri|root)/i.test(key) && typeof value === "string") return logicalSportsEvidenceUri(value);
  if (typeof value === "number" && /(?:rate|coverage|percentage)$/i.test(key)) return percentage(value);
  return safeText(value);
}

function publicEvidenceEntries(row: SportsIdentityBridgeEvidenceRow) {
  return Object.entries(row).filter(([key]) => !/(?:physical|filesystem|absolute)(?:path|root|uri)?|(?:file|source|package)path/i.test(key));
}

function EvidenceRows({ rows, empty }: { rows: SportsIdentityBridgeEvidenceRow[]; empty: string }) {
  if (!rows.length) return <p className="rounded-xl border border-dashed border-slate-300 bg-slate-50 px-4 py-5 text-center text-sm text-slate-500">{empty}</p>;
  return <div className="grid gap-3 md:grid-cols-2">{rows.map((row, index) => {
    const entries = publicEvidenceEntries(row);
    const stableKey = [row.namespace, row.namespaceId, row.joinContract, row.contractId, row.season, row.role, index].filter((item) => item !== undefined && item !== null).join(":");
    return <dl key={stableKey || String(index)} className="grid min-w-0 gap-2 rounded-xl border border-slate-200 bg-slate-50 p-4 sm:grid-cols-2">{entries.map(([key, value]) => <div key={key} className="min-w-0"><dt className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">{humanizeEvidenceKey(key)}</dt><dd className="mt-1 break-words text-xs font-semibold leading-5 text-slate-800">{evidenceValue(key, value)}</dd></div>)}</dl>;
  })}</div>;
}

function BridgeMetric({ label, value, detail }: { label: string; value: string; detail: string }) {
  return <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm"><div className="text-xs font-semibold uppercase tracking-wide text-slate-500">{label}</div><div className="mt-2 text-2xl font-semibold tabular-nums text-slate-950">{value}</div><div className="mt-1 text-xs leading-5 text-slate-500">{detail}</div></div>;
}

function MetricGrid({ dataset }: { dataset: ActiveSportsDataset }) {
  const totals = dataset.totals;
  if (dataset.league.trim().toUpperCase() === "NFL") {
    const nflItems = [
      { label: "Games", value: number(totals.games), detail: "Canonical game authority" },
      { label: "Plays", value: number(totals.plays), detail: "Canonical play authority" },
      { label: "Drives", value: number(totals.drives), detail: "Canonical drive authority" },
      { label: "Team-game rows", value: number(totals.teamGameRows), detail: "Team-game fact authority" },
      { label: "Player-game rows", value: number(totals.playerGameRows), detail: "Player-game fact authority" },
      { label: "Gold pregame games", value: number(totals.goldPregameGames), detail: "Research-only Gold game rows" },
      { label: "Gold play states", value: number(totals.goldPlayStates), detail: "Research-only Gold play rows" },
      { label: "Registered tables", value: number(totals.tables), detail: `${number(totals.canonicalRows)} canonical rows` },
    ];
    return <section className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4" aria-label="NFL dataset evidence summary">{nflItems.map((item) => <article key={item.label} className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm"><div className="text-xs font-semibold uppercase tracking-wide text-slate-500">{item.label}</div><div className="mt-2 break-words text-2xl font-semibold tabular-nums text-slate-950">{item.value}</div><div className="mt-1 text-xs leading-5 text-slate-500">{item.detail}</div></article>)}</section>;
  }
  const currentStatcast = dataset.datasetId === "asp.mlb.statcast.current-pa.v1";
  const items = [
    { label: currentStatcast ? "Date coverage" : "Seasons", value: dataset.dateCoverage ? `${dataset.dateCoverage.earliestDate}–${dataset.dateCoverage.latestDate}` : dataset.seasons?.length ? `${Math.min(...dataset.seasons)}–${Math.max(...dataset.seasons)}` : "—", detail: dataset.dateCoverage ? "Exact accepted plate-appearance dates" : dataset.league },
    { label: "Games", value: number(totals.games), detail: "Registered manifest evidence" },
    { label: "Plate appearances", value: number(totals.plateAppearances), detail: "Registered manifest evidence" },
    { label: "Transitions", value: number(totals.transitions), detail: "Registered manifest evidence" },
    { label: "Starter targets", value: number(totals.starterTargets), detail: "Registered manifest evidence" },
    { label: "Bullpen appearances", value: number(totals.bullpenAppearances), detail: "Registered manifest evidence" },
    { label: "Player priors", value: number(totals.playerPriors), detail: "Registered manifest evidence" },
    { label: "Partitions", value: number(totals.partitions), detail: currentStatcast ? "Content-addressed current Statcast PA partitions" : `${percentage(totals.playerIdentityCoverage)} primary player identity-reference coverage; canonical cross-family bridge absent` },
  ];
  return <section className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4" aria-label="Dataset evidence summary">{items.map((item) => <article key={item.label} className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm"><div className="text-xs font-semibold uppercase tracking-wide text-slate-500">{item.label}</div><div className="mt-2 break-words text-2xl font-semibold tabular-nums text-slate-950">{item.value}</div><div className="mt-1 text-xs leading-5 text-slate-500">{item.detail}</div></article>)}</section>;
}

function FamilyChart({ dataset }: { dataset: ActiveSportsDataset }) {
  const maximum = Math.max(1, ...dataset.families.map((item) => item.rows));
  return <div className="space-y-3" role="img" aria-label="Family volume chart">{dataset.families.map((row) => <div key={row.family} className="grid gap-2 sm:grid-cols-[190px_minmax(0,1fr)_100px] sm:items-center"><div className="break-words text-xs font-semibold text-slate-700">{row.family.replaceAll("_", " ")}</div><div className="h-3 overflow-hidden rounded-full bg-slate-100"><div className="h-full rounded-full bg-gradient-to-r from-cyan-600 to-blue-500" style={{ width: `${Math.max(1, row.rows / maximum * 100)}%` }} /></div><div className="text-right font-mono text-xs tabular-nums text-slate-600">{number(row.rows)}</div></div>)}</div>;
}

function SeasonCoverage({ dataset }: { dataset: ActiveSportsDataset }) {
  if (dataset.datasetId === "asp.mlb.statcast.current-pa.v1") {
    return <div className="overflow-x-auto"><table className="w-full min-w-[560px] text-left text-xs"><thead><tr className="border-b border-slate-200 text-slate-500">{["Season", "Earliest accepted date", "Latest accepted date", "Plate appearances"].map((label) => <th key={label} className="px-3 py-3 font-semibold uppercase tracking-wide">{label}</th>)}</tr></thead><tbody>{dataset.seasonCoverage.map((row) => <tr key={row.season} className="border-b border-slate-100 last:border-0"><td className="px-3 py-3 font-semibold text-slate-900">{row.season}</td><td className="px-3 py-3 font-mono">{safeText(row.earliestDate)}</td><td className="px-3 py-3 font-mono">{safeText(row.latestDate)}</td><td className="px-3 py-3 tabular-nums">{number(row.plateAppearances)}</td></tr>)}</tbody></table></div>;
  }
  return <div className="overflow-x-auto"><table className="w-full min-w-[720px] text-left text-xs"><thead><tr className="border-b border-slate-200 text-slate-500">{["Season", "Games", "Plate appearances", "Transitions", "Starter targets", "Bullpen"].map((label) => <th key={label} className="px-3 py-3 font-semibold uppercase tracking-wide">{label}</th>)}</tr></thead><tbody>{dataset.seasonCoverage.map((row) => <tr key={row.season} className="border-b border-slate-100 last:border-0"><td className="px-3 py-3 font-semibold text-slate-900">{row.season}</td><td className="px-3 py-3 tabular-nums">{number(row.games)}</td><td className="px-3 py-3 tabular-nums">{number(row.plateAppearances)}</td><td className="px-3 py-3 tabular-nums">{number(row.transitions)}</td><td className="px-3 py-3 tabular-nums">{number(row.starterTargets)}</td><td className="px-3 py-3 tabular-nums">{number(row.bullpenAppearances)}</td></tr>)}</tbody></table></div>;
}

function recordNumber(record: Record<string, unknown> | undefined, key: string) {
  const value = record?.[key];
  return typeof value === "number" && Number.isFinite(value) ? value : undefined;
}

function recordText(record: Record<string, unknown> | undefined, key: string) {
  const value = record?.[key];
  return typeof value === "string" || typeof value === "boolean" ? safeText(value) : "—";
}

function NflSeasonAndCurrentCoverage({ dataset }: { dataset: ActiveSportsDataset }) {
  const quality = dataset.quality;
  const schedule = quality?.scheduleBySeasonAndGameType ?? [];
  const playByPlay = quality?.pbpBySeasonAndGameType ?? [];
  const rows = schedule.map((item) => {
    const pbp = playByPlay.find((candidate) => candidate.season === item.season && candidate.gameType === item.gameType);
    return { ...item, pbpGames: pbp?.games, plays: pbp?.plays };
  });
  const current = quality?.current2026;
  return <div className="space-y-4">
    <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
      <Detail label="Evidence start" value={dataset.dateCoverage?.earliestDate || dataset.evidenceCutoff} />
      <Detail label="Evidence end" value={dataset.dateCoverage?.latestDate || dataset.evidenceCutoff} />
      <Detail label="2026 scheduled games" value={number(recordNumber(current, "scheduledGames"))} />
      <Detail label="2026 completed games" value={number(recordNumber(current, "completedGames"))} />
      <Detail label="2026 minimum date" value={recordText(current, "minimumDate")} />
      <Detail label="2026 maximum date" value={recordText(current, "maximumDate")} />
      <Detail label="Completed-game evidence" value={recordText(current, "completedGameEvidence")} />
      <Detail label="Current sync" value={safeText(dataset.nflCurrentSync?.status)} />
    </div>
    {dataset.nflCurrentSync?.latestSuccessfulAtUtc ? <p className="text-xs text-slate-500">Latest successful NFL foundation sync: <span className="font-mono">{safeText(dataset.nflCurrentSync.latestSuccessfulAtUtc)}</span></p> : null}
    <div className="overflow-x-auto"><table className="w-full min-w-[760px] text-left text-xs"><thead><tr className="border-b border-slate-200 text-slate-500">{["Season", "Game type", "Scheduled", "Completed", "PBP games", "Plays"].map((label) => <th key={label} className="px-3 py-3 font-semibold uppercase tracking-wide">{label}</th>)}</tr></thead><tbody>{rows.map((row) => <tr key={`${row.season}-${row.gameType}`} className="border-b border-slate-100 last:border-0"><td className="px-3 py-3 font-semibold text-slate-900">{row.season}</td><td className="px-3 py-3">{row.gameType}</td><td className="px-3 py-3 tabular-nums">{number(row.scheduledGames)}</td><td className="px-3 py-3 tabular-nums">{number(row.completedGames)}</td><td className="px-3 py-3 tabular-nums">{number(row.pbpGames)}</td><td className="px-3 py-3 tabular-nums">{number(row.plays)}</td></tr>)}</tbody></table></div>
  </div>;
}

function NflSourceFamilyCoverage({ dataset }: { dataset: ActiveSportsDataset }) {
  const families = dataset.sourceFamilies ?? [];
  return <Card title="NFL source-family coverage" description="Exact nflverse source families, eras, releases, licenses, and publication status returned by the registered authority.">
    <div className="mb-4 flex flex-wrap items-center justify-between gap-2"><div className="text-sm text-slate-600">Provider: <strong>{safeText(dataset.sourceProvider)}</strong></div><Pill value={`${families.filter((item) => item.status === "COMPLETE").length} / ${families.length} complete`} /></div>
    <div className="overflow-x-auto"><table className="w-full min-w-[1080px] text-left text-xs"><thead><tr className="border-b border-slate-200 text-slate-500">{["Family", "Required", "Status", "Seasons / dates", "Partitions", "Rows", "Schema variants", "Latest source update"].map((label) => <th key={label} className="px-3 py-3 font-semibold uppercase tracking-wide">{label}</th>)}</tr></thead><tbody>{families.map((family) => <tr key={family.familyId} className="border-b border-slate-100 align-top last:border-0"><td className="px-3 py-3"><div className="font-semibold text-slate-900">{family.familyId.replaceAll("_", " ")}</div><div className="mt-1 text-[11px] text-slate-500">Releases: {family.releaseTags.join(", ") || "—"}<br />Licenses: {family.licenseIds.join(", ") || "—"}{family.missingSeasons.length ? <><br />Missing seasons: {family.missingSeasons.join(", ")}</> : null}</div></td><td className="px-3 py-3">{family.mandatory ? "MANDATORY" : "OPTIONAL"}</td><td className="px-3 py-3"><Pill value={family.status} /></td><td className="px-3 py-3">{family.seasons.length ? `${Math.min(...family.seasons)}–${Math.max(...family.seasons)}` : "—"}<div className="mt-1 font-mono text-[11px] text-slate-500">{family.minimumDate || "—"} through {family.maximumDate || "—"}</div></td><td className="px-3 py-3 tabular-nums">{number(family.partitionCount)}</td><td className="px-3 py-3 tabular-nums"><div>{number(family.rowCount)}</div>{family.rowsBySeason.length ? <details className="mt-1 text-[11px] text-slate-500"><summary className="cursor-pointer">By season</summary><div className="mt-1 max-h-44 overflow-auto whitespace-nowrap font-mono">{family.rowsBySeason.map((entry) => <div key={entry.season}>{entry.season}: {number(entry.rowCount)}</div>)}</div></details> : null}</td><td className="px-3 py-3 tabular-nums">{number(family.schemaVariantCount)}</td><td className="px-3 py-3 font-mono text-[11px]">{safeText(family.latestSourceUpdate)}</td></tr>)}</tbody></table></div>
  </Card>;
}

function NflFeatureAuthority({ dataset }: { dataset: ActiveSportsDataset }) {
  const families = Object.entries(dataset.featureFamilies ?? {});
  const eraContracts = Object.entries(dataset.featureEraContracts ?? {});
  return <Card title="NFL Gold feature-family authority" description="Exact research feature inventory by family. These are data contracts only; no estimator was fit or connected.">
    <div className="grid gap-3 lg:grid-cols-2">{families.map(([family, features]) => <details key={family} className="rounded-xl border border-slate-200 bg-slate-50 p-4"><summary className="cursor-pointer text-sm font-semibold text-slate-950">{family.replaceAll("_", " ")} <span className="ml-2 text-xs font-normal text-slate-500">{features.length} features</span></summary><ol className="mt-3 grid gap-1 text-xs leading-5 text-slate-700 sm:grid-cols-2">{features.map((feature, index) => <li key={feature} className="break-words"><span className="mr-1 font-mono text-slate-400">{index + 1}.</span>{feature}</li>)}</ol></details>)}</div>
    {eraContracts.length ? <div className="mt-5"><h3 className="text-sm font-semibold text-slate-950">Feature-era contracts</h3><div className="mt-3 grid gap-3 md:grid-cols-2 xl:grid-cols-3">{eraContracts.map(([family, contract]) => <dl key={family} className="rounded-xl border border-slate-200 p-4"><dt className="text-xs font-semibold uppercase tracking-wide text-slate-600">{family.replaceAll("_", " ")}</dt>{Object.entries(contract).map(([key, value]) => <div key={key} className="mt-2"><dt className="text-[11px] font-semibold uppercase tracking-wide text-slate-400">{humanizeEvidenceKey(key)}</dt><dd className="mt-0.5 text-xs text-slate-700">{safeText(value)}</dd></div>)}</dl>)}</div></div> : null}
  </Card>;
}

function NflQualityReview({ dataset }: { dataset: ActiveSportsDataset }) {
  const quality = dataset.quality;
  if (!quality) return null;
  const identity = quality.identity;
  const reconciliation = quality.reconciliation;
  const state = quality.stateQuality;
  const market = quality.marketCoverage;
  const gold = quality.gold;
  return <Card title="NFL identity, reconciliation, and market review" description="Observed quality facts remain separate from model eligibility; market snapshots are post-evidence research inputs only when their timing is proven.">
    <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
      <Detail label="Duplicate game identities" value={number(recordNumber(identity, "duplicateGameIdentities"))} />
      <Detail label="Duplicate play identities" value={number(recordNumber(identity, "duplicatePlayIdentities"))} />
      <Detail label="Duplicate player identities" value={number(recordNumber(identity, "duplicateCanonicalPlayerIdentities"))} />
      <Detail label="Ambiguous identities" value={number(recordNumber(identity, "ambiguousIdentityCount"))} />
      <Detail label="Roster rows missing GSIS ID" value={number(recordNumber(identity, "rosterRowsMissingGsisId"))} />
      <Detail label="Unresolved stat player IDs" value={number(recordNumber(identity, "unresolvedDistinctStatPlayerIds"))} />
      <Detail label="PBP games without schedule" value={number(recordNumber(reconciliation, "pbpGamesWithoutSchedule"))} />
      <Detail label="Completed games without PBP" value={number(recordNumber(reconciliation, "completed1999To2025RegPostGamesWithoutPbp"))} />
      <Detail label="Impossible clock rows" value={number(recordNumber(state, "impossibleClockRows"))} />
      <Detail label="Impossible score games" value={number(recordNumber(state, "impossibleScoreGames"))} />
      <Detail label="Gold pregame games" value={number(recordNumber(gold, "pregameGames"))} />
      <Detail label="Gold eligible play states" value={number(recordNumber(gold, "eligiblePlayStates"))} />
    </div>
    <div className="mt-5 rounded-xl border border-amber-200 bg-amber-50 p-4"><div className="flex flex-wrap items-center justify-between gap-2"><h3 className="font-semibold text-amber-950">Historical market coverage</h3><Pill value={recordText(market, "timingSemantics")} /></div><dl className="mt-3 grid gap-3 sm:grid-cols-2 xl:grid-cols-5"><Detail label="Market records" value={number(recordNumber(market, "records"))} /><Detail label="Two-sided moneyline" value={number(recordNumber(market, "completeTwoSidedMoneyline"))} /><Detail label="Two-sided spread" value={number(recordNumber(market, "completeTwoSidedSpread"))} /><Detail label="Two-sided total" value={number(recordNumber(market, "completeTwoSidedTotal"))} /><Detail label="Core predictor eligible" value={recordText(market, "corePredictorEligible")} /></dl></div>
    <p className="mt-4 text-xs font-semibold text-slate-600">Models fitted: {number(quality.modelsFitted)} · Workspace activation: disabled · NFL workflow remains a research foundation.</p>
  </Card>;
}

function CurrentEvidenceBoundary({ dataset }: { dataset: ActiveSportsDataset }) {
  if (dataset.datasetId !== "asp.mlb.statcast.current-pa.v1" || !dataset.dateCoverage) return null;
  const sync = dataset.currentStatcastSync;
  const resulting = (sync?.resultingCoverage && typeof sync.resultingCoverage === "object" ? sync.resultingCoverage : {}) as Record<string, unknown>;
  const numeric = (value: unknown) => typeof value === "number" ? value : undefined;
  const sourcePitches = sync?.sourcePitches ?? sync?.sourcePitchRows ?? numeric(resulting.sourcePitchRows);
  const acceptedPitches = sync?.acceptedPitches ?? sync?.acceptedPitchRows ?? numeric(resulting.acceptedPitchRows);
  const goldRows = sync?.goldRows ?? numeric(resulting.goldRows);
  const rejected = sync?.rejectedPlateAppearances ?? numeric(resulting.rejectedPlateAppearances);
  const silverPartitions = numeric(sync?.silverPartitionCount) ?? numeric(resulting.partitionCount);
  const completeEmptyPartitions = numeric(sync?.completeEmptyPartitionCount) ?? numeric(resulting.completeEmptyPartitionCount) ?? 0;
  const completePartitions = silverPartitions === undefined ? undefined : Math.max(0, silverPartitions - completeEmptyPartitions);
  const revisedPartitions = sync?.revisedPartitionCount ?? (Array.isArray(sync?.datesCorrected) ? sync.datesCorrected.length : 0);
  const rejectReasons = Object.entries(sync?.rejectReasons ?? {})
    .sort(([left], [right]) => left.localeCompare(right))
    .map(([reason, count]) => `${reason}: ${number(count)}`)
    .join(", ") || "None";
  return <Card title="Current Statcast evidence boundary" description="Exact accepted plate-appearance coverage; no season endpoint is inferred from mutable current state.">
    <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
      <Detail label="Earliest accepted date" value={dataset.dateCoverage.earliestDate} />
      <Detail label="Latest accepted date" value={dataset.dateCoverage.latestDate} />
      <Detail label="Accepted plate appearances" value={number(dataset.dateCoverage.rowCount)} />
      <Detail label="Content-addressed partitions" value={number(dataset.dateCoverage.partitionCount)} />
    </div>
    {sync ? <div className="mt-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
      <Detail label="Nightly sync status" value={safeText(sync.status)} />
      <Detail label="Latest fully completed date" value={safeText(sync.latestMlbFinalDate ?? sync.latestFullyCompletedDate ?? sync.requestedThroughDate)} />
      <Detail label="Source / accepted pitches" value={`${number(sourcePitches)} / ${number(acceptedPitches)}`} />
      <Detail label="Gold rows" value={number(goldRows)} />
      <Detail label="Rejected plate appearances" value={number(rejected)} />
      <Detail label="Reject reasons" value={rejectReasons} />
      <Detail label="Silver partitions (complete / empty / revised)" value={`${number(completePartitions)} / ${number(completeEmptyPartitions)} / ${number(revisedPartitions)}`} />
      <Detail label="Last attempted" value={safeText(sync.attemptedAtUtc)} />
      <Detail label="Last successful" value={safeText(sync.lastSuccessfulAtUtc)} />
      <Detail label="Model fits" value="0" />
    </div> : null}
    {dataset.temporalContract ? <div className="mt-4 grid gap-3 lg:grid-cols-3">
      <Detail label="Eligible evidence" value={dataset.temporalContract.intendedCombinedEligibleEvidence.join(" through ")} />
      <Detail label="Development / model selection" value={dataset.temporalContract.intendedCombinedDevelopmentSelection.join(" through ")} />
      <Detail label="Final untouched OOT" value={dataset.temporalContract.intendedCombinedFinalOot.join(" through ")} />
    </div> : null}
    <div className="mt-4 flex flex-wrap items-start justify-between gap-3 rounded-xl border border-cyan-200 bg-cyan-50 p-4 text-cyan-950">
      <div><div className="text-sm font-semibold">Evidence registration only</div><p className="mt-1 text-sm leading-6">No model was fit, scored, calibrated, selected, or promoted by this Data Warehouse registration.</p></div>
      <Pill value={dataset.modelingStatus || "EVIDENCE_REGISTERED_NO_FIT"} />
    </div>
  </Card>;
}

function Populations({ dataset }: { dataset: ActiveSportsDataset }) {
  const total = Math.max(1, dataset.populations.reduce((sum, item) => sum + item.rows, 0));
  return (
    <>
      <div className="flex h-6 overflow-hidden rounded-full bg-slate-100" role="img" aria-label="Dataset population composition">
        {dataset.populations.map((item, index) => <div key={item.populationId} className={index % 3 === 0 ? "bg-cyan-600" : index % 3 === 1 ? "bg-violet-500" : "bg-slate-500"} style={{ width: `${item.rows / total * 100}%` }} title={`${item.populationId}: ${number(item.rows)}`} />)}
      </div>
      <div className="mt-4 grid gap-3 md:grid-cols-3">
        {dataset.populations.map((item) => (
          <article key={item.populationId} className="rounded-xl border border-slate-200 bg-slate-50 p-4">
            <h3 className="text-sm font-semibold text-slate-950">{item.populationId.replaceAll("_", " ")}</h3>
            <div className="mt-1 text-xl font-semibold tabular-nums">{number(item.rows)}</div>
            <div className="mt-1 text-xs text-slate-500">{Math.round((item.rows / total) * 100)}% of registered rows</div>
            {item.uses?.length ? <div className="mt-3"><div className="text-[11px] font-semibold uppercase tracking-wide text-emerald-700">Permitted use</div><ul className="mt-1 grid gap-0.5 text-xs leading-5 text-emerald-900">{item.uses.map((u) => <li key={u}>· {u}</li>)}</ul></div> : null}
            {item.prohibitions?.length ? <div className="mt-2"><div className="text-[11px] font-semibold uppercase tracking-wide text-amber-700">Prohibited</div><ul className="mt-1 grid gap-0.5 text-xs leading-5 text-amber-900">{item.prohibitions.map((p) => <li key={p}>· {p}</li>)}</ul></div> : null}
            <details className="mt-3 border-t border-slate-200 pt-2">
              <summary className="cursor-pointer text-xs font-semibold text-slate-600">View technical query</summary>
              <p className="mt-2 break-words font-mono text-[11px] leading-5 text-slate-500">{item.predicate}</p>
            </details>
          </article>
        ))}
      </div>
    </>
  );
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

function IdentityBridgeAuthority({ dataset }: { dataset: ActiveSportsDataset }) {
  const bridge = dataset.identityBridge;
  const requiredArtifact = dataset.featureAudit?.missingBridge.requiredArtifact || "SPORTS_IDENTITY_BRIDGE_V1";
  const missingReason = dataset.featureAudit?.missingBridge.reason || "No immutable identity companion is registered for this dataset version.";
  if (!bridge) {
    return <Card title="MLB identity bridge" description="A companion identity authority is shown only when its exact parent registration, manifest, and partition authority match this dataset.">
      <div className="flex items-start gap-3 rounded-xl border border-amber-200 bg-amber-50 p-4 text-amber-950">
        <Fingerprint size={20} className="mt-0.5 shrink-0" />
        <div className="min-w-0 flex-1"><div className="text-sm font-semibold">No governed MLB identity bridge is registered.</div><p className="mt-1 text-sm leading-6">{safeText(missingReason)}</p><div className="mt-3 inline-flex rounded-lg border border-amber-200 bg-white px-3 py-2 font-mono text-xs font-semibold">{safeText(requiredArtifact)}</div></div>
        <Pill value="NOT REGISTERED" />
      </div>
    </Card>;
  }

  const validated = hasValidatedIdentityBridge(dataset);
  const audit = bridge.joinAudit;
  return <Card title="MLB identity bridge" description="Immutable alias and governed-player authority bound to the active FD1 registration. Counts and joins come only from the registered companion evidence.">
    <div className={`flex flex-wrap items-start justify-between gap-4 rounded-xl border p-4 ${validated ? "border-emerald-200 bg-emerald-50" : "border-amber-200 bg-amber-50"}`}>
      <div className="flex min-w-0 flex-1 items-start gap-3">
        {validated ? <CheckCircle2 size={21} className="mt-0.5 shrink-0 text-emerald-700" /> : <Fingerprint size={21} className="mt-0.5 shrink-0 text-amber-700" />}
        <div className="min-w-0"><div className="break-words font-mono text-xs font-semibold text-slate-950">{safeText(bridge.contractName)} · {safeText(bridge.contractVersion)}</div><p className="mt-1 text-sm leading-6 text-slate-700">{validated ? "The active companion passed its declared validation and exact join audit without name-based or fuzzy matching." : "The companion is visible, but its active validation and exact-match gates are not all satisfied."}</p></div>
      </div>
      <Pill value={bridge.validationStatus} />
    </div>

    <section className="mt-5 grid gap-3 sm:grid-cols-2 xl:grid-cols-5" aria-label="Identity bridge totals">
      <BridgeMetric label="Alias rows" value={number(bridge.totals.aliasRows)} detail={`${number(bridge.totals.packageFiles)} package files · ${number(bridge.totals.packageBytes)} bytes`} />
      <BridgeMetric label="Portable players" value={number(bridge.totals.portablePlayers)} detail={`${number(bridge.totals.primaryPortablePlayers)} primary`} />
      <BridgeMetric label="Governed players" value={number(bridge.totals.governedPlayers)} detail={`${number(bridge.totals.primaryGovernedPlayers)} primary`} />
      <BridgeMetric label="Namespaces" value={number(bridge.totals.namespaces)} detail={`${number(bridge.totals.joinContracts)} join contracts`} />
      <BridgeMetric label="Join references" value={number(bridge.totals.joinReferences)} detail={`${percentage(audit.mappingRate)} exact mapping rate`} />
    </section>

    <div className="mt-5 grid gap-4 xl:grid-cols-2">
      <section className="rounded-xl border border-slate-200 p-4">
        <div className="flex flex-wrap items-center justify-between gap-2"><h3 className="font-semibold text-slate-950">Exact join audit</h3><Pill value={audit.status} /></div>
        <div className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-3">
          <Detail label="Total references" value={number(audit.totalReferences)} />
          <Detail label="Resolved" value={number(audit.resolvedReferences)} />
          <Detail label="Unresolved" value={number(audit.unresolvedReferences)} />
          <Detail label="Ambiguous" value={number(audit.ambiguousReferences)} />
          <Detail label="Multiply mapped" value={number(audit.multiplyMappedReferences)} />
          <Detail label="Mapping rate" value={percentage(audit.mappingRate)} />
        </div>
        <p className={`mt-4 flex items-start gap-2 rounded-lg px-3 py-2 text-xs font-semibold leading-5 ${bridge.noNamesOrFuzzyMatching ? "bg-emerald-50 text-emerald-900" : "bg-amber-50 text-amber-950"}`}><ShieldCheck size={15} className="mt-0.5 shrink-0" />Name-based or fuzzy matching used: {bridge.noNamesOrFuzzyMatching ? "no" : "not proven absent"}.</p>
      </section>
      <section className="rounded-xl border border-slate-200 p-4">
        <div className="flex flex-wrap items-center justify-between gap-2"><h3 className="font-semibold text-slate-950">Parent authority binding</h3><Pill value={bridge.active ? "ACTIVE" : "INACTIVE"} /></div>
        <dl className="mt-4 grid gap-3 sm:grid-cols-2">
          <Detail label="Parent registration" value={bridge.parentRegistrationId} />
          <Detail label="Parent manifest SHA-256" value={bridge.parentManifestSha} />
          <Detail label="Parent partition authority" value={bridge.parentPartitionAuthoritySha} />
          <Detail label="Registered at" value={bridge.registeredAt} />
        </dl>
      </section>
    </div>

    <div className="mt-5 grid gap-5 xl:grid-cols-2">
      <section><h3 className="text-sm font-semibold text-slate-950">Namespace evidence</h3><p className="mt-1 mb-3 text-xs leading-5 text-slate-500">Declared namespace counts and exact identity coverage.</p><EvidenceRows rows={bridge.namespaceEvidence} empty="No namespace evidence rows were returned." /></section>
      <section><h3 className="text-sm font-semibold text-slate-950">Join contracts</h3><p className="mt-1 mb-3 text-xs leading-5 text-slate-500">Registered join-reference outcomes from the immutable audit artifact.</p><EvidenceRows rows={audit.joins} empty="No join-contract rows were returned." /></section>
    </div>

    <section className="mt-5"><h3 className="text-sm font-semibold text-slate-950">Y−1 prior coverage</h3><p className="mt-1 mb-3 text-xs leading-5 text-slate-500">Season and role coverage for leakage-safe prior joins. Genuine missing priors remain missing-prior cases, not identity failures.</p><EvidenceRows rows={bridge.yMinus1Coverage} empty="No Y−1 coverage rows were returned." /></section>

    <div className="mt-5 grid gap-4 xl:grid-cols-2">
      <section className="rounded-xl border border-slate-200 p-4"><div className="flex flex-wrap items-center justify-between gap-2"><h3 className="font-semibold text-slate-950">Bridge rights</h3><Pill value={bridge.rights.status} /></div>{bridge.rights.allowedPurposes.length ? <p className="mt-3 text-xs leading-5 text-emerald-800">Allowed: {bridge.rights.allowedPurposes.map(safeText).join("; ")}</p> : <p className="mt-3 text-xs text-slate-500">No allowed purposes were returned.</p>}{bridge.rights.prohibitedPurposes.length ? <p className="mt-2 text-xs leading-5 text-amber-900">Prohibited: {bridge.rights.prohibitedPurposes.map(safeText).join("; ")}</p> : null}</section>
      <section className="rounded-xl border border-slate-200 p-4"><h3 className="font-semibold text-slate-950">Bridge limitations</h3>{bridge.limitations.length ? <ul className="mt-3 space-y-2">{bridge.limitations.map((limitation) => <li key={limitation} className="flex gap-2 text-xs leading-5 text-amber-900"><Scale size={14} className="mt-0.5 shrink-0" />{safeText(limitation)}</li>)}</ul> : <p className="mt-3 text-xs text-slate-500">No bridge-specific limitations were returned.</p>}</section>
    </div>

    <details className="mt-5 rounded-xl border border-slate-200 bg-slate-50 p-4"><summary className="cursor-pointer text-sm font-semibold text-cyan-800">Show immutable bridge identifiers</summary><dl className="mt-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-3"><Detail label="Registration ID" value={bridge.registrationId} /><Detail label="Manifest ID" value={bridge.manifestId} /><Detail label="Manifest SHA-256" value={bridge.manifestSha} /><Detail label="Package ID" value={bridge.packageId} /><Detail label="Alias authority SHA-256" value={bridge.aliasAuthoritySha} /><Detail label="Dimension authority SHA-256" value={bridge.dimensionAuthoritySha} /><Detail label="Validation report SHA-256" value={bridge.validationReportSha} /><Detail label="Join artifact ID" value={audit.artifactId} /><Detail label="Join artifact SHA-256" value={audit.artifactSha} /><Detail label="Logical bridge root" value={logicalExchangeUri(bridge.logicalRoot)} /><Detail label="Logical join audit" value={logicalSportsEvidenceUri(audit.logicalUri)} /></dl></details>
  </Card>;
}

function FeatureAuthority({ dataset }: { dataset: ActiveSportsDataset }) {
  const audit = dataset.featureAudit;
  if (!audit) return null;
  const bridgeValidated = hasValidatedIdentityBridge(dataset);
  const showPackageOnlyRows = !bridgeValidated || audit.status.toUpperCase() !== "BLOCKED";
  return <Card title="Plate-appearance feature authority" description={bridgeValidated ? "The validated identity companion clears the former package-only bridge blocker. Feature materialization remains a separate governed action." : "Package-only identity evidence for MLB_PA_FEATURE_VIEW_V1. Zero joins are reported as a governed blocker, not filled or inferred."}>
    <div className={`flex flex-wrap items-start justify-between gap-3 rounded-xl border p-4 ${bridgeValidated ? "border-emerald-200 bg-emerald-50" : "border-amber-200 bg-amber-50"}`}>
      <div className="min-w-0"><div className={`break-words font-mono text-xs font-semibold ${bridgeValidated ? "text-emerald-950" : "text-amber-950"}`}>{audit.contractVersion}</div><p className={`mt-1 text-sm leading-6 ${bridgeValidated ? "text-emerald-950" : "text-amber-950"}`}>{bridgeValidated ? `Registered ${dataset.identityBridge?.contractVersion} authority ${dataset.identityBridge?.registrationId} supplies the exact package-bound identity bridge.` : audit.missingBridge.reason}</p></div><Pill value={bridgeValidated ? "BRIDGE VALIDATED" : audit.status} />
    </div>
    <dl className="mt-4 grid gap-3 sm:grid-cols-2">
      <Detail label="Plate-appearance namespace" value={audit.observedNamespaces.plateAppearance.join(", ")} />
      <Detail label="Player-prior namespaces" value={audit.observedNamespaces.playerPrior.join(", ")} />
    </dl>
    {showPackageOnlyRows ? <div className="mt-4 overflow-x-auto"><table className="w-full min-w-[680px] text-left text-xs"><thead><tr className="border-b border-slate-200 text-slate-500">{["Season", "Plate appearances", "Eligible batting priors", "Batter Y-1 joins", "Eligible pitching priors", "Pitcher Y-1 joins"].map((label) => <th key={label} className="px-3 py-3 font-semibold uppercase tracking-wide">{label}</th>)}</tr></thead><tbody>{audit.perSeasonRows.map((row) => <tr key={row.season} className="border-b border-slate-100 last:border-0"><td className="px-3 py-3 font-semibold text-slate-900">{row.season}</td><td className="px-3 py-3 tabular-nums">{number(row.plateAppearanceRows)}</td><td className="px-3 py-3 tabular-nums">{number(row.eligibleBattingPriorRows)}</td><td className="px-3 py-3 font-semibold tabular-nums text-amber-900">{number(row.batterYMinus1JoinMatches)} / {number(row.batterYMinus1JoinDenominator)}</td><td className="px-3 py-3 tabular-nums">{number(row.eligiblePitchingPriorRows)}</td><td className="px-3 py-3 font-semibold tabular-nums text-amber-900">{number(row.pitcherYMinus1JoinMatches)} / {number(row.pitcherYMinus1JoinDenominator)}</td></tr>)}</tbody></table></div> : null}
    <p className="mt-4 break-words text-xs leading-5 text-slate-600">{bridgeValidated ? <>Registered authority: <span className="font-mono font-semibold">{dataset.identityBridge?.registrationId}</span>. Name-based or fuzzy identity matching used: <strong>{dataset.identityBridge?.noNamesOrFuzzyMatching ? "no" : "not proven absent"}</strong>.</> : <>Required authority: <span className="font-mono font-semibold">{audit.missingBridge.requiredArtifact}</span>. Fuzzy or inferred identity matching used: <strong>{audit.joinEvidence.inferenceOrFuzzyMatchingUsed ? "yes" : "no"}</strong>.</>}</p>
  </Card>;
}

function Detail({ label, value }: { label: string; value: string }) {
  return <div className="min-w-0 rounded-lg border border-slate-200 bg-slate-50 p-3"><dt className="text-xs font-semibold uppercase tracking-wide text-slate-500">{label}</dt><dd className="mt-1 break-all font-mono text-xs leading-5 text-slate-800">{safeText(value)}</dd></div>;
}

function DatasetDetails({ dataset }: { dataset: ActiveSportsDataset }) {
  const isNfl = dataset.league.trim().toUpperCase() === "NFL";
  return <>
    <MetricGrid dataset={dataset} />
    <CurrentEvidenceBoundary dataset={dataset} />
    <div className="grid gap-5 xl:grid-cols-2"><Card title="Family volume" description="Declared rows by logical data family."><FamilyChart dataset={dataset} /></Card><Card title={isNfl ? "NFL season and current-2026 coverage" : "Season coverage"} description={isNfl ? "Schedule, completed-game, play-by-play, and current-season evidence returned by the NFL authority." : "Registered evidence by season and target family."}>{isNfl ? <NflSeasonAndCurrentCoverage dataset={dataset} /> : <SeasonCoverage dataset={dataset} />}</Card></div>
    {isNfl ? <><NflSourceFamilyCoverage dataset={dataset} /><NflFeatureAuthority dataset={dataset} /><NflQualityReview dataset={dataset} /></> : null}
    {dataset.populations.length ? <Card title="Population composition" description="Governed population precedence, permitted research uses, and prohibitions."><Populations dataset={dataset} /></Card> : null}
    {!isNfl ? <><div className="grid gap-5 xl:grid-cols-2">{dataset.folds.length ? <Card title="Temporal fold timeline" description="Frozen retrospective rolling-origin validation folds."><Folds dataset={dataset} /></Card> : null}<Card title="Evidence coverage matrix" description="Only coverage states returned by the registered dataset service are shown."><Coverage dataset={dataset} /></Card></div><IdentityBridgeAuthority dataset={dataset} /><FeatureAuthority dataset={dataset} /></> : null}
    <div className="grid gap-5 xl:grid-cols-2"><Card title="Source rights" description="Approved uses and prohibited redistribution remain part of the registration."><Rights dataset={dataset} /></Card><Card title="Known limitations" description="Retrospective evidence is not prospective proof."><ul className="space-y-2">{dataset.limitations.map((limitation) => <li key={limitation} className="flex gap-3 rounded-lg border border-amber-100 bg-amber-50 px-3 py-2 text-sm leading-6 text-amber-950"><Scale size={16} className="mt-1 shrink-0" />{limitation}</li>)}</ul></Card></div>
    <Card title="Technical registration details" description="Checksums remain inspectable without exposing administrator-controlled physical evidence paths."><details><summary className="cursor-pointer text-sm font-semibold text-cyan-800">Show immutable identifiers</summary><dl className="mt-4 grid gap-3 sm:grid-cols-2"><Detail label="Sport" value={dataset.sport} /><Detail label="League" value={dataset.league} />{dataset.authorityLayer ? <Detail label="Authority layer" value={dataset.authorityLayer} /> : null}{dataset.authorityState ? <Detail label="Authority state" value={dataset.authorityState} /> : null}<Detail label="Registration ID" value={dataset.registrationId} /><Detail label="Dataset ID" value={dataset.datasetId} /><Detail label="Dataset version" value={dataset.datasetVersionId} /><Detail label="Manifest ID" value={dataset.manifestId} /><Detail label="Manifest SHA-256" value={dataset.manifestSha} /><Detail label="Partition authority SHA-256" value={dataset.partitionAuthoritySha || "Unavailable"} /><Detail label="Package ID" value={dataset.packageId} /><Detail label="Logical root" value={logicalSportsEvidenceUri(dataset.logicalRoot)} /><Detail label="Evidence cutoff" value={dataset.evidenceCutoff} /></dl></details></Card>
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

function DatasetCatalogSelection({
  datasets, selectedRegistrationId, onSelect, onRefresh,
}: {
  datasets: ActiveSportsDataset[];
  selectedRegistrationId: string;
  onSelect: (registrationId: string) => void;
  onRefresh: () => void;
}) {
  const [role, setRole] = useState<string | null>(null);
  const [activation, setActivation] = useState<"idle" | "saving" | "error">("idle");
  const [message, setMessage] = useState("");
  const selected = datasets.find((item) => item.registrationId === selectedRegistrationId) ?? datasets[0];
  const selectedActivationEligible = selected?.workspaceActivationEligible !== false;
  useEffect(() => {
    let current = true;
    void me().then((response) => { if (current) setRole(String(response.user.role).toLowerCase()); }).catch(() => { if (current) setRole(""); });
    return () => { current = false; };
  }, []);
  async function activate() {
    if (!selected || selected.active || !selectedActivationEligible || role !== "admin" || activation === "saving") return;
    setActivation("saving");
    setMessage("");
    try {
      await activateSportsDataset(selected.registrationId);
      setActivation("idle");
      setMessage(`${selected.datasetId} is now the workspace dataset. No project contract was saved.`);
      onRefresh();
    } catch (error) {
      setActivation("error");
      setMessage(error instanceof Error ? error.message : "Dataset selection failed closed.");
    }
  }
  return <Card title="Registered dataset catalog" description="Inspect any validated registration. Read-only authorities cannot change the workspace dataset; eligible changes remain an explicit administrator action and never save a project forecast contract.">
    <div className="grid gap-3 lg:grid-cols-2">{datasets.map((item) => <button key={item.registrationId} type="button" onClick={() => onSelect(item.registrationId)} className={`rounded-xl border p-4 text-left transition ${item.registrationId === selected?.registrationId ? "border-cyan-400 bg-cyan-50" : "border-slate-200 bg-white hover:border-slate-300"}`}>
      <div className="flex flex-wrap items-center justify-between gap-2"><span className="font-semibold text-slate-950">{item.datasetId}</span><Pill value={item.active ? "WORKSPACE ACTIVE" : item.workspaceActivationEligible === false ? "READ-ONLY AUTHORITY" : "AVAILABLE"} /></div>
      <div className="mt-2 flex flex-wrap items-center gap-2 text-xs font-semibold text-slate-700"><span>{item.sport} · {item.league}</span>{item.authorityLayer ? <Pill value={item.authorityLayer} /> : null}{item.authorityState ? <Pill value={item.authorityState} /> : null}</div>
      <div className="mt-2 flex flex-wrap gap-1.5" aria-label={`${item.league} dataset classification`}><Pill value={`SPORT ${item.league === "NFL" ? "FOOTBALL" : "BASEBALL"}`} /><Pill value={`LEAGUE ${item.league}`} /><Pill value={`GRAIN ${item.league === "NFL" ? "GAME / PLAY" : "PLATE APPEARANCE"}`} /><Pill value={`PREDICTION UNIT ${item.league === "NFL" ? "GAME" : "PLATE APPEARANCE"}`} /><Pill value="POINT-IN-TIME DECLARED" /><Pill value={item.authorityState?.toUpperCase().includes("SEALED") ? "SEALED" : "SEALED STATUS DECLARED BY AUTHORITY"} /><Pill value={item.rights.length ? "SOURCE RIGHTS RECORDED" : "SOURCE RIGHTS UNAVAILABLE"} /></div>
      <div className="mt-2 text-xs text-slate-600">{item.dateCoverage ? `${item.dateCoverage.earliestDate} through ${item.dateCoverage.latestDate}` : `Evidence cutoff ${item.evidenceCutoff}`}</div>
      <div className="mt-1 break-all font-mono text-[11px] text-slate-500">{item.registrationId}</div>
    </button>)}</div>
    {selected ? <div className="mt-4 flex flex-wrap items-center gap-3">
      {selectedActivationEligible ? <button type="button" disabled={selected.active || role !== "admin" || activation === "saving"} onClick={() => void activate()} className="inline-flex min-h-10 items-center gap-2 rounded-lg bg-slate-950 px-3 py-2 text-sm font-semibold text-white disabled:cursor-not-allowed disabled:bg-slate-300"><Database size={15} />{selected.active ? "Current workspace dataset" : activation === "saving" ? "Selecting…" : "Use for workflow"}</button> : <span className="inline-flex min-h-10 items-center gap-2 rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-sm font-semibold text-slate-700"><LockKeyhole size={15} /> Read-only authority</span>}
      <span className="text-xs text-slate-500">{selectedActivationEligible ? "Inspection is transient. Workflow selection changes only when you press the button." : "This authority is available for inspection only and cannot change the workspace dataset."}</span>
    </div> : null}
    {message ? <p className={`mt-3 rounded-lg border px-3 py-2 text-xs font-semibold ${activation === "error" ? "border-amber-300 bg-amber-50 text-amber-950" : "border-cyan-200 bg-cyan-50 text-cyan-950"}`} role="status">{message}</p> : null}
  </Card>;
}

export function DataWarehouseEvidencePage() {
  const evidence = useSportsDatasetCatalog();
  const [selectedRegistrationId, setSelectedRegistrationId] = useState("");
  const [leagueFilter, setLeagueFilter] = useState<"ALL" | "MLB" | "NFL">("ALL");
  const filteredDatasets = evidence.status === "ready"
    ? evidence.data.filter((item) => leagueFilter === "ALL" || item.league.trim().toUpperCase() === leagueFilter)
    : [];
  const selected = evidence.status === "ready"
    ? filteredDatasets.find((item) => item.registrationId === selectedRegistrationId)
      ?? filteredDatasets.find((item) => item.active)
      ?? filteredDatasets[0]
    : null;
  useEffect(() => {
    if (selected && selected.registrationId !== selectedRegistrationId) setSelectedRegistrationId(selected.registrationId);
  }, [selected, selectedRegistrationId]);
  const status = selected ? selected.validationStatus : evidence.status === "loading" ? "Loading" : "Not registered";
  const summary = useMemo(() => selected ? `${selected.datasetId} · ${selected.registrationId}` : "", [selected]);
  return <Page status={status}>
    <div className="mb-4"><Gen3CatalogSection mode="warehouse" /></div>
    {evidence.status === "ready" ? <section className="mb-4 flex flex-wrap items-center justify-between gap-3 rounded-xl border border-slate-200 bg-white p-4" aria-label="Data Warehouse sport and league filters"><div><p className="text-sm font-semibold text-slate-950">Sport / league classification</p><p className="text-xs text-slate-500">Read-only filtering never changes a registration.</p></div><div className="flex gap-2">{(["ALL", "MLB", "NFL"] as const).map((filter) => <button key={filter} type="button" aria-pressed={leagueFilter === filter} onClick={() => setLeagueFilter(filter)} className={`rounded-lg border px-3 py-2 text-sm font-semibold ${leagueFilter === filter ? "border-cyan-500 bg-cyan-50 text-cyan-900" : "border-slate-200 text-slate-600"}`}>{filter === "ALL" ? "All Sports" : filter}</button>)}</div></section> : null}
    {evidence.status === "loading" ? <StateMessage kind="loading" title="Loading governed dataset evidence" detail="Reading the target-local registration service." /> : evidence.status === "error" ? <StateMessage kind="error" title="Dataset evidence unavailable" detail={evidence.error}><button type="button" onClick={evidence.refresh} className="mt-5 inline-flex items-center gap-2 rounded-lg border border-amber-300 bg-white px-3 py-2 text-sm font-semibold text-amber-950"><RefreshCw size={15} /> Retry</button></StateMessage> : evidence.status === "empty" ? <StateMessage kind="empty" title="No Sports Dataset Registered" detail="No governed sports manifest is registered in this workspace. No warehouse values are inferred or prefilled."><div className="mt-4 inline-flex rounded-lg border border-slate-200 bg-white px-3 py-2 font-mono text-xs font-semibold text-slate-700">SPORTS_DATASET_MANIFEST_V1</div><RegistrationAction onRegistered={evidence.refresh} /></StateMessage> : filteredDatasets.length === 0 ? <StateMessage kind="empty" title={`No ${leagueFilter} dataset registered`} detail="This filter has no governed dataset authority. No placeholder dataset is shown." /> : <><div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-950"><span className="flex items-center gap-2 font-semibold"><ShieldCheck size={17} /> Registered evidence is {selected?.validationStatus}</span><span className="break-all font-mono text-xs">{summary}</span></div><DatasetCatalogSelection datasets={filteredDatasets} selectedRegistrationId={selectedRegistrationId} onSelect={setSelectedRegistrationId} onRefresh={evidence.refresh} />{selected ? <DatasetDetails dataset={selected} /> : null}</>}
  </Page>;
}
