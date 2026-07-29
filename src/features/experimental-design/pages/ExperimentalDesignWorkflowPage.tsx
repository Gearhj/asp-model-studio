import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import {
  AlertTriangle,
  ArrowLeft,
  ArrowRight,
  Check,
  Database,
  Download,
  FileText,
  FlaskConical,
  GitBranch,
  Loader2,
  Play,
  Plus,
  RefreshCw,
  Save,
  ShieldCheck,
  Square,
  Trash2,
} from "lucide-react";
import WorkflowPlaceholderStep from "../../../steps/WorkflowPlaceholderStep";
import TimeSeriesWorkflowPage from "../../../workflows/time-series/TimeSeriesWorkflowPage";
import LlmWorkflowPage from "../../../workflows/llm/LlmWorkflowPage";
import { experimentalDesignJourney } from "../../../config/workflows";
import {
  linkDatasetToProject,
  listDatasets,
  type DatasetSummary,
} from "../../../lib/datasetLibrary";
import {
  analyzeExperimentalObservations,
  calculateExperimentalPower,
  cancelExperimentalSimulation,
  captureExperimentalDocumentation,
  createExperimentalSimulation,
  generateExperimentalDesign,
  getExperimentalSimulation,
  getExperimentalStudy,
  randomizeExperimentalDesign,
  recommendExperimentalDesign,
  retryExperimentalSimulation,
  saveExperimentalStudy,
  type AnalysisResult,
  type DesignResult,
  type DocumentationResult,
  type ExperimentalFactor,
  type NuisanceFactor,
  type PowerResult,
  type RandomizationResult,
  type SimulationJob,
  type Study,
  type StudyContract,
} from "../../../lib/experimentalDesignApi";
import { useWorkflowStore } from "../../../state/useWorkflowStore";
import {
  AliasMap,
  DesignMatrixChart,
  EffectParetoChart,
  FactorStructureMap,
  PowerCurveChart,
  ResidualPlot,
} from "../components";


const inputClass =
  "w-full rounded-xl border border-slate-300 bg-white px-3.5 py-2.5 text-sm text-slate-950 shadow-sm outline-none transition focus:border-cyan-500 focus:ring-4 focus:ring-cyan-100";
const labelClass = "mb-1.5 block text-xs font-bold uppercase tracking-[0.12em] text-slate-600";
const cardClass = "rounded-2xl border border-slate-200 bg-white p-5 shadow-[0_18px_45px_rgba(15,23,42,0.055)]";
const secondaryButton =
  "inline-flex min-h-10 items-center justify-center gap-2 rounded-xl border border-slate-300 bg-white px-4 py-2 text-sm font-bold text-slate-700 shadow-sm transition hover:border-slate-400 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50";
const primaryButton =
  "inline-flex min-h-10 items-center justify-center gap-2 rounded-xl bg-slate-950 px-4 py-2 text-sm font-bold text-white shadow-sm transition hover:bg-cyan-800 disabled:cursor-not-allowed disabled:opacity-50";

type Recommendation = Awaited<ReturnType<typeof recommendExperimentalDesign>>;

function Field({
  label,
  value,
  onChange,
  placeholder,
  type = "text",
  min,
  max,
  step,
}: {
  label: string;
  value: string | number;
  onChange: (value: string) => void;
  placeholder?: string;
  type?: "text" | "number";
  min?: number;
  max?: number;
  step?: number;
}) {
  return (
    <label className="block">
      <span className={labelClass}>{label}</span>
      <input
        className={inputClass}
        type={type}
        value={value}
        min={min}
        max={max}
        step={step}
        placeholder={placeholder}
        onChange={(event) => onChange(event.target.value)}
      />
    </label>
  );
}

function TextArea({
  label,
  value,
  onChange,
  placeholder,
  rows = 4,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  rows?: number;
}) {
  return (
    <label className="block">
      <span className={labelClass}>{label}</span>
      <textarea
        className={inputClass}
        value={value}
        rows={rows}
        placeholder={placeholder}
        onChange={(event) => onChange(event.target.value)}
      />
    </label>
  );
}

function SectionHeader({
  eyebrow,
  title,
  description,
}: {
  eyebrow: string;
  title: string;
  description: string;
}) {
  return (
    <div className="mb-5">
      <p className="text-xs font-black uppercase tracking-[0.18em] text-cyan-700">{eyebrow}</p>
      <h2 className="mt-1 text-xl font-black tracking-tight text-slate-950">{title}</h2>
      <p className="mt-2 max-w-3xl text-sm leading-6 text-slate-600">{description}</p>
    </div>
  );
}

function Metric({
  label,
  value,
  detail,
}: {
  label: string;
  value: string;
  detail?: string;
}) {
  return (
    <div className="rounded-xl border border-slate-200 bg-slate-50 px-4 py-3">
      <p className="text-[11px] font-black uppercase tracking-[0.12em] text-slate-500">{label}</p>
      <p className="mt-1 text-xl font-black text-slate-950">{value}</p>
      {detail ? <p className="mt-1 text-xs text-slate-500">{detail}</p> : null}
    </div>
  );
}

