import { DATASET_API_BASE } from "./datasetLibrary";

export type NotebookCodeLanguage = "python" | "sql" | "r" | "sas_compatible";
export type NotebookCellType = "markdown" | NotebookCodeLanguage;
export type NotebookCellKind = "markdown" | "code";

export type NotebookCellOutput = {
  ok?: boolean;
  status?: string;
  stdout?: string;
  stderr?: string;
  error?: string;
  runtimeMs?: number;
  returnCode?: number;
  executionCount?: number;
  rows?: Array<Record<string, unknown>>;
  columns?: string[];
  messages?: string[];
  warnings?: string[];
  listing?: string;
  log?: string;
  translatedPython?: string;
  html?: string;
  truncated?: boolean;
  images?: Array<{ mimeType: string; data: string; alt?: string }>;
  tables?: Array<{ title?: string; columns?: string[]; rows?: Array<Record<string, unknown>> }>;
};

export type NotebookCell = {
  cellId: string;
  cellType: NotebookCellType;
  cellKind?: NotebookCellKind;
  language?: NotebookCodeLanguage;
  source: string;
  output?: NotebookCellOutput;
  createdAt?: string;
  updatedAt?: string;
  lastRunAt?: string;
};

export type AtlasNotebook = {
  notebookId?: string;
  name: string;
  description?: string;
  projectId?: string;
  projectName?: string;
  primaryDatasetId?: string;
  primaryVersionId?: string;
  secondaryDatasetId?: string;
  secondaryVersionId?: string;
  createdAt?: string;
  updatedAt?: string;
  createdBy?: string;
  tags?: string[];
  defaultCodeLanguage?: NotebookCodeLanguage;
  cells: NotebookCell[];
};

export type NotebookSummary = {
  notebookId: string;
  name: string;
  projectId?: string;
  projectName?: string;
  primaryDatasetId?: string;
  primaryVersionId?: string;
  createdAt?: string;
  updatedAt?: string;
  cellCount: number;
  lastRunStatus: string;
};

export type NotebookRunResult = {
  ok: boolean;
  status: string;
  output: NotebookCellOutput;
  runtimeMs: number;
  warnings?: string[];
  error?: string;
};

