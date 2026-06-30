import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import StepShell from "../components/StepShell";
import { logDecision } from "../lib/decisionJournal";
import {
  buildDataAccessMetadata,
  inferDataQuality,
  loadDataAccessMetadata,
  loadDatasetVersions,
  queryTemplates,
  recordDatasetVersion,
  saveDataAccessMetadata,
  validateSql,
  type DataAccessMetadata,
  type DataQualitySummary,
  type DataSourceType,
  type SamplingMethod,
} from "../lib/enterpriseDataAccess";
import { saveLocalDataset, type LocalDataset } from "../lib/localDataset";
import { useWorkflowStore } from "../state/useWorkflowStore";

const BASE =
  (import.meta.env?.VITE_API_BASE as string | undefined)?.replace(/\/$/, "") ||
  "http://127.0.0.1:8001/api";

const sourceCards: { id: DataSourceType; title: string; body: string }[] = [
  { id: "upload", title: "Upload File", body: "CSV and JSON parse locally. Excel, Parquet, Feather, SAS, Pickle, and ZIP are staged for backend import." },
  { id: "sql", title: "SQL Database", body: "Author governed SQL, validate queries, capture lineage, and generate Python extraction code." },
  { id: "cloud", title: "Cloud Storage", body: "Document S3, Azure Blob, GCS, SharePoint, or OneDrive paths for governed ingestion." },
  { id: "existing", title: "Existing Dataset", body: "Reuse previously imported project datasets and preserve dataset version history." },
  { id: "python", title: "Python Loader", body: "Advanced users can document Python or Spark loading logic that assigns the final dataframe to df." },
];

const databaseProviders = ["Oracle", "SQL Server", "PostgreSQL", "MySQL", "Snowflake", "BigQuery", "Databricks SQL", "Teradata", "SQLite", "DuckDB"];
const cloudProviders = ["AWS S3", "Azure Blob Storage", "Google Cloud Storage", "SharePoint", "OneDrive"];

function parseDelimitedLine(line: string) {
  const out: string[] = [];
  let cur = "";
  let inQuotes = false;
  for (let i = 0; i < line.length; i++) {
    const c = line[i];
    if (c === '"') inQuotes = !inQuotes;
    else if (c === "," && !inQuotes) {
      out.push(cur);
      cur = "";
    } else {
      cur += c;
    }
  }
  out.push(cur);
  return out.map((value) => value.replace(/^"(.*)"$/s, "$1").trim());
}

function coerce(value: string) {
  if (value === "") return "";
  const numeric = Number(value);
  return Number.isFinite(numeric) ? numeric : value;
}

function parseCSV(text: string) {
  const lines = text.replace(/\r/g, "").split("\n").filter((line) => line.trim().length);
  if (!lines.length) return { headers: [] as string[], rows: [] as Record<string, unknown>[] };
  const headers = parseDelimitedLine(lines[0]);
  const rows = lines.slice(1).map((line) => {
    const values = parseDelimitedLine(line);
    const row: Record<string, unknown> = {};
    headers.forEach((header, index) => {
      row[header] = coerce(values[index] ?? "");
    });
    return row;
  });
  return { headers, rows };
}

function parseJSON(text: string) {
  const parsed = JSON.parse(text);
  const rows = Array.isArray(parsed) ? parsed : Array.isArray(parsed?.data) ? parsed.data : [];
  if (!Array.isArray(rows) || !rows.length) return { headers: [] as string[], rows: [] as Record<string, unknown>[] };
  const headers = Array.from(new Set(rows.flatMap((row) => Object.keys(row ?? {}))));
  return { headers, rows: rows as Record<string, unknown>[] };
}

function isNumericVector(vals: unknown[]) {
  const nonMissing = vals.filter((value) => value !== null && value !== undefined && String(value).trim() !== "");
  if (!nonMissing.length) return false;
  return nonMissing.filter((value) => Number.isFinite(Number(value))).length / nonMissing.length >= 0.6;
}

