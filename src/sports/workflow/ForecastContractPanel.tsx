import { useMemo, useState } from "react";
import { CalendarRange, FlaskConical, ShieldCheck, Sparkles, TriangleAlert } from "lucide-react";
import type { SportsProjectMetadata } from "../sportsConfig";
import { FORECAST_LIFECYCLES, TARGETS_BY_WORKFLOW } from "../sportsConfig";
import {
  DEFAULT_TEMPORAL,
  DEFERRED_CHRONOLOGICAL_VALIDATION,
  GOVERNED_TEMPORAL,
  SEASON_ROLE_POLICY,
  governedDevelopmentSeasons,
  isCanonicalIsoDate,
  isEligibleDevelopmentStart,
  saveTemporalDraft,
  seasonRoleCoverageError,
  temporalDesignMode,
  validateCustomTemporalDesign,
  type ForecastContract,
  type ForecastContractCoverage,
  type ForecastDateRange,
  type TemporalDesignMode,
} from "./workflowState";
import type { ForecastContractLoadStatus } from "./useForecastContract";
import { sportsAuthorityPresentation, type SportsAuthorityErrorCode } from "./sportsAuthorityErrors";

const YEARS = [2019, 2020, 2021, 2022, 2023, 2024, 2025, 2026];
const DEV_START_CANDIDATES = [2021, 2022, 2023];
const SOURCE_TIMELINE = [2021, 2022, 2023, 2024, 2025, 2026];
const EMPTY_RANGE: ForecastDateRange = { startDate: "", endDate: "" };

type DateFieldKey =
  | "eligibleEvidenceStart"
  | "eligibleEvidenceEnd"
  | "developmentSelectionStart"
  | "developmentSelectionEnd"
  | "finalOotStart"
  | "finalOotEnd";