async function jsonFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${DATASET_API_BASE}${path}`, {
    credentials: "include",
    ...init,
    headers: {
      ...(init?.body instanceof FormData ? {} : { "Content-Type": "application/json" }),
      ...(init?.headers ?? {}),
    },
  });
  const payload = await response.json().catch(() => null);
  if (!response.ok || payload?.ok === false) {
    throw new Error(payload?.detail ?? payload?.error ?? `ATLAS notebook request failed with HTTP ${response.status}.`);
  }
  return payload as T;
}

export const NOTEBOOK_CODE_LANGUAGES: Array<{ value: NotebookCodeLanguage; label: string }> = [
  { value: "python", label: "Python" },
  { value: "sql", label: "SQL" },
  { value: "r", label: "R" },
  { value: "sas_compatible", label: "SAS-compatible" },
];

export function isCodeLanguage(value: string | undefined): value is NotebookCodeLanguage {
  return value === "python" || value === "sql" || value === "r" || value === "sas_compatible";
}

export function effectiveCellKind(cell: Pick<NotebookCell, "cellType" | "cellKind">): NotebookCellKind {
  return cell.cellKind || (cell.cellType === "markdown" ? "markdown" : "code");
}

export function effectiveCellLanguage(cell: Pick<NotebookCell, "cellType" | "language">, fallback: NotebookCodeLanguage = "python"): NotebookCodeLanguage {
  if (isCodeLanguage(cell.language)) return cell.language;
  if (isCodeLanguage(cell.cellType)) return cell.cellType;
  return fallback;
}

export function executionCellType(cell: NotebookCell, fallback: NotebookCodeLanguage = "python"): NotebookCellType {
  return effectiveCellKind(cell) === "markdown" ? "markdown" : effectiveCellLanguage(cell, fallback);
}

export function normalizeNotebook(notebook: AtlasNotebook): AtlasNotebook {
  const firstCodeLanguage = notebook.cells.map((cell) => effectiveCellLanguage(cell, "python")).find((_, index) => effectiveCellKind(notebook.cells[index]) === "code") || "python";
  const defaultCodeLanguage = isCodeLanguage(notebook.defaultCodeLanguage) ? notebook.defaultCodeLanguage : firstCodeLanguage;
  return {
    ...notebook,
    defaultCodeLanguage,
    cells: (notebook.cells || []).map((cell) => {
      const kind = effectiveCellKind(cell);
      const language = kind === "code" ? effectiveCellLanguage(cell, defaultCodeLanguage) : undefined;
      return {
        ...cell,
        cellKind: kind,
        language,
        cellType: kind === "markdown" ? "markdown" : language || defaultCodeLanguage,
      };
    }),
  };
}

export function createNotebookCell(cellType: NotebookCellType, source?: string): NotebookCell {
  const cellKind = cellType === "markdown" ? "markdown" : "code";
  const language = cellKind === "code" ? effectiveCellLanguage({ cellType }) : undefined;
  return {
    cellId: `cell_${Math.random().toString(16).slice(2)}_${Date.now()}`,
    cellType,
    cellKind,
    language,
    source: source ?? defaultSourceForCell(cellType),
    output: { status: "idle" },
  };
}

export function createCodeCell(language: NotebookCodeLanguage, source?: string): NotebookCell {
  return createNotebookCell(language, source ?? defaultSourceForCell(language));
}

export function defaultSourceForCell(cellType: NotebookCellType): string {
  if (cellType === "markdown") {
    return "## Analysis Notes\n\n- Question:\n- Method:\n- Key output:\n- Governance interpretation:";
  }
  if (cellType === "sql") {
    return "SELECT *\nFROM REG_TRAIN\nLIMIT 100;";
  }
  if (cellType === "r") {
    return "print(\"ATLAS R notebook cell\")\nprint(head(df))";
  }
  if (cellType === "sas_compatible") {
    return "proc contents data=work.primary;\nrun;\n\nproc means data=work.primary n mean median std min max;\nrun;";
  }
  return "import pandas as pd\n\ndf = pd.DataFrame(preview_rows)\nprint(\"Rows, columns:\", df.shape)\natlas_display(df.head(), title=\"Preview rows\")";
}

export const CELL_TEMPLATE_SNIPPETS: Array<{ group: string; label: string; cellType: NotebookCellType; source: string }> = [
  { group: "Python", label: "Load Dataset", cellType: "python", source: "import pandas as pd\n\ndf = pd.DataFrame(preview_rows)\nprint('Rows, columns:', df.shape)\ndf.head()" },
  { group: "Python", label: "Profile Dataset", cellType: "python", source: "import pandas as pd\n\ndf = pd.DataFrame(preview_rows)\nprint(df.describe(include='all').transpose())" },
  { group: "Python", label: "Histogram", cellType: "python", source: "import pandas as pd\nimport matplotlib.pyplot as plt\n\ndf = pd.DataFrame(preview_rows)\ncolumn = df.select_dtypes(include='number').columns[0]\nplt.figure(figsize=(7,4))\ndf[column].dropna().hist(bins=30)\nplt.title(f'Histogram of {column}')\nplt.xlabel(column)\nplt.ylabel('Count')\nplt.show()" },
  { group: "Python", label: "Scatter", cellType: "python", source: "import pandas as pd\nimport matplotlib.pyplot as plt\n\ndf = pd.DataFrame(preview_rows)\nnums = list(df.select_dtypes(include='number').columns[:2])\nplt.figure(figsize=(7,4))\nplt.scatter(df[nums[0]], df[nums[1]], alpha=0.45)\nplt.xlabel(nums[0])\nplt.ylabel(nums[1])\nplt.title(f'{nums[1]} by {nums[0]}')\nplt.show()" },
  { group: "Python", label: "Box Plot", cellType: "python", source: "import pandas as pd\nimport matplotlib.pyplot as plt\n\ndf = pd.DataFrame(preview_rows)\ncolumn = 'MedHouseVal' if 'MedHouseVal' in df.columns else df.select_dtypes(include='number').columns[0]\nplt.figure(figsize=(6,4))\nplt.boxplot(df[column].dropna(), vert=True)\nplt.title(f'Box Plot of {column}')\nplt.ylabel(column)\nplt.show()" },
  { group: "Python", label: "Correlation Heatmap", cellType: "python", source: "import pandas as pd\nimport matplotlib.pyplot as plt\n\ndf = pd.DataFrame(preview_rows).select_dtypes(include='number')\ncorr = df.corr(numeric_only=True)\nplt.figure(figsize=(7,6))\nplt.imshow(corr, cmap='RdBu_r', vmin=-1, vmax=1)\nplt.colorbar(label='Correlation')\nplt.xticks(range(len(corr.columns)), corr.columns, rotation=90)\nplt.yticks(range(len(corr.index)), corr.index)\nplt.title('Correlation Heatmap')\nplt.tight_layout()\nplt.show()" },
  { group: "Python", label: "Group Summary Bar Chart", cellType: "python", source: "import pandas as pd\nimport matplotlib.pyplot as plt\n\ndf = pd.DataFrame(preview_rows)\ncat = df.select_dtypes(exclude='number').columns[0] if len(df.select_dtypes(exclude='number').columns) else df.columns[0]\nnum = df.select_dtypes(include='number').columns[0]\nsummary = df.groupby(cat)[num].mean().head(12)\nsummary.plot(kind='bar', figsize=(8,4))\nplt.title(f'Average {num} by {cat}')\nplt.ylabel(num)\nplt.tight_layout()\nplt.show()" },
  { group: "Python", label: "Residual Plot", cellType: "python", source: "import pandas as pd\nimport matplotlib.pyplot as plt\n\ndf = pd.DataFrame(preview_rows)\ny = 'actual' if 'actual' in df.columns else df.select_dtypes(include='number').columns[-1]\nyhat = 'prediction' if 'prediction' in df.columns else df.select_dtypes(include='number').columns[0]\nresidual = df[y] - df[yhat]\nplt.figure(figsize=(7,4))\nplt.scatter(df[yhat], residual, alpha=0.6)\nplt.axhline(0, color='black', linewidth=1)\nplt.title('Residuals vs Predicted')\nplt.xlabel(yhat)\nplt.ylabel('Residual')\nplt.show()" },
  { group: "Python", label: "Actual vs Predicted Plot", cellType: "python", source: "import pandas as pd\nimport matplotlib.pyplot as plt\n\ndf = pd.DataFrame(preview_rows)\ny = 'actual' if 'actual' in df.columns else df.select_dtypes(include='number').columns[-1]\nyhat = 'prediction' if 'prediction' in df.columns else df.select_dtypes(include='number').columns[0]\nplt.figure(figsize=(6,6))\nplt.scatter(df[y], df[yhat], alpha=0.6)\nlow = min(df[y].min(), df[yhat].min())\nhigh = max(df[y].max(), df[yhat].max())\nplt.plot([low, high], [low, high], color='black', linestyle='--')\nplt.title('Actual vs Predicted')\nplt.xlabel(y)\nplt.ylabel(yhat)\nplt.show()" },
  { group: "Python", label: "Missingness Summary", cellType: "python", source: "import pandas as pd\nimport matplotlib.pyplot as plt\n\ndf = pd.DataFrame(preview_rows)\nmissing = df.isna().mean().sort_values(ascending=False).head(20)\nprint(missing)\nmissing.plot(kind='bar', figsize=(8,4))\nplt.title('Missingness Rate by Field')\nplt.ylabel('Missing rate')\nplt.tight_layout()\nplt.show()" },
  { group: "Python", label: "Display Table", cellType: "python", source: "import pandas as pd\n\ndf = pd.DataFrame(preview_rows)\natlas_display(df.head(25), title='Preview rows')" },
  { group: "SQL", label: "Select Preview", cellType: "sql", source: "SELECT *\nFROM REG_TRAIN\nLIMIT 100;" },
  { group: "SQL", label: "Group Summary", cellType: "sql", source: "SELECT column_name, COUNT(*) AS record_count\nFROM REG_TRAIN\nGROUP BY column_name\nORDER BY record_count DESC\nLIMIT 25;" },
  { group: "SQL", label: "Rare Event Review", cellType: "sql", source: "SELECT target, COUNT(*) AS records\nFROM REG_TRAIN\nGROUP BY target\nORDER BY records DESC;" },
  { group: "SQL", label: "Scored Output Review", cellType: "sql", source: "SELECT score, prediction, actual\nFROM REG_TRAIN\nLIMIT 100;" },
  { group: "SQL", label: "Join Datasets", cellType: "sql", source: "SELECT a.*\nFROM REG_TRAIN a\nLEFT JOIN SECONDARY b\n  ON a.id = b.id\nLIMIT 100;" },
  { group: "R", label: "Load Dataset", cellType: "r", source: "df <- atlas_preview_rows\nprint(dim(df))\nprint(head(df))" },
  { group: "R", label: "Summary Statistics", cellType: "r", source: "df <- atlas_preview_rows\nprint(summary(df))" },
  { group: "R", label: "Group Summary", cellType: "r", source: "df <- atlas_preview_rows\nprint(head(df))\n# Add aggregate logic here once grouping fields are selected." },
  { group: "R", label: "Basic Plot", cellType: "r", source: "df <- atlas_preview_rows\nprint(\"R plot rendering is environment-dependent in this local phase.\")\nprint(head(df))" },
  { group: "SAS", label: "PROC CONTENTS", cellType: "sas_compatible", source: "proc contents data=REG_TRAIN;\nrun;" },
  { group: "SAS", label: "PROC MEANS", cellType: "sas_compatible", source: "proc means data=REG_TRAIN;\nrun;" },
  { group: "SAS", label: "PROC FREQ", cellType: "sas_compatible", source: "proc freq data=REG_TRAIN;\nrun;" },
  { group: "SAS", label: "PROC CORR", cellType: "sas_compatible", source: "proc corr data=REG_TRAIN;\nrun;" },
  { group: "Markdown", label: "Analysis Plan", cellType: "markdown", source: "## Analysis Plan\n\n- Objective:\n- Dataset:\n- Method:\n- Expected evidence:" },
  { group: "Markdown", label: "Findings", cellType: "markdown", source: "## Findings\n\n1. Key result:\n2. Supporting evidence:\n3. Limitation:\n4. Recommended action:" },
  { group: "Markdown", label: "Model Review", cellType: "markdown", source: "## Model Review\n\n- Champion model:\n- Performance evidence:\n- Stability evidence:\n- Interpretation notes:" },
  { group: "Markdown", label: "Governance Notes", cellType: "markdown", source: "## Governance Notes\n\n- Decision:\n- Rationale:\n- Controls:\n- Open risks:" },
];

export function notebookTemplateCells(template: string, defaultCodeLanguage: NotebookCodeLanguage = "python"): NotebookCell[] {
  if (template === "eda") {
    return [
      createNotebookCell("markdown", "## EDA Summary\n\nProfile the selected dataset and summarize key data quality observations."),
      createCodeCell(defaultCodeLanguage),
    ];
  }
  if (template === "model-review") {
    return [
      createNotebookCell("markdown", "## Model Review\n\nAttach scored-output diagnostics, residual/lift evidence, and validation notes."),
      createCodeCell(defaultCodeLanguage),
    ];
  }
  if (template === "governance") {
    return [
      createNotebookCell("markdown", "## Governance Evidence\n\nState the decision, supporting evidence, limitations, and review status."),
      createCodeCell(defaultCodeLanguage),
    ];
  }
  return [createNotebookCell("markdown", "## Notebook Introduction\n\n- Analysis objective:\n- Dataset:\n- Evidence to produce:\n- Governance use:"), createCodeCell(defaultCodeLanguage)];
}

export async function listNotebooks(): Promise<NotebookSummary[]> {
  const payload = await jsonFetch<{ ok: true; notebooks: NotebookSummary[] }>("/notebooks");
  return payload.notebooks;
}

export async function saveNotebook(notebook: AtlasNotebook): Promise<AtlasNotebook> {
  const method = notebook.notebookId ? "PUT" : "POST";
  const path = notebook.notebookId ? `/notebooks/${encodeURIComponent(notebook.notebookId)}` : "/notebooks";
  const payload = await jsonFetch<{ ok: true; notebook: AtlasNotebook }>(path, {
    method,
    body: JSON.stringify(notebook),
  });
  return payload.notebook;
}

export async function getNotebook(notebookId: string): Promise<AtlasNotebook> {
  const payload = await jsonFetch<{ ok: true; notebook: AtlasNotebook }>(`/notebooks/${encodeURIComponent(notebookId)}`);
  return payload.notebook;
}

export async function deleteNotebook(notebookId: string): Promise<void> {
  await jsonFetch(`/notebooks/${encodeURIComponent(notebookId)}`, { method: "DELETE" });
}

export async function runNotebookCell(notebookId: string, cell: NotebookCell, context: Partial<AtlasNotebook>): Promise<NotebookRunResult> {
  return jsonFetch<NotebookRunResult>(`/notebooks/${encodeURIComponent(notebookId)}/run-cell`, {
    method: "POST",
    body: JSON.stringify({
      cellId: cell.cellId,
      cellType: cell.cellType,
      source: cell.source,
      projectId: context.projectId ?? "",
      primaryDatasetId: context.primaryDatasetId ?? "",
      primaryVersionId: context.primaryVersionId ?? "",
      secondaryDatasetId: context.secondaryDatasetId ?? "",
      secondaryVersionId: context.secondaryVersionId ?? "",
    }),
  });
}

export async function runNotebook(notebookId: string): Promise<{ ok: boolean; results: NotebookRunResult[]; notebook: AtlasNotebook }> {
  return jsonFetch(`/notebooks/${encodeURIComponent(notebookId)}/run-all`, { method: "POST" });
}

export async function exportNotebookIpynb(notebookId: string): Promise<Blob> {
  return blobFetch(`/notebooks/${encodeURIComponent(notebookId)}/export/ipynb`);
}

export async function exportNotebookHtml(notebookId: string): Promise<Blob> {
  return blobFetch(`/notebooks/${encodeURIComponent(notebookId)}/export/html`);
}

export async function attachNotebookToDocumentation(input: { notebookId: string; projectId?: string; documentId?: string; sectionId?: string; cellIds?: string[]; summary?: string }) {
  return jsonFetch<{ ok: true; evidence: Record<string, unknown> }>(`/notebooks/${encodeURIComponent(input.notebookId)}/attach-to-documentation`, {
    method: "POST",
    body: JSON.stringify({
      projectId: input.projectId ?? "",
      documentId: input.documentId ?? "",
      sectionId: input.sectionId ?? "appendices",
      cellIds: input.cellIds ?? [],
      summary: input.summary ?? "",
    }),
  });
}

async function blobFetch(path: string): Promise<Blob> {
  const response = await fetch(`${DATASET_API_BASE}${path}`, {
    method: "POST",
    credentials: "include",
  });
  if (!response.ok) {
    const payload = await response.json().catch(() => null);
    throw new Error(payload?.detail ?? payload?.error ?? `ATLAS notebook export failed with HTTP ${response.status}.`);
  }
  return response.blob();
}

export function downloadBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}
