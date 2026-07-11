import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";

const root = process.cwd();
const read = (file) => fs.readFileSync(path.join(root, file), "utf8");
const pkg = JSON.parse(read("package.json"));
const app = read("src/apps/ModelingApp.tsx");
const sidebar = read("src/components/Sidebar.tsx");
const page = read("src/steps/EvidenceGraph.tsx");
const client = read("src/lib/evidenceGraph.ts");
const financialTaxonomyClient = read("src/lib/financialServicesEvidence.ts");
const main = read("server/main.py");
const router = read("server/evidence/evidence_router.py");
const store = read("server/evidence/evidence_store.py");
const financialTaxonomyServer = read("server/evidence/financial_services_taxonomy.py");
const types = read("server/evidence/evidence_types.py");
const overview = read("src/steps/ProjectOverview.tsx");
const datasetDetail = read("src/steps/DatasetDetail.tsx");
const notebook = read("src/steps/NotebookStudio.tsx");
const sqlStudio = read("src/steps/SqlDataStudio.tsx");
const docs = read("src/steps/ModelDocumentationStudio.tsx");
const diagnostics = read("src/steps/ModelDiagnostics.tsx");

assert.equal(pkg.scripts["test:evidence-graph"], "node tests/evidenceGraph.test.mjs", "package script must run Evidence Graph tests.");

