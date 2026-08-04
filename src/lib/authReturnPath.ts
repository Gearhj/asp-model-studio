/**
 * Preserve a same-origin deep link across authentication without accepting an
 * external or protocol-relative redirect. Authentication routes themselves
 * are rejected to avoid redirect loops.
 */
export function safeAuthReturnPath(value: string | null | undefined): string | null {
  const candidate = String(value ?? "").trim();
  if (!candidate.startsWith("/") || candidate.startsWith("//") || candidate.includes("\\")) {
    return null;
  }
  try {
    const parsed = new URL(candidate, "http://atlas.local");
    if (parsed.origin !== "http://atlas.local") return null;
    if (parsed.pathname === "/login" || parsed.pathname === "/register") return null;
    return `${parsed.pathname}${parsed.search}${parsed.hash}`;
  } catch {
    return null;
  }
}

export function loginPathForReturnTo(pathname: string, search = "", hash = "") {
  const returnTo = safeAuthReturnPath(`${pathname}${search}${hash}`);
  return returnTo
    ? `/login?returnTo=${encodeURIComponent(returnTo)}`
    : "/login";
}
