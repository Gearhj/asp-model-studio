// UX-NEWPROJECT-001 (generalization): schema-driven configuration for the
// unified Project Setup section shown at the top of the New Project page.
// One shared rendering path (see src/steps/NewProject.tsx's
// UnifiedProjectSetupSection) consumes this config -- workflow differences
// live here as data, never as forked JSX per workflow type.
import type { ProjectType } from "./workflows";

export type ProjectSetupFieldSpec = {
  label: string;
  /** Short form used inside guidance sentences ("Enter a {guidanceLabel} to
   *  continue.") -- distinct from `label` because the visible field label can
   *  carry punctuation (e.g. "Model ID #") that reads awkwardly in a sentence.
   *  Defaults to `label` when omitted. */
  guidanceLabel?: string;
  placeholder: string;
  helperText: string;
  required: boolean;
};

export type ProjectSetupFormConfig = {
  heading: string;
  description: string;
  buttonLabel: string;
  nameField: ProjectSetupFieldSpec;
  /** null = this workflow type has no product meaning for a Model ID; the
   *  field is not rendered at all (not shown-and-optional, genuinely absent). */
  modelIdField: ProjectSetupFieldSpec | null;
  /** Compact "Required Setup" chip value. */
  requiredSummary: string;
  /** Compact "Optional" chip value, or null when nothing optional applies. */
  optionalSummary: string | null;
};

const MODEL_ID_HELPER_REQUIRED = "The organization's unique identifier for this model, such as 15211.";
const MODEL_ID_HELPER_OPTIONAL = "Optional. ATLAS creates a project identifier automatically if left blank.";
const PROJECT_NAME_HELPER = "A clear, descriptive name for this project.";
const PROJECT_NAME_PLACEHOLDER = "Untitled ATLAS Project";

const OPTIONAL_MODEL_ID_FIELD: ProjectSetupFieldSpec = {
  label: "Model ID #",
  guidanceLabel: "Model ID",
  placeholder: "15211",
  helperText: MODEL_ID_HELPER_OPTIONAL,
  required: false,
};

/** Statically configured for every workflow type exposed on the New Project
 * page today (projectTypeOptions in ./workflows). Predictive Modeling keeps
 * its existing required Model Name + Model ID behavior unchanged. */
export const PROJECT_SETUP_FORMS: Partial<Record<ProjectType, ProjectSetupFormConfig>> = {
  "predictive-modeling": {
    heading: "Create the model record that will anchor this project",
    description:
      "Enter the official Model Name and Model ID used by your organization. These values will flow into the Model Registry, validation records, evidence, and Model Development Documentation.",
    buttonLabel: "Create Predictive Modeling Project",
    nameField: {
      label: "Model Name",
      placeholder: "Credit Card Fraud Detection Model",
      helperText: "The official business or governance name for this model.",
      required: true,
    },
    modelIdField: {
      label: "Model ID #",
      guidanceLabel: "Model ID",
      placeholder: "15211",
      helperText: MODEL_ID_HELPER_REQUIRED,
      required: true,
    },
    requiredSummary: "Model Name and Model ID",
    optionalSummary: null,
  },
  "ab-testing": {
    heading: "Create the project record that will anchor this experiment",
    description: "Enter the project identity used to organize experiment design, results, evidence, and documentation.",
    buttonLabel: "Create Experimentation Project",
    nameField: { label: "Project Name", placeholder: PROJECT_NAME_PLACEHOLDER, helperText: PROJECT_NAME_HELPER, required: true },
    modelIdField: OPTIONAL_MODEL_ID_FIELD,
    requiredSummary: "Project Name",
    optionalSummary: "Model ID",
  },
  optimization: {
    heading: "Create the project record that will anchor this optimization study",
    description:
      "Enter the project identity used to organize objectives, constraints, scenarios, recommendations, evidence, and documentation.",
    buttonLabel: "Create Optimization Project",
    nameField: { label: "Project Name", placeholder: PROJECT_NAME_PLACEHOLDER, helperText: PROJECT_NAME_HELPER, required: true },
    modelIdField: OPTIONAL_MODEL_ID_FIELD,
    requiredSummary: "Project Name",
    optionalSummary: "Model ID",
  },
  time_series_forecasting: {
    heading: "Create the project record that will anchor this forecasting study",
    description: "Enter the project identity used to organize source data, forecast runs, diagnostics, evidence, and documentation.",
    buttonLabel: "Create Time Series & Forecasting Project",
    nameField: { label: "Project Name", placeholder: PROJECT_NAME_PLACEHOLDER, helperText: PROJECT_NAME_HELPER, required: true },
    modelIdField: OPTIONAL_MODEL_ID_FIELD,
    requiredSummary: "Project Name",
    optionalSummary: "Model ID",
  },
  llm_generative_ai: {
    heading: "Create the project record that will anchor this AI workflow",
    description: "Enter the project identity used to organize prompts, evaluations, evidence, governance, and documentation.",
    buttonLabel: "Create LLM / Generative AI Project",
    nameField: { label: "Project Name", placeholder: PROJECT_NAME_PLACEHOLDER, helperText: PROJECT_NAME_HELPER, required: true },
    modelIdField: OPTIONAL_MODEL_ID_FIELD,
    requiredSummary: "Project Name",
    optionalSummary: "Model ID",
  },
  "graph-analytics": {
    heading: "Create the project record that will anchor this graph analysis",
    description: "Enter the project identity used to organize graph data, analytical runs, evidence, and documentation.",
    buttonLabel: "Create Graph Analytics Project",
    nameField: { label: "Project Name", placeholder: PROJECT_NAME_PLACEHOLDER, helperText: PROJECT_NAME_HELPER, required: true },
    modelIdField: OPTIONAL_MODEL_ID_FIELD,
    requiredSummary: "Project Name",
    optionalSummary: "Model ID",
  },
  "computer-vision": {
    heading: "Create the project record that will anchor this computer vision workflow",
    description: "Enter the project identity used to organize image or video data, model development, evidence, and documentation.",
    buttonLabel: "Create Computer Vision Project",
    nameField: { label: "Project Name", placeholder: PROJECT_NAME_PLACEHOLDER, helperText: PROJECT_NAME_HELPER, required: true },
    modelIdField: OPTIONAL_MODEL_ID_FIELD,
    requiredSummary: "Project Name",
    optionalSummary: "Model ID",
  },
  "reinforcement-learning": {
    heading: "Create the project record that will anchor this reinforcement-learning study",
    description: "Enter the project identity used to organize environments, policies, experiments, evidence, and documentation.",
    buttonLabel: "Create Reinforcement Learning Project",
    nameField: { label: "Project Name", placeholder: PROJECT_NAME_PLACEHOLDER, helperText: PROJECT_NAME_HELPER, required: true },
    modelIdField: OPTIONAL_MODEL_ID_FIELD,
    requiredSummary: "Project Name",
    optionalSummary: "Model ID",
  },
  "custom-workflow": {
    heading: "Create the project record that will anchor this workflow",
    description: "Enter the project identity used to organize workflow steps, analytical results, evidence, and documentation.",
    buttonLabel: "Create Custom Workflow Project",
    nameField: { label: "Project Name", placeholder: PROJECT_NAME_PLACEHOLDER, helperText: PROJECT_NAME_HELPER, required: true },
    // Custom Workflow is user-defined with no fixed governed-model identity concept --
    // a Model ID has no product meaning here, so it is not rendered at all (not
    // shown-and-optional; genuinely absent, per "do not display it merely for
    // visual consistency if it is not used").
    modelIdField: null,
    requiredSummary: "Project Name",
    optionalSummary: null,
  },
};

