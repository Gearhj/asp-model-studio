import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

const root = process.cwd();
const read = (file) => fs.readFileSync(path.join(root, file), "utf8");

const packageJson = JSON.parse(read("package.json"));
const app = read("src/apps/ModelingApp.tsx");
const sidebar = read("src/components/Sidebar.tsx");
const studio = read("src/steps/ModelDocumentationStudio.tsx");
const lib = read("src/lib/modelDocumentation.ts");
const router = read("server/model_documentation/documentation_router.py");
const store = read("server/model_documentation/documentation_store.py");
const main = read("server/main.py");
const overview = read("src/steps/ProjectOverview.tsx");
const diagnostics = read("src/steps/ModelDiagnostics.tsx");
const chartStudio = read("src/steps/ChartStudio.tsx");
const analytics = read("src/steps/AnalyticsWorkbench.tsx");

assert.equal(packageJson.scripts["test:model-documentation"], "node tests/modelDocumentationStudio.test.mjs");

assert.match(app, /ModelDocumentationStudio/, "Model Documentation Studio must be imported.");
assert.match(app, /path="\/model-document-studio"/, "Model Documentation Studio route must be registered.");
assert.match(app, /path="\/model-document"[\s\S]*Navigate to="\/model-document-studio"/, "Old Model Document route must redirect to Studio.");
assert.match(app, /path="\/model-development-document"[\s\S]*Navigate to="\/model-document-studio"/, "Old Model Development Document route must redirect to Studio.");
assert.match(sidebar, /Model Documentation Studio/, "Sidebar must expose Model Documentation Studio.");
assert.match(sidebar, /to="\/model-document-studio"/, "Sidebar route must point to Model Documentation Studio.");
assert.equal((sidebar.match(/Model Documentation Studio/g) ?? []).length, 1, "Sidebar should expose one primary Model Documentation Studio entry.");
assert.doesNotMatch(sidebar, />Model Document</, "Sidebar must not expose duplicate Model Document entry.");
assert.doesNotMatch(sidebar, />Model Development Document</, "Sidebar must not expose duplicate Model Development Document entry.");
assert.match(sidebar, /workflowSteps\.map/, "Workflow documentation checkpoint should come from workflow step metadata, not a duplicate sidebar product.");

