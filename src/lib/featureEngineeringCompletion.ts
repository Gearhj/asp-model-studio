import type { CanonicalDatasetIdentity } from "./datasetIdentity";
import type { EvidenceItem } from "./evidenceGraph";
import type { FeatureManifest } from "./featureManifest";

const API_BASE =
  (import.meta.env.VITE_API_BASE as string | undefined)?.replace(/\/$/, "") ||
  "http://127.0.0.1:8001/api";

type DocumentationSection = {
  sectionId?: string;
  status?: string;
  attachedEvidence?: Array<Record<string, unknown>>;
};

type DocumentationRecord = {
  documentId?: string;
  projectId?: string;
  templateType?: string;
  sections?: DocumentationSection[];
};

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    credentials: "include",
    ...init,
    headers: {
      Accept: "application/json",
      ...(init?.body ? { "Content-Type": "application/json" } : {}),
      ...(init?.headers ?? {}),
    },
  });
  const payload = await response.json().catch(() => null);
  if (!response.ok || payload?.ok === false) {
    throw new Error(
      payload?.detail ??
        payload?.error ??
        `ATLAS documentation request failed with HTTP ${response.status}.`,
    );
  }
  return payload as T;
}

function evidenceIdentifier(item: Record<string, unknown>) {
  return String(
    item.evidenceId ?? item.evidence_id ?? item.sourceRef ?? "",
  ).trim();
}

export async function syncFeatureEngineeringMdd(
  identity: CanonicalDatasetIdentity,
  evidence: EvidenceItem,
  manifest: FeatureManifest,
) {
  const context = await request<{
    ok: boolean;
    documents: DocumentationRecord[];
  }>(`/model-documentation/project-context/${encodeURIComponent(identity.project_id)}`);
  const matching = (context.documents ?? []).filter(
    (document) =>
      document.projectId === identity.project_id &&
      document.templateType === "model_development_document",
  );
  if (matching.length !== 1 || !matching[0].documentId) {
    throw new Error(
      matching.length
        ? "ATLAS found multiple Model Development Documents for this project. Select an exact document before continuing."
        : "ATLAS could not find the project's Model Development Document draft.",
    );
  }

  const documentId = matching[0].documentId;
  const attachment = {
    evidenceId: evidence.evidenceId,
    type: "feature_engineering",
    source: "Feature Engineering",
    sourceRef: evidence.evidenceId,
    title: evidence.title,
    summary: evidence.summary,
    project_id: identity.project_id,
    dataset_id: identity.dataset_id,
    dataset_version_id: identity.dataset_version_id,
    manifest_hash: manifest.manifest_hash,
    materialization_hash: manifest.materialization_hash,
    attachedAt: new Date().toISOString(),
  };
  const attached = await request<{
    ok: boolean;
    document: DocumentationRecord;
  }>(`/model-documentation/${encodeURIComponent(documentId)}/attach-evidence`, {
    method: "POST",
    body: JSON.stringify({
      sectionId: "feature_engineering",
      evidence: attachment,
    }),
  });
  if (attached.document.projectId !== identity.project_id) {
    throw new Error(
      "The Model Development Document response did not match the active project.",
    );
  }
  const section = (attached.document.sections ?? []).find(
    (item) => item.sectionId === "feature_engineering",
  );
  const matchingAttachments = (section?.attachedEvidence ?? []).filter(
    (item) => evidenceIdentifier(item) === evidence.evidenceId,
  );
  const exact = matchingAttachments.find(
    (item) =>
      item.project_id === identity.project_id &&
      item.dataset_id === identity.dataset_id &&
      item.dataset_version_id === identity.dataset_version_id &&
      item.manifest_hash === manifest.manifest_hash &&
      item.materialization_hash === manifest.materialization_hash,
  );
  if (!exact || matchingAttachments.length !== 1) {
    throw new Error(
      "The Model Development Document did not confirm one exact Feature Engineering evidence attachment.",
    );
  }
  return {
    documentId,
    sectionStatus: section?.status ?? "draft",
    evidenceId: evidence.evidenceId,
    attachmentCount: matchingAttachments.length,
  };
}
