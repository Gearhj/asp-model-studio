import fs from "node:fs";
import path from "node:path";

const root = process.cwd();

function read(relativePath) {
  return fs.readFileSync(path.join(root, relativePath), "utf8");
}

function assert(condition, message) {
  if (!condition) {
    throw new Error(message);
  }
}

const router = read("server/datasets/dataset_router.py");
const registry = read("server/datasets/dataset_registry.py");
const appRoutes = read("src/apps/ModelingApp.tsx");
const sidebar = read("src/components/Sidebar.tsx");
const dataAcquisition = read("src/steps/Step01_DataAcquisition.tsx");
const localDataset = read("src/lib/localDataset.ts");

[
  "/datasets",
  "/datasets/{dataset_id}",
  "/datasets/{dataset_id}/versions",
  "/datasets/upload",
  "/datasets/register",
  "/datasets/{dataset_id}/versions/{version_id}/preview",
  "/datasets/{dataset_id}/share",
  "/projects/{project_id}/datasets/link",
  "/system/diagnostics",
  "/users/switch-dev-user",
].forEach((endpoint) => {
  assert(router.includes(endpoint), `Missing backend endpoint: ${endpoint}`);
});

assert(registry.includes("server/artifacts") || registry.includes("ARTIFACT_ROOT"), "Dataset registry must use backend artifact storage.");
assert(registry.includes("user_can_access"), "Dataset registry must enforce backend ACL checks.");
assert(registry.includes("MAX_SAMPLE_ROWS"), "Dataset registry must store compact sample artifacts.");
assert(!registry.includes("localStorage"), "Dataset registry must not persist datasets in browser localStorage.");

assert(appRoutes.includes('path="/datasets"'), "Dataset Library route is not registered.");
assert(appRoutes.includes('path="/datasets/:datasetId"'), "Dataset Detail route is not registered.");
assert(appRoutes.includes('path="/system/diagnostics"'), "System Diagnostics route is not registered.");
assert(sidebar.includes("Dataset Library"), "Sidebar is missing Dataset Library navigation.");
assert(sidebar.includes("System Diagnostics"), "Sidebar is missing System Diagnostics navigation.");

assert(dataAcquisition.includes("getDatasetPreview"), "Data Acquisition Existing Dataset does not load Dataset Library previews.");
assert(dataAcquisition.includes("linkDatasetToProject"), "Data Acquisition does not link selected datasets to projects.");
assert(localDataset.includes("dataset_library"), "LocalDataset does not preserve Dataset Library references.");

// Card View and Detailed View no longer duplicate their action JSX -- both
// render one shared action model (src/lib/datasetActions.ts) through shared
// controls. The action labels, tooltips, and confirmation text therefore live
// in those modules rather than inline in the page. The assertions below are
// unchanged: every string must still be present in the Dataset Library feature.
const datasetLibraryPage = [
  read("src/steps/DatasetLibrary.tsx"),
  read("src/lib/datasetActions.ts"),
  read("src/components/datasets/DatasetActionControls.tsx"),
].join("\n");
[
  "DATASET_LIBRARY_VIEW_MODE_KEY",
  "atlas-dataset-library-view-mode",
  "readSavedViewMode(DATASET_LIBRARY_VIEW_MODE_KEY, \"detail\")",
  "DatasetSortKey",
  "compareDatasetRows",
  "sort.direction",
  "ownerFilter",
  "All Owners",
  "Detailed View",
  "DatasetDetailTable",
  "SortableDatasetHeader",
  "Dataset Name",
  "Rows",
  "Columns",
  "Owner",
  "Updated",
  "Linked Projects",
  "Status",
  "Actions",
  "Training",
  "Test",
  "OOT",
  "Scored Outputs",
  "Regression",
  "Classification",
  "Linked to Current Project",
  "Unlinked",
  "Open in Analytics",
  "Open in Chart Studio",
  "Open in Model Diagnostics",
  "Link to current project",
  "Delete",
  "ShareResourceDialog",
  "Archive dataset",
  "min-w-[1360px]",
  "sticky right-0",
  "Export metadata",
  "setDatasetViewMode",
  "formatDatasetType",
  "formatSourceType",
].forEach((text) => {
  assert(datasetLibraryPage.includes(text), `Dataset Library detailed view is missing: ${text}`);
});

const projectOverview = read("src/steps/ProjectOverview.tsx");
assert(projectOverview.includes("Share Project"), "Project Overview must expose project sharing.");
assert(projectOverview.includes('resourceType="project"'), "Project sharing must use the governed sharing dialog.");

console.log("Dataset Library v1 static checks passed.");