export function ForecastContractPanel({
  projectId,
  metadata,
  existing,
  coverage,
  authorityStatus,
  authorityError,
  authorityErrorCode,
  onRegister,
}: {
  projectId: string;
  metadata: SportsProjectMetadata | null;
  existing: ForecastContract | null;
  coverage: ForecastContractCoverage | null;
  authorityStatus: ForecastContractLoadStatus;
  authorityError: string | null;
  authorityErrorCode: SportsAuthorityErrorCode | null;
  onRegister: (contract: ForecastContract) => Promise<void>;
}) {
  const targets = TARGETS_BY_WORKFLOW["mlb-forecasting"];
  const [target, setTarget] = useState(existing?.target || metadata?.primaryTarget || "Plate-Appearance Outcome");
  const [lifecycle, setLifecycle] = useState(existing?.lifecycle || metadata?.lifecycle || "Pregame — Final");
  const [mode, setMode] = useState<TemporalDesignMode>(temporalDesignMode(existing));
  const govDev = governedDevelopmentSeasons(existing?.developmentSeasons ?? DEFAULT_TEMPORAL.developmentSeasons);
  const [devStart, setDevStart] = useState(govDev[0]);
  const [devEnd, setDevEnd] = useState(govDev[govDev.length - 1]);
  const [valSeason, setValSeason] = useState(existing?.validationSeason ?? DEFAULT_TEMPORAL.validationSeason);
  const [frozenSeason, setFrozenSeason] = useState(existing?.frozenSeason ?? DEFAULT_TEMPORAL.frozenSeason);
  const [prospective] = useState<number | null>(existing?.prospectiveSeason ?? DEFAULT_TEMPORAL.prospectiveSeason);
  const [eligibleEvidence, setEligibleEvidence] = useState<ForecastDateRange>(existing?.eligibleEvidence ?? EMPTY_RANGE);
  const [developmentSelection, setDevelopmentSelection] = useState<ForecastDateRange>(existing?.developmentSelection ?? EMPTY_RANGE);
  const [finalOot, setFinalOot] = useState<ForecastDateRange>(existing?.finalOot ?? EMPTY_RANGE);
  const [evidenceMode, setEvidenceMode] = useState<"STRICT" | "ENHANCED">(existing?.evidenceMode || "STRICT");
  const [purpose, setPurpose] = useState(existing?.researchPurpose || metadata?.researchPurpose || "");
  const [notes, setNotes] = useState(existing?.notes || metadata?.description || "");
  const [excludePriorFamilies, setExcludePriorFamilies] = useState(false);
  const [draftSaved, setDraftSaved] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);

  const devSeasons = YEARS.filter((year) => year >= devStart && year <= devEnd);
  const seasonCoverageError = seasonRoleCoverageError(devStart, frozenSeason, coverage);
  const seasonValid = devSeasons.length > 0 && devEnd < valSeason && valSeason < frozenSeason && seasonCoverageError === null;
  const isRevised = !isEligibleDevelopmentStart(devStart);
  const noPriorSeason = devStart <= 2021;
  const customValidation = useMemo(
    () => validateCustomTemporalDesign({ eligibleEvidence, developmentSelection, finalOot }, coverage),
    [coverage, developmentSelection, eligibleEvidence, finalOot],
  );
  const backendReady = authorityStatus === "ready";
  const registering = authorityStatus === "saving";
  const authorityFailure = authorityErrorCode ? sportsAuthorityPresentation(authorityErrorCode, authorityError || "") : null;

  const common = (): Omit<ForecastContract, "temporalDesignMode"> => ({
    projectId,
    version: existing?.version ?? 0,
    target,
    lifecycle,
    evidenceMode,
    intendedOutputs: metadata?.secondaryTargets?.length ? [metadata.primaryTarget, ...metadata.secondaryTargets] : [target],
    researchPurpose: purpose.trim(),
    notes: notes.trim(),
    savedAt: "",
  });

  const registerSeasonContract = async () => {
    if (!seasonValid || isRevised || !backendReady) return;
    setSaveError(null);
    try {
      await onRegister({
        ...common(),
        temporalDesignMode: "SEASON_ROLES",
        developmentSeasons: governedDevelopmentSeasons(devSeasons),
        validationSeason: valSeason,
        frozenSeason,
        prospectiveSeason: prospective,
        chronologicalValidation: DEFERRED_CHRONOLOGICAL_VALIDATION,
        coverageAuthority: coverage,
      });
    } catch (caught) {
      setSaveError(caught instanceof Error ? caught.message : "The forecast contract could not be registered.");
    }
  };

  const registerCustomContract = async () => {
    if (!customValidation.valid || !backendReady) return;
    setSaveError(null);
    try {
      await onRegister({
        ...common(),
        temporalDesignMode: "CUSTOM_DATES_ROLLING_ORIGIN",
        eligibleEvidence,
        developmentSelection,
        finalOot,
        chronologicalValidation: DEFERRED_CHRONOLOGICAL_VALIDATION,
        coverageAuthority: coverage,
      });
    } catch (caught) {
      setSaveError(caught instanceof Error ? caught.message : "The forecast contract could not be registered.");
    }
  };

  const saveRevised = () => {
    if (!seasonValid) return;
    saveTemporalDraft({
      projectId,
      developmentSeasons: devSeasons,
      validationSeason: valSeason,
      frozenSeason,
      excludePriorFamilies,
      rationale: purpose.trim() || notes.trim(),
      savedAt: new Date().toISOString(),
    });
    setDraftSaved(true);
  };

  const setDate = (field: DateFieldKey, value: string) => {
    const setters: Record<DateFieldKey, () => void> = {
      eligibleEvidenceStart: () => setEligibleEvidence((current) => ({ ...current, startDate: value })),
      eligibleEvidenceEnd: () => setEligibleEvidence((current) => ({ ...current, endDate: value })),
      developmentSelectionStart: () => setDevelopmentSelection((current) => ({ ...current, startDate: value })),
      developmentSelectionEnd: () => setDevelopmentSelection((current) => ({ ...current, endDate: value })),
      finalOotStart: () => setFinalOot((current) => ({ ...current, startDate: value })),
      finalOotEnd: () => setFinalOot((current) => ({ ...current, endDate: value })),
    };
    setters[field]();
  };

  return (
    <section className="sports-panel p-5 sm:p-6">
      <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-cyan-700"><Sparkles size={14} /> Prefilled from your project — review and formalize</div>

      {authorityStatus === "loading" ? <AuthorityNotice tone="slate">Loading the backend forecast-contract authority…</AuthorityNotice> : null}
      {authorityStatus === "error" && authorityFailure ? <AuthorityNotice tone="rose"><span data-authority-error-code={authorityErrorCode}><b>{authorityFailure.title}.</b> {authorityFailure.message}</span></AuthorityNotice> : null}
      {authorityError && authorityStatus !== "error" ? <AuthorityNotice tone="rose">{authorityFailure ? <span data-authority-error-code={authorityErrorCode}><b>{authorityFailure.title}.</b> {authorityFailure.message}</span> : authorityError}</AuthorityNotice> : null}

      <div className="mt-4 grid gap-4 md:grid-cols-2">
        <Field label="Forecast target"><select value={target} onChange={(event) => setTarget(event.target.value)} className="wf-input">{targets.map((item) => <option key={item}>{item}</option>)}</select></Field>
        <Field label="Forecast lifecycle"><select value={lifecycle} onChange={(event) => setLifecycle(event.target.value)} className="wf-input">{FORECAST_LIFECYCLES.map((item) => <option key={item}>{item}</option>)}</select></Field>
      </div>

      <fieldset className="mt-6">
        <legend className="text-sm font-semibold uppercase tracking-wide text-slate-900">Temporal design</legend>
        <div className="mt-2 grid gap-2 sm:grid-cols-2">
          <ModeChoice checked={mode === "SEASON_ROLES"} label="Season roles" onClick={() => setMode("SEASON_ROLES")} />
          <ModeChoice checked={mode === "CUSTOM_DATES_ROLLING_ORIGIN"} label="Custom dates / rolling-origin" onClick={() => setMode("CUSTOM_DATES_ROLLING_ORIGIN")} />
        </div>
      </fieldset>

      {mode === "SEASON_ROLES" ? (
        <SeasonRolesEditor
          devStart={devStart}
          devEnd={devEnd}
          valSeason={valSeason}
          frozenSeason={frozenSeason}
          devSeasons={devSeasons}
          isRevised={isRevised}
          noPriorSeason={noPriorSeason}
          seasonValid={seasonValid}
          excludePriorFamilies={excludePriorFamilies}
          draftSaved={draftSaved}
          coverageError={seasonCoverageError}
          setDevStart={setDevStart}
          setDevEnd={setDevEnd}
          setValSeason={setValSeason}
          setFrozenSeason={setFrozenSeason}
          setExcludePriorFamilies={setExcludePriorFamilies}
        />
      ) : (
        <div className="mt-5 space-y-4">
          <CoverageAuthority coverage={coverage} eligibleEvidence={eligibleEvidence} missingIntervals={customValidation.missingIntervals} />
          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
            <DateField label="Eligible evidence start" value={eligibleEvidence.startDate} onChange={(value) => setDate("eligibleEvidenceStart", value)} error={customValidation.fieldErrors.eligibleEvidenceStart} />
            <DateField label="Eligible evidence end" value={eligibleEvidence.endDate} onChange={(value) => setDate("eligibleEvidenceEnd", value)} error={customValidation.fieldErrors.eligibleEvidenceEnd} />
            <DateField label="Development and model-selection start" value={developmentSelection.startDate} onChange={(value) => setDate("developmentSelectionStart", value)} error={customValidation.fieldErrors.developmentSelectionStart} />
            <DateField label="Development and model-selection end" value={developmentSelection.endDate} onChange={(value) => setDate("developmentSelectionEnd", value)} error={customValidation.fieldErrors.developmentSelectionEnd} />
            <DateField label="Final OOT start" value={finalOot.startDate} onChange={(value) => setDate("finalOotStart", value)} error={customValidation.fieldErrors.finalOotStart} />
            <DateField label="Final OOT end" value={finalOot.endDate} onChange={(value) => setDate("finalOotEnd", value)} error={customValidation.fieldErrors.finalOotEnd} />
          </div>
          <CustomDateTimeline coverage={coverage} eligibleEvidence={eligibleEvidence} developmentSelection={developmentSelection} finalOot={finalOot} />
          {(customValidation.coverageMessage || customValidation.errors.length > 0) ? (
            <div role="alert" className="rounded-xl border border-rose-200 bg-rose-50 p-4 text-sm text-rose-900">
              {customValidation.coverageMessage ? <p className="font-semibold">{customValidation.coverageMessage}</p> : null}
              {customValidation.errors.length ? <ul className="mt-1 space-y-1">{customValidation.errors.map((error) => <li key={error}>· {error}</li>)}</ul> : null}
            </div>
          ) : null}
        </div>
      )}

      <div className="mt-5 rounded-xl border border-cyan-200 bg-cyan-50/60 p-4 text-sm text-slate-700">
        <div className="flex items-center gap-2 font-semibold text-cyan-900"><CalendarRange size={16} /> Chronological validation is required</div>
        <p className="mt-1">“Exact chronological fold boundaries, grouping, and preprocessing rules will be configured in Validation &amp; Calibration.”</p>
        <p className="mt-1 text-xs text-slate-600">That later stage supports five expanding-window folds using approximately balanced game counts or five manual validation date ranges. Stage 1 records only the broad boundary.</p>
      </div>

      <div className="mt-6">
        <div className="text-sm font-semibold text-slate-900">Evidence mode</div>
        <div className="mt-2 grid gap-2 sm:grid-cols-2">
          {(["STRICT", "ENHANCED"] as const).map((item) => (
            <button key={item} type="button" onClick={() => setEvidenceMode(item)} className={`rounded-xl border px-4 py-3 text-left text-sm ${evidenceMode === item ? "border-cyan-500 bg-cyan-50" : "border-slate-200 bg-white hover:border-slate-300"}`}>
              <div className="flex items-center gap-2 font-semibold text-slate-900"><ShieldCheck size={15} className={evidenceMode === item ? "text-cyan-600" : "text-slate-400"} /> {item === "ENHANCED" ? "Enhanced research" : "Strict pregame"}</div>
              <div className="mt-1 text-xs text-slate-500">{item === "ENHANCED" ? "May include research-only evidence with timing limitations and is not automatically deployment-safe." : "Only evidence proven available before first pitch."}</div>
            </button>
          ))}
        </div>
      </div>

      <div className="mt-6 grid gap-4">
        <Field label="Research purpose"><input value={purpose} onChange={(event) => setPurpose(event.target.value)} placeholder="Establish a leakage-safe game simulation baseline" className="wf-input" /></Field>
        <Field label="Notes"><textarea value={notes} onChange={(event) => setNotes(event.target.value)} rows={3} placeholder="Scope, decision context, known limitations." className="wf-input" /></Field>
      </div>

      {saveError ? <div role="alert" className="mt-4 rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-sm font-semibold text-rose-800">{saveError}</div> : null}

      {mode === "SEASON_ROLES" && isRevised ? (
        <button onClick={saveRevised} disabled={!seasonValid} className="sports-primary-button mt-6 disabled:cursor-not-allowed disabled:opacity-50"><FlaskConical size={16} /> Create revised temporal experiment</button>
      ) : (
        <button
          onClick={() => void (mode === "SEASON_ROLES" ? registerSeasonContract() : registerCustomContract())}
          disabled={registering || !backendReady || (mode === "SEASON_ROLES" ? !seasonValid : !customValidation.valid)}
          className="sports-primary-button mt-6 disabled:cursor-not-allowed disabled:opacity-50"
        >
          <ShieldCheck size={16} /> {registering ? "Registering…" : "Save & Register Forecast Contract"}
        </button>
      )}
    </section>
  );
}

