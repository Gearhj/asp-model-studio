import { useCallback, useEffect, useState } from "react";
import { BASE } from "../../lib/api";
import {
  sanitizeSportsAuthorityMessage,
  sportsAuthorityErrorCode,
  sportsAuthorityServerMessage,
  type SportsAuthorityErrorCode,
} from "./sportsAuthorityErrors";

const rawEnv = (import.meta as any)?.env ?? {};
const devUserId = rawEnv.DEV ? String(rawEnv.VITE_ATLAS_DEV_USER_ID || "local-dev-user") : "";

export type ProjectSportsEvidenceCoverage = {
  earliestDate: string;
  latestDate: string;
  family: string;
  rowCount: number;
  partitionCount: number;
};

export type ProjectSportsEvidenceLinkage = {
  projectId: string;
  registrationId: string;
  datasetId: string;
  datasetVersionId: string;
  manifestSha: string;
  activationRevision: number;
  coverage: ProjectSportsEvidenceCoverage;
};

export class ProjectSportsEvidenceHttpError extends Error {
  readonly status: number;
  readonly code: SportsAuthorityErrorCode;
  readonly detail: unknown;

  constructor(status: number, code: SportsAuthorityErrorCode, message: string, detail: unknown) {
    super(sanitizeSportsAuthorityMessage(message));
    this.name = "ProjectSportsEvidenceHttpError";
    this.status = status;
    this.code = code;
    this.detail = detail;
  }
}

function record(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : null;
}

function normalizeLinkage(value: unknown, expectedProjectId: string): ProjectSportsEvidenceLinkage {
  const raw = record(value);
  const coverage = record(raw?.coverage);
  const linkage: ProjectSportsEvidenceLinkage = {
    projectId: String(raw?.projectId || "").trim(),
    registrationId: String(raw?.registrationId || "").trim(),
    datasetId: String(raw?.datasetId || "").trim(),
    datasetVersionId: String(raw?.datasetVersionId || "").trim(),
    manifestSha: String(raw?.manifestSha || "").trim(),
    activationRevision: Number(raw?.activationRevision),
    coverage: {
      earliestDate: String(coverage?.earliestDate || "").trim(),
      latestDate: String(coverage?.latestDate || "").trim(),
      family: String(coverage?.family || "").trim(),
      rowCount: Number(coverage?.rowCount),
      partitionCount: Number(coverage?.partitionCount),
    },
  };
  if (
    linkage.projectId !== expectedProjectId
    || !linkage.registrationId
    || !linkage.datasetId
    || !linkage.datasetVersionId
    || !/^[a-f0-9]{64}$/i.test(linkage.manifestSha)
    || !/^\d{4}-\d{2}-\d{2}$/.test(linkage.coverage.earliestDate)
    || !/^\d{4}-\d{2}-\d{2}$/.test(linkage.coverage.latestDate)
    || !Number.isInteger(linkage.activationRevision)
    || !Number.isFinite(linkage.coverage.rowCount)
    || !Number.isFinite(linkage.coverage.partitionCount)
  ) {
    throw new ProjectSportsEvidenceHttpError(502, "BACKEND_UNAVAILABLE", "The project evidence-dataset response was incomplete.", value);
  }
  return linkage;
}

async function request(projectId: string, init: RequestInit) {
  let response: Response;
  try {
    response = await fetch(`${BASE}/projects/${encodeURIComponent(projectId)}/sports/evidence-dataset`, {
      credentials: "include",
      ...init,
      headers: {
        Accept: "application/json",
        ...(init.body ? { "Content-Type": "application/json" } : {}),
        ...(devUserId ? { "X-ATLAS-USER-ID": devUserId } : {}),
        ...(init.headers ?? {}),
      },
    });
  } catch (cause) {
    const code = sportsAuthorityErrorCode(0, null, cause);
    throw new ProjectSportsEvidenceHttpError(0, code, cause instanceof Error ? cause.message : "Backend request failed.", cause);
  }
  const payload: unknown = await response.json().catch(() => null);
  if (!response.ok || record(payload)?.ok === false) {
    const detail = record(payload)?.detail ?? payload;
    const code = sportsAuthorityErrorCode(response.status, detail);
    const message = sportsAuthorityServerMessage(detail, `Project evidence-dataset request failed with HTTP ${response.status}.`);
    throw new ProjectSportsEvidenceHttpError(response.status, code, message, detail);
  }
  return normalizeLinkage(record(payload)?.linkage, projectId);
}

export function getProjectSportsEvidenceDataset(projectId: string, signal?: AbortSignal) {
  return request(projectId, { method: "GET", signal });
}

export function putProjectSportsEvidenceDataset(projectId: string, registrationId: string, signal?: AbortSignal) {
  return request(projectId, {
    method: "PUT",
    signal,
    body: JSON.stringify({ registrationId }),
  });
}

export type ProjectSportsEvidenceState = {
  status: "loading" | "ready" | "unlinked" | "saving" | "error";
  linkage: ProjectSportsEvidenceLinkage | null;
  error: string | null;
  errorCode: SportsAuthorityErrorCode | null;
  refresh: () => Promise<void>;
  select: (registrationId: string) => Promise<ProjectSportsEvidenceLinkage>;
};

export function useProjectSportsEvidenceDataset(projectId: string): ProjectSportsEvidenceState {
  const [status, setStatus] = useState<ProjectSportsEvidenceState["status"]>("loading");
  const [linkage, setLinkage] = useState<ProjectSportsEvidenceLinkage | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [errorCode, setErrorCode] = useState<SportsAuthorityErrorCode | null>(null);

  const load = useCallback(async (signal?: AbortSignal) => {
    if (!projectId) {
      setStatus("error");
      setLinkage(null);
      setErrorCode("PROJECT_NOT_REGISTERED");
      setError("No canonical sports-project ID is present in this workflow URL.");
      return;
    }
    setStatus("loading");
    setError(null);
    setErrorCode(null);
    try {
      const next = await getProjectSportsEvidenceDataset(projectId, signal);
      if (signal?.aborted) return;
      setLinkage(next);
      setStatus("ready");
    } catch (caught) {
      if (signal?.aborted) return;
      const code = caught instanceof ProjectSportsEvidenceHttpError ? caught.code : sportsAuthorityErrorCode(undefined, null, caught);
      setLinkage(null);
      setErrorCode(code);
      setError(caught instanceof Error ? sanitizeSportsAuthorityMessage(caught.message) : "The project evidence dataset could not be loaded.");
      setStatus(code === "DATASET_NOT_LINKED" ? "unlinked" : "error");
    }
  }, [projectId]);

  useEffect(() => {
    const controller = new AbortController();
    void load(controller.signal);
    return () => controller.abort();
  }, [load]);

  const refresh = useCallback(async () => load(), [load]);
  const select = useCallback(async (registrationId: string) => {
    setStatus("saving");
    setError(null);
    setErrorCode(null);
    try {
      const next = await putProjectSportsEvidenceDataset(projectId, registrationId);
      setLinkage(next);
      setStatus("ready");
      return next;
    } catch (caught) {
      const code = caught instanceof ProjectSportsEvidenceHttpError ? caught.code : sportsAuthorityErrorCode(undefined, null, caught);
      setErrorCode(code);
      setError(caught instanceof Error ? sanitizeSportsAuthorityMessage(caught.message) : "The project evidence dataset could not be linked.");
      setStatus(code === "DATASET_NOT_LINKED" ? "unlinked" : "error");
      throw caught;
    }
  }, [projectId]);

  return { status, linkage, error, errorCode, refresh, select };
}
