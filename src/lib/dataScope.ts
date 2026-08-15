export type AtlasDataScopeTone =
  | "neutral"
  | "info"
  | "success"
  | "warning"
  | "danger";

export const ATLAS_DATA_SCOPE_METADATA = {
  full_dataset: { label: "Full Dataset", tone: "success" },
  complete_browser_dataset: { label: "Complete Browser Dataset", tone: "info" },
  preview_profile: { label: "Preview Profile", tone: "warning" },
  rendered_sample: { label: "Rendered Sample", tone: "neutral" },
  registered_structural_population: {
    label: "Registered Structural Population",
    tone: "success",
  },
  training_pipeline: { label: "Training-Only Pipeline", tone: "info" },
  full_governed_population: { label: "Full Governed Population", tone: "success" },
  full_governed_population_structural_only: {
    label: "Full Governed Population · Structural Only",
    tone: "warning",
  },
  development_population: { label: "Development Population", tone: "info" },
  out_of_fold: { label: "Out-of-Fold Development", tone: "info" },
  final_holdout: { label: "Final Holdout · Evaluation Only", tone: "warning" },
  out_of_time: { label: "Out-of-Time Holdout", tone: "warning" },
  bounded_visual_sample: { label: "Bounded Visual Sample", tone: "neutral" },
  unavailable: { label: "Scope Unavailable", tone: "danger" },
} as const satisfies Record<
  string,
  { label: string; tone: AtlasDataScopeTone }
>;

export type AtlasDataScope = keyof typeof ATLAS_DATA_SCOPE_METADATA;

export function resolveAtlasDataScope(scope: unknown) {
  const recognized =
    typeof scope === "string" &&
    Object.prototype.hasOwnProperty.call(ATLAS_DATA_SCOPE_METADATA, scope);
  const resolvedScope: AtlasDataScope = recognized
    ? (scope as AtlasDataScope)
    : "unavailable";
  return {
    scope: resolvedScope,
    recognized,
    ...ATLAS_DATA_SCOPE_METADATA[resolvedScope],
  };
}

export function getAtlasDataScopeLabel(scope: unknown) {
  return resolveAtlasDataScope(scope).label;
}