function SeasonRolesEditor(props: {
  devStart: number; devEnd: number; valSeason: number; frozenSeason: number; devSeasons: number[];
  isRevised: boolean; noPriorSeason: boolean; seasonValid: boolean; excludePriorFamilies: boolean; draftSaved: boolean;
  coverageError: string | null;
  setDevStart: (value: number) => void; setDevEnd: (value: number) => void; setValSeason: (value: number) => void;
  setFrozenSeason: (value: number) => void; setExcludePriorFamilies: (value: boolean) => void;
}) {
  return (
    <div className="mt-5">
      <div className="flex flex-wrap items-center justify-between gap-2"><div className="text-sm font-semibold text-slate-900">Season-role policy</div><div className="text-[11px] font-semibold text-slate-500">Source evidence {GOVERNED_TEMPORAL.sourceEvidenceSeasons[0]}–{GOVERNED_TEMPORAL.sourceEvidenceSeasons.slice(-1)[0]}</div></div>
      <p className="mt-1 text-xs text-slate-500">Development trains, validation selects, and the frozen season is held out. <b>Every registered season exists</b>; earlier seasons carry another governed role.</p>
      <div className="mt-3 grid gap-3 sm:grid-cols-2">
        <div className="rounded-xl border border-slate-200 bg-slate-50 p-3"><div className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">Source evidence</div><div className="mt-0.5 text-lg font-semibold text-slate-900">2021–2025</div><div className="text-xs text-slate-500">all registered FD1 seasons</div></div>
        <div className="rounded-xl border border-cyan-200 bg-cyan-50/60 p-3"><div className="text-[11px] font-semibold uppercase tracking-wide text-cyan-700">Current Gen-2 model policy</div><div className="mt-0.5 text-sm font-semibold text-slate-900">Dev 2023 · Val 2024 · Frozen 2025</div><div className="text-xs text-slate-500">2021–2022 = prior-history evidence</div></div>
      </div>
      <div className="mt-3 grid gap-4 sm:grid-cols-4">
        <Field label="Development start"><select value={props.devStart} onChange={(event) => props.setDevStart(Number(event.target.value))} className="wf-input">{DEV_START_CANDIDATES.filter((year) => year <= props.devEnd).map((year) => <option key={year} value={year}>{year}{isEligibleDevelopmentStart(year) ? "" : " — not eligible"}</option>)}</select></Field>
        <Field label="Development end"><select value={props.devEnd} onChange={(event) => props.setDevEnd(Number(event.target.value))} className="wf-input">{YEARS.filter((year) => year >= props.devStart && year < props.valSeason && year <= 2023).map((year) => <option key={year}>{year}</option>)}</select></Field>
        <Field label="Validation"><select value={props.valSeason} onChange={(event) => props.setValSeason(Number(event.target.value))} className="wf-input">{YEARS.filter((year) => year > props.devEnd && year < props.frozenSeason).map((year) => <option key={year}>{year}</option>)}</select></Field>
        <Field label="Frozen final"><select value={props.frozenSeason} onChange={(event) => props.setFrozenSeason(Number(event.target.value))} className="wf-input">{YEARS.filter((year) => year > props.valSeason).map((year) => <option key={year}>{year}</option>)}</select></Field>
      </div>
      <SourceEvidenceTimeline devSeasons={props.devSeasons} valSeason={props.valSeason} frozenSeason={props.frozenSeason} isRevised={props.isRevised} />
      <div className="mt-3 rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs text-slate-600"><b>{props.devStart} — {SEASON_ROLE_POLICY[props.devStart]?.role}:</b> {SEASON_ROLE_POLICY[props.devStart]?.reason}</div>
      {props.isRevised ? (
        <div className="mt-3 rounded-xl border border-amber-300 bg-amber-50 p-4">
          <div className="flex items-center gap-2 text-sm font-semibold text-amber-900"><TriangleAlert size={15} /> Revised temporal experiment — research specification</div>
          <p className="mt-1 text-xs text-amber-900">A development start of <b>{props.devStart}</b> is <b>not part of the registered Gen-2 policy</b>. This research draft does not overwrite the governed season-role contract.</p>
          <p className="mt-1 rounded-md bg-white/70 px-2 py-1 text-[11px] text-amber-900"><b>Not yet executable in this cockpit:</b> the materialized modeling matrix contains 2023–2025 only, so this research draft cannot fabricate the missing modeling rows.</p>
          {props.noPriorSeason ? (
            <div className="mt-2 rounded-lg border border-amber-200 bg-white p-3 text-xs">
              <div className="font-semibold text-slate-900">2021 feasibility assessment</div>
              <ul className="mt-1 space-y-0.5 text-slate-600">
                <li>· Target rows available: <b className="text-emerald-700">YES</b></li>
                <li>· Y−1 player-state features: <b className="text-rose-700">NOT AVAILABLE</b> — no pre-2021 registered history</li>
              </ul>
              <label className="mt-2 flex items-center gap-2 font-semibold text-slate-700"><input type="checkbox" checked={props.excludePriorFamilies} onChange={(event) => props.setExcludePriorFamilies(event.target.checked)} className="h-4 w-4 rounded border-slate-300" /> Exclude prior-history feature families for this experiment</label>
              <p className="mt-1 text-[11px] text-slate-500">This tool records the intent; it does not fabricate the modeling rows.</p>
            </div>
          ) : null}
          {props.draftSaved ? <div className="mt-2 rounded-md bg-emerald-100 px-2 py-1 text-[11px] font-semibold text-emerald-800">Revised temporal experiment saved as a research draft — the registered Gen-2 contract is unchanged.</div> : null}
        </div>
      ) : null}
      {!props.seasonValid && !props.coverageError ? <p className="mt-2 text-xs font-semibold text-amber-700">Development must end before validation, and validation before the frozen season.</p> : null}
      {props.coverageError ? <p role="alert" className="mt-2 text-xs font-semibold text-rose-700">{props.coverageError}</p> : null}
    </div>
  );
}

