export type VifSimulatorCandidate = {
  featureName: string;
  zone: "acceptable" | "review" | "material" | "unavailable";
};

function normalizedName(value: string | null | undefined) {
  return String(value ?? "").trim().toLocaleLowerCase();
}

/** Resolve the candidate using VIF-only state; this function never mutates. */
export function resolveVifSimulatorCandidate<T extends VifSimulatorCandidate>(
  rows: readonly T[],
  selectedVifVariable: string | null | undefined,
): T | null {
  const selected = normalizedName(selectedVifVariable);
  if (selected) {
    return (
      rows.find((row) => normalizedName(row.featureName) === selected) ?? null
    );
  }
  return (
    rows.find((row) => row.zone === "material") ??
    rows.find((row) => row.zone === "review") ??
    null
  );
}