for (const term of [
  "Model Documentation Studio",
  "Project",
  "Template",
  "Document Outline",
  "Section Editor",
  "Evidence Library",
  "Document Quality",
  "Export Package",
  "Model Development Document",
  "Model Validation Evidence Pack",
  "Model Monitoring Handoff",
  "Executive Summary",
  "Technical Appendix",
  "Use Auto Draft",
  "Save Section",
  "Run Quality Check",
  "Export to Word",
  "Export to PowerPoint",
  "Export Evidence Pack to Excel",
  "Create Documentation Workspace",
  "Refresh Workspace Evidence",
  "Documentation Readiness",
  "Refresh Evidence",
  "Pull Latest Project Evidence",
  "Pull Dataset Evidence",
  "Pull Model Diagnostics Evidence",
  "Pull Chart Studio Evidence",
  "Pull Analytics Workbench Evidence",
  "Pull Governance Notes",
  "Evidence Coverage Summary",
  "Export readiness warning",
  "Document Preview",
  "Selected Section",
  "Full Document Summary",
  "Section-level evidence recommendations",
  "Attach Recommended Evidence",
  "Preview Evidence",
  "Open Source Pages",
  "Advanced details",
  "Recommended for this section",
  "Attach to Current Section",
  "Auto-Attach Available Evidence",
  "attached",
  "available",
  "critical gap",
  "Needs Evidence means ATLAS could not find or attach required supporting artifacts",
  "Needs Evidence",
  "Ready for Review",
  "Your session is not authenticated. Sign in again to create a documentation workspace.",
]) {
  assert.match(studio, new RegExp(term.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")), `Studio UI missing ${term}.`);
}

assert.doesNotMatch(studio, /<pre className="mt-2 max-h-28/, "Evidence Library should not show raw JSON by default.");
assert.match(studio, /details className=.*Advanced details/s, "Raw evidence details should be hidden under Advanced details.");
assert.match(studio, /window\.confirm/, "Exports should warn when required evidence is missing.");
assert.match(studio, /RightPaneTabs/, "Studio must use tabbed right-side Evidence, Quality, Export, and Source Pages.");
assert.match(studio, /filterEvidenceItems/, "Evidence Library must support filters and search.");
assert.match(studio, /normalizeStatus/, "Studio must normalize legacy missing evidence statuses.");
assert.match(studio, /handleAutoAttachAvailableEvidence/, "Studio must implement Auto-Attach Available Evidence.");
assert.match(studio, /sectionEvidenceReadiness/, "Studio outline must show evidence readiness counts per section.");
assert.match(studio, /recommendedEvidenceForSection/, "Studio must map recommended evidence to selected sections.");
assert.doesNotMatch(studio, /Legacy Model Development Document/, "Studio should not link to a legacy duplicate document product.");
assert.match(studio, /Documentation Review Checkpoint/, "Studio source pages should link to the workflow documentation checkpoint.");
assert.match(lib, /credentials: "include"/, "Documentation requests must include auth credentials.");
assert.match(lib, /response\.status === 401/, "Documentation client must map 401s to friendly inline auth guidance.");

for (const fn of [
  "listDocumentationTemplates",
  "getDocumentationProjectContext",
  "createModelDocumentation",
  "saveDocumentationSection",
  "attachDocumentationEvidence",
  "runDocumentationQualityCheck",
  "getDocumentationEvidenceLibrary",
  "exportModelDocumentation",
]) {
  assert.match(lib, new RegExp(`export async function ${fn}\\(`), `Documentation API missing ${fn}.`);
}

for (const endpoint of [
  '@router.get("/model-documentation/templates")',
  '@router.get("/model-documentation/project-context/{project_id}")',
  '@router.post("/model-documentation/create")',
  '@router.get("/model-documentation/{document_id}")',
  '@router.post("/model-documentation/{document_id}/save-section")',
  '@router.post("/model-documentation/{document_id}/attach-evidence")',
  '@router.post("/model-documentation/{document_id}/quality-check")',
  '@router.get("/model-documentation/{document_id}/evidence-library")',
  '@router.post("/model-documentation/{document_id}/export/word")',
  '@router.post("/model-documentation/{document_id}/export/powerpoint")',
  '@router.post("/model-documentation/{document_id}/export/evidence-excel")',
]) {
  assert.match(router, new RegExp(endpoint.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")), `Router missing ${endpoint}.`);
}

assert.match(main, /model_documentation_router/, "Backend main must import the documentation router.");
assert.match(main, /Model Documentation Studio/, "Backend main must register documentation router tag.");

for (const term of [
  "MODEL_DEVELOPMENT_OUTLINE",
  "DOCUMENTATION_ROOT",
  '"artifacts" / "model_documentation"',
  "model_development_document",
  "validation_evidence_pack",
  "monitoring_handoff",
  "executive_summary",
  "technical_appendix",
  "build_project_context",
  "create_document",
  "save_section",
  "attach_evidence",
  "quality_check",
  "evidence_library",
  "export_word",
  "export_powerpoint",
  "export_evidence_excel",
  "list_analytics_insights",
  "model_diagnostics",
  "ready_for_review",
  "Project Metadata and Workflow Context",
  "Target Definition Evidence",
  "Dataset Inventory",
  "Governance and Fair Lending Notes",
  "dedupe_evidence",
]) {
  assert.match(store, new RegExp(term.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")), `Documentation store missing ${term}.`);
}

assert.doesNotMatch(store, /status = "missing_evidence"/, "Newly drafted sections should not default to scary Missing Evidence status.");
assert.match(store, /section_id == "target_definition"[\s\S]*target_metadata/, "Target Definition must auto-attach target metadata.");
assert.match(store, /section_id in \{"data_sources", "development_test_oot", "target_definition", "population_definition"\}/, "Data Sources and split sections must auto-attach Dataset Library evidence.");
assert.match(store, /section_id in \{"model_diagnostics", "scoring_external_validation", "performance_summary"/, "Performance sections must auto-attach diagnostics evidence when available.");
assert.match(store, /section_id == "fair_lending_governance"[\s\S]*Governance and Fair Lending Notes/, "Fair Lending and Governance must auto-attach governance warnings.");

for (const sectionId of [
  "executive_summary",
  "business_objective",
  "target_definition",
  "data_sources",
  "missing_value_treatment",
  "outlier_treatment",
  "feature_engineering",
  "candidate_models",
  "champion_model_selection",
  "performance_summary",
  "model_interpretation",
  "model_diagnostics",
  "fair_lending_governance",
  "implementation_plan",
  "monitoring_plan",
]) {
  assert.match(store, new RegExp(sectionId), `Model Development Document outline missing ${sectionId}.`);
}

assert.match(overview, /Open Model Documentation Studio/, "Project Overview must link to Model Documentation Studio.");
assert.match(diagnostics, /Add Diagnostic to Model Documentation/, "Model Diagnostics must link evidence into documentation workflow.");
assert.match(chartStudio, /Add Chart to Model Documentation/, "Chart Studio must link chart evidence into documentation workflow.");
assert.match(analytics, /Add Insight to Model Documentation/, "Analytics Workbench must link insights into documentation workflow.");

console.log("Model Documentation Studio Phase 11 checks passed.");