/** Defensive fallback for any ProjectType not explicitly configured above
 * (the New Project page's own card grid only ever selects the 9 types listed,
 * but ProjectType's union is wider) -- synthesizes accurate, non-overclaiming
 * copy from the resolved workflow's own label rather than leaving the section
 * blank or reusing Predictive Modeling's language. */
export function resolveProjectSetupFormConfig(projectType: ProjectType, workflowLabel: string): ProjectSetupFormConfig {
  const known = PROJECT_SETUP_FORMS[projectType];
  if (known) return known;
  return {
    heading: `Create the project record that will anchor this ${workflowLabel.toLowerCase()} workflow`,
    description: "Enter the project identity used to organize this workflow's analysis, evidence, and documentation.",
    buttonLabel: "Create Project",
    nameField: { label: "Project Name", placeholder: PROJECT_NAME_PLACEHOLDER, helperText: PROJECT_NAME_HELPER, required: true },
    modelIdField: OPTIONAL_MODEL_ID_FIELD,
    requiredSummary: "Project Name",
    optionalSummary: "Model ID",
  };
}

/** Generic, workflow-agnostic completion guidance -- computed from field
 * validity, never forked per workflow. Handles: N required fields (combined
 * message when all missing, field-specific when one missing), an optional
 * field reassurance message, and the ready state. */
export function computeSetupGuidance(
  config: ProjectSetupFormConfig,
  values: { name: string; modelId: string }
): string {
  const requiredFields: Array<{ label: string; valid: boolean }> = [
    { label: config.nameField.guidanceLabel ?? config.nameField.label, valid: Boolean(values.name.trim()) },
  ];
  if (config.modelIdField?.required) {
    requiredFields.push({ label: config.modelIdField.guidanceLabel ?? config.modelIdField.label, valid: Boolean(values.modelId.trim()) });
  }
  const missing = requiredFields.filter((field) => !field.valid);
  if (missing.length > 1 && missing.length === requiredFields.length) {
    return "Enter both required fields to continue.";
  }
  if (missing.length > 0) {
    return `Enter a ${missing[0].label} to continue.`;
  }
  if (config.modelIdField && !config.modelIdField.required && !values.modelId.trim()) {
    return `${config.modelIdField.guidanceLabel ?? config.modelIdField.label} is optional.`;
  }
  return "Ready to create the project.";
}

export function isProjectSetupComplete(config: ProjectSetupFormConfig, values: { name: string; modelId: string }): boolean {
  const nameValid = Boolean(values.name.trim());
  const modelIdValid = !config.modelIdField?.required || Boolean(values.modelId.trim());
  return nameValid && modelIdValid;
}