function CoverageAuthority({ coverage, eligibleEvidence, missingIntervals }: { coverage: ForecastContractCoverage | null; eligibleEvidence: ForecastDateRange; missingIntervals: ForecastDateRange[] }) {
  return (
    <div className="rounded-xl border border-slate-200 bg-slate-50 p-4">
      <div className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">Registered Data Warehouse coverage</div>
      <dl className="mt-2 grid gap-2 text-sm sm:grid-cols-2 lg:grid-cols-4">
        <div><dt className="text-xs text-slate-500">Earliest registered evidence</dt><dd className="font-semibold text-slate-900">{coverage?.earliestDate || "Unavailable"}</dd></div>
        <div><dt className="text-xs text-slate-500">Latest registered evidence</dt><dd className="font-semibold text-slate-900">{coverage?.latestDate || "Unavailable"}</dd></div>
        <div><dt className="text-xs text-slate-500">Requested date range</dt><dd className="font-semibold text-slate-900">{eligibleEvidence.startDate || "—"} through {eligibleEvidence.endDate || "—"}</dd></div>
        <div><dt className="text-xs text-slate-500">Missing interval</dt><dd className={`font-semibold ${missingIntervals.length ? "text-rose-700" : "text-emerald-700"}`}>{missingIntervals.length ? missingIntervals.map((item) => `${item.startDate} through ${item.endDate}`).join("; ") : "None"}</dd></div>
      </dl>
      {coverage ? <details className="mt-2 text-xs text-slate-500"><summary className="cursor-pointer font-semibold">Coverage authority</summary><div className="mt-1 break-all font-mono">{coverage.datasetVersionId} · manifest {coverage.manifestSha} · registration {coverage.registrationId}</div></details> : null}
    </div>
  );
}

