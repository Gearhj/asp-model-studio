import { Database, ListTree, RefreshCw, ShieldCheck, Table2, TriangleAlert } from "lucide-react";
import type { CurrentGoldDataReview, CurrentGoldReviewState, Stage2Check, Stage2Column } from "./currentGoldDataReview";

const ROLE_STYLE: Record<Stage2Column["classification"], string> = {
  IDENTIFIER: "border-amber-200 bg-amber-50 text-amber-800",
  GROUPING: "border-violet-200 bg-violet-50 text-violet-800",
  TIME: "border-cyan-200 bg-cyan-50 text-cyan-800",
  TARGET: "border-rose-200 bg-rose-50 text-rose-800",
  PREGAME_FEATURE: "border-emerald-200 bg-emerald-50 text-emerald-800",
  SIMULATION_GENERATED_STATE: "border-blue-200 bg-blue-50 text-blue-800",
  MISSINGNESS_INDICATOR: "border-fuchsia-200 bg-fuchsia-50 text-fuchsia-800",
  RESEARCH_ONLY: "border-slate-300 bg-slate-100 text-slate-700",
  EXCLUDED: "border-slate-200 bg-white text-slate-500",
};

function int(value: number) {
  return Math.round(value).toLocaleString();
}

function pct(value: number) {
  return `${(value * 100).toFixed(2)}%`;
}

function shortSha(value: string) {
  return value ? `${value.slice(0, 12)}…${value.slice(-8)}` : "—";
}

function StatusBadge({ check }: { check: Stage2Check }) {
  const pass = check.status === "PASS" || check.status === "PASS_WITH_CONDITIONS";
  return <span className={`inline-flex rounded-full border px-2 py-0.5 text-[10px] font-semibold ${pass ? "border-emerald-200 bg-emerald-50 text-emerald-800" : "border-amber-200 bg-amber-50 text-amber-900"}`}>{check.status.replaceAll("_", " ")}</span>;
}

function RoleBadge({ role }: { role: Stage2Column["classification"] }) {
  return <span className={`inline-flex rounded-full border px-2 py-0.5 text-[10px] font-semibold ${ROLE_STYLE[role]}`}>{role}</span>;
}

function Metric({ label, value, detail }: { label: string; value: string; detail?: string }) {
  return <div className="rounded-xl border border-slate-200 bg-white p-3"><div className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">{label}</div><div className="mt-1 text-lg font-semibold tabular-nums text-slate-950">{value}</div>{detail ? <div className="mt-0.5 text-[11px] text-slate-500">{detail}</div> : null}</div>;
}

function Authority({ review }: { review: CurrentGoldDataReview }) {
  return (
    <section className="rounded-2xl border border-cyan-200 bg-cyan-50/60 p-5" data-testid="stage2-current-gold-authority">
      <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.14em] text-cyan-800"><Database size={15} /> Project-linked materialization authority</div>
      <div className="mt-3 grid gap-3 lg:grid-cols-2">
        <div className="rounded-xl border border-cyan-200 bg-white p-4">
          <div className="text-xs font-semibold uppercase text-slate-500">Registered source evidence</div>
          <div className="mt-1 font-semibold text-slate-950">{review.sourceAuthority.datasetId}</div>
          <dl className="mt-2 grid gap-1 text-xs text-slate-600">
            <div><b>Registration:</b> {review.sourceAuthority.registrationId}</div>
            <div className="break-all"><b>Version:</b> {review.sourceAuthority.datasetVersionId}</div>
            <div><b>Manifest:</b> <span className="font-mono">{shortSha(review.sourceAuthority.manifestSha)}</span></div>
            <div><b>Evidence:</b> {review.sourceAuthority.dateCoverage.earliestDate} through {review.sourceAuthority.dateCoverage.latestDate} · {int(review.sourceAuthority.rowCount)} accepted source PAs</div>
          </dl>
        </div>
        <div className="rounded-xl border border-emerald-200 bg-white p-4">
          <div className="text-xs font-semibold uppercase text-slate-500">Materialized current Gold</div>
          <div className="mt-1 font-semibold text-slate-950">{review.goldAuthority.datasetId}</div>
          <dl className="mt-2 grid gap-1 text-xs text-slate-600">
            <div><b>Contract:</b> {review.goldAuthority.manifestContract} v{review.goldAuthority.manifestVersion}</div>
            <div><b>Manifest:</b> <span className="font-mono">{shortSha(review.goldAuthority.manifestSha)}</span></div>
            <div><b>Source binding:</b> <span className="font-mono">{shortSha(review.goldAuthority.sourceSilverManifestSha)}</span></div>
            <div><b>Verification:</b> {review.goldAuthority.verified ? "content address and all four partitions verified" : "not verified"}</div>
          </dl>
        </div>
      </div>
      <p className="mt-3 text-xs text-cyan-900">The registered source contains accepted PA evidence; the smaller Gold row count is the exact identity-matched, feature-materialized modeling population. They are related by the same immutable Silver publication SHA, not by workspace-active state.</p>
    </section>
  );
}

