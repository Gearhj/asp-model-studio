// Ambient cache of the authenticated user's id, mirroring the backend's
// active_user() ContextVar pattern (server/security/security_store.py). The
// backend resolves identity per-request from the session cookie; the browser
// has no equivalent per-call context, so this small module gives client-only
// code (e.g. src/lib/localDataset.ts) a synchronous way to read "who is
// signed in right now" without prop-drilling userId through every step page.
// Kept in sync by src/lib/auth.ts's login/register/me/logout calls.
let cachedUserId: string | null = null;

export function setCachedUserId(userId: string | null) {
  cachedUserId = userId || null;
}

export function getCachedUserId(): string | null {
  return cachedUserId;
}
