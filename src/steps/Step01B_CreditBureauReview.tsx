import { useMemo, useState } from "react";
import StepShell from "../components/StepShell";
import {
  detectBureauSpecialValues,
  loadBureauMetadata,
  loadBureauTreatmentDecisions,
  parseBureauMetadataCsv,
  saveBureauMetadata,
  saveBureauTreatmentDecision,
  treatmentLabels,
  type BureauSpecialValueProfile,
  type BureauTreatment,
} from "../lib/creditBureau";

const treatmentOptions = Object.entries(treatmentLabels) as [BureauTreatment, string][];

function formatPercent(value: number | null) {
  return typeof value === "number" && Number.isFinite(value) ? `${(value * 100).toFixed(2)}%` : "-";
}

function formatNumber(value: number | null) {
  return typeof value === "number" && Number.isFinite(value) ? value.toFixed(4) : "-";
}

export default function Step01BCreditBureauReview() {
  const [version, setVersion] = useState(0);
  const [metadataRows, setMetadataRows] = useState(() => loadBureauMetadata());
  const [decisions, setDecisions] = useState(() => loadBureauTreatmentDecisions());
  const [drafts, setDrafts] = useState<Record<string, { treatment: BureauTreatment; rationale: string }>>({});
  const profiles = useMemo(() => detectBureauSpecialValues(), [version]);
  const decisionMap = useMemo(
    () => new Map(decisions.map((decision) => [`${decision.variableName}::${decision.value}`, decision])),
    [decisions]
  );

  const handleMetadataUpload = async (file: File | undefined) => {
    if (!file) return;
    const text = await file.text();
    const rows = parseBureauMetadataCsv(text);
    saveBureauMetadata(rows);
    setMetadataRows(rows);
    setVersion((current) => current + 1);
  };

  const draftFor = (profile: BureauSpecialValueProfile) => {
    const key = `${profile.variableName}::${profile.value}`;
    const decision = decisionMap.get(key);
    return drafts[key] ?? { treatment: decision?.treatment ?? profile.recommendedTreatment, rationale: decision?.rationale ?? "" };
  };

  const updateDraft = (profile: BureauSpecialValueProfile, patch: Partial<{ treatment: BureauTreatment; rationale: string }>) => {
    const key = `${profile.variableName}::${profile.value}`;
    setDrafts((current) => ({
      ...current,
      [key]: { ...draftFor(profile), ...patch },
    }));
  };

  const saveDecision = (profile: BureauSpecialValueProfile) => {
    const draft = draftFor(profile);
    const next = saveBureauTreatmentDecision(profile, draft.treatment, draft.rationale);
    setDecisions(next);
  };

  return (
    <StepShell
      title="Step 1B: Credit Bureau Data Review"
      subtitle="Detect bureau special values, profile target behavior, select treatments, and document rationale before missing-value or outlier handling."
      nextPath="/step02"
    >
      <div className="space-y-5">
        <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
          <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
            <div>
              <h2 className="text-base font-semibold text-slate-950">Bureau Metadata</h2>
              <p className="mt-1 max-w-3xl text-sm text-slate-600">
                Upload optional metadata with columns such as variable name, bureau source, description, valid numeric
                range, special value definitions, variable family, regulatory sensitivity, and allowed for modeling.
              </p>
            </div>
            <label className="inline-flex cursor-pointer items-center rounded-lg bg-slate-950 px-3 py-2 text-sm font-semibold text-white shadow-sm hover:bg-slate-800">
              Upload Metadata CSV
              <input className="hidden" type="file" accept=".csv,text/csv" onChange={(event) => handleMetadataUpload(event.target.files?.[0])} />
            </label>
          </div>
          <div className="mt-4 grid gap-3 md:grid-cols-3">
            <Stat label="Metadata Rows" value={metadataRows.length} />
            <Stat label="Bureau Variables Detected" value={new Set(profiles.map((profile) => profile.variableName)).size} />
            <Stat label="Special Values Detected" value={profiles.length} />
          </div>
        </section>

        <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
          <h2 className="text-base font-semibold text-slate-950">Special Value Profiling</h2>
          <p className="mt-1 text-sm text-slate-600">
            Special bureau values are profiled separately from ordinary missing values and numeric outliers.
          </p>

          <div className="mt-4 overflow-auto rounded-lg border border-slate-200">
            <table className="min-w-[1500px] w-full text-sm">
              <thead className="bg-slate-50 text-left text-xs uppercase tracking-wide text-slate-500">
                <tr>
                  <th className="px-3 py-2">Variable</th>
                  <th className="px-3 py-2">Value</th>
                  <th className="px-3 py-2">Definition</th>
                  <th className="px-3 py-2">Count</th>
                  <th className="px-3 py-2">Percent</th>
                  <th className="px-3 py-2">Special Event Rate</th>
                  <th className="px-3 py-2">Regular Event Rate</th>
                  <th className="px-3 py-2">Recommendation</th>
                  <th className="px-3 py-2">Selected Treatment</th>
                  <th className="px-3 py-2">Rationale</th>
                  <th className="px-3 py-2">Action</th>
                </tr>
              </thead>
              <tbody>
                {profiles.map((profile) => {
                  const draft = draftFor(profile);
                  const needsRationale = draft.treatment !== profile.recommendedTreatment || profile.percent >= 0.3;
                  return (
                    <tr key={`${profile.variableName}-${profile.value}`} className="border-t align-top">
                      <td className="px-3 py-2 font-semibold text-slate-900">{profile.variableName}</td>
                      <td className="px-3 py-2 font-mono">{profile.value}</td>
                      <td className="px-3 py-2">
                        <div className="font-medium text-slate-800">{profile.label}</div>
                        <div className="text-xs text-slate-500">{profile.group}</div>
                        {profile.warning && <div className="mt-1 rounded bg-amber-50 px-2 py-1 text-xs text-amber-900">{profile.warning}</div>}
                      </td>
                      <td className="px-3 py-2">{profile.count.toLocaleString()}</td>
                      <td className="px-3 py-2">{formatPercent(profile.percent)}</td>
                      <td className="px-3 py-2">{formatPercent(profile.eventRate)}</td>
                      <td className="px-3 py-2">{formatPercent(profile.regularEventRate)}</td>
                      <td className="px-3 py-2">
                        <div className="font-semibold text-slate-800">{treatmentLabels[profile.recommendedTreatment]}</div>
                        <div className="mt-1 text-xs leading-5 text-slate-500">{profile.recommendationReason}</div>
                        <div className="mt-1 text-xs text-slate-500">
                          Regular median {formatNumber(profile.regularMedian)} | mean {formatNumber(profile.regularMean)}
                        </div>
                      </td>
                      <td className="px-3 py-2">
                        <select
                          className="w-full rounded-md border border-slate-300 bg-white px-2 py-1"
                          value={draft.treatment}
                          onChange={(event) => updateDraft(profile, { treatment: event.target.value as BureauTreatment })}
                        >
                          {treatmentOptions.map(([value, label]) => (
                            <option key={value} value={value}>
                              {label}
                            </option>
                          ))}
                        </select>
                      </td>
                      <td className="px-3 py-2">
                        <textarea
                          className={`min-h-20 w-full rounded-md border px-2 py-1 ${needsRationale && !draft.rationale.trim() ? "border-amber-300 bg-amber-50" : "border-slate-300"}`}
                          value={draft.rationale}
                          onChange={(event) => updateDraft(profile, { rationale: event.target.value })}
                          placeholder={needsRationale ? "Rationale strongly recommended" : "Optional rationale"}
                        />
                      </td>
                      <td className="px-3 py-2">
                        <button
                          type="button"
                          className="rounded-md bg-slate-950 px-3 py-1.5 text-xs font-semibold text-white hover:bg-slate-800"
                          onClick={() => saveDecision(profile)}
                        >
                          Save
                        </button>
                      </td>
                    </tr>
                  );
                })}
                {!profiles.length && (
                  <tr>
                    <td colSpan={11} className="px-3 py-8 text-center text-sm text-slate-500">
                      No likely bureau special values detected. Upload metadata if bureau attributes use custom codes.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </section>
      </div>
    </StepShell>
  );
}

function Stat({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2">
      <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">{label}</div>
      <div className="mt-1 text-lg font-semibold text-slate-950">{value.toLocaleString()}</div>
    </div>
  );
}
