import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const read = (path) => readFile(new URL(`../${path}`, import.meta.url), "utf8");
const [workflows, routeWrapper, shell, demoData, workflowPage, templates, registryPrimitives, registryService] = await Promise.all([
  read("src/config/workflows.ts"),
  read("src/features/experimental-design/pages/ExperimentalDesignWorkflowPage.tsx"),
  read("src/workflows/llm/LlmWorkflowShell.tsx"),
  read("src/workflows/llm/llmDemoData.ts"),
  read("src/workflows/llm/LlmWorkflowPage.tsx"),
  read("server/validation/validation_templates.py"),
  read("src/components/registry/RegistryPrimitives.tsx"),
  read("server/registry/registry_service.py"),
]);

const expectedSteps = [
  "Use Case & Risk Context",
  "Data & Knowledge Sources",
  "Task Design & Output Schema",
  "Prompt & Instruction Design",
  "Retrieval / RAG Configuration",
  "Evaluation Dataset",
  "LLM Evaluation",
  "Safety, Compliance & Red-Team Review",
  "Human Review & Quality Control",
  "Deployment & Monitoring Plan",
  "Recommendation & Approval",
  "Documentation",
];

test("LLM / Generative AI workflow exists with expected step order", () => {
  assert.match(workflows, /id: "llm_generative_ai"/);
  assert.match(workflows, /label: "LLM \/ Generative AI"/);
  const workflowStart = workflows.indexOf('const llmGenerativeAiSteps');
  const workflowEnd = workflows.indexOf('export const experimentalDesignJourney', workflowStart);
  const workflowBlock = workflows.slice(workflowStart, workflowEnd);
  let lastIndex = -1;
  for (const label of expectedSteps) {
    const index = workflowBlock.indexOf(`["${label}"`);
    assert.notEqual(index, -1, `Missing LLM step: ${label}`);
    assert.ok(index > lastIndex, `LLM step is out of order: ${label}`);
    lastIndex = index;
  }
});

test("LLM workflow routes through dedicated components, not generic placeholder pages", () => {
  assert.match(routeWrapper, /workflowId === "llm_generative_ai"/);
  assert.match(routeWrapper, /LlmWorkflowPage/);
  assert.match(routeWrapper, /WorkflowPlaceholderStep/);
  assert.ok(!workflowPage.includes("WorkflowPlaceholderStep"), "LLM page must not import the generic placeholder renderer");
  assert.ok(!shell.includes("WorkflowPlaceholderStep"), "LLM shell must not render the generic placeholder body");
});

test("LLM pages include code, evidence, source, prompt, RAG, evaluation, and safety support", () => {
  for (const token of [
    "llmPages",
    "LLM / GENERATIVE AI WORKFLOW",
    "Code & Reproducibility",
    "llm_use_case_context",
    "llm_source_inventory",
    "llm_task_design",
    "llm_prompt_design",
    "llm_retrieval_configuration",
    "llm_evaluation_dataset",
    "llm_evaluation_results",
    "llm_safety_red_team_review",
    "llm_human_review_quality_control",
    "llm_deployment_monitoring_plan",
    "llm_recommendation_approval",
    "llm_governance_documentation_package",
    "Retrieval / RAG Configuration",
    "hallucination",
    "UDAAP",
    "Manual evaluation",
  ]) {
    assert.ok(`${shell}\n${demoData}`.includes(token), `Missing LLM renderer token ${token}`);
  }
});

