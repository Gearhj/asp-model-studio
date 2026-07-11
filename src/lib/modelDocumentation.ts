import { DATASET_API_BASE } from "./datasetLibrary";

export type DocumentationTemplate = {
  templateType: string;
  label: string;
  status: "available" | "coming_soon" | string;
  description: string;
};

export type DocumentationEvidence = {
  type: string;
  title: string;
  source: string;
  createdAt?: string;
  rows?: Array<Record<string, unknown>>;
  preview?: Record<string, unknown>;
};

export type DocumentationSectionStatus =
  | "draft"
  | "needs_review"
  | "ready_for_review"
  | "complete"
  | "needs_evidence"
  | "missing_evidence"
  | "not_applicable";

export type DocumentationSection = {
  sectionId: string;
  title: string;
  order: number;
  required: boolean;
  status: DocumentationSectionStatus;
  autoDraft: string;
  userNarrative: string;
  attachedEvidence: DocumentationEvidence[];
  includeInExport: boolean;
  missingEvidenceWarning?: string;
};

export type DocumentationQuality = {
  completionPct: number;
  requiredSectionsComplete: number;
  requiredSectionsTotal: number;
  sectionsNeedingReview: number;
  missingEvidenceCount: number;
  governanceWarningsCount: number;
  exportReady: boolean;
  checks: Array<{ id: string; label: string; status: string; detail: string }>;
};

export type ModelDocumentationDocument = {
  documentId: string;
  projectId: string;
  projectName: string;
  templateType: string;
  createdAt: string;
  updatedAt: string;
  createdBy: string;
  sections: DocumentationSection[];
  quality: DocumentationQuality;
  exports: Array<Record<string, unknown>>;
  contextSummary?: Record<string, unknown>;
};

export type DocumentationProjectContext = {
  project: {
    projectId: string;
    projectName: string;
    projectType: string;
    taskType: string;
    target: string;
    championModel?: string;
    createdAt?: string;
    lastModified?: string;
    recoveryStatus?: string;
    storageLocation?: string;
  };
  datasets: Array<Record<string, unknown>>;
  analyticsInsights: Array<Record<string, unknown>>;
  chartInsights: Array<Record<string, unknown>>;
  diagnosticInsights: Array<Record<string, unknown>>;
  recoveredShell?: boolean;
};

async function documentationFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${DATASET_API_BASE}${path}`, {
    credentials: "include",
    ...init,
    headers: {
      ...(init?.body instanceof FormData ? {} : { "Content-Type": "application/json" }),
      ...(init?.headers ?? {}),
    },
  });
  const contentType = response.headers.get("Content-Type") ?? "";
  if (!contentType.includes("application/json")) {
    if (!response.ok) throw new Error(`ATLAS documentation request failed with HTTP ${response.status}.`);
    return response as T;
  }
  const payload = await response.json().catch(() => null);
  if (!response.ok || payload?.ok === false) {
    if (response.status === 401) {
      throw new Error("Your session is not authenticated. Sign in again to create a documentation workspace.");
    }
    throw new Error(payload?.detail ?? payload?.error ?? `ATLAS documentation request failed with HTTP ${response.status}.`);
  }
  return payload as T;
}

export async function listDocumentationTemplates() {
  const payload = await documentationFetch<{ ok: true; templates: DocumentationTemplate[] }>("/model-documentation/templates");
  return payload.templates;
}

export async function getDocumentationProjectContext(projectId: string) {
  return documentationFetch<{ ok: true; context: DocumentationProjectContext; documents: Array<Record<string, unknown>> }>(
    `/model-documentation/project-context/${encodeURIComponent(projectId)}`
  );
}

export async function createModelDocumentation(projectId: string, templateType = "model_development_document") {
  const payload = await documentationFetch<{ ok: true; document: ModelDocumentationDocument }>("/model-documentation/create", {
    method: "POST",
    body: JSON.stringify({ projectId, templateType }),
  });
  return payload.document;
}

export async function saveDocumentationSection(documentId: string, section: DocumentationSection) {
  const payload = await documentationFetch<{ ok: true; document: ModelDocumentationDocument }>(
    `/model-documentation/${encodeURIComponent(documentId)}/save-section`,
    {
      method: "POST",
      body: JSON.stringify({
        sectionId: section.sectionId,
        userNarrative: section.userNarrative,
        status: section.status,
        attachedEvidence: section.attachedEvidence,
        includeInExport: section.includeInExport,
      }),
    }
  );
  return payload.document;
}

export async function attachDocumentationEvidence(documentId: string, sectionId: string, evidence: DocumentationEvidence) {
  const payload = await documentationFetch<{ ok: true; document: ModelDocumentationDocument }>(
    `/model-documentation/${encodeURIComponent(documentId)}/attach-evidence`,
    {
      method: "POST",
      body: JSON.stringify({ sectionId, evidence }),
    }
  );
  return payload.document;
}

export async function runDocumentationQualityCheck(documentId: string) {
  const payload = await documentationFetch<{ ok: true; document: ModelDocumentationDocument; quality: DocumentationQuality }>(
    `/model-documentation/${encodeURIComponent(documentId)}/quality-check`,
    { method: "POST" }
  );
  return payload.document;
}

export async function getDocumentationEvidenceLibrary(documentId: string, projectId: string) {
  const payload = await documentationFetch<{ ok: true; items: DocumentationEvidence[] }>(
    `/model-documentation/${encodeURIComponent(documentId)}/evidence-library?projectId=${encodeURIComponent(projectId)}`
  );
  return payload.items;
}

export type DocumentationExportFormat = "word" | "powerpoint" | "evidence-excel";

export async function exportModelDocumentation(documentId: string, format: DocumentationExportFormat) {
  const response = await fetch(`${DATASET_API_BASE}/model-documentation/${encodeURIComponent(documentId)}/export/${format}`, {
    method: "POST",
    credentials: "include",
  });
  if (!response.ok) {
    const payload = await response.json().catch(() => null);
    if (response.status === 401) {
      throw new Error("Your session is not authenticated. Sign in again to create a documentation workspace.");
    }
    throw new Error(payload?.detail ?? payload?.error ?? `ATLAS documentation export failed with HTTP ${response.status}.`);
  }
  const disposition = response.headers.get("Content-Disposition") ?? "";
  const blob = await response.blob();
  return { blob, filename: filenameFromDisposition(disposition) ?? defaultExportName(format) };
}

function filenameFromDisposition(disposition: string) {
  const match = /filename="?([^";]+)"?/i.exec(disposition);
  return match?.[1];
}

function defaultExportName(format: DocumentationExportFormat) {
  if (format === "word") return "atlas-model-development-document.docx";
  if (format === "powerpoint") return "atlas-model-development-summary.pptx";
  return "atlas-model-documentation-evidence-pack.xlsx";
}