function CustomDateTimeline({ coverage, eligibleEvidence, developmentSelection, finalOot }: { coverage: ForecastContractCoverage | null; eligibleEvidence: ForecastDateRange; developmentSelection: ForecastDateRange; finalOot: ForecastDateRange }) {
  const toDay = (value: string) => Date.parse(`${value}T00:00:00Z`) / 86_400_000;
  const complete = [eligibleEvidence.startDate, eligibleEvidence.endDate, developmentSelection.startDate, developmentSelection.endDate, finalOot.startDate, finalOot.endDate].every(isCanonicalIsoDate);
  if (!complete || eligibleEvidence.startDate > eligibleEvidence.endDate) return <div className="rounded-xl border border-dashed border-slate-300 bg-white p-4 text-sm text-slate-500">Enter all six dates to draw the actual interval timeline.</div>;
  const start = toDay(eligibleEvidence.startDate);
  const span = Math.max(1, toDay(eligibleEvidence.endDate) - start + 1);
  const styleFor = (range: ForecastDateRange) => ({ left: `${Math.max(0, Math.min(100, ((toDay(range.startDate) - start) / span) * 100))}%`, width: `${Math.max(1.5, Math.min(100, ((toDay(range.endDate) - toDay(range.startDate) + 1) / span) * 100))}%` });
  const priorEnd = new Date(Date.parse(`${eligibleEvidence.startDate}T00:00:00Z`) - 86_400_000).toISOString().slice(0, 10);
  const prior = coverage && coverage.earliestDate < eligibleEvidence.startDate ? `${coverage.earliestDate} through ${priorEnd}` : null;
  return (
    <div className="rounded-xl border border-slate-200 bg-white p-4" aria-label="Custom temporal design timeline">
      <div className="flex items-center justify-between gap-3 text-xs font-semibold text-slate-600"><span>{eligibleEvidence.startDate}</span><span>Eligible evidence</span><span>{eligibleEvidence.endDate}</span></div>
      <div className="relative mt-3 h-14 overflow-hidden rounded-lg bg-slate-100"><div className="absolute inset-x-0 top-2 h-4 rounded bg-cyan-200" /><div className="absolute top-2 h-4 rounded bg-emerald-500" style={styleFor(developmentSelection)} title={`Development and selection ${developmentSelection.startDate} through ${developmentSelection.endDate}`} /><div className="absolute bottom-2 h-4 rounded bg-rose-500" style={styleFor(finalOot)} title={`Final OOT ${finalOot.startDate} through ${finalOot.endDate}`} /></div>
      <div className="mt-2 flex flex-wrap gap-3 text-[11px] font-semibold"><span className="text-emerald-700">Development/selection {developmentSelection.startDate}–{developmentSelection.endDate}</span><span className="text-rose-700">Final OOT {finalOot.startDate}–{finalOot.endDate}</span></div>
      {prior ? <div className="mt-2 text-xs text-slate-500">Earlier registered evidence, derived from the selected boundary: {prior}.</div> : null}
    </div>
  );
}