function GateReview({ review }: { review: CurrentGoldDataReview }) {
  return (
    <section className="rounded-2xl border border-slate-200 bg-white p-5" data-testid="stage2-quality-gates">
      <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.14em] text-cyan-700"><ShieldCheck size={15} /> Point-in-time, identity, and leakage review</div>
      <div className="mt-3 grid gap-2 sm:grid-cols-2 xl:grid-cols-3">
        {review.checks.map((check) => <div key={check.code} className="rounded-xl border border-slate-200 bg-slate-50 p-3"><div className="flex items-start justify-between gap-2"><div className="text-xs font-semibold text-slate-800">{check.code.replaceAll("_", " ")}</div><StatusBadge check={check} /></div><p className="mt-1 text-xs leading-5 text-slate-600">{check.detail}</p></div>)}
      </div>
      <div className="mt-3 grid gap-2 sm:grid-cols-2 xl:grid-cols-4" aria-label="Exact identity diagnostics">
        <Metric label="Duplicate PA IDs" value={int(review.identity.duplicateCanonicalPaIdentities + review.identity.duplicatePlateAppearanceIdentities)} detail="canonical + public keys" />
        <Metric label="Unresolved players" value={int(review.identity.unresolvedPlayerIdentities)} detail={`${int(review.identity.matchedExactPlayerCount)} exact players`} />
        <Metric label="Ambiguous players" value={int(review.identity.ambiguousPlayerIdentities)} detail="exact authority conflicts" />
        <Metric label="Game identity issues" value={int(review.identity.unresolvedGameIdentities + review.identity.ambiguousGameIdentities)} detail="non-null, one-to-one included mappings" />
      </div>
      <p className="mt-2 text-xs text-slate-500">Historical canonical/public alias strings differ on {int(review.identity.paAliasValueDifferences)} PA rows and {int(review.identity.gameAliasValueDifferences)} game rows; each key remains unique and every included game mapping is one-to-one, so alias rendering differences are not unresolved identities.</p>
      <div className={`mt-3 rounded-xl border px-4 py-3 text-sm ${review.acceptance.allowed ? "border-emerald-200 bg-emerald-50 text-emerald-900" : "border-amber-200 bg-amber-50 text-amber-950"}`}>
        <b>{review.acceptance.allowed ? "Acceptance gate satisfied." : "Acceptance remains blocked."}</b>
        {review.acceptance.blockers.length ? <ul className="mt-1 list-disc pl-5 text-xs">{review.acceptance.blockers.map((item) => <li key={item}>{item}</li>)}</ul> : <span> The materialized matrix matches the project-linked authority and every blocking review is resolved.</span>}
      </div>
    </section>
  );
}