function targetMeta(rows: Record<string, unknown>[], target: string) {
  if (!target) return { kind: "none" as const, eventRate: null as number | null };
  const vals = rows.map((row) => row[target]);
  if (!isNumericVector(vals)) {
    const counts = new Map<string, number>();
    vals.forEach((value) => counts.set(String(value), (counts.get(String(value)) ?? 0) + 1));
    const sorted = Array.from(counts.values()).sort((a, b) => b - a);
    const total = sorted.reduce((sum, count) => sum + count, 0);
    const event = total - (sorted[0] ?? 0);
    return { kind: "binary" as const, eventRate: total ? event / total : null };
  }
  const ones = vals.filter((value) => Number(value) === 1).length;
  const zeros = vals.filter((value) => Number(value) === 0).length;
  if (ones + zeros >= vals.length * 0.8) return { kind: "binary" as const, eventRate: vals.length ? ones / vals.length : null };
  return { kind: "continuous" as const, eventRate: null };
}

function summarizeColumn(rows: Record<string, unknown>[], column: string, target: string) {
  const values = rows.map((row) => row[column]);
  const missing = values.filter((value) => value === null || value === undefined || String(value).trim() === "").length;
  const numeric = isNumericVector(values);
  const distinct = new Set(values.map(String)).size;
  if (!numeric) return { type: "Categorical", missingPct: rows.length ? missing / rows.length : 0, distinct, mean: null, min: null, max: null };
  const nums = values.map(Number).filter(Number.isFinite);
  const mean = nums.length ? nums.reduce((sum, value) => sum + value, 0) / nums.length : null;
  return {
    type: column === target ? "Target" : "Numeric",
    missingPct: rows.length ? missing / rows.length : 0,
    distinct,
    mean,
    min: nums.length ? Math.min(...nums) : null,
    max: nums.length ? Math.max(...nums) : null,
  };
}

function formatNumber(value: unknown, digits = 4) {
  const numeric = Number(value);
  return Number.isFinite(numeric) ? numeric.toFixed(digits) : "-";
}

function formatPercent(value: unknown) {
  const numeric = Number(value);
  return Number.isFinite(numeric) ? `${(numeric * 100).toFixed(2)}%` : "-";
}

function applySampling(rows: Record<string, unknown>[], method: SamplingMethod, detail: string) {
  const n = Number(detail) || 1000;
  if (method === "top_n") return rows.slice(0, Math.max(1, n));
  if (method === "sample") return rows.slice(0, Math.min(rows.length, Math.max(1, n)));
  if (method === "random") return [...rows].sort(() => Math.random() - 0.5).slice(0, Math.min(rows.length, Math.max(1, n)));
  return rows;
}