assert.match(app, /import EvidenceGraph/, "Evidence Graph route component must be imported.");
assert.match(app, /path="\/model-evidence-center"/, "Model Evidence Center route must be registered.");
assert.match(app, /path="\/evidence-graph" element={<Navigate to="\/model-evidence-center" replace/, "Old Evidence Graph route must redirect to Model Evidence Center.");
assert.match(sidebar, /Model Evidence Center/, "Sidebar must expose Model Evidence Center.");
assert.doesNotMatch(sidebar, />Evidence Graph</, "Sidebar must not show Evidence Graph as the primary label.");
assert.match(sidebar, /Network/, "Sidebar should use a graph/network icon.");

for (const label of ["Model Evidence Center", "Collects the proof behind your model", "Why this matters", "What counts as evidence?"]) {
  assert(page.includes(label), `Model Evidence Center page must include ${label}.`);
}
for (const label of ["Evidence Inventory", "Timeline", "Evidence Map", "Coverage", "Financial Services", "Financial Services Coverage", "Credit Risk Evidence Coverage"]) {
  assert(page.includes(label), `Model Evidence Center page must include ${label} tab or section.`);
}
for (const label of ["Capture Current Project Evidence", "Export Model Evidence Pack", "Recommended Next Actions", "Open Source", "Mark Ready", "Mark Needs Review", "Attach to Documentation", "Add Credit Risk Evidence", "Save Credit Risk Evidence"]) {
  assert(page.includes(label), `Model Evidence Center page must include ${label} action.`);
}
for (const phrase of ["Interactive Graph Canvas", "Evidence Map graph canvas", "No evidence map yet", "Capture current project evidence to build the map"]) {
  assert(page.includes(phrase), `Evidence Map or empty state must include ${phrase}.`);
}
for (const phrase of ["Evidence Flow", "Source View", "Documentation View", "Credit Risk View", "Reset View", "Zoom -", "Zoom +"]) {
  assert(page.includes(phrase), `Interactive Evidence Map controls must include ${phrase}.`);
}
for (const phrase of ["Expand Map", "Exit Map Focus", "Show edge labels", "Show only selected connections", "Group documentation sections"]) {
  assert(page.includes(phrase), `Evidence Map layout controls must include ${phrase}.`);
}
for (const phrase of ["Node Type", "Financial Domain", "Documentation Section", "Selected Node Detail"]) {
  assert(page.includes(phrase), `Interactive Evidence Map filters/detail must include ${phrase}.`);
}
assert(page.includes("evidence-map-full-width-workspace"), "Evidence Map must render a full-width graph workspace.");
assert(page.includes("selected-node-detail-below-map"), "Selected Node Detail must render below the graph.");
assert(page.includes('tab !== "map" && <aside'), "Evidence Map must not render the right detail rail beside the graph.");
assert(page.includes('tab === "map" && mapFocusMode ? "hidden"'), "Expand Map focus mode must hide the filter rail.");
for (const phrase of ["Dataset", "Notebook", "Diagnostic", "Governance", "Needs Review", "Credit Risk Evidence", "Documentation Section"]) {
  assert(page.includes(phrase), `Interactive Evidence Map legend must include ${phrase}.`);
}
for (const phrase of ["uses dataset", "generated from", "supports section", "documents", "requires review", "linked to project", "governance flag"]) {
  assert(store.includes(phrase) || page.includes(phrase), `Evidence Map must support edge relationship ${phrase}.`);
}
for (const column of ["Title", "Type", "Credit Risk", "Source", "Project", "Dataset", "Status", "Importance", "Created", "Document support", "Actions"]) {
  assert(page.includes(column), `Evidence table must include ${column} column.`);
}
for (const filter of ["Financial Domain", "Credit Risk Technique", "Product Type", "Model Purpose", "Regulatory Relevance"]) {
  assert(page.includes(filter), `Model Evidence Center must include ${filter} filter.`);
}

for (const endpoint of [
  "@router.get(\"/evidence\")",
  "@router.post(\"/evidence\")",
  "@router.get(\"/evidence/graph\")",
  "@router.get(\"/evidence/coverage/{project_id}\")",
  "@router.get(\"/evidence/project/{project_id}\")",
  "@router.get(\"/evidence/dataset/{dataset_id}\")",
  "@router.post(\"/evidence/auto-capture\")",
  "@router.post(\"/evidence/export/excel\")",
]) {
  assert(router.includes(endpoint), `Backend router must define ${endpoint}.`);
}
for (const query of ["financialDomain", "financialTechnique", "productType", "modelPurpose", "regulatoryRelevance"]) {
  assert(router.includes(query), `Backend router must expose ${query} evidence filter.`);
  assert(store.includes(query), `Evidence store must filter/persist ${query}.`);
}
assert.match(main, /evidence_router/, "FastAPI app must import and include Evidence Graph router.");
assert.match(main, /include_router\(evidence_router/, "FastAPI app must register Evidence Graph router.");

assert(store.includes("server/artifacts/evidence") || store.includes("/ \"evidence\""), "Store must persist evidence under server artifacts evidence folder.");
assert(store.includes("evidence_registry.json"), "Store must maintain evidence_registry.json.");
assert(store.includes("quality_score"), "Store must calculate evidence quality.");
assert(store.includes("auto_capture"), "Store must support auto-capture.");
assert(store.includes("export_excel"), "Store must support Excel export.");
for (const graphField of ["source", "target", "label", "metadata", "Project", "Export Package", "Governance Warning"]) {
  assert(store.includes(graphField), `Evidence graph API must expose graph-ready ${graphField}.`);
}

for (const evidenceType of ["dataset", "sql_query", "sql_result", "eda", "model_training", "evaluation", "model_diagnostics", "chart", "notebook", "documentation", "governance", "decision", "export"]) {
  assert(types.includes(`"${evidenceType}"`), `Evidence type ${evidenceType} must be supported.`);
}
for (const tag of ["credit_risk", "fraud", "aml", "marketing", "fair_lending", "monitoring", "governance"]) {
  assert(client.includes(`"${tag}"`) || types.includes(`"${tag}"`), `Financial services tag ${tag} must be available.`);
}
for (const domain of ["credit_risk", "fraud_aml", "marketing_profitability", "model_risk_governance", "portfolio_risk", "decision_strategy"]) {
  assert(financialTaxonomyClient.includes(domain), `Frontend taxonomy missing financial domain ${domain}.`);
  assert(financialTaxonomyServer.includes(domain), `Backend taxonomy missing financial domain ${domain}.`);
}
for (const technique of ["pdo", "woe", "iv", "manual_binning", "reject_inference", "ttc", "pit", "psi", "challenger_champion", "adverse_action", "fair_lending", "monotonic_constraints", "cutoff_optimization", "strategy_trees", "risk_based_pricing", "monotonic_gbm", "surrogate_scorecard", "scorecard_scaling", "odds_calibration"]) {
  assert(financialTaxonomyClient.includes(technique), `Frontend taxonomy missing credit-risk technique ${technique}.`);
  assert(financialTaxonomyServer.includes(technique), `Backend taxonomy missing credit-risk technique ${technique}.`);
}
for (const phrase of ["Score = Offset + Factor * ln(odds)", "Factor = PDO / ln(2)", "Offset = BaseScore - Factor * ln(BaseOdds)"]) {
  assert(page.includes(phrase) || financialTaxonomyClient.includes(phrase), `PDO formula guidance missing: ${phrase}.`);
}
for (const fn of ["listEvidence", "createEvidence", "updateEvidence", "deleteEvidence", "getProjectEvidence", "getDatasetEvidence", "getEvidenceGraph", "getEvidenceCoverage", "autoCaptureEvidence", "exportEvidencePack", "evidenceQualityScore"]) {
  assert(client.includes(`function ${fn}`) || client.includes(`async function ${fn}`), `Client must export ${fn}.`);
}

assert(overview.includes("Evidence Summary") && overview.includes("Financial Services Evidence") && overview.includes("Open Model Evidence Center"), "Project Overview must show Evidence Summary, Financial Services Evidence, and Model Evidence Center link.");
assert(datasetDetail.includes("Evidence linked to this dataset") && datasetDetail.includes("Save Dataset to Model Evidence Center"), "Dataset Detail must include dataset evidence panel.");
assert(notebook.includes("Save Notebook Output to Model Evidence Center") && notebook.includes("Open Model Evidence Center"), "Notebook Studio must save output to Model Evidence Center.");
assert(sqlStudio.includes("Save Query to Model Evidence Center") && sqlStudio.includes("Save SQL Result to Model Evidence Center"), "SQL Data Studio must save query and result evidence.");
assert(docs.includes("Import from Model Evidence Center") && docs.includes("credit_risk"), "Model Documentation Studio must import and filter Credit Risk Evidence.");
for (const hook of ["Save PSI Evidence", "Save Cutoff Evidence", "Save Fair Lending Review Note", "Save Challenger/Champion Evidence"]) {
  assert(diagnostics.includes(hook), `Model Diagnostics missing credit-risk hook: ${hook}.`);
}

console.log("Model Evidence Center Phase 14E tests passed.");