test("LLM pages expose page-specific governance and evaluation content", () => {
  for (const token of [
    "LLM / GENERATIVE AI WORKFLOW",
    "customer impact",
    "Human review",
    "sensitive data",
    "Prohibited uses",
    "Source inventory table",
    "PII/confidentiality flags",
    "Output schema preview",
    "label definitions",
    "extraction field map",
    "System instruction",
    "Developer instruction",
    "user prompt template",
    "Token estimate",
    "Instruction conflict",
    "chunking strategy",
    "Embedding model label",
    "Top-k",
    "Citation preview",
    "golden answer",
    "adversarial example",
    "Rubric",
    "Groundedness",
    "citation accuracy",
    "hallucination rate",
    "refusal correctness",
    "classification precision/recall/F1",
    "prompt injection",
    "data leakage",
    "fair lending",
    "privacy",
    "Sampling strategy",
    "Override process",
    "Monitoring threshold table",
    "change control",
    "residual risks",
    "LLM governance package",
  ]) {
    assert.ok(`${shell}\n${demoData}`.includes(token), `Missing LLM page-specific token ${token}`);
  }
});

test("LLM dedicated pages include the required unique acceptance phrases", () => {
  for (const token of [
    "Allowed/prohibited behavior matrix",
    "Source inventory table",
    "Output schema preview",
    "Prompt component editor",
    "Document-to-chunk pipeline",
    "Evaluation coverage matrix",
    "Hallucination/citation matrix",
    "Safety risk heatmap",
    "Human review workflow diagram",
    "Version and change-control summary",
    "Required controls checklist",
    "LLM governance package",
  ]) {
    assert.ok(`${shell}\n${demoData}`.includes(token), `Missing required LLM acceptance phrase ${token}`);
  }
  assert.ok(!demoData.includes("Predictive Modeling Workflow"), "LLM page data should not use the Predictive Modeling Workflow header");
});

test("LLM pages do not reuse the rejected generic controls scaffold", () => {
  const workflowSource = `${shell}\n${demoData}\n${workflowPage}`;
  assert.equal((workflowSource.match(/Workflow Controls/g) ?? []).length, 0, "LLM must not render the generic Workflow Controls block");
  assert.ok((workflowSource.match(/Recommended default/g) ?? []).length <= 3, "LLM must not contain repeated generic Recommended default dropdown values");
  assert.ok(!workflowPage.includes("WorkflowPlaceholderStep"), "WorkflowPlaceholderStep must not be the LLM main renderer");
  assert.ok(!demoData.includes("Predictive Modeling Workflow"), "LLM pages must not say Predictive Modeling Workflow");
});

test("LLM named workspaces cover required positive page checks", () => {
  const workflowSource = `${shell}\n${demoData}`;
  for (const token of [
    "System instruction editor",
    "User prompt template editor",
    "Token estimate",
    "Instruction conflict panel",
    "Document-to-chunk pipeline",
    "Top-k",
    "Retrieval preview",
    "Citation preview",
    "Hallucination/citation matrix",
    "Error examples table",
    "Safety risk heatmap",
    "Red-team checklist",
  ]) {
    assert.ok(workflowSource.includes(token), `Missing required LLM positive check ${token}`);
  }
});

test("LLM pages are structurally differentiated", () => {
  const layouts = [...demoData.matchAll(/layout: "([^"]+)"/g)].map((match) => match[1]);
  const titles = [...demoData.matchAll(/^    title: "([^"]+)"/gm)].map((match) => match[1]);
  assert.equal(layouts.length, 12, "LLM should define one layout per workflow step");
  assert.equal(titles.length, 12, "LLM should define one title per workflow step");
  assert.ok(new Set(layouts).size >= 10, "LLM pages should not reuse one repeated chart structure");
  assert.ok(new Set(titles).size === 12, "LLM pages should not reuse one repeated diagnostic title");
});

test("LLM registry classification and validation template exist", () => {
  assert.match(registryService, /llm_workflow/);
  assert.match(registryPrimitives, /LLM Workflow/);
  assert.match(templates, /LLM_ITEMS/);
  assert.match(templates, /"llm_generative_ai"/);
  for (const item of ["use_case_risk", "source_inventory", "task_schema", "prompt_design", "retrieval", "evaluation", "safety", "human_review", "deployment_monitoring"]) {
    assert.ok(templates.includes(item), `Missing LLM validation item ${item}`);
  }
});