export default function Step01DataAcquisition() {
  const navigate = useNavigate();
  const [sourceType, setSourceType] = useState<DataSourceType>("upload");
  const [headers, setHeaders] = useState<string[]>([]);
  const [rows, setRows] = useState<Record<string, unknown>[]>([]);
  const [fileName, setFileName] = useState("");
  const [message, setMessage] = useState("");
  const [target, setTarget] = useState("");
  const [kept, setKept] = useState<Record<string, boolean>>({});
  const [samplingMethod, setSamplingMethod] = useState<SamplingMethod>("full");
  const [samplingDetail, setSamplingDetail] = useState("1000");
  const [connectionName, setConnectionName] = useState("Development connection");
  const [provider, setProvider] = useState("Oracle");
  const [database, setDatabase] = useState("");
  const [schema, setSchema] = useState("");
  const [sql, setSql] = useState(queryTemplates()[0].sql);
  const [savedQueries, setSavedQueries] = useState<string[]>([]);
  const [favoriteQueries, setFavoriteQueries] = useState<string[]>([]);
  const [cloudProvider, setCloudProvider] = useState("AWS S3");
  const [cloudPath, setCloudPath] = useState("");
  const [pythonCode, setPythonCode] = useState("import pandas as pd\n\n# Assign final dataframe to df\n# df = pd.read_sql(...)\n");
  const [metadata, setMetadata] = useState<DataAccessMetadata | null>(() => loadDataAccessMetadata());
  const [quality, setQuality] = useState<DataQualitySummary | null>(null);
  const datasetVersions = loadDatasetVersions();

  const sampleRows = useMemo(() => applySampling(rows, samplingMethod, samplingDetail).slice(0, 5000), [rows, samplingMethod, samplingDetail]);
  const previewRows = sampleRows.slice(0, 100);
  const targetInfo = useMemo(() => targetMeta(sampleRows, target), [sampleRows, target]);
  const selectable = headers.filter((header) => header !== target);
  const selected = selectable.filter((header) => kept[header]);
  const sqlWarnings = useMemo(() => validateSql(sql), [sql]);
  const generatedMetadata = useMemo(() => {
    if (!headers.length) return null;
    return buildDataAccessMetadata({
      dataset: { headers, rows: sampleRows, target },
      sourceType,
      sourceLabel: sourceType === "sql" ? `${provider} SQL` : sourceType === "cloud" ? cloudProvider : sourceType === "python" ? "Python loader" : fileName || "Uploaded file",
      fileName,
      fileType: fileName.split(".").pop(),
      connectionName,
      provider,
      database,
      schema,
      sqlQuery: sourceType === "sql" ? sql : undefined,
      cloudProvider: sourceType === "cloud" ? cloudProvider : undefined,
      cloudPath: sourceType === "cloud" ? cloudPath : undefined,
      pythonCode: sourceType === "python" ? pythonCode : undefined,
      samplingMethod,
      samplingDetail,
    });
  }, [headers, sampleRows, target, sourceType, provider, cloudProvider, fileName, connectionName, database, schema, sql, cloudPath, pythonCode, samplingMethod, samplingDetail]);

  const variableSummary = useMemo(
    () =>
      headers.map((column) => ({
        column,
        ...summarizeColumn(sampleRows, column, target),
      })),
    [headers, sampleRows, target]
  );

  async function onFile(file: File) {
    setMessage("");
    setFileName(file.name);
    const extension = file.name.split(".").pop()?.toLowerCase() ?? "";
    const textFormats = ["csv", "txt", "json"];
    if (!textFormats.includes(extension)) {
      setMessage(`${extension.toUpperCase()} files are recognized but require backend parser support before they can be loaded into the browser preview.`);
      return;
    }
    try {
      const text = await file.text();
      const parsed = extension === "json" ? parseJSON(text) : parseCSV(text);
      setHeaders(parsed.headers);
      setRows(parsed.rows);
      const keep: Record<string, boolean> = {};
      parsed.headers.forEach((header) => {
        keep[header] = true;
      });
      setKept(keep);
      const guessedTarget =
        parsed.headers.find((header) => /^(target|label|class|bad|default|fraud|response|outcome|event)$/i.test(header)) ??
        parsed.headers.find((header) => /target|label|outcome/i.test(header)) ??
        "";
      setTarget(guessedTarget);
      const dq = inferDataQuality({ headers: parsed.headers, rows: parsed.rows.slice(0, 5000), target: guessedTarget || null });
      setQuality(dq);
      logDecision({
        workflowStep: "Data Acquisition",
        actionType: "workflow_setting_changed",
        subject: "Data source",
        previousValue: metadata?.sourceLabel,
        newValue: `Uploaded ${file.name}`,
        systemRecommendation: "Capture data source, version, sampling method, and data quality immediately after import.",
        followStatus: "followed",
      });
    } catch (err: any) {
      setMessage(err?.message ?? "Unable to parse file.");
    }
  }

  function saveQueryMetadata() {
    const stubHeaders = ["customer_id", "observation_date", "target", "feature_1", "feature_2"];
    const stubRows: Record<string, unknown>[] = [];
    setHeaders(stubHeaders);
    setRows(stubRows);
    const keep: Record<string, boolean> = {};
    stubHeaders.forEach((header) => {
      keep[header] = header !== "target";
    });
    setKept(keep);
    setTarget("target");
    setMessage("SQL metadata saved. Real query execution requires a backend connector; upload query output or connect the backend to populate rows.");
  }

  async function persistDataset() {
    if (!headers.length) throw new Error("No dataset or query metadata is available.");
    const selectedColumns = selected.length ? selected : selectable;
    const meta = generatedMetadata;
    const dq = quality ?? inferDataQuality({ headers, rows: sampleRows, target: target || null });
    const payload: LocalDataset = {
      headers,
      rows: sampleRows,
      target: target || null,
      selected_columns: selectedColumns,
      problem_type: targetInfo.kind === "continuous" ? "regression" : "classification",
      data_access: meta ?? undefined,
      data_quality: dq,
    };
    const localSaveStatus = saveLocalDataset(payload);
    if (meta) {
      saveDataAccessMetadata(meta);
      recordDatasetVersion(payload, meta);
      setMetadata(meta);
    }
    setQuality(dq);
    useWorkflowStore.setState((state: any) => ({
      ...state,
      hasDataset: rows.length > 0 || headers.length > 0,
      trainSpec: {
        ...(state?.trainSpec ?? {}),
        data: {
          ...(state?.trainSpec?.data ?? {}),
          source: sourceType,
          n_samples: sampleRows.length,
          task: targetInfo.kind === "continuous" ? "regression" : "binary",
          target,
          selected_columns: selectedColumns,
          dataset_version: meta?.version,
        },
      },
    }));

    window.setTimeout(() => {
      fetch(`${BASE}/data/set_sample`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      }).catch((err) => console.error("set_sample error:", err));
    }, 0);

    if (localSaveStatus === "sample") setMessage("A browser sample was cached for fast EDA. Full execution remains a backend responsibility for enterprise sources.");
    logDecision({
      workflowStep: "Data Acquisition",
      actionType: "workflow_setting_changed",
      subject: "Dataset version",
      previousValue: metadata?.version,
      newValue: meta?.version,
      systemRecommendation: "Use dataset version, hash, source, query, and sampling metadata in model governance documentation.",
      followStatus: "followed",
    });
  }

  return (
    <StepShell
      title="Step 1: Data Access & Data Acquisition"
      subtitle="Connect to enterprise data sources, validate extraction logic, preview data, capture lineage, and persist the governed modeling dataset."
      nextDisabled={!headers.length}
      onNext={async () => {
        await persistDataset();
        navigate("/step01b");
      }}
    >
      <div className="space-y-5">
        {message && <div className="rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900">{message}</div>}

        <section className="grid gap-3 md:grid-cols-5">
          {sourceCards.map((card) => (
            <button
              key={card.id}
              type="button"
              className={`rounded-xl border p-4 text-left shadow-sm transition ${sourceType === card.id ? "border-slate-950 bg-white" : "border-slate-200 bg-white/80 hover:bg-white"}`}
              onClick={() => setSourceType(card.id)}
            >
              <div className="text-sm font-semibold text-slate-950">{card.title}</div>
              <p className="mt-2 text-xs leading-5 text-slate-500">{card.body}</p>
            </button>
          ))}
        </section>

        <section className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
          {sourceType === "upload" && (
            <UploadPanel fileName={fileName} onFile={onFile} />
          )}
          {sourceType === "sql" && (
            <SqlPanel
              provider={provider}
              setProvider={setProvider}
              connectionName={connectionName}
              setConnectionName={setConnectionName}
              database={database}
              setDatabase={setDatabase}
              schema={schema}
              setSchema={setSchema}
              sql={sql}
              setSql={setSql}
              warnings={sqlWarnings}
              savedQueries={savedQueries}
              favoriteQueries={favoriteQueries}
              onTemplate={(template) => setSql(template)}
              onSave={() => setSavedQueries((current) => [sql, ...current].slice(0, 8))}
              onFavorite={() => setFavoriteQueries((current) => [sql, ...current.filter((item) => item !== sql)].slice(0, 5))}
              onSaveMetadata={saveQueryMetadata}
            />
          )}
          {sourceType === "cloud" && (
            <CloudPanel cloudProvider={cloudProvider} setCloudProvider={setCloudProvider} cloudPath={cloudPath} setCloudPath={setCloudPath} />
          )}
          {sourceType === "existing" && (
            <ExistingDatasetPanel versions={datasetVersions} />
          )}
          {sourceType === "python" && (
            <PythonPanel pythonCode={pythonCode} setPythonCode={setPythonCode} />
          )}
        </section>

        <section className="grid gap-4 xl:grid-cols-[1.1fr_0.9fr]">
          <DataPreview
            headers={headers}
            rows={previewRows}
            target={target}
            setTarget={(next) => {
              logDecision({
                workflowStep: "Data Acquisition",
                actionType: "target_variable_selected",
                subject: "Target variable",
                previousValue: target,
                newValue: next,
              });
              setTarget(next);
              if (rows.length) setQuality(inferDataQuality({ headers, rows: rows.slice(0, 5000), target: next || null }));
            }}
            samplingMethod={samplingMethod}
            setSamplingMethod={setSamplingMethod}
            samplingDetail={samplingDetail}
            setSamplingDetail={setSamplingDetail}
            targetInfo={targetInfo}
          />
          <DataQualityPanel quality={quality} metadata={generatedMetadata ?? metadata} />
        </section>

        {!!headers.length && (
          <section className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
            <div className="flex items-center justify-between gap-3">
              <div>
                <h2 className="text-base font-semibold text-slate-950">Variable Summary</h2>
                <p className="mt-1 text-sm text-slate-500">Review data types, missingness, distinct counts, and selected model inputs.</p>
              </div>
              <div className="flex gap-2">
                <button className="rounded-lg border px-3 py-2 text-sm" onClick={() => setKept(Object.fromEntries(headers.map((header) => [header, header !== target])))}>Select all</button>
                <button className="rounded-lg border px-3 py-2 text-sm" onClick={() => setKept(Object.fromEntries(headers.map((header) => [header, false])))}>None</button>
              </div>
            </div>
            <div className="mt-4 max-h-[560px] overflow-auto rounded-lg border border-slate-200">
              <table className="min-w-full text-sm">
                <thead className="sticky top-0 bg-slate-50 text-xs uppercase text-slate-500">
                  <tr>
                    <th className="px-3 py-2 text-center">Keep</th>
                    <th className="px-3 py-2 text-left">Column</th>
                    <th className="px-3 py-2 text-left">Type</th>
                    <th className="px-3 py-2 text-right">Missing %</th>
                    <th className="px-3 py-2 text-right">Distinct</th>
                    <th className="px-3 py-2 text-right">Mean</th>
                    <th className="px-3 py-2 text-right">Min</th>
                    <th className="px-3 py-2 text-right">Max</th>
                  </tr>
                </thead>
                <tbody>
                  {variableSummary.map((row) => (
                    <tr key={row.column} className="border-t">
                      <td className="px-3 py-2 text-center">
                        {row.column === target ? <span className="text-xs text-slate-400">target</span> : (
                          <input
                            type="checkbox"
                            checked={!!kept[row.column]}
                            onChange={(event) => {
                              setKept((current) => ({ ...current, [row.column]: event.target.checked }));
                              logDecision({
                                workflowStep: "Data Acquisition",
                                actionType: "feature_inclusion_changed",
                                subject: row.column,
                                previousValue: kept[row.column] ? "included" : "excluded",
                                newValue: event.target.checked ? "included" : "excluded",
                              });
                            }}
                          />
                        )}
                      </td>
                      <td className="px-3 py-2 font-medium">{row.column}</td>
                      <td className="px-3 py-2">{row.type}</td>
                      <td className="px-3 py-2 text-right">{formatPercent(row.missingPct)}</td>
                      <td className="px-3 py-2 text-right">{row.distinct.toLocaleString()}</td>
                      <td className="px-3 py-2 text-right">{formatNumber(row.mean)}</td>
                      <td className="px-3 py-2 text-right">{formatNumber(row.min)}</td>
                      <td className="px-3 py-2 text-right">{formatNumber(row.max)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        )}

        <section className="grid gap-4 lg:grid-cols-2">
          <LineagePanel metadata={generatedMetadata ?? metadata} />
          <PythonSyncPanel metadata={generatedMetadata ?? metadata} />
        </section>
      </div>
    </StepShell>
  );
}

function UploadPanel({ fileName, onFile }: { fileName: string; onFile: (file: File) => void }) {
  return (
    <div>
      <h2 className="text-base font-semibold text-slate-950">Upload File</h2>
      <p className="mt-1 text-sm text-slate-500">Supported source types: CSV, Excel, Parquet, Feather, JSON, SAS datasets, Pickle, and ZIP. CSV and JSON parse locally today.</p>
      <div className="mt-4 flex flex-wrap items-center gap-3">
        <label className="cursor-pointer rounded-lg bg-slate-950 px-4 py-2 text-sm font-semibold text-white">
          Choose File
          <input className="hidden" type="file" accept=".csv,.txt,.json,.xlsx,.xls,.parquet,.feather,.sas7bdat,.pkl,.zip" onChange={(event) => event.target.files?.[0] && onFile(event.target.files[0])} />
        </label>
        <span className="text-sm text-slate-600">{fileName || "No file selected"}</span>
      </div>
    </div>
  );
}

function SqlPanel(props: {
  provider: string;
  setProvider: (value: string) => void;
  connectionName: string;
  setConnectionName: (value: string) => void;
  database: string;
  setDatabase: (value: string) => void;
  schema: string;
  setSchema: (value: string) => void;
  sql: string;
  setSql: (value: string) => void;
  warnings: string[];
  savedQueries: string[];
  favoriteQueries: string[];
  onTemplate: (sql: string) => void;
  onSave: () => void;
  onFavorite: () => void;
  onSaveMetadata: () => void;
}) {
  return (
    <div className="grid gap-4 xl:grid-cols-[280px_minmax(0,1fr)]">
      <aside className="rounded-lg border border-slate-200 bg-slate-50 p-3">
        <h2 className="text-sm font-semibold text-slate-950">Database Explorer</h2>
        <div className="mt-3 space-y-2 text-sm text-slate-700">
          <div className="font-medium">{props.provider}</div>
          <div className="pl-3">Connection: {props.connectionName}</div>
          <div className="pl-3">Schemas</div>
          <div className="pl-6">CUSTOMER_BASE</div>
          <div className="pl-8 text-xs text-slate-500">customer_id PK, open_date, status</div>
          <div className="pl-6">TRANSACTION_HISTORY</div>
          <div className="pl-8 text-xs text-slate-500">customer_id FK, amount, txn_date</div>
          <div className="pl-6">BUREAU_ATTRIBUTES</div>
          <div className="pl-8 text-xs text-slate-500">fico_score, trades, inquiries</div>
        </div>
      </aside>
      <div>
        <div className="grid gap-3 md:grid-cols-4">
          <Select label="Provider" value={props.provider} onChange={props.setProvider} options={databaseProviders} />
          <Input label="Connection Name" value={props.connectionName} onChange={props.setConnectionName} />
          <Input label="Database" value={props.database} onChange={props.setDatabase} />
          <Input label="Schema" value={props.schema} onChange={props.setSchema} />
        </div>
        <div className="mt-4 flex flex-wrap gap-2">
          {queryTemplates().map((template) => (
            <button key={template.name} className="rounded-full border border-slate-300 bg-white px-3 py-1 text-xs font-medium" onClick={() => props.onTemplate(template.sql)}>
              {template.name}
            </button>
          ))}
        </div>
        <textarea
          className="mt-4 min-h-[260px] w-full rounded-lg border border-slate-300 bg-slate-950 p-4 font-mono text-sm text-emerald-100"
          value={props.sql}
          onChange={(event) => props.setSql(event.target.value)}
          spellCheck={false}
        />
        <div className="mt-3 flex flex-wrap gap-2">
          <button className="rounded-lg border px-3 py-2 text-sm" onClick={props.onSave}>Save Query</button>
          <button className="rounded-lg border px-3 py-2 text-sm" onClick={props.onFavorite}>Favorite</button>
          <button className="rounded-lg bg-slate-950 px-3 py-2 text-sm font-semibold text-white" onClick={props.onSaveMetadata}>Validate & Save Query Metadata</button>
        </div>
        {!!props.warnings.length && (
          <div className="mt-3 rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900">
            <div className="font-semibold">Query validation</div>
            <ul className="mt-1 list-disc pl-5">{props.warnings.map((warning) => <li key={warning}>{warning}</li>)}</ul>
          </div>
        )}
        <div className="mt-3 grid gap-3 md:grid-cols-2">
          <QueryList title="Saved Queries" queries={props.savedQueries} />
          <QueryList title="Favorites" queries={props.favoriteQueries} />
        </div>
      </div>
    </div>
  );
}

function CloudPanel({ cloudProvider, setCloudProvider, cloudPath, setCloudPath }: { cloudProvider: string; setCloudProvider: (value: string) => void; cloudPath: string; setCloudPath: (value: string) => void }) {
  return (
    <div>
      <h2 className="text-base font-semibold text-slate-950">Cloud Storage</h2>
      <p className="mt-1 text-sm text-slate-500">Capture cloud data source metadata now. Actual object reads should be handled by backend connectors with governed credentials.</p>
      <div className="mt-4 grid gap-3 md:grid-cols-[240px_minmax(0,1fr)]">
        <Select label="Cloud Provider" value={cloudProvider} onChange={setCloudProvider} options={cloudProviders} />
        <Input label="Path / URL" value={cloudPath} onChange={setCloudPath} placeholder="s3://bucket/path/train.parquet" />
      </div>
    </div>
  );
}

function ExistingDatasetPanel({ versions }: { versions: ReturnType<typeof loadDatasetVersions> }) {
  return (
    <div>
      <h2 className="text-base font-semibold text-slate-950">Existing Project Dataset</h2>
      <p className="mt-1 text-sm text-slate-500">Recent dataset versions are available for audit comparison and reuse planning.</p>
      <div className="mt-4 overflow-auto rounded-lg border border-slate-200">
        <table className="min-w-full text-sm">
          <thead className="bg-slate-50 text-xs uppercase text-slate-500">
            <tr><th className="px-3 py-2 text-left">Version</th><th className="px-3 py-2 text-left">Source</th><th className="px-3 py-2 text-right">Rows</th><th className="px-3 py-2 text-right">Columns</th><th className="px-3 py-2 text-left">Imported</th></tr>
          </thead>
          <tbody>{versions.map((row) => <tr key={row.version} className="border-t"><td className="px-3 py-2 font-mono text-xs">{row.version}</td><td className="px-3 py-2">{row.sourceLabel}</td><td className="px-3 py-2 text-right">{row.rows}</td><td className="px-3 py-2 text-right">{row.columns}</td><td className="px-3 py-2">{new Date(row.importedAt).toLocaleString()}</td></tr>)}</tbody>
        </table>
        {!versions.length && <div className="p-6 text-center text-sm text-slate-500">No dataset versions captured yet.</div>}
      </div>
    </div>
  );
}

function PythonPanel({ pythonCode, setPythonCode }: { pythonCode: string; setPythonCode: (value: string) => void }) {
  return (
    <div>
      <h2 className="text-base font-semibold text-slate-950">Python Loader</h2>
      <p className="mt-1 text-sm text-slate-500">Document advanced loading code. Backend execution can later synchronize the resulting dataframe back into the app.</p>
      <textarea className="mt-4 min-h-[260px] w-full rounded-lg border border-slate-300 bg-slate-950 p-4 font-mono text-sm text-emerald-100" value={pythonCode} onChange={(event) => setPythonCode(event.target.value)} spellCheck={false} />
    </div>
  );
}

function DataPreview(props: {
  headers: string[];
  rows: Record<string, unknown>[];
  target: string;
  setTarget: (value: string) => void;
  samplingMethod: SamplingMethod;
  setSamplingMethod: (value: SamplingMethod) => void;
  samplingDetail: string;
  setSamplingDetail: (value: string) => void;
  targetInfo: { kind: "none" | "binary" | "continuous"; eventRate: number | null };
}) {
  return (
    <section className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 className="text-base font-semibold text-slate-950">Data Preview</h2>
          <p className="mt-1 text-sm text-slate-500">First 100 rows, schema profile, and sampling controls.</p>
        </div>
        <div className="grid gap-2 md:grid-cols-3">
          <Select label="Sampling" value={props.samplingMethod} onChange={(value) => props.setSamplingMethod(value as SamplingMethod)} options={["full", "sample", "random", "stratified", "time_based", "top_n"]} />
          <Input label="Sample detail" value={props.samplingDetail} onChange={props.setSamplingDetail} />
          <Select label="Target" value={props.target} onChange={props.setTarget} options={["", ...props.headers]} />
        </div>
      </div>
      <div className="mt-4 grid gap-3 md:grid-cols-4">
        <Stat label="Rows in Preview" value={props.rows.length} />
        <Stat label="Columns" value={props.headers.length} />
        <Stat label="Target Type" value={props.targetInfo.kind} />
        <Stat label="Event Rate" value={props.targetInfo.eventRate === null ? "-" : formatPercent(props.targetInfo.eventRate)} />
      </div>
      <div className="mt-4 max-h-[360px] overflow-auto rounded-lg border border-slate-200">
        <table className="min-w-full text-xs">
          <thead className="sticky top-0 bg-slate-50 text-slate-500">
            <tr>{props.headers.map((header) => <th key={header} className="whitespace-nowrap px-3 py-2 text-left">{header}</th>)}</tr>
          </thead>
          <tbody>{props.rows.map((row, index) => <tr key={index} className="border-t">{props.headers.map((header) => <td key={header} className="whitespace-nowrap px-3 py-2">{String(row[header] ?? "")}</td>)}</tr>)}</tbody>
        </table>
        {!props.headers.length && <div className="p-8 text-center text-sm text-slate-500">Load data or save SQL metadata to begin.</div>}
      </div>
    </section>
  );
}

function DataQualityPanel({ quality, metadata }: { quality: DataQualitySummary | null; metadata: DataAccessMetadata | null }) {
  return (
    <section className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
      <h2 className="text-base font-semibold text-slate-950">Data Quality Report</h2>
      <p className="mt-1 text-sm text-slate-500">Automatically generated after import and included in governance documentation.</p>
      <div className="mt-4 grid gap-3 md:grid-cols-2">
        <Stat label="Dataset Version" value={metadata?.version ?? "-"} />
        <Stat label="Dataset Hash" value={metadata?.hash ?? "-"} />
        <Stat label="Duplicate Rows" value={quality?.duplicateRows ?? "-"} />
        <Stat label="Memory Estimate" value={quality ? `${quality.memoryEstimateMb.toFixed(2)} MB` : "-"} />
      </div>
      {quality && (
        <div className="mt-4 grid gap-3 text-sm">
          <QualityLine label="Highest Missing Fields" value={quality.missing.slice(0, 5).map((row) => `${row.column} ${formatPercent(row.percent)}`).join(", ") || "-"} />
          <QualityLine label="Potential Leakage" value={quality.potentialLeakageColumns.join(", ") || "-"} />
          <QualityLine label="Constant Columns" value={quality.constantColumns.join(", ") || "-"} />
          <QualityLine label="Near-Zero Variance" value={quality.nearZeroVarianceColumns.join(", ") || "-"} />
          <QualityLine label="High-Cardinality Categoricals" value={quality.highCardinalityCategoricals.join(", ") || "-"} />
          <QualityLine label="Date Ranges" value={quality.dateRanges.map((row) => `${row.column}: ${row.min} to ${row.max}`).join(", ") || "-"} />
        </div>
      )}
    </section>
  );
}

function LineagePanel({ metadata }: { metadata: DataAccessMetadata | null }) {
  return (
    <section className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
      <h2 className="text-base font-semibold text-slate-950">Data Lineage</h2>
      <div className="mt-4 flex flex-wrap items-center gap-2 text-sm">
        {(metadata?.lineage ?? ["Source not captured"]).map((item, index, arr) => (
          <span key={`${item}-${index}`} className="flex items-center gap-2">
            <span className="rounded-full border border-slate-200 bg-slate-50 px-3 py-1">{item}</span>
            {index < arr.length - 1 && <span className="text-slate-400">to</span>}
          </span>
        ))}
      </div>
    </section>
  );
}

function PythonSyncPanel({ metadata }: { metadata: DataAccessMetadata | null }) {
  return (
    <section className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
      <h2 className="text-base font-semibold text-slate-950">Python Synchronization</h2>
      <pre className="mt-4 max-h-[260px] overflow-auto rounded-lg bg-slate-950 p-4 text-xs text-emerald-100">{metadata?.generatedPython ?? "Generated loader code appears after data source metadata is captured."}</pre>
    </section>
  );
}

function Select({ label, value, onChange, options }: { label: string; value: string; onChange: (value: string) => void; options: string[] }) {
  return (
    <label className="grid gap-1 text-xs font-semibold uppercase text-slate-500">
      {label}
      <select className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-normal normal-case text-slate-900" value={value} onChange={(event) => onChange(event.target.value)}>
        {options.map((option) => <option key={option} value={option}>{option || "Select"}</option>)}
      </select>
    </label>
  );
}

function Input({ label, value, onChange, placeholder }: { label: string; value: string; onChange: (value: string) => void; placeholder?: string }) {
  return (
    <label className="grid gap-1 text-xs font-semibold uppercase text-slate-500">
      {label}
      <input className="rounded-lg border border-slate-300 px-3 py-2 text-sm font-normal normal-case text-slate-900" value={value} placeholder={placeholder} onChange={(event) => onChange(event.target.value)} />
    </label>
  );
}

function Stat({ label, value }: { label: string; value: unknown }) {
  return (
    <div className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2">
      <div className="text-xs font-semibold uppercase text-slate-500">{label}</div>
      <div className="mt-1 truncate text-sm font-semibold text-slate-950">{String(value)}</div>
    </div>
  );
}

function QualityLine({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-slate-200 px-3 py-2">
      <div className="text-xs font-semibold uppercase text-slate-500">{label}</div>
      <div className="mt-1 text-slate-800">{value}</div>
    </div>
  );
}

function QueryList({ title, queries }: { title: string; queries: string[] }) {
  return (
    <div className="rounded-lg border border-slate-200 bg-slate-50 p-3">
      <div className="text-xs font-semibold uppercase text-slate-500">{title}</div>
      <div className="mt-2 space-y-2">{queries.length ? queries.map((query, index) => <div key={index} className="truncate text-xs text-slate-600">{query}</div>) : <div className="text-xs text-slate-400">None</div>}</div>
    </div>
  );
}
