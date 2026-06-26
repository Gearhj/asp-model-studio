// src/lib/api.ts
// Minimal, safe helper (does not change any page that doesn't import it)

const rawEnv = (import.meta as any)?.env?.VITE_API_BASE as string | undefined;

// Prefer VITE_API_BASE; otherwise fallback to a dev-friendly "/api" which vite
// proxies to FastAPI on 8001. Normalize trailing slash off.
export const BASE =
  (rawEnv && !rawEnv.endsWith("/") ? rawEnv : rawEnv?.slice(0, -1)) ||
  "/api";

type Json = Record<string, unknown>;

export async function getJSON<T = any>(path: string, init: RequestInit = {}): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    method: "GET",
    ...init,
    headers: {
      "Accept": "application/json",
      ...(init.headers || {}),
    },
  });
  if (!res.ok) throw new Error(`GET ${path} failed: ${res.status}`);
  return res.json();
}

export async function postJSON<T = any>(path: string, body: Json, init: RequestInit = {}): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    method: "POST",
    body: JSON.stringify(body),
    ...init,
    headers: {
      "Content-Type": "application/json",
      "Accept": "application/json",
      ...(init.headers || {}),
    },
  });
  if (!res.ok) throw new Error(`POST ${path} failed: ${res.status}`);
  return res.json();
}
