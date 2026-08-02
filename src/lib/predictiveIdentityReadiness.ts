import {
  DatasetIdentityError,
  requireCanonicalDatasetIdentity,
  type CanonicalDatasetIdentity,
  type CanonicalDatasetIdentityInput,
} from "./datasetIdentity";

export const PREDICTIVE_IDENTITY_STATUSES = [
  "idle",
  "loading",
  "ready",
  "missing",
  "stale",
  "legacy_unresolved",
  "contradictory",
  "unauthorized",
  "error",
] as const;

export type PredictiveIdentityStatus = (typeof PREDICTIVE_IDENTITY_STATUSES)[number];

export type ActiveIdentityProbe =
  | { kind: "ready"; identity: CanonicalDatasetIdentityInput }
  | { kind: "http_error"; status: number; detail?: string }
  | { kind: "network_error"; detail?: string };

export type LocalIdentityProbe =
  | { kind: "missing" }
  | { kind: "exact"; identity: CanonicalDatasetIdentityInput }
  | { kind: "legacy_unresolved" }
  | { kind: "contradictory" };

export type PredictiveIdentityReadiness = {
  status: PredictiveIdentityStatus;
  projectId: string;
  identity: CanonicalDatasetIdentity | null;
  message: string;
  httpStatus?: number;
};

export type PredictiveIdentityClassificationInput = {
  projectId: string;
  hasDataset: boolean;
  persistedIdentity?: CanonicalDatasetIdentityInput | null;
  activeProbe: ActiveIdentityProbe;
  localProbe?: LocalIdentityProbe;
};

function state(
  status: PredictiveIdentityStatus,
  projectId: string,
  message: string,
  options: { identity?: CanonicalDatasetIdentity | null; httpStatus?: number } = {},
): PredictiveIdentityReadiness {
  return {
    status,
    projectId,
    identity: options.identity ?? null,
    message,
    ...(options.httpStatus == null ? {} : { httpStatus: options.httpStatus }),
  };
}

function sameIdentity(left: CanonicalDatasetIdentity, right: CanonicalDatasetIdentity) {
  return left.project_id === right.project_id
    && left.dataset_id === right.dataset_id
    && left.dataset_version_id === right.dataset_version_id;
}

function legacyOnly(input: CanonicalDatasetIdentityInput | null | undefined) {
  if (!input || typeof input !== "object") return false;
  const record = input as Record<string, unknown>;
  const legacyVersion = String(record.dataset_version ?? record.version_id ?? "").trim();
  const exactVersion = String(record.dataset_version_id ?? "").trim();
  return Boolean(legacyVersion && !exactVersion);
}

/**
 * Pure, fail-closed classification for route readiness. It never selects a
 * Dataset Library link and never upgrades a legacy/pseudo version.
 */