function ExactTable({
  rows,
  columns,
  caption,
  limit,
  downloadName,
}: {
  rows: Array<Record<string, unknown>>;
  columns: string[];
  caption: string;
  limit?: number;
  downloadName?: string;
}) {
  const [query, setQuery] = useState("");
  const [sort, setSort] = useState<{ column: string; direction: "asc" | "desc" } | null>(null);
  const filtered = useMemo(() => {
    const normalizedQuery = query.trim().toLocaleLowerCase();
    const matching = normalizedQuery
      ? rows.filter((row) =>
          columns.some((column) =>
            String(row[column] ?? "")
              .toLocaleLowerCase()
              .includes(normalizedQuery),
          ),
        )
      : [...rows];
    if (!sort) return matching;
    return matching.sort((left, right) => {
      const leftValue = left[sort.column];
      const rightValue = right[sort.column];
      const numeric =
        typeof leftValue === "number" && typeof rightValue === "number"
          ? leftValue - rightValue
          : String(leftValue ?? "").localeCompare(String(rightValue ?? ""), undefined, {
              numeric: true,
              sensitivity: "base",
            });
      return sort.direction === "asc" ? numeric : -numeric;
    });
  }, [columns, query, rows, sort]);
  const visible = typeof limit === "number" ? filtered.slice(0, limit) : filtered;
  const exportCsv = () => {
    const escape = (value: unknown) => {
      const text = typeof value === "object" && value !== null ? JSON.stringify(value) : String(value ?? "");
      return `"${text.replaceAll('"', '""')}"`;
    };
    const csv = [
      columns.map(escape).join(","),
      ...filtered.map((row) => columns.map((column) => escape(row[column])).join(",")),
    ].join("\r\n");
    const url = URL.createObjectURL(new Blob([csv], { type: "text/csv;charset=utf-8" }));
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = downloadName || `${caption.toLocaleLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "") || "atlas-experimental-design"}.csv`;
    anchor.click();
    URL.revokeObjectURL(url);
  };
  return (
    <div className="overflow-hidden rounded-xl border border-slate-200">
      <div className="flex flex-wrap items-end justify-between gap-3 border-b border-slate-200 bg-slate-50 p-3">
        <label className="min-w-56 flex-1">
          <span className="sr-only">Filter {caption}</span>
          <input
            className={`${inputClass} bg-white`}
            type="search"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Filter exact rows…"
          />
        </label>
        <button type="button" className={secondaryButton} onClick={exportCsv} disabled={!filtered.length}>
          <Download className="h-4 w-4" />
          Export CSV
        </button>
      </div>
      <div className="overflow-auto">
        <table className="min-w-full border-collapse text-left text-xs">
          <caption className="sr-only">{caption}</caption>
          <thead className="sticky top-0 z-10 bg-slate-950 text-white">
            <tr>
              {columns.map((column) => (
                <th key={column} scope="col" aria-sort={sort?.column === column ? (sort.direction === "asc" ? "ascending" : "descending") : "none"} className="whitespace-nowrap p-0 font-bold">
                  <button
                    type="button"
                    className="flex w-full items-center justify-between gap-2 px-3 py-2.5 text-left hover:bg-slate-800 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-[-2px] focus-visible:outline-cyan-300"
                    onClick={() =>
                      setSort((current) =>
                        current?.column === column
                          ? { column, direction: current.direction === "asc" ? "desc" : "asc" }
                          : { column, direction: "asc" },
                      )
                    }
                  >
                    {column}
                    <span aria-hidden="true" className="text-[10px] text-slate-400">
                      {sort?.column === column ? (sort.direction === "asc" ? "▲" : "▼") : "↕"}
                    </span>
                  </button>
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100 bg-white">
            {visible.map((row, index) => (
              <tr key={String(row.runId ?? row.source ?? index)} className="hover:bg-cyan-50/50">
                {columns.map((column) => (
                  <td key={column} className="whitespace-nowrap px-3 py-2 text-slate-700">
                    {typeof row[column] === "number" ? Number(row[column]).toLocaleString(undefined, { maximumFractionDigits: 5 }) : String(row[column] ?? "—")}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p aria-live="polite" className="border-t border-slate-200 bg-slate-50 px-3 py-2 text-xs text-slate-500">
        Showing {visible.length.toLocaleString()} of {filtered.length.toLocaleString()} matching rows
        {filtered.length !== rows.length ? ` (${rows.length.toLocaleString()} total)` : ""}.
      </p>
    </div>
  );
}

function ExperimentalDesignWorkspace() {
  const { stepNumber } = useParams();
  const navigate = useNavigate();
  const projectId = useWorkflowStore((state) => state.projectId);
  const projectName = useWorkflowStore((state) => state.projectName);
  const setWorkflowStepStatus = useWorkflowStore((state) => state.setWorkflowStepStatus);
  const setCurrentStepId = useWorkflowStore((state) => state.setCurrentStepId);
  const activeStepNumber = Math.max(1, Math.min(12, Number(stepNumber || 1)));
  const journeyStep = experimentalDesignJourney[activeStepNumber - 1];

  const [study, setStudy] = useState<Study | null>(null);
  const [contract, setContract] = useState<StudyContract | null>(null);
  const [versions, setVersions] = useState<Array<{ versionNumber: number; contractHash: string; changeSummary?: string; createdAt?: string }>>([]);
  const [recommendation, setRecommendation] = useState<Recommendation | null>(null);
  const [power, setPower] = useState<PowerResult | undefined>();
  const [design, setDesign] = useState<DesignResult | undefined>();
  const [randomization, setRandomization] = useState<RandomizationResult | undefined>();
  const [simulation, setSimulation] = useState<SimulationJob | undefined>();
  const [analysis, setAnalysis] = useState<AnalysisResult | undefined>();
  const [documentation, setDocumentation] = useState<DocumentationResult | undefined>();
  const [datasetOptions, setDatasetOptions] = useState<DatasetSummary[]>([]);
  const [selectedDatasetId, setSelectedDatasetId] = useState("");
  const [observationText, setObservationText] = useState("");
  const [syntheticInput, setSyntheticInput] = useState(false);
  const [simulationIterations, setSimulationIterations] = useState(2500);
  const [tableLimit, setTableLimit] = useState<number | undefined>(100);
  const [loading, setLoading] = useState(true);
  const [working, setWorking] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [savedFingerprint, setSavedFingerprint] = useState("");

  const hydrate = useCallback((nextStudy: Study) => {
    setStudy(nextStudy);
    setContract(nextStudy.contract);
    setPower(nextStudy.artifacts.power);
    setDesign(nextStudy.artifacts.design);
    setRandomization(nextStudy.artifacts.randomization);
    setSimulation(nextStudy.artifacts.simulation);
    setAnalysis(nextStudy.artifacts.analysis);
    setDocumentation(nextStudy.artifacts.documentation);
    setSavedFingerprint(JSON.stringify(nextStudy.contract));
  }, []);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError("");
    getExperimentalStudy(projectId)
      .then((response) => {
        if (cancelled) return;
        hydrate(response.study);
        setVersions(response.versions);
        const latestJob = response.jobs.find((job) => ["queued", "running", "cancelling", "complete", "interrupted", "failed", "cancelled"].includes(job.status));
        if (latestJob && !response.study.artifacts.simulation) setSimulation(latestJob);
      })
      .catch((reason) => {
        if (!cancelled) setError(reason instanceof Error ? reason.message : "Experimental Design could not be loaded.");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [hydrate, projectId]);

  useEffect(() => {
    if (activeStepNumber !== 1 || datasetOptions.length) return;
    void listDatasets()
      .then((response) => {
        setDatasetOptions(response.datasets);
        setSelectedDatasetId((current) => current || response.datasets[0]?.datasetId || "");
      })
      .catch(() => undefined);
  }, [activeStepNumber, datasetOptions.length]);

  useEffect(() => {
    if (!simulation || !["queued", "running", "cancelling"].includes(simulation.status)) return undefined;
    let cancelled = false;
    const poll = window.setInterval(() => {
      getExperimentalSimulation(projectId, simulation.simulationJobId)
        .then((response) => {
          if (cancelled) return;
          setSimulation(response.job);
          if (["complete", "failed", "cancelled", "interrupted"].includes(response.job.status)) {
            window.clearInterval(poll);
            if (response.job.status === "complete") {
              setNotice("Simulation completed and its evidence artifact was captured.");
              void getExperimentalStudy(projectId).then((fresh) => hydrate(fresh.study));
            }
          }
        })
        .catch((reason) => {
          if (!cancelled) setError(reason instanceof Error ? reason.message : "Simulation status could not be refreshed.");
          window.clearInterval(poll);
        });
    }, 750);
    return () => {
      cancelled = true;
      window.clearInterval(poll);
    };
  }, [hydrate, projectId, simulation?.simulationJobId, simulation?.status]);

  const dirty = Boolean(contract && JSON.stringify(contract) !== savedFingerprint);

  const patchContract = useCallback((updater: (current: StudyContract) => StudyContract) => {
    setContract((current) => (current ? updater(current) : current));
    setNotice("");
  }, []);

  const persist = useCallback(
    async (summary: string) => {
      if (!contract) throw new Error("Study contract has not loaded.");
      setWorking("save");
      setError("");
      try {
        const response = await saveExperimentalStudy(projectId, contract, summary);
        hydrate(response.study);
        setNotice(response.changed ? `Study version ${response.study.currentVersion} saved.` : "Study is already current.");
        return response.study;
      } catch (reason) {
        const message = reason instanceof Error ? reason.message : "Study could not be saved.";
        setError(message);
        throw reason;
      } finally {
        setWorking("");
      }
    },
    [contract, hydrate, projectId],
  );

  const saveAndContinue = async () => {
    try {
      await persist(`Completed ${journeyStep.label}.`);
      setWorkflowStepStatus(journeyStep.id, "complete");
      const next = experimentalDesignJourney[activeStepNumber];
      if (next) {
        setCurrentStepId(next.id);
        navigate(next.route);
      }
    } catch {
      // persist reports the actionable error.
    }
  };

  const runAfterSave = async <T,>(label: string, action: () => Promise<T>) => {
    setWorking(label);
    setError("");
    setNotice("");
    try {
      if (dirty) await persist(`Saved contract before ${label}.`);
      return await action();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : `${label} failed.`);
      return undefined;
    } finally {
      setWorking("");
    }
  };

  const updateRecommendation = async () => {
    if (!contract) return;
    const result = await runAfterSave("recommendation", () => recommendExperimentalDesign(projectId, contract));
    if (result) setRecommendation(result);
  };

  useEffect(() => {
    if (activeStepNumber !== 5 || !contract || recommendation) return;
    void recommendExperimentalDesign(projectId, contract).then(setRecommendation).catch(() => undefined);
  }, [activeStepNumber, contract, projectId, recommendation]);

  const calculatePower = async () => {
    const result = await runAfterSave("power calculation", () => calculateExperimentalPower(projectId));
    if (result) {
      setPower(result);
      if (result.study) hydrate(result.study);
      setNotice("Power plan calculated from the persisted study contract.");
    }
  };

  const generateDesign = async () => {
    const result = await runAfterSave("design generation", () => generateExperimentalDesign(projectId));
    if (result) {
      setDesign(result);
      setRandomization(undefined);
      setSimulation(undefined);
      setAnalysis(undefined);
      hydrate(result.study);
      setNotice(`${result.runCount.toLocaleString()} design runs generated and evidence captured.`);
    }
  };

  const randomize = async () => {
    if (!contract) return;
    const result = await runAfterSave("randomization", () => randomizeExperimentalDesign(projectId, contract.randomization.seed));
    if (result) {
      setRandomization(result);
      hydrate(result.study);
      setNotice(`Run order regenerated reproducibly with seed ${result.seed}.`);
    }
  };

  const startSimulation = async () => {
    if (!contract) return;
    const result = await runAfterSave("simulation", () =>
      createExperimentalSimulation(projectId, {
        iterations: simulationIterations,
        seed: contract.randomization.seed,
        samplePerCell: power?.perCell,
      }),
    );
    if (result) {
      setSimulation(result.job);
      setNotice("Simulation queued. You may leave this page; progress is durable.");
    }
  };

  const stopSimulation = async () => {
    if (!simulation) return;
    setWorking("cancel simulation");
    try {
      const response = await cancelExperimentalSimulation(projectId, simulation.simulationJobId);
      setSimulation(response.job);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Simulation could not be cancelled.");
    } finally {
      setWorking("");
    }
  };

  const retrySimulation = async () => {
    if (!simulation) return;
    setWorking("retry simulation");
    try {
      const response = await retryExperimentalSimulation(projectId, simulation.simulationJobId);
      setSimulation(response.job);
      setNotice("A new simulation job was queued from the recoverable request.");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Simulation could not be retried.");
    } finally {
      setWorking("");
    }
  };

  const populateSyntheticObservations = () => {
    if (!design?.rows?.length) return;
    const values = design.rows.map((row, index) => {
      const coded = row._coded as Record<string, number> | undefined;
      const signal = Object.values(coded || {}).reduce((sum, value, factorIndex) => sum + Number(value) * (0.7 / (factorIndex + 1)), 0);
      const deterministicNoise = Math.sin((index + 1) * 12.9898) * 0.18;
      return `${String(row.runId)},${(10 + signal + deterministicNoise).toFixed(5)}`;
    });
    setObservationText(["runId,response", ...values].join("\n"));
    setSyntheticInput(true);
  };

  const analyze = async () => {
    const observations = observationText
      .split(/\r?\n/)
      .slice(observationText.toLowerCase().startsWith("runid") ? 1 : 0)
      .map((line) => line.split(","))
      .map(([runId, response]) => ({ runId: String(runId || "").trim(), response: Number(response) }))
      .filter((row) => row.runId && Number.isFinite(row.response));
    const result = await runAfterSave("observed analysis", () => analyzeExperimentalObservations(projectId, observations));
    if (result) {
      setAnalysis(result);
      hydrate(result.study);
      setNotice(`${result.observationCount} observed responses analyzed. ${syntheticInput ? "Input is explicitly marked synthetic." : ""}`);
    }
  };

  const captureDocumentation = async () => {
    const result = await runAfterSave("documentation capture", () => captureExperimentalDocumentation(projectId));
    if (result) {
      setDocumentation(result.documentation);
      setNotice("Documentation and evidence snapshots were captured.");
      const fresh = await getExperimentalStudy(projectId);
      hydrate(fresh.study);
    }
  };

  const bindSelectedDataset = async () => {
    const dataset = datasetOptions.find((item) => item.datasetId === selectedDatasetId);
    const version = dataset?.latestVersion;
    if (!dataset || !version) {
      setError("Choose a Dataset Library asset with a registered version.");
      return;
    }
    setWorking("dataset binding");
    setError("");
    try {
      await linkDatasetToProject(projectId, dataset.datasetId, version.versionId, "experimental_observations");
      patchContract((current) => ({
        ...current,
        dataStrategy: { ...current.dataStrategy, mode: current.dataStrategy.mode === "prospective" ? "hybrid" : "existing" },
        datasetBindings: [
          ...current.datasetBindings.filter((binding) => binding.datasetId !== dataset.datasetId),
          {
            datasetId: dataset.datasetId,
            versionId: version.versionId,
            datasetRole: "experimental_observations",
            name: dataset.name,
            rowCount: version.rowCount,
            columnCount: version.columnCount,
            hash: version.hash,
            boundAt: new Date().toISOString(),
          },
        ],
      }));
      setNotice(`${dataset.name} ${version.versionId} is linked; save the study to version its lineage.`);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Dataset version could not be linked.");
    } finally {
      setWorking("");
    }
  };

  if (loading || !contract || !study) {
    return (
      <main className="flex min-h-[70vh] items-center justify-center">
        <div className="flex items-center gap-3 text-sm font-bold text-slate-600">
          <Loader2 className="h-5 w-5 animate-spin text-cyan-700" /> Loading governed study contract…
        </div>
      </main>
    );
  }

  const stepBody = (() => {
    if (activeStepNumber === 1) {
      return (
        <div className="grid gap-5 xl:grid-cols-[1.1fr_0.9fr]">
          <section className={cardClass}>
            <SectionHeader eyebrow="Study charter" title="Anchor every design choice to a decision" description="Define the business purpose, population, and accountable action before introducing statistical machinery." />
            <div className="space-y-4">
              <Field label="Study title" value={contract.title} onChange={(value) => patchContract((current) => ({ ...current, title: value }))} />
              <TextArea label="Business objective" value={contract.objective.businessObjective} onChange={(value) => patchContract((current) => ({ ...current, objective: { ...current.objective, businessObjective: value } }))} placeholder="What measurable business problem should this study resolve?" />
              <TextArea label="Decision this study informs" value={contract.objective.decision} onChange={(value) => patchContract((current) => ({ ...current, objective: { ...current.objective, decision: value } }))} placeholder="For example: select the contact strategy for a controlled rollout." />
              <Field label="Experimental population" value={contract.objective.population} onChange={(value) => patchContract((current) => ({ ...current, objective: { ...current.objective, population: value } }))} placeholder="Eligible accounts, locations, batches, campaigns…" />
            </div>
          </section>
          <section className={`${cardClass} bg-slate-950 text-white`}>
            <p className="text-xs font-black uppercase tracking-[0.18em] text-cyan-300">Decision-first design</p>
            <h3 className="mt-2 text-2xl font-black">A design is defensible only when its use is explicit.</h3>
            <div className="mt-6 space-y-4 text-sm leading-6 text-slate-300">
              <p>ATLAS versions this charter with the factor, response, design, and analysis contract.</p>
              <p>Changing it later invalidates affected power, design, simulation, analysis, and documentation artifacts.</p>
            </div>
            <div className="mt-8 rounded-xl border border-cyan-800 bg-cyan-950/60 p-4 text-sm text-cyan-100">
              <ShieldCheck className="mb-2 h-5 w-5" />
              No design family is auto-selected. Recommendations remain advisory until an analyst confirms one.
            </div>
          </section>
          <section className={`${cardClass} xl:col-span-2`}>
            <SectionHeader eyebrow="Data strategy & acquisition" title="Plan prospective capture or bind governed observed data" description="Experimental design can begin before observations exist. Existing and completed studies must bind an exact Dataset Library version before it can serve as analysis lineage." />
            <div className="grid gap-4 lg:grid-cols-[220px_1fr_auto]">
              <label>
                <span className={labelClass}>Data strategy</span>
                <select className={inputClass} value={contract.dataStrategy.mode} onChange={(event) => patchContract((current) => ({ ...current, dataStrategy: { ...current.dataStrategy, mode: event.target.value } }))}>
                  <option value="prospective">Prospective collection</option>
                  <option value="existing">Existing / completed study</option>
                  <option value="hybrid">Hybrid</option>
                </select>
              </label>
              <label>
                <span className={labelClass}>Dataset Library version</span>
                <select className={inputClass} value={selectedDatasetId} onChange={(event) => setSelectedDatasetId(event.target.value)}>
                  {!datasetOptions.length ? <option value="">No accessible registered datasets</option> : null}
                  {datasetOptions.map((dataset) => <option key={dataset.datasetId} value={dataset.datasetId}>{dataset.name} · {dataset.latestVersion?.versionId || "no version"}</option>)}
                </select>
              </label>
              <button className={`${secondaryButton} self-end`} disabled={!selectedDatasetId || working === "dataset binding"} onClick={bindSelectedDataset}>{working === "dataset binding" ? <Loader2 className="h-4 w-4 animate-spin" /> : <Database className="h-4 w-4" />} Bind version</button>
            </div>
            <div className="mt-4 grid gap-4 md:grid-cols-2">
              <TextArea label="Prospective capture plan" value={contract.dataStrategy.capturePlan} onChange={(value) => patchContract((current) => ({ ...current, dataStrategy: { ...current.dataStrategy, capturePlan: value } }))} placeholder="How will run IDs, treatment settings, responses, protocol deviations, and timestamps be captured?" />
              <TextArea label="Data lineage and provenance notes" value={contract.dataStrategy.provenanceNotes} onChange={(value) => patchContract((current) => ({ ...current, dataStrategy: { ...current.dataStrategy, provenanceNotes: value } }))} placeholder="Source systems, joins, measurement timing, reconciliation, and quality controls." />
            </div>
            {contract.datasetBindings.length ? (
              <div className="mt-4 overflow-hidden rounded-xl border border-slate-200">
                <table className="min-w-full text-left text-xs">
                  <caption className="sr-only">Governed Experimental Design dataset bindings</caption>
                  <thead className="bg-slate-100 text-slate-600"><tr><th className="px-3 py-2">Dataset</th><th className="px-3 py-2">Version</th><th className="px-3 py-2">Rows</th><th className="px-3 py-2">Columns</th><th className="px-3 py-2">Role</th><th className="px-3 py-2"><span className="sr-only">Actions</span></th></tr></thead>
                  <tbody className="divide-y divide-slate-100">
                    {contract.datasetBindings.map((binding) => (
                      <tr key={`${binding.datasetId}-${binding.versionId}`}>
                        <td className="px-3 py-2 font-bold text-slate-900">{binding.name || binding.datasetId}</td>
                        <td className="px-3 py-2 text-slate-600">{binding.versionId}</td>
                        <td className="px-3 py-2 text-slate-600">{binding.rowCount?.toLocaleString() || "—"}</td>
                        <td className="px-3 py-2 text-slate-600">{binding.columnCount?.toLocaleString() || "—"}</td>
                        <td className="px-3 py-2 text-slate-600">{binding.datasetRole}</td>
                        <td className="px-3 py-2 text-right"><button className="text-slate-400 hover:text-red-600" aria-label={`Remove ${binding.name || binding.datasetId} binding`} onClick={() => patchContract((current) => ({ ...current, datasetBindings: current.datasetBindings.filter((item) => !(item.datasetId === binding.datasetId && item.versionId === binding.versionId)) }))}><Trash2 className="h-4 w-4" /></button></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : <p className="mt-4 rounded-xl border border-dashed border-slate-300 bg-slate-50 px-4 py-3 text-xs text-slate-600">No observed dataset is bound. This is valid for a prospective study when the capture plan is documented.</p>}
            <button className="mt-4 text-xs font-black text-cyan-700 hover:text-cyan-900" onClick={() => navigate("/datasets")}>Open Dataset Library →</button>
          </section>
        </div>
      );
    }
    if (activeStepNumber === 2) {
      return (
        <section className={cardClass}>
          <SectionHeader eyebrow="Response contract" title="Make the statistical question testable" description="Name the primary response, unit of randomization, hypotheses, and practical decision threshold." />
          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
            <Field label="Primary response" value={contract.objective.primaryResponse.name} onChange={(value) => patchContract((current) => ({ ...current, objective: { ...current.objective, primaryResponse: { ...current.objective.primaryResponse, name: value } } }))} placeholder="Conversion rate" />
            <label>
              <span className={labelClass}>Response type</span>
              <select className={inputClass} value={contract.objective.primaryResponse.type} onChange={(event) => patchContract((current) => ({ ...current, objective: { ...current.objective, primaryResponse: { ...current.objective.primaryResponse, type: event.target.value }, }, power: { ...current.power, responseKind: event.target.value === "binary" ? "binary" : "continuous" } }))}>
                <option value="continuous">Continuous</option>
                <option value="binary">Binary</option>
                <option value="count">Count</option>
              </select>
            </label>
            <label>
              <span className={labelClass}>Desired direction</span>
              <select className={inputClass} value={contract.objective.primaryResponse.direction} onChange={(event) => patchContract((current) => ({ ...current, objective: { ...current.objective, primaryResponse: { ...current.objective.primaryResponse, direction: event.target.value } } }))}>
                <option value="maximize">Maximize</option>
                <option value="minimize">Minimize</option>
                <option value="target">Hit a target</option>
              </select>
            </label>
            <Field label="Response unit" value={contract.objective.primaryResponse.unit} onChange={(value) => patchContract((current) => ({ ...current, objective: { ...current.objective, primaryResponse: { ...current.objective.primaryResponse, unit: value } } }))} placeholder="%, dollars, minutes…" />
          </div>
          <div className="mt-4 grid gap-4 md:grid-cols-2">
            <Field label="Unit of randomization" value={contract.objective.unitOfRandomization} onChange={(value) => patchContract((current) => ({ ...current, objective: { ...current.objective, unitOfRandomization: value } }))} placeholder="Customer, branch, batch, session…" />
            <Field label="Success criterion" value={contract.objective.successCriterion} onChange={(value) => patchContract((current) => ({ ...current, objective: { ...current.objective, successCriterion: value } }))} placeholder="Practical and statistical decision rule" />
            <TextArea label="Null hypothesis" value={contract.objective.nullHypothesis} onChange={(value) => patchContract((current) => ({ ...current, objective: { ...current.objective, nullHypothesis: value } }))} placeholder="No practically meaningful treatment effect…" />
            <TextArea label="Alternative hypothesis" value={contract.objective.alternativeHypothesis} onChange={(value) => patchContract((current) => ({ ...current, objective: { ...current.objective, alternativeHypothesis: value } }))} placeholder="At least one treatment creates a meaningful effect…" />
          </div>
        </section>
      );
    }
    if (activeStepNumber === 3) {
      const addFactor = () => patchContract((current) => ({
        ...current,
        factors: [...current.factors, { factorId: crypto.randomUUID(), name: `Factor ${current.factors.length + 1}`, kind: "categorical", levels: ["Control", "Treatment"], unit: "", controllable: true }],
      }));
      const updateFactor = (index: number, patch: Partial<ExperimentalFactor>) => patchContract((current) => ({ ...current, factors: current.factors.map((factor, position) => (position === index ? { ...factor, ...patch } : factor)) }));
      return (
        <div className="grid gap-5 2xl:grid-cols-[1.05fr_0.95fr]">
          <section className={cardClass}>
            <div className="flex flex-wrap items-start justify-between gap-3">
              <SectionHeader eyebrow="Treatment structure" title="Define factors and real operating levels" description="Keep controllable factors separate from measured covariates and nuisance sources." />
              <button className={secondaryButton} onClick={addFactor}><Plus className="h-4 w-4" /> Add factor</button>
            </div>
            <div className="space-y-3">
              {contract.factors.map((factor, index) => (
                <div key={factor.factorId} className="grid gap-3 rounded-xl border border-slate-200 bg-slate-50 p-3 md:grid-cols-[1fr_150px_1.4fr_110px_42px]">
                  <Field label="Factor" value={factor.name} onChange={(value) => updateFactor(index, { name: value })} />
                  <label><span className={labelClass}>Type</span><select className={inputClass} value={factor.kind} onChange={(event) => updateFactor(index, { kind: event.target.value as ExperimentalFactor["kind"] })}><option value="categorical">Categorical</option><option value="continuous">Continuous</option><option value="ordinal">Ordinal</option></select></label>
                  <Field label="Levels (comma separated)" value={factor.levels.join(", ")} onChange={(value) => updateFactor(index, { levels: value.split(",").map((item) => item.trim()).filter(Boolean) })} />
                  <Field label="Unit" value={factor.unit} onChange={(value) => updateFactor(index, { unit: value })} />
                  <button aria-label={`Remove ${factor.name}`} className="mt-6 flex h-10 w-10 items-center justify-center rounded-xl text-slate-400 hover:bg-red-50 hover:text-red-600" onClick={() => patchContract((current) => ({ ...current, factors: current.factors.filter((_, position) => position !== index) }))}><Trash2 className="h-4 w-4" /></button>
                </div>
              ))}
              {!contract.factors.length ? <button className="w-full rounded-xl border border-dashed border-slate-300 p-8 text-sm font-bold text-slate-500 hover:border-cyan-400 hover:text-cyan-700" onClick={addFactor}>Add the first controllable factor</button> : null}
            </div>
          </section>
          <section className={cardClass}>
            <SectionHeader eyebrow="Visual structure" title="What can move the response?" description="Solid links are controlled treatments; nuisance links are added on the next page." />
            <FactorStructureMap factors={contract.factors} nuisance={contract.nuisanceFactors} />
          </section>
        </div>
      );
    }
    if (activeStepNumber === 4) {
      const addNuisance = () => patchContract((current) => ({ ...current, nuisanceFactors: [...current.nuisanceFactors, { nuisanceId: crypto.randomUUID(), name: `Nuisance ${current.nuisanceFactors.length + 1}`, strategy: "block", levels: ["Block 1", "Block 2"] }] }));
      const updateNuisance = (index: number, patch: Partial<NuisanceFactor>) => patchContract((current) => ({ ...current, nuisanceFactors: current.nuisanceFactors.map((factor, position) => (position === index ? { ...factor, ...patch } : factor)) }));
      return (
        <div className="grid gap-5 xl:grid-cols-[1.1fr_0.9fr]">
          <section className={cardClass}>
            <div className="flex flex-wrap items-start justify-between gap-3">
              <SectionHeader eyebrow="Nuisance control" title="Block what you know; measure what you cannot control" description="Document nuisance variables explicitly so randomization and analysis do not silently ignore them." />
              <button className={secondaryButton} onClick={addNuisance}><Plus className="h-4 w-4" /> Add nuisance factor</button>
            </div>
            <div className="space-y-3">
              {contract.nuisanceFactors.map((factor, index) => (
                <div key={factor.nuisanceId} className="grid gap-3 rounded-xl border border-slate-200 bg-slate-50 p-3 md:grid-cols-[1fr_150px_1.2fr_42px]">
                  <Field label="Nuisance factor" value={factor.name} onChange={(value) => updateNuisance(index, { name: value })} />
                  <label><span className={labelClass}>Strategy</span><select className={inputClass} value={factor.strategy} onChange={(event) => updateNuisance(index, { strategy: event.target.value })}><option value="block">Block</option><option value="measure">Measure</option><option value="hold_constant">Hold constant</option></select></label>
                  <Field label="Levels (comma separated)" value={factor.levels.join(", ")} onChange={(value) => updateNuisance(index, { levels: value.split(",").map((item) => item.trim()).filter(Boolean) })} />
                  <button aria-label={`Remove ${factor.name}`} className="mt-6 flex h-10 w-10 items-center justify-center rounded-xl text-slate-400 hover:bg-red-50 hover:text-red-600" onClick={() => patchContract((current) => ({ ...current, nuisanceFactors: current.nuisanceFactors.filter((_, position) => position !== index) }))}><Trash2 className="h-4 w-4" /></button>
                </div>
              ))}
            </div>
          </section>
          <section className={cardClass}>
            <SectionHeader eyebrow="Blocking decision" title="Make the control strategy explicit" description="Blocking changes the matrix and randomization architecture, so it is versioned with the study." />
            <label className="flex items-start gap-3 rounded-xl border border-slate-200 bg-slate-50 p-4">
              <input type="checkbox" className="mt-1 h-4 w-4 accent-cyan-700" checked={contract.blocking.enabled} onChange={(event) => patchContract((current) => ({ ...current, blocking: { ...current.blocking, enabled: event.target.checked } }))} />
              <span><span className="block text-sm font-bold text-slate-900">Use a blocked design</span><span className="mt-1 block text-xs leading-5 text-slate-500">Randomize treatment order independently inside declared blocks.</span></span>
            </label>
            <div className="mt-4 space-y-4">
              <Field label="Blocking variables" value={contract.blocking.variables.join(", ")} onChange={(value) => patchContract((current) => ({ ...current, blocking: { ...current.blocking, variables: value.split(",").map((item) => item.trim()).filter(Boolean) } }))} placeholder="Site, batch, week…" />
              <TextArea label="Blocking rationale" value={contract.blocking.rationale} onChange={(value) => patchContract((current) => ({ ...current, blocking: { ...current.blocking, rationale: value } }))} />
            </div>
          </section>
        </div>
      );
    }
    if (activeStepNumber === 5) {
      return (
        <section className={cardClass}>
          <div className="flex flex-wrap items-start justify-between gap-3">
            <SectionHeader eyebrow="Analyst decision" title="Compare design families and confirm the estimability tradeoff" description="ATLAS narrows the eligible choices but never selects a design on the analyst’s behalf." />
            <button className={secondaryButton} disabled={Boolean(working)} onClick={updateRecommendation}><RefreshCw className={`h-4 w-4 ${working === "recommendation" ? "animate-spin" : ""}`} /> Refresh recommendation</button>
          </div>
          {recommendation ? (
            <>
              <div className="mb-4 rounded-xl border border-cyan-200 bg-cyan-50 p-4 text-sm text-cyan-950">
                <span className="font-black">Advisory recommendation:</span> {recommendation.recommendation ? recommendation.catalog.find((item) => item.family === recommendation.recommendation)?.label : "No family is eligible yet"}. {recommendation.rationale}
              </div>
              <div className="grid gap-4 lg:grid-cols-2 2xl:grid-cols-3">
                {recommendation.catalog.map((item) => {
                  const selected = contract.design.family === item.family;
                  return (
                    <button
                      type="button"
                      key={item.family}
                      disabled={!item.eligible}
                      aria-pressed={selected}
                      onClick={() => patchContract((current) => ({ ...current, design: { ...current.design, family: item.family, analystConfirmed: false } }))}
                      className={`rounded-2xl border p-4 text-left transition ${selected ? "border-cyan-500 bg-cyan-50 ring-4 ring-cyan-100" : "border-slate-200 bg-white hover:border-slate-400"} disabled:cursor-not-allowed disabled:bg-slate-50 disabled:opacity-55`}
                    >
                      <div className="flex items-center justify-between gap-3">
                        <span className="font-black text-slate-950">{item.label}</span>
                        {item.estimatedRuns ? <span className="rounded-full bg-slate-100 px-2.5 py-1 text-xs font-bold text-slate-600">~{item.estimatedRuns} runs</span> : null}
                      </div>
                      <p className="mt-3 text-sm leading-6 text-slate-700">{item.strength}</p>
                      <p className="mt-2 text-xs leading-5 text-slate-500">{item.tradeoff}</p>
                      <p className={`mt-3 text-xs font-black uppercase tracking-wider ${item.eligible ? "text-emerald-700" : "text-slate-400"}`}>{item.eligible ? "Eligible" : "Not eligible for this contract"}</p>
                    </button>
                  );
                })}
              </div>
            </>
          ) : <div className="rounded-xl border border-dashed border-slate-300 p-8 text-center text-sm text-slate-500">Loading family comparison…</div>}
          <div className="mt-5 grid gap-4 lg:grid-cols-[1fr_220px_220px]">
            <TextArea label="Selection rationale" value={contract.design.rationale} onChange={(value) => patchContract((current) => ({ ...current, design: { ...current.design, rationale: value } }))} placeholder="Why is this design appropriate for the estimands, budget, and operating constraints?" />
            <Field label="Replicates" type="number" min={1} max={20} value={contract.design.replicates} onChange={(value) => patchContract((current) => ({ ...current, design: { ...current.design, replicates: Number(value) } }))} />
            <Field label="Center points" type="number" min={1} max={20} value={contract.design.centerPoints} onChange={(value) => patchContract((current) => ({ ...current, design: { ...current.design, centerPoints: Number(value) } }))} />
          </div>
          <label className={`mt-4 flex items-start gap-3 rounded-xl border p-4 ${contract.design.analystConfirmed ? "border-emerald-300 bg-emerald-50" : "border-amber-300 bg-amber-50"}`}>
            <input type="checkbox" className="mt-1 h-4 w-4 accent-emerald-700" checked={contract.design.analystConfirmed} disabled={!contract.design.family} onChange={(event) => patchContract((current) => ({ ...current, design: { ...current.design, analystConfirmed: event.target.checked } }))} />
            <span><span className="block text-sm font-black text-slate-950">I confirm this design family and its stated estimability tradeoffs.</span><span className="mt-1 block text-xs text-slate-600">Required before backend matrix generation. This creates an attributable contract version.</span></span>
          </label>
        </section>
      );
    }
    if (activeStepNumber === 6) {
      return (
        <div className="grid gap-5 2xl:grid-cols-[0.72fr_1.28fr]">
          <section className={cardClass}>
            <SectionHeader eyebrow="Power contract" title="Declare the effect worth detecting" description="Power is calculated from persisted assumptions and adjusted for the number of declared effects." />
            <div className="grid gap-4 sm:grid-cols-2">
              <Field label="Alpha" type="number" min={0.0001} max={0.25} step={0.001} value={contract.power.alpha} onChange={(value) => patchContract((current) => ({ ...current, power: { ...current.power, alpha: Number(value) } }))} />
              <Field label="Target power" type="number" min={0.5} max={0.999} step={0.01} value={contract.power.targetPower} onChange={(value) => patchContract((current) => ({ ...current, power: { ...current.power, targetPower: Number(value) } }))} />
              <Field label="Minimum detectable effect" type="number" min={0.000001} step={0.01} value={contract.power.minimumDetectableEffect} onChange={(value) => patchContract((current) => ({ ...current, power: { ...current.power, minimumDetectableEffect: Number(value) } }))} />
              {contract.power.responseKind === "binary" ? <Field label="Baseline event rate" type="number" min={0.0001} max={0.9999} step={0.01} value={contract.power.baselineRate} onChange={(value) => patchContract((current) => ({ ...current, power: { ...current.power, baselineRate: Number(value) } }))} /> : <Field label="Response standard deviation" type="number" min={0.000001} step={0.1} value={contract.power.standardDeviation} onChange={(value) => patchContract((current) => ({ ...current, power: { ...current.power, standardDeviation: Number(value) } }))} />}
              <Field label="Effects tested" type="number" min={1} max={128} value={contract.power.effectsTested} onChange={(value) => patchContract((current) => ({ ...current, power: { ...current.power, effectsTested: Number(value) } }))} />
            </div>
            <button className={`${primaryButton} mt-5 w-full`} disabled={Boolean(working)} onClick={calculatePower}>{working === "power calculation" ? <Loader2 className="h-4 w-4 animate-spin" /> : <FlaskConical className="h-4 w-4" />} Calculate governed power plan</button>
            {power ? <div className="mt-4 grid grid-cols-2 gap-3"><Metric label="Per cell" value={power.perCell.toLocaleString()} /><Metric label="Total sample" value={power.totalSample.toLocaleString()} /><Metric label="Achieved power" value={`${(power.achievedPower * 100).toFixed(1)}%`} /><Metric label="Treatment cells" value={power.treatmentCells.toLocaleString()} /></div> : null}
          </section>
          <section className={cardClass}>
            <SectionHeader eyebrow="Sensitivity" title="Power versus total sample" description="The marked point is the smallest integer per-cell sample reaching the declared target under the stated approximation." />
            <PowerCurveChart result={power} />
            {power ? <p className="mt-3 rounded-xl bg-amber-50 px-4 py-3 text-xs leading-5 text-amber-900">{power.warning}</p> : null}
            {power ? (
              <div className="mt-5">
                <ExactTable
                  rows={power.curve as Array<Record<string, unknown>>}
                  columns={["perCell", "total", "power"]}
                  caption="Exact power sensitivity results"
                  downloadName="atlas-experimental-design-power-sensitivity.csv"
                />
              </div>
            ) : null}
          </section>
        </div>
      );
    }
    if (activeStepNumber === 7) {
      const columns = design ? ["runId", ...design.factorNames, ...(design.rows.some((row) => "block" in row) ? ["block"] : []), ...(design.rows.some((row) => "replicate" in row) ? ["replicate"] : [])] : [];
      return (
        <div className="space-y-5">
          <section className={cardClass}>
            <div className="flex flex-wrap items-start justify-between gap-3">
              <SectionHeader eyebrow="Backend-authoritative artifact" title="Generate the design matrix and review estimability" description="The exact matrix, coded structure, contract hash, alias map, and version identity are generated and persisted by the backend." />
              <button className={primaryButton} disabled={Boolean(working)} onClick={generateDesign}>{working === "design generation" ? <Loader2 className="h-4 w-4 animate-spin" /> : <Database className="h-4 w-4" />} Generate current design</button>
            </div>
            {design ? <div className="grid gap-3 sm:grid-cols-3"><Metric label="Design version" value={design.designVersion.slice(-12)} detail={design.family.replaceAll("_", " ")} /><Metric label="Generated runs" value={design.runCount.toLocaleString()} /><Metric label="Alias links" value={design.aliasStructure.length.toLocaleString()} /></div> : null}
          </section>
          <div className="grid gap-5 2xl:grid-cols-[1.15fr_0.85fr]">
            <section className={cardClass}><SectionHeader eyebrow="Visual intelligence" title="Coded matrix coverage" description="Color encodes the governed low-to-high factor settings; hover a cell for the exact value." /><DesignMatrixChart design={design} /></section>
            <section className={cardClass}><SectionHeader eyebrow="Confounding review" title="Alias structure" description="Fractional designs expose the defining relation; unaliased designs state that explicitly." /><AliasMap design={design} /></section>
          </div>
          {design ? (
            <section className={cardClass}>
              <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
                <SectionHeader eyebrow="Exact evidence" title="Semantic design matrix" description="Use the row selector to inspect or expose the complete generated artifact." />
                <label className="text-xs font-bold text-slate-600">Rows <select className="ml-2 rounded-lg border border-slate-300 bg-white px-2 py-1.5" value={tableLimit ?? "all"} onChange={(event) => setTableLimit(event.target.value === "all" ? undefined : Number(event.target.value))}><option value="100">100</option><option value="250">250</option><option value="all">All {design.rows.length}</option></select></label>
              </div>
              <ExactTable rows={design.rows as Array<Record<string, unknown>>} columns={columns} caption="Exact generated experimental design matrix" limit={tableLimit} downloadName={`${design.designVersion}-matrix.csv`} />
            </section>
          ) : null}
        </div>
      );
    }
    if (activeStepNumber === 8) {
      const columns = randomization ? ["runOrder", "runId", ...design!.factorNames, ...(randomization.rows.some((row) => "block" in row) ? ["block", "randomizedOrderWithinBlock"] : [])] : [];
      return (
        <div className="grid gap-5 2xl:grid-cols-[0.42fr_1.58fr]">
          <section className={cardClass}>
            <SectionHeader eyebrow="Reproducible allocation" title="Persist the randomization seed" description="ATLAS randomizes the generated design, within block when applicable." />
            <Field label="Randomization seed" type="number" value={contract.randomization.seed} onChange={(value) => patchContract((current) => ({ ...current, randomization: { ...current.randomization, seed: Number(value) } }))} />
            <button className={`${primaryButton} mt-4 w-full`} disabled={!design || Boolean(working)} onClick={randomize}>{working === "randomization" ? <Loader2 className="h-4 w-4 animate-spin" /> : <GitBranch className="h-4 w-4" />} Generate run order</button>
            {randomization ? <div className="mt-4 space-y-3"><Metric label="Method" value={randomization.method.replaceAll("_", " ")} /><Metric label="Persisted seed" value={randomization.seed.toLocaleString()} /></div> : null}
          </section>
          <section className={cardClass}>
            <SectionHeader eyebrow="Run plan" title="Exact randomized execution order" description="This semantic table is the authoritative operational handoff; regenerating with the same seed reproduces it." />
            {randomization ? <ExactTable rows={randomization.rows as Array<Record<string, unknown>>} columns={columns} caption="Randomized experimental run plan" limit={tableLimit} downloadName={`${randomization.randomizationVersion}-run-plan.csv`} /> : <div className="rounded-xl border border-dashed border-slate-300 p-12 text-center text-sm text-slate-500">Generate a design, then create the randomized run order.</div>}
          </section>
        </div>
      );
    }
    if (activeStepNumber === 9) {
      const terminalRecoverable = simulation && ["failed", "cancelled", "interrupted"].includes(simulation.status);
      return (
        <div className="grid gap-5 xl:grid-cols-[0.62fr_1.38fr]">
          <section className={cardClass}>
            <SectionHeader eyebrow="Durable background job" title="Stress-test operating characteristics" description="Simulation is bounded, cancellable, seeded, persisted, and recoverable after interruption." />
            <Field label="Iterations" type="number" min={100} max={20000} step={100} value={simulationIterations} onChange={(value) => setSimulationIterations(Math.max(100, Math.min(20000, Number(value))))} />
            <div className="mt-4 flex gap-2">
              <button className={`${primaryButton} flex-1`} disabled={!design || Boolean(simulation && ["queued", "running", "cancelling"].includes(simulation.status)) || Boolean(working)} onClick={startSimulation}><Play className="h-4 w-4" /> Start simulation</button>
              {simulation && ["queued", "running", "cancelling"].includes(simulation.status) ? <button className={secondaryButton} onClick={stopSimulation}><Square className="h-4 w-4" /> Cancel</button> : null}
              {terminalRecoverable ? <button className={secondaryButton} onClick={retrySimulation}><RefreshCw className="h-4 w-4" /> Retry</button> : null}
            </div>
            {simulation ? (
              <div className="mt-5">
                <div className="flex items-center justify-between text-xs font-bold text-slate-600"><span className="capitalize">{simulation.status}</span><span>{Math.round(simulation.progress * 100)}%</span></div>
                <div className="mt-2 h-2 overflow-hidden rounded-full bg-slate-200"><div className="h-full rounded-full bg-cyan-600 transition-all" style={{ width: `${Math.max(2, simulation.progress * 100)}%` }} /></div>
                <p className="mt-3 break-all text-[11px] text-slate-400">{simulation.simulationJobId}</p>
                {simulation.error?.message ? <p className="mt-3 rounded-xl bg-red-50 p-3 text-xs text-red-800">{simulation.error.message}</p> : null}
              </div>
            ) : null}
          </section>
          <section className={cardClass}>
            <SectionHeader eyebrow="Operating characteristics" title="What should this design detect under its assumptions?" description="These metrics never masquerade as observed experimental results." />
            {simulation?.status === "complete" ? (
              <>
                <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
                  <Metric label="Empirical power" value={`${((simulation.results.empiricalPower ?? 0) * 100).toFixed(1)}%`} />
                  <Metric label="False-negative rate" value={`${((simulation.results.falseNegativeRate ?? 0) * 100).toFixed(1)}%`} />
                  <Metric label="Wrong-direction rate" value={`${((simulation.results.wrongDirectionRate ?? 0) * 100).toFixed(2)}%`} />
                  <Metric label="Iterations" value={simulation.iterations.toLocaleString()} detail={`Seed ${simulation.seed}`} />
                </div>
                <div className="mt-5 rounded-xl border border-violet-200 bg-violet-50 p-4 text-sm leading-6 text-violet-950"><FlaskConical className="mb-2 h-5 w-5" />{simulation.results.warning}</div>
              </>
            ) : <div className="flex min-h-64 items-center justify-center rounded-xl border border-dashed border-slate-300 bg-slate-50 text-center text-sm text-slate-500">Run a simulation to populate operating-characteristic evidence.</div>}
          </section>
        </div>
      );
    }
    if (activeStepNumber === 10) {
      return (
        <div className="space-y-5">
          <div className="grid gap-5 xl:grid-cols-[0.62fr_1.38fr]">
            <section className={cardClass}>
              <SectionHeader eyebrow="Observed input" title="Match responses to generated run IDs" description="Paste runId,response pairs. ATLAS will not infer observed results from simulations." />
              {syntheticInput ? <p className="mb-3 rounded-xl border border-violet-300 bg-violet-50 p-3 text-xs font-bold text-violet-900">SYNTHETIC TEST INPUT — not operational experiment evidence.</p> : null}
              <TextArea label="Observed response CSV" value={observationText} onChange={(value) => { setObservationText(value); setSyntheticInput(false); }} rows={12} placeholder={"runId,response\nR0001,10.4\nR0002,11.1"} />
              <div className="mt-3 grid gap-2 sm:grid-cols-2">
                <button className={secondaryButton} disabled={!design} onClick={populateSyntheticObservations}><FlaskConical className="h-4 w-4" /> Synthetic test data</button>
                <button className={primaryButton} disabled={!observationText.trim() || Boolean(working)} onClick={analyze}>{working === "observed analysis" ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />} Analyze observed data</button>
              </div>
            </section>
            <section className={cardClass}>
              <SectionHeader eyebrow="ANOVA evidence" title="Treatment variation versus residual variation" description="The backend reports explicit degrees of freedom and leaves unavailable statistics blank." />
              {analysis ? <ExactTable rows={analysis.anovaTable} columns={["source", "df", "sumSquares", "meanSquare", "f", "p"]} caption="ANOVA table" /> : <div className="flex min-h-64 items-center justify-center rounded-xl border border-dashed border-slate-300 bg-slate-50 text-center text-sm text-slate-500">No observed-response analysis is available.</div>}
            </section>
          </div>
          <div className="grid gap-5 xl:grid-cols-2">
            <section className={cardClass}><SectionHeader eyebrow="Effects" title="Main and interaction effect ranking" description="Magnitude supports triage; practical and statistical significance still require analyst review." /><EffectParetoChart analysis={analysis} /></section>
            <section className={cardClass}><SectionHeader eyebrow="Diagnostics" title="Residuals versus fitted response" description="Pattern, spread, and outliers reveal model limitations." /><ResidualPlot analysis={analysis} /></section>
          </div>
        </div>
      );
    }
    if (activeStepNumber === 11) {
      return (
        <div className="grid gap-5 xl:grid-cols-[1.05fr_0.95fr]">
          <section className={cardClass}>
            <SectionHeader eyebrow="Decision translation" title="Recommend only what the evidence supports" description="Optimization is available only from observed cells; simulation output is never substituted." />
            {analysis ? (
              <div className="rounded-2xl bg-slate-950 p-6 text-white">
                <p className="text-xs font-black uppercase tracking-[0.16em] text-cyan-300">Best observed treatment cell</p>
                <p className="mt-3 text-xl font-black">{analysis.recommendation.bestObservedCell}</p>
                <p className="mt-2 text-3xl font-black text-cyan-300">{analysis.recommendation.meanResponse.toFixed(4)}</p>
                <p className="mt-4 text-sm leading-6 text-slate-300">{analysis.recommendation.basis}</p>
              </div>
            ) : <div className="rounded-xl border border-amber-300 bg-amber-50 p-5 text-sm leading-6 text-amber-950"><AlertTriangle className="mb-2 h-5 w-5" />No observed analysis exists. ATLAS will not fabricate an optimal configuration from the design plan or simulation.</div>}
            <div className="mt-5">
              <TextArea label="Decision / rollout rationale" value={contract.objective.decision} onChange={(value) => patchContract((current) => ({ ...current, objective: { ...current.objective, decision: value } }))} rows={5} />
            </div>
          </section>
          <section className={cardClass}>
            <SectionHeader eyebrow="Limitations" title="Record the boundary of the recommendation" description="One limitation per line becomes part of the versioned reproducibility and documentation package." />
            <TextArea label="Known limitations" value={contract.limitations.join("\n")} onChange={(value) => patchContract((current) => ({ ...current, limitations: value.split(/\r?\n/).map((item) => item.trim()).filter(Boolean) }))} rows={12} placeholder={"Limited to the eligible population\nNo evidence outside tested factor ranges\nResidual degrees of freedom are limited"} />
            {analysis?.warnings?.map((warning) => <p key={warning} className="mt-3 rounded-xl bg-amber-50 px-4 py-3 text-xs leading-5 text-amber-900">{warning}</p>)}
          </section>
        </div>
      );
    }
    return (
      <div className="grid gap-5 xl:grid-cols-[0.72fr_1.28fr]">
        <section className={cardClass}>
          <SectionHeader eyebrow="Evidence package" title="Capture a version-bound documentation snapshot" description="The package records readiness, study version, contract hash, design version, seed, simulation job, analysis, and limitations." />
          <button className={`${primaryButton} w-full`} disabled={Boolean(working)} onClick={captureDocumentation}>{working === "documentation capture" ? <Loader2 className="h-4 w-4 animate-spin" /> : <FileText className="h-4 w-4" />} Generate evidence package</button>
          {documentation ? <div className="mt-5 grid grid-cols-2 gap-3"><Metric label="Readiness" value={`${documentation.readinessScore}%`} /><Metric label="Status" value={documentation.status} /></div> : null}
          <div className="mt-5 rounded-xl border border-slate-200 bg-slate-50 p-4 text-xs leading-5 text-slate-600">
            <p><span className="font-black text-slate-900">Study version:</span> {study.currentVersion}</p>
            <p><span className="font-black text-slate-900">Contract hash:</span> {study.contractHash?.slice(0, 20) || "unsaved"}</p>
            <p><span className="font-black text-slate-900">Design version:</span> {design?.designVersion || "not generated"}</p>
            <p><span className="font-black text-slate-900">Randomization seed:</span> {randomization?.seed ?? "not generated"}</p>
          </div>
        </section>
        <section className={cardClass}>
          <SectionHeader eyebrow="Coverage" title="Documentation readiness by governed section" description="Missing sections remain explicit and cannot be styled as completed evidence." />
          {documentation?.sections?.length ? (
            <div className="space-y-2">
              {documentation.sections.map((section) => (
                <div key={section.title} className="flex items-center justify-between rounded-xl border border-slate-200 px-4 py-3">
                  <span className="text-sm font-bold text-slate-800">{section.title}</span>
                  <span className={`inline-flex items-center gap-1 rounded-full px-2.5 py-1 text-xs font-black ${section.status === "ready" ? "bg-emerald-100 text-emerald-800" : "bg-amber-100 text-amber-800"}`}>{section.status === "ready" ? <Check className="h-3.5 w-3.5" /> : <AlertTriangle className="h-3.5 w-3.5" />}{section.status}</span>
                </div>
              ))}
            </div>
          ) : <div className="flex min-h-64 items-center justify-center rounded-xl border border-dashed border-slate-300 bg-slate-50 text-center text-sm text-slate-500">Generate the package to evaluate coverage.</div>}
        </section>
      </div>
    );
  })();

  const stepBlockers = study.blockers.filter((blocker) => Number(blocker.step) <= activeStepNumber);
  const previous = experimentalDesignJourney[activeStepNumber - 2];
  const next = experimentalDesignJourney[activeStepNumber];

  return (
    <main className="mx-auto w-full max-w-[1700px] px-4 pb-32 pt-5 sm:px-6 lg:px-8">
      <section className="overflow-hidden rounded-[28px] border border-slate-200 bg-white shadow-[0_24px_70px_rgba(15,23,42,0.08)]">
        <div className="bg-[radial-gradient(circle_at_80%_0%,rgba(34,211,238,0.17),transparent_34%),linear-gradient(135deg,#020617,#0f172a_70%,#164e63)] px-5 py-6 text-white sm:px-7">
          <div className="flex flex-wrap items-start justify-between gap-5">
            <div>
              <div className="flex flex-wrap items-center gap-2 text-xs font-black uppercase tracking-[0.16em] text-cyan-300">
                <span>Experimental Design</span><span className="text-slate-600">/</span><span>Step {activeStepNumber} of 12</span>
              </div>
              <h1 className="mt-2 text-2xl font-black tracking-tight sm:text-3xl">{journeyStep.label}</h1>
              <p className="mt-2 max-w-3xl text-sm leading-6 text-slate-300">{journeyStep.question} {journeyStep.purpose}</p>
            </div>
            <div className="flex flex-wrap gap-2 text-xs font-bold">
              <span className="rounded-full border border-slate-700 bg-slate-900/70 px-3 py-1.5">{projectName}</span>
              <span className="rounded-full border border-cyan-800 bg-cyan-950/70 px-3 py-1.5">Study v{study.currentVersion}</span>
              <span className={`rounded-full border px-3 py-1.5 ${dirty ? "border-amber-500 bg-amber-950/70 text-amber-200" : "border-emerald-700 bg-emerald-950/60 text-emerald-200"}`}>{dirty ? "Unsaved changes" : "Backend current"}</span>
            </div>
          </div>
          <nav aria-label="Experimental Design workflow steps" className="mt-6 overflow-x-auto pb-1">
            <ol className="flex min-w-max gap-2">
              {experimentalDesignJourney.map((step) => {
                const selected = step.stepNumber === activeStepNumber;
                const blocked = study.blockers.some((blocker) => Number(blocker.step) === step.stepNumber);
                return (
                  <li key={step.id}>
                    <button
                      onClick={() => navigate(step.route)}
                      aria-current={selected ? "step" : undefined}
                      className={`flex min-h-11 items-center gap-2 rounded-xl border px-3 text-left transition ${selected ? "border-cyan-300 bg-cyan-300 text-slate-950" : "border-slate-700 bg-slate-900/60 text-slate-300 hover:border-slate-500 hover:text-white"}`}
                    >
                      <span className={`flex h-6 w-6 items-center justify-center rounded-full text-[11px] font-black ${selected ? "bg-slate-950 text-white" : blocked ? "bg-amber-950 text-amber-300" : "bg-slate-800 text-slate-300"}`}>{step.stepNumber}</span>
                      <span className="max-w-32 text-xs font-bold">{step.shortLabel}</span>
                    </button>
                  </li>
                );
              })}
            </ol>
          </nav>
        </div>
        <div className="grid gap-4 border-b border-slate-200 bg-slate-50 px-5 py-4 sm:grid-cols-2 lg:grid-cols-5 sm:px-7">
          <div><p className="text-[10px] font-black uppercase tracking-wider text-slate-500">Primary response</p><p className="mt-1 truncate text-sm font-bold text-slate-900">{contract.objective.primaryResponse.name || "Not defined"}</p></div>
          <div><p className="text-[10px] font-black uppercase tracking-wider text-slate-500">Factors</p><p className="mt-1 text-sm font-bold text-slate-900">{contract.factors.length} controlled · {contract.nuisanceFactors.length} nuisance</p></div>
          <div><p className="text-[10px] font-black uppercase tracking-wider text-slate-500">Design</p><p className="mt-1 text-sm font-bold capitalize text-slate-900">{contract.design.family ? contract.design.family.replaceAll("_", " ") : "Not confirmed"}</p></div>
          <div><p className="text-[10px] font-black uppercase tracking-wider text-slate-500">Artifacts</p><p className="mt-1 text-sm font-bold text-slate-900">{Object.keys(study.artifacts).length} current</p></div>
          <div><p className="text-[10px] font-black uppercase tracking-wider text-slate-500">Open blockers</p><p className={`mt-1 text-sm font-bold ${study.blockers.length ? "text-amber-700" : "text-emerald-700"}`}>{study.blockers.length}</p></div>
        </div>
      </section>

      {error ? <div role="alert" className="mt-5 flex items-start gap-3 rounded-2xl border border-red-300 bg-red-50 p-4 text-sm text-red-900"><AlertTriangle className="mt-0.5 h-5 w-5 shrink-0" /><div><p className="font-black">Action could not be completed</p><p className="mt-1">{error}</p></div></div> : null}
      {notice ? <div role="status" className="mt-5 flex items-start gap-3 rounded-2xl border border-emerald-300 bg-emerald-50 p-4 text-sm text-emerald-900"><Check className="mt-0.5 h-5 w-5 shrink-0" /><p className="font-bold">{notice}</p></div> : null}
      {stepBlockers.length ? <div className="mt-5 rounded-2xl border border-amber-300 bg-amber-50 p-4"><p className="text-xs font-black uppercase tracking-[0.14em] text-amber-800">Contract blockers through this step</p><ul className="mt-2 space-y-1 text-sm text-amber-950">{stepBlockers.map((blocker) => <li key={blocker.code} className="flex gap-2"><AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />{blocker.message}</li>)}</ul></div> : null}

      <div className="mt-5">{stepBody}</div>

      <section className="mt-5 grid gap-4 lg:grid-cols-[1fr_340px]">
        <div className="rounded-2xl border border-slate-200 bg-white p-4">
          <p className="text-xs font-black uppercase tracking-[0.12em] text-slate-500">What this page changes</p>
          <p className="mt-2 text-sm text-slate-700">{journeyStep.output} {journeyStep.transition}</p>
        </div>
        <div className="rounded-2xl border border-slate-200 bg-white p-4">
          <p className="text-xs font-black uppercase tracking-[0.12em] text-slate-500">Version history</p>
          <p className="mt-2 text-sm font-bold text-slate-900">{versions.length || study.currentVersion} immutable contract snapshot(s)</p>
          <p className="mt-1 text-xs text-slate-500">Changing upstream assumptions invalidates affected downstream artifacts.</p>
        </div>
      </section>

      <div className="fixed inset-x-0 bottom-0 z-30 border-t border-slate-200 bg-white/95 px-4 py-3 shadow-[0_-14px_40px_rgba(15,23,42,0.1)] backdrop-blur-xl lg:pl-[calc(var(--atlas-sidebar-width,0px)+1rem)]">
        <div className="mx-auto flex w-full max-w-[1700px] flex-wrap items-center justify-between gap-3">
          <div className="flex gap-2">
            <button className={secondaryButton} disabled={!previous} onClick={() => previous && navigate(previous.route)}><ArrowLeft className="h-4 w-4" /> Back</button>
            <button className={secondaryButton} disabled={Boolean(working) || !dirty} onClick={() => void persist(`Saved ${journeyStep.label} draft.`)}>{working === "save" ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />} Save draft</button>
          </div>
          <div className="flex items-center gap-3">
            <span className="hidden text-xs font-bold text-slate-500 sm:inline">{next ? `Next: ${next.label}` : "Final workflow step"}</span>
            <button className={`${primaryButton} min-w-48`} disabled={Boolean(working)} onClick={saveAndContinue}>{working === "save" ? <Loader2 className="h-4 w-4 animate-spin" /> : next ? <ArrowRight className="h-4 w-4" /> : <ShieldCheck className="h-4 w-4" />}{next ? "Save & continue" : "Save final study"}</button>
          </div>
        </div>
      </div>
    </main>
  );
}

export default function ExperimentalDesignWorkflowPage() {
  const { workflowId } = useParams();
  if (workflowId === "time_series_forecasting") return <TimeSeriesWorkflowPage />;
  if (workflowId === "llm_generative_ai") return <LlmWorkflowPage />;
  if (workflowId === "experimental-design") return <ExperimentalDesignWorkspace />;
  return <WorkflowPlaceholderStep />;
}
