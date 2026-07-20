export function safeArray<T = unknown>(value: unknown): T[] {
  return Array.isArray(value) ? (value as T[]) : [];
}

export function safeObject<T extends Record<string, unknown> = Record<string, unknown>>(value: unknown): T {
  return value && typeof value === "object" && !Array.isArray(value) ? (value as T) : ({} as T);
}

export function formatNullableMetric(value: unknown, digits = 2, unavailable = "Unavailable") {
  const number = Number(value);
  if (!Number.isFinite(number)) return unavailable;
  return number.toLocaleString(undefined, { maximumFractionDigits: digits });
}

export function getDatasetScopeLabel(scope: unknown) {
  if (scope === "full_dataset") return "Full Dataset";
  if (scope === "complete_browser_dataset") return "Complete Browser Dataset";
  if (scope === "preview_profile") return "Preview Profile";
  if (scope === "rendered_sample") return "Rendered Sample";
  return "Unavailable";
}
