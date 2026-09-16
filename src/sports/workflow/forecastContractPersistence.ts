import { BASE } from "../../lib/api";
import {
  loadContract,
  normalizeForecastContract,
  saveContract,
  type ForecastContract,
  type ForecastContractCoverage,
} from "./workflowState";
import {
  sanitizeSportsAuthorityMessage,
  sportsAuthorityErrorCode,
  sportsAuthorityServerMessage,
  type SportsAuthorityErrorCode,
} from "./sportsAuthorityErrors";

const rawEnv = (import.meta as any)?.env ?? {};
const devUserId = rawEnv.DEV ? String(rawEnv.VITE_ATLAS_DEV_USER_ID || "local-dev-user") : "";

export type ForecastContractEnvelope = {
  contract: ForecastContract | null;
  history: ForecastContract[];
  coverage: ForecastContractCoverage | null;
  compatibilityDraft: ForecastContract | null;
};

export class ForecastContractHttpError extends Error {
  status: number;
  code: SportsAuthorityErrorCode;
  detail: unknown;

  constructor(status: number, code: SportsAuthorityErrorCode, message: string, detail: unknown) {
    super(sanitizeSportsAuthorityMessage(message));
    this.name = "ForecastContractHttpError";
    this.status = status;
    this.code = code;
    this.detail = detail;
  }
}

function text(value: unknown): string {
  return typeof value === "string" ? value.trim() : "";
}

function coverageFrom(value: unknown): ForecastContractCoverage | null {
  if (!value || typeof value !== "object") return null;
  const raw = value as Record<string, unknown>;
  const earliestDate = text(raw.earliestDate ?? raw.earliest_date);
  const latestDate = text(raw.latestDate ?? raw.latest_date);
  const registrationId = text(raw.registrationId ?? raw.registration_id);
  const datasetId = text(raw.datasetId ?? raw.dataset_id);
  const datasetVersionId = text(raw.datasetVersionId ?? raw.dataset_version_id);
  const manifestSha = text(raw.manifestSha ?? raw.manifest_sha ?? raw.manifestSha256 ?? raw.manifest_sha256);
  if (!earliestDate || !latestDate || !registrationId || !datasetVersionId || !manifestSha) return null;
  return {
    earliestDate,
    latestDate,
    registrationId,
    datasetId,
    datasetVersionId,
    manifestSha,
    family: text(raw.family) || undefined,
    populationId: text(raw.populationId ?? raw.population_id) || undefined,
    rowCount: Number.isFinite(Number(raw.rowCount ?? raw.row_count)) ? Number(raw.rowCount ?? raw.row_count) : undefined,
    partitionCount: Number.isFinite(Number(raw.partitionCount ?? raw.partition_count)) ? Number(raw.partitionCount ?? raw.partition_count) : undefined,
  };
}

function errorMessage(payload: unknown, status: number): string {
  if (!payload || typeof payload !== "object") return `Forecast contract request failed with HTTP ${status}.`;
  const raw = payload as Record<string, unknown>;
  if (typeof raw.detail === "string") return raw.detail;
  if (raw.detail && typeof raw.detail === "object") {
    const detail = raw.detail as Record<string, unknown>;
    for (const key of ["message", "coverageMessage", "coverage_message", "error"]) {
      if (typeof detail[key] === "string" && detail[key]) return String(detail[key]);
    }
  }
  if (typeof raw.error === "string") return raw.error;
  return `Forecast contract request failed with HTTP ${status}.`;
}

async function request(projectId: string, init: RequestInit): Promise<ForecastContractEnvelope> {
  let response: Response;
  try {
    response = await fetch(`${BASE}/projects/${encodeURIComponent(projectId)}/sports/forecast-contract`, {
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
    throw new ForecastContractHttpError(0, code, cause instanceof Error ? cause.message : "Backend request failed.", cause);
  }
  const payload = await response.json().catch(() => null);
  if (!response.ok || payload?.ok === false) {
    const detail = payload?.detail ?? payload;
    const code = sportsAuthorityErrorCode(response.status, detail);
    throw new ForecastContractHttpError(
      response.status,
      code,
      sportsAuthorityServerMessage(detail, errorMessage(payload, response.status)),
      detail,
    );
  }
  const contract = normalizeForecastContract(payload?.contract, projectId);
  const history = Array.isArray(payload?.history)
    ? payload.history.flatMap((item: unknown) => {
        const normalized = normalizeForecastContract(item, projectId);
        return normalized ? [normalized] : [];
      })
    : [];
  return { contract, history, coverage: coverageFrom(payload?.coverage), compatibilityDraft: null };
}

function registrationDraft(contract: ForecastContract): Record<string, unknown> {
  const { version: _version, savedAt: _savedAt, ...draft } = contract;
  if (contract.temporalDesignMode === "CUSTOM_DATES_ROLLING_ORIGIN") {
    const {
      eligibleEvidence,
      developmentSelection,
      finalOot,
      developmentSeasons: _developmentSeasons,
      validationSeason: _validationSeason,
      frozenSeason: _frozenSeason,
      prospectiveSeason: _prospectiveSeason,
      ...common
    } = draft;
    return {
      ...common,
      eligibleEvidenceStart: eligibleEvidence?.startDate || "",
      eligibleEvidenceEnd: eligibleEvidence?.endDate || "",
      developmentSelectionStart: developmentSelection?.startDate || "",
      developmentSelectionEnd: developmentSelection?.endDate || "",
      finalOotStart: finalOot?.startDate || "",
      finalOotEnd: finalOot?.endDate || "",
    };
  }
  return draft;
}

export async function putForecastContract(
  projectId: string,
  expectedVersion: number,
  contract: ForecastContract,
  signal?: AbortSignal,
): Promise<ForecastContractEnvelope> {
  const envelope = await request(projectId, {
    method: "PUT",
    signal,
    body: JSON.stringify({ expectedVersion, contract: registrationDraft(contract) }),
  });
  if (!envelope.contract) throw new Error("The backend did not acknowledge the registered forecast contract.");
  saveContract(envelope.contract);
  return envelope;
}

/**
 * Hydrates the backend authority. A project-scoped legacy browser contract is
 * migrated only after a successful GET proves the backend has no contract.
 */
export async function hydrateForecastContract(projectId: string, signal?: AbortSignal): Promise<ForecastContractEnvelope> {
  const envelope = await request(projectId, { method: "GET", signal });
  if (envelope.contract) {
    saveContract(envelope.contract);
    return envelope;
  }
  const legacy = loadContract(projectId);
  return { ...envelope, compatibilityDraft: legacy };
}