export function classifyPredictiveIdentity(
  input: PredictiveIdentityClassificationInput,
): PredictiveIdentityReadiness {
  const projectId = String(input.projectId ?? "").trim();
  if (!projectId) {
    return state("idle", "", "Select a project before resolving its dataset identity.");
  }

  if (input.activeProbe.kind === "network_error") {
    return state(
      "error",
      projectId,
      "ATLAS could not verify the active Dataset Library version. Retry when the backend is available.",
    );
  }

  if (input.activeProbe.kind === "http_error") {
    const httpStatus = input.activeProbe.status;
    if (httpStatus === 401 || httpStatus === 403) {
      return state(
        "unauthorized",
        projectId,
        httpStatus === 401
          ? "Your ATLAS session is not authorized to resolve this project. Sign in again."
          : "You do not have permission to use this project's governed dataset.",
        { httpStatus },
      );
    }

    if (httpStatus === 409 || httpStatus === 404) {
      if (!input.persistedIdentity) {
        return input.hasDataset
          ? state(
              "legacy_unresolved",
              projectId,
              "This project predates the canonical Dataset Library lineage contract. Reactivate one exact registered version in Data Acquisition; ATLAS will not choose a linked version automatically.",
              { httpStatus },
            )
          : state(
              "missing",
              projectId,
              "Dataset selection is required before this Predictive Modeling route can open.",
              { httpStatus },
            );
      }

      return state(
        legacyOnly(input.persistedIdentity) ? "legacy_unresolved" : "stale",
        projectId,
        legacyOnly(input.persistedIdentity)
          ? "The restored project contains a legacy dataset version that cannot be promoted to canonical identity. Reactivate the exact registered version in Data Acquisition."
          : "The restored project names a dataset version that is not active in the backend. Reactivate that exact registered version in Data Acquisition.",
        { httpStatus },
      );
    }

    return state(
      "error",
      projectId,
      `ATLAS could not verify dataset identity (HTTP ${httpStatus}).`,
      { httpStatus },
    );
  }

  let activeIdentity: CanonicalDatasetIdentity;
  try {
    activeIdentity = requireCanonicalDatasetIdentity(
      input.activeProbe.identity,
      "Authoritative active dataset identity",
    );
  } catch {
    return state(
      "contradictory",
      projectId,
      "The backend returned an incomplete canonical dataset identity. Modeling remains blocked.",
    );
  }

  if (activeIdentity.project_id !== projectId) {
    return state(
      "contradictory",
      projectId,
      "The active dataset identity belongs to a different project. Modeling remains blocked.",
    );
  }

  if (!input.persistedIdentity) {
    return state(
      input.hasDataset ? "legacy_unresolved" : "contradictory",
      projectId,
      input.hasDataset
        ? "The backend has an active dataset, but the restored workflow does not contain the exact canonical triple. Recover through Data Acquisition without relabeling prior artifacts."
        : "The backend reports an active dataset while the restored workflow reports no selected dataset. Modeling remains blocked.",
    );
  }

  let persistedIdentity: CanonicalDatasetIdentity;
  try {
    persistedIdentity = requireCanonicalDatasetIdentity(
      input.persistedIdentity,
      "Persisted workflow dataset identity",
    );
  } catch (error) {
    const status = legacyOnly(input.persistedIdentity)
      || (error instanceof DatasetIdentityError && error.code === "missing_canonical_identity")
      ? "legacy_unresolved"
      : "contradictory";
    return state(
      status,
      projectId,
      status === "legacy_unresolved"
        ? "The restored workflow has versionless or legacy dataset evidence. Select and activate one exact registered version in Data Acquisition."
        : "The restored workflow contains contradictory dataset identifiers. Modeling remains blocked.",
    );
  }

  if (!sameIdentity(persistedIdentity, activeIdentity)) {
    return state(
      "contradictory",
      projectId,
      "The restored workflow and active backend scope identify different dataset versions. ATLAS will not choose between them.",
    );
  }

  if (input.localProbe?.kind === "legacy_unresolved") {
    return state(
      "legacy_unresolved",
      projectId,
      "The browser contains legacy dataset state that cannot be mapped to the active canonical version.",
    );
  }
  if (input.localProbe?.kind === "contradictory") {
    return state(
      "contradictory",
      projectId,
      "The browser dataset cache conflicts with the verified project dataset identity. Reload it through Data Acquisition.",
    );
  }
  if (input.localProbe?.kind === "exact") {
    try {
      const localIdentity = requireCanonicalDatasetIdentity(
        input.localProbe.identity,
        "Browser dataset identity",
      );
      if (!sameIdentity(persistedIdentity, localIdentity)) {
        return state(
          "contradictory",
          projectId,
          "The browser dataset cache belongs to a different dataset version. Modeling remains blocked.",
        );
      }
    } catch {
      return state(
        "contradictory",
        projectId,
        "The browser dataset cache contains an incomplete canonical identity.",
      );
    }
  }

  return state(
    "ready",
    projectId,
    "The exact registered Dataset Library version is verified for this project.",
    { identity: activeIdentity },
  );
}