function MatrixContract({ review }: { review: CurrentGoldDataReview }) {
  const sim = review.matrix.columns.filter((item) => item.classification === "SIMULATION_GENERATED_STATE");
  return (
    <section className="rounded-2xl border border-slate-200 bg-white p-5" data-testid="stage2-current-gold-matrix">
      <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.14em] text-cyan-700"><ListTree size={15} /> Current Gold matrix contract</div>
      <div className="mt-3 grid gap-3 sm:grid-cols-2 lg:grid-cols-4 xl:grid-cols-6">
        <Metric label="Gold rows" value={int(review.goldAuthority.rowCount)} detail="materialized PA rows" />
        <Metric label="Predictors" value={int(review.matrix.predictorCount)} detail={`${review.matrix.totalColumns} total authority columns`} />
        <Metric label="Seasons" value={review.matrix.seasons.join(", ")} detail="required 2023–2026" />
        <Metric label="Development" value={int(review.matrix.development.rows)} detail={`${review.matrix.development.startDate}–${review.matrix.development.endDate}`} />
        <Metric label="Final OOT" value={int(review.matrix.finalOot.rows)} detail={`${review.matrix.finalOot.startDate}–${review.matrix.finalOot.endDate}`} />
        <Metric label="Target" value={`${review.targetTaxonomy.classOrder.length}-class PA`} detail={review.targetTaxonomy.column} />
      </div>

      <div className="mt-4 rounded-xl border border-blue-200 bg-blue-50 p-4">
        <div className="text-xs font-semibold uppercase tracking-wide text-blue-800">Conditional PA simulation state</div>
        <p className="mt-1 text-sm leading-6 text-blue-950">These five predictors may train the conditional PA model, but forecast-time values must be generated by the simulator. Future actual game state is prohibited.</p>
        <div className="mt-2 flex flex-wrap gap-1.5">{sim.map((item) => <span key={item.name} className="rounded-md border border-blue-200 bg-white px-2 py-1 font-mono text-[11px] text-blue-900">{item.name}</span>)}</div>
      </div>

      <details className="mt-4 rounded-xl border border-slate-200 bg-slate-50 px-4 py-3" open>
        <summary className="cursor-pointer text-sm font-semibold text-slate-800">Exact ordered 48 predictors</summary>
        <ol className="mt-3 grid gap-1.5 sm:grid-cols-2 xl:grid-cols-3">{review.matrix.orderedPredictors.map((name, index) => {
          const column = review.matrix.columns.find((item) => item.name === name)!;
          return <li key={name} className="flex items-center gap-2 rounded-lg border border-slate-200 bg-white px-2.5 py-2 text-xs"><span className="w-6 shrink-0 text-right font-mono text-slate-400">{index + 1}</span><span className="min-w-0 flex-1 break-all font-mono text-slate-800">{name}</span><RoleBadge role={column.classification} /></li>;
        })}</ol>
      </details>

      <details className="mt-3 rounded-xl border border-slate-200 bg-slate-50 px-4 py-3">
        <summary className="cursor-pointer text-sm font-semibold text-slate-800">All {review.matrix.totalColumns} column roles</summary>
        <div className="mt-3 max-h-96 overflow-auto"><table className="w-full min-w-[720px] text-left text-xs"><thead className="sticky top-0 bg-slate-100"><tr>{["Column", "Type", "Role", "Predictor order"].map((item) => <th key={item} className="border-b border-slate-200 px-2 py-2 text-slate-500">{item}</th>)}</tr></thead><tbody>{review.matrix.columns.map((column) => <tr key={column.name}><td className="border-b border-slate-100 px-2 py-2 font-mono text-slate-800">{column.name}</td><td className="border-b border-slate-100 px-2 py-2 text-slate-500">{column.dtype}{column.nullable ? " · nullable" : ""}</td><td className="border-b border-slate-100 px-2 py-2"><RoleBadge role={column.classification} /></td><td className="border-b border-slate-100 px-2 py-2 tabular-nums text-slate-600">{column.predictorOrder ?? "—"}</td></tr>)}</tbody></table></div>
      </details>
    </section>
  );
}

