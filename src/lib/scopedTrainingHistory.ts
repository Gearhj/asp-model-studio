import {
  requireCanonicalDatasetIdentity,
  type CanonicalDatasetIdentityInput,
} from "./datasetIdentity";

const API_BASE =
  (import.meta.env?.VITE_API_BASE as string | undefined)?.replace(/\/$/, "") ||
  "http://127.0.0.1:8001/api";

export type ScopedTrainingHistoryResult<T = unknown> =
  | { status: "success"; httpStatus: 200; summary: T }
  | { status: "empty"; httpStatus: 200 | 404; summary: null }
  | { status: "unauthenticated"; httpStatus: 401; summary: null }
  | { status: "unauthorized"; httpStatus: 403; summary: null }
  | { status: "stale"; httpStatus: 409; summary: null }
  | { status: "invalid"; httpStatus: 422; summary: null }
  | { status: "error"; httpStatus: number; summary: null }
  | { status: "network_error"; httpStatus: 0; summary: null }
  | { status: "aborted"; httpStatus: 0; summary: null };

export async function requestScopedTrainingHistory<T = unknown>(
  identityInput: CanonicalDatasetIdentityInput,
  signal?: AbortSignal,
): Promise<ScopedTrainingHistoryResult<T>> {
  const identity = requireCanonicalDatasetIdentity(
    identityInput,
    "Training history dataset identity",
  );
  const query = new URLSearchParams({
    project_id: identity.project_id,
    dataset_id: identity.dataset_id,
    dataset_version_id: identity.dataset_version_id,
  });

  try {
    const response = await fetch(`${API_BASE}/train/last?${query.toString()}`, {
      credentials: "include",
      signal,
    });
    const payload = await response.json().catch(() => null);
    if (response.status === 401) return { status: "unauthenticated", httpStatus: 401, summary: null };
    if (response.status === 403) return { status: "unauthorized", httpStatus: 403, summary: null };
    if (response.status === 404) return { status: "empty", httpStatus: 404, summary: null };
    if (response.status === 409) return { status: "stale", httpStatus: 409, summary: null };
    if (response.status === 422) return { status: "invalid", httpStatus: 422, summary: null };
    if (!response.ok) return { status: "error", httpStatus: response.status, summary: null };
    if (payload?.summary == null) return { status: "empty", httpStatus: 200, summary: null };
    return { status: "success", httpStatus: 200, summary: payload.summary as T };
  } catch (error) {
    if (signal?.aborted || (error instanceof DOMException && error.name === "AbortError")) {
      return { status: "aborted", httpStatus: 0, summary: null };
    }
    return { status: "network_error", httpStatus: 0, summary: null };
  }
}

