export const SPORTS_AUTHORITY_ERROR_CODES = [
  "BACKEND_UNAVAILABLE",
  "PROJECT_NOT_REGISTERED",
  "DATASET_NOT_LINKED",
  "SOURCE_COVERAGE_UNAVAILABLE",
  "SOURCE_COVERAGE_INSUFFICIENT",
] as const;

export type SportsAuthorityErrorCode = typeof SPORTS_AUTHORITY_ERROR_CODES[number] | "UNKNOWN";

function record(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : null;
}

function nestedDetail(value: unknown) {
  const outer = record(value);
  return record(outer?.detail) ?? outer;
}

export function sanitizeSportsAuthorityMessage(message: string) {
  return message
    .replace(/\bATLAS project\b/gi, "ASP Model Studio sports project")
    .replace(/\bATLAS persistence\b/gi, "project persistence")
    .replace(/\bATLAS database\b/gi, "ASP Model Studio database");
}

export function sportsAuthorityErrorCode(status: number | undefined, detail: unknown, cause?: unknown): SportsAuthorityErrorCode {
  const payload = nestedDetail(detail);
  const rawCode = String(payload?.code || "").trim().toUpperCase();
  if ((SPORTS_AUTHORITY_ERROR_CODES as readonly string[]).includes(rawCode)) {
    return rawCode as SportsAuthorityErrorCode;
  }
  if (cause instanceof TypeError || status === 502 || status === 503 || status === 504 || status === 0) return "BACKEND_UNAVAILABLE";
  if (status === 404) return "PROJECT_NOT_REGISTERED";
  if (status === 422) return "SOURCE_COVERAGE_INSUFFICIENT";
  if (status === 409) return "DATASET_NOT_LINKED";
  return "UNKNOWN";
}

export function sportsAuthorityServerMessage(detail: unknown, fallback = "") {
  const payload = nestedDetail(detail);
  for (const key of ["message", "coverageMessage", "coverage_message", "error"]) {
    if (typeof payload?.[key] === "string" && payload[key]) return sanitizeSportsAuthorityMessage(String(payload[key]));
  }
  return sanitizeSportsAuthorityMessage(fallback);
}

export function sportsAuthorityPresentation(code: SportsAuthorityErrorCode, serverMessage = "") {
  const message = sanitizeSportsAuthorityMessage(serverMessage);
  if (code === "BACKEND_UNAVAILABLE") return {
    title: "Backend unavailable",
    message: "The ASP Model Studio backend cannot be reached. Restore it, then retry this project-scoped request.",
  };
  if (code === "PROJECT_NOT_REGISTERED") return {
    title: "Project not registered",
    message: "This ASP Model Studio sports project is not registered in backend persistence. Reopen it from Sports Projects to reconcile its canonical project ID, then retry.",
  };
  if (code === "DATASET_NOT_LINKED") return {
    title: "Evidence dataset not linked",
    message: "Select a registered evidence dataset for this project before registering its forecast contract.",
  };
  if (code === "SOURCE_COVERAGE_UNAVAILABLE") return {
    title: "Source coverage unavailable",
    message: "The linked dataset does not expose complete registered plate-appearance date coverage. Select another governed registration or repair that registration's metadata.",
  };
  if (code === "SOURCE_COVERAGE_INSUFFICIENT") return {
    title: "Source coverage insufficient",
    message: message || "The requested eligible range extends beyond the linked dataset's registered source coverage.",
  };
  return {
    title: "Project authority request failed",
    message: message || "The project-scoped authority request could not be completed.",
  };
}