function MissingnessReview({ review }: { review: CurrentGoldDataReview }) {
  return (
    <section className="rounded-2xl border border-slate-200 bg-white p-5" data-testid="stage2-missingness-review">
      <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.14em] text-cyan-700"><TriangleAlert size={15} /> Predictor missingness diagnostics</div>
      <p className="mt-2 text-sm text-slate-600">{review.missingness.note}</p>
      <div className="mt-3 max-h-[620px] overflow-auto rounded-xl border border-slate-200">
        <table className="w-full min-w-[1180px] text-left text-xs">
          <thead className="sticky top-0 z-10 bg-slate-50"><tr>{["#", "Predictor", "Role", "Overall", "Development", "Final OOT", "Indicator prevalence", "Affected rows", "Players", "Reason", "Season / month"].map((item) => <th key={item} className="border-b border-slate-200 px-2 py-2 font-semibold text-slate-500">{item}</th>)}</tr></thead>
          <tbody>{review.missingness.predictors.map((item) => <tr key={item.feature} className="align-top"><td className="border-b border-slate-100 px-2 py-2 text-slate-400">{item.order}</td><td className="border-b border-slate-100 px-2 py-2 font-mono font-semibold text-slate-800">{item.feature}</td><td className="border-b border-slate-100 px-2 py-2"><RoleBadge role={item.classification} /></td><td className="border-b border-slate-100 px-2 py-2 tabular-nums">{pct(item.overallMissingPct)}<div className="text-[10px] text-slate-400">{int(item.missingRows)} null</div></td><td className="border-b border-slate-100 px-2 py-2 tabular-nums">{pct(item.developmentMissingPct)}</td><td className="border-b border-slate-100 px-2 py-2 tabular-nums">{pct(item.finalOotMissingPct)}</td><td className="border-b border-slate-100 px-2 py-2 tabular-nums">{pct(item.indicatorPrevalence)}<div className="max-w-44 break-all text-[10px] text-slate-400">{item.indicatorField || "no paired indicator"}</div></td><td className="border-b border-slate-100 px-2 py-2 tabular-nums">{int(item.affectedRows)}</td><td className="border-b border-slate-100 px-2 py-2 tabular-nums">{int(item.affectedPlayerCount)}</td><td className="border-b border-slate-100 px-2 py-2"><div className="font-semibold text-slate-700">{item.primaryReasonCategory || "NONE"}</div><div className="text-[10px] text-slate-400">{item.reasonCounts.map((reason) => `${reason.category} ${int(reason.rows)}`).join(" · ") || "No missing condition"}</div></td><td className="border-b border-slate-100 px-2 py-2"><details><summary className="cursor-pointer font-semibold text-cyan-700">View detail</summary><div className="mt-1 max-w-64 text-[10px] leading-4 text-slate-500"><b>Season:</b> {item.bySeason.map((row) => `${row.season} ${pct(row.missingPct)}`).join(" · ")}<br /><b>Month:</b> {item.byMonth.map((row) => `${row.month} ${pct(row.missingPct)}`).join(" · ")}</div></details></td></tr>)}</tbody>
        </table>
      </div>
    </section>
  );
}