function SourceEvidenceTimeline({ devSeasons, valSeason, frozenSeason, isRevised }: { devSeasons: number[]; valSeason: number; frozenSeason: number; isRevised: boolean }) {
  const roleOf = (year: number) => {
    if (isRevised && devSeasons.includes(year)) return { label: "DEV?", cls: "bg-violet-500 ring-2 ring-violet-300", textCls: "text-violet-600" };
    if (!isRevised && devSeasons.includes(year)) return { label: "DEV", cls: "bg-emerald-500", textCls: "text-emerald-600" };
    if (year === valSeason) return { label: "VAL", cls: "bg-amber-500", textCls: "text-amber-600" };
    if (year === frozenSeason) return { label: "FROZEN", cls: "bg-rose-500 ring-2 ring-rose-300", textCls: "text-rose-600" };
    if (SEASON_ROLE_POLICY[year]?.role === "PRIOR HISTORY") return { label: "PRIOR", cls: "bg-slate-400", textCls: "text-slate-500" };
    return { label: "FUTURE", cls: "bg-slate-300", textCls: "text-slate-400" };
  };
  return <div className="mt-4"><div className="flex gap-1">{SOURCE_TIMELINE.map((year) => { const role = roleOf(year); return <div key={year} className="flex-1 text-center"><div className={`flex h-8 items-center justify-center rounded text-xs font-bold text-white ${role.cls}`}>{year}</div><div className={`mt-1 text-[10px] font-semibold uppercase ${role.textCls}`}>{role.label}</div></div>; })}</div><div className="mt-2 flex flex-wrap gap-2"><span className="inline-flex items-center gap-1.5 rounded-md border border-rose-200 bg-rose-50 px-2 py-1 text-[11px] font-semibold text-rose-700"><ShieldCheck size={12} /> {frozenSeason} FROZEN — never used for model selection</span></div></div>;
}

