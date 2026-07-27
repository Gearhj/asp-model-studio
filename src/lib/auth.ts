import { DATASET_API_BASE, type AtlasUser } from "./datasetLibrary";
import { getCachedUserId, setCachedUserId } from "./authSession";
import { clearUserDatasetState } from "./localDataset";

async function authFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${DATASET_API_BASE}${path}`, {
    credentials: "include",
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers ?? {}),
    },
  });
  const payload = await response.json().catch(() => null);
  if (!response.ok || payload?.ok === false) {
    throw new Error(payload?.detail ?? payload?.error ?? `ATLAS auth request failed with HTTP ${response.status}.`);
  }
  return payload as T;
}

export type AuthResponse = {
  ok: true;
  user: AtlasUser;
  sessionExpiresAt?: string;
};

export async function login(email: string, password: string) {
  const response = await authFetch<AuthResponse>("/auth/login", {
    method: "POST",
    body: JSON.stringify({ email, password }),
  });
  setCachedUserId(response.user?.userId ?? null);
  return response;
}

export async function register(email: string, displayName: string, password: string) {
  const response = await authFetch<AuthResponse>("/auth/register", {
    method: "POST",
    body: JSON.stringify({ email, displayName, password }),
  });
  setCachedUserId(response.user?.userId ?? null);
  return response;
}

export async function logout() {
  // Clear this user's scoped browser dataset state BEFORE dropping the
  // cached identity -- clearUserDatasetState needs the outgoing userId to
  // know which sessionStorage keys belong to them (dataset lifecycle /
  // browser state isolation repair, Stage 6.2).
  const outgoingUserId = getCachedUserId();
  const response = await authFetch<{ ok: true }>("/auth/logout", { method: "POST" });
  if (outgoingUserId) clearUserDatasetState(outgoingUserId);
  setCachedUserId(null);
  return response;
}

export async function me() {
  const response = await authFetch<AuthResponse>("/auth/me");
  setCachedUserId(response.user?.userId ?? null);
  return response;
}

export async function changePassword(currentPassword: string, newPassword: string) {
  return authFetch<{ ok: true }>("/auth/change-password", {
    method: "POST",
    body: JSON.stringify({ currentPassword, newPassword }),
  });
}

export async function adminUsers() {
  return authFetch<{ ok: true; users: AtlasUser[] }>("/admin/users");
}

export async function adminCreateUser(input: { email: string; displayName: string; password: string; role: string }) {
  return authFetch<AuthResponse>("/admin/users", {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export async function adminSetRole(userId: string, role: string) {
  return authFetch<AuthResponse>(`/admin/users/${userId}/role`, {
    method: "POST",
    body: JSON.stringify({ role }),
  });
}

export async function adminDisableUser(userId: string) {
  return authFetch<AuthResponse>(`/admin/users/${userId}/disable`, { method: "POST" });
}

export async function adminEnableUser(userId: string) {
  return authFetch<AuthResponse>(`/admin/users/${userId}/enable`, { method: "POST" });
}

export async function adminUnlockUser(userId: string) {
  return authFetch<AuthResponse>(`/admin/users/${userId}/unlock`, { method: "POST" });
}

export async function auditEvents(filters: Record<string, string> = {}) {
  const params = new URLSearchParams(Object.entries(filters).filter(([, value]) => Boolean(value)));
  return authFetch<{ ok: true; events: Array<Record<string, unknown>> }>(`/audit/events${params.toString() ? `?${params}` : ""}`);
}

export async function grantProjectAccess(projectId: string, userId: string, permission: string) {
  return authFetch<{ ok: true }>(`/projects/${projectId}/access/grant`, {
    method: "POST",
    body: JSON.stringify({ userId, permission }),
  });
}