function TargetAndTreatment({ review }: { review: CurrentGoldDataReview }) {
  const overall = review.targetTaxonomy.distributions.overall || [];
  const treatment = review.modelingTreatment;
  return (
    <section className="grid gap-4 xl:grid-cols-2">
      <div className="rounded-2xl border border-slate-200 bg-white p-5"><div className="text-xs font-semibold uppercase tracking-[0.14em] text-cyan-700">Exact target taxonomy</div><div className="mt-3 grid gap-2 sm:grid-cols-2">{review.targetTaxonomy.classOrder.map((name, index) => { const row = overall.find((item) => item.class === name); return <div key={name} className="flex items-center justify-between rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-sm"><span><span className="mr-2 font-mono text-xs text-slate-400">{index + 1}</span><b>{name}</b></span><span className="tabular-nums text-slate-600">{int(row?.rows || 0)}</span></div>; })}</div></div>
      <div className="rounded-2xl border border-slate-200 bg-white p-5"><div className="text-xs font-semibold uppercase tracking-[0.14em] text-cyan-700">Modeling treatment — defined, not performed</div><dl className="mt-3 grid gap-2 text-sm"><Treatment label="Cold-start rows" value={treatment.coldStartRows} /><Treatment label="Imputation / priors" value={treatment.imputation} /><Treatment label="Missing and insufficient flags" value={treatment.missingFlags} /><Treatment label="Global imputation" value={treatment.globalImputation} /><Treatment label="Validation / OOT preprocessing" value={treatment.validationOrOotPreprocessing} /><Treatment label="Forecast-time game state" value={treatment.simulationStateForecastRule} /></dl></div>
    </section>
  );
}

function Treatment({ label, value }: { label: string; value: string }) {
  return <div className="grid gap-1 rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 sm:grid-cols-[190px_1fr]"><dt className="font-semibold text-slate-700">{label}</dt><dd className="font-mono text-xs text-slate-600">{value}</dd></div>;
}

function Preview({ review }: { review: CurrentGoldDataReview }) {
  const preview = review.preview;
  return <section className="rounded-2xl border border-slate-200 bg-white p-5"><div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.14em] text-cyan-700"><Table2 size={15} /> Verified current Gold row preview</div><div className="mt-3 max-h-96 overflow-auto rounded-xl border border-slate-200"><table className="w-full min-w-[1200px] text-left text-xs"><thead className="sticky top-0 bg-slate-50"><tr>{preview.columns.map((name) => <th key={name} className="border-b border-slate-200 px-2 py-2 font-semibold text-slate-600">{name}</th>)}</tr></thead><tbody>{preview.rows.map((row, index) => <tr key={index}>{preview.columns.map((name) => <td key={name} className="whitespace-nowrap border-b border-slate-100 px-2 py-2 text-slate-600">{row[name] == null ? <span className="text-slate-300">null</span> : String(row[name])}</td>)}</tr>)}</tbody></table></div><p className="mt-2 text-xs text-slate-500">Bounded to {preview.limit} existing verified rows. No source data was rebuilt and no model was fit or scored.</p></section>;
}

export function CurrentGoldDataReviewPanel({ state }: { state: CurrentGoldReviewState }) {
  if (state.status === "loading" || state.status === "idle") return <section className="rounded-2xl border border-slate-200 bg-white p-6" role="status"><div className="flex items-center gap-3 text-sm text-slate-600"><span className="h-4 w-4 animate-spin rounded-full border-2 border-slate-300 border-t-cyan-600" /> Verifying the project-linked current Gold matrix and its quality evidence…</div></section>;
  if (state.status === "error" || !state.review) return <section className="rounded-2xl border border-rose-200 bg-rose-50 p-6" role="alert"><div className="flex items-center gap-2 font-semibold text-rose-900"><TriangleAlert size={18} /> Current Gold review unavailable</div><p className="mt-1 text-sm text-rose-800">{state.error || "The exact project-linked matrix could not be verified."}</p><button type="button" onClick={() => void state.refresh()} className="mt-3 inline-flex items-center gap-1.5 rounded-lg border border-rose-300 bg-white px-3 py-2 text-sm font-semibold text-rose-800"><RefreshCw size={14} /> Retry</button></section>;
  const review = state.review;
  return <div className="space-y-4"><Authority review={review} /><MatrixContract review={review} /><GateReview review={review} /><TargetAndTreatment review={review} /><MissingnessReview review={review} /><Preview review={review} /></div>;
}