function ModeChoice({ checked, label, onClick }: { checked: boolean; label: string; onClick: () => void }) {
  return <label className={`flex cursor-pointer items-center gap-3 rounded-xl border p-3 text-sm font-semibold ${checked ? "border-cyan-500 bg-cyan-50 text-cyan-950" : "border-slate-200 bg-white text-slate-700"}`}><input type="radio" name="temporal-design" checked={checked} onChange={onClick} className="h-4 w-4" />{label}</label>;
}

function DateField({ label, value, onChange, error }: { label: string; value: string; onChange: (value: string) => void; error?: string }) {
  return <label className="flex flex-col gap-1.5"><span className="text-xs font-semibold uppercase tracking-wide text-slate-500">{label}</span><input type="date" value={value} onInput={(event) => onChange(event.currentTarget.value)} className={`wf-input ${error ? "border-rose-400" : ""}`} />{error ? <span className="text-xs font-semibold text-rose-700">{error}</span> : null}</label>;
}

function AuthorityNotice({ children, tone }: { children: React.ReactNode; tone: "slate" | "rose" }) {
  return <div className={`mt-4 rounded-lg border px-3 py-2 text-sm ${tone === "rose" ? "border-rose-200 bg-rose-50 text-rose-800" : "border-slate-200 bg-slate-50 text-slate-600"}`}>{children}</div>;
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return <label className="flex flex-col gap-1.5"><span className="text-xs font-semibold uppercase tracking-wide text-slate-500">{label}</span>{children}</label>;
}
