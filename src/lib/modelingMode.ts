export type ModelingMode = "guided" | "advanced";

export const MODELING_MODE_KEY = "modeling-tool-mode";

export function loadModelingMode(): ModelingMode {
  if (typeof localStorage === "undefined") return "guided";
  return localStorage.getItem(MODELING_MODE_KEY) === "advanced" ? "advanced" : "guided";
}

export function saveModelingMode(mode: ModelingMode) {
  localStorage.setItem(MODELING_MODE_KEY, mode);
  window.dispatchEvent(new CustomEvent("modeling-mode-updated", { detail: { mode } }));
}

export function modeDescription(mode: ModelingMode) {
  return mode === "advanced"
    ? "Advanced mode emphasizes editable Python, experiment comparison, notebook export, and governance artifacts."
    : "Guided mode emphasizes visual workflow steps, recommended defaults, explanations, and guardrails.";
}
