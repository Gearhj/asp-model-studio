// Dataset Library: Card View / Detailed View action parity.
//
// PROVEN ROOT CAUSE guarded here: the Dataset Library rendered its actions as
// inline JSX in TWO independent places -- `DatasetDetailTable` exposed 9 actions
// (open, analytics, chart-studio, sql-studio, model-diagnostics, link, share,
// export, archive) while the card grid exposed 3 (open, share, archive). The
// view toggle therefore changed available FUNCTIONALITY, not just presentation:
// SQL Data Studio, Analytics, Chart Studio, Model Diagnostics, Link to Project,
// and Export were unreachable from Card View.
//
// Both views now derive from `buildDatasetActions()`. These tests EXECUTE that
// model rather than regex the component, so they fail if the two views can ever
// diverge again.
import assert from "node:assert/strict";
import { mkdir, readFile, rm, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import test from "node:test";
import ts from "typescript";

const ROOT = new URL("..", import.meta.url);
const TMP_DIR = fileURLToPath(new URL("../.tmp/dataset-action-parity-tests", import.meta.url));

async function transpile(sourcePath, outputName) {
  const source = await readFile(new URL(sourcePath, ROOT), "utf8");
  const patched = source.replace(/import\.meta\.env\?\.\w+ as string \| undefined/g, "undefined");
  const output = ts.transpileModule(patched, {
    compilerOptions: { module: ts.ModuleKind.ES2022, target: ts.ScriptTarget.ES2022 },
  }).outputText;
  const outPath = path.join(TMP_DIR, outputName);
  await mkdir(path.dirname(outPath), { recursive: true });
  await writeFile(outPath, output, "utf8");
  return import(pathToFileURL(outPath).href);
}

await rm(TMP_DIR, { recursive: true, force: true });
const model = await transpile("src/lib/datasetActions.ts", "datasetActions.js");
const library = await readFile(new URL("src/steps/DatasetLibrary.tsx", ROOT), "utf8");
const controls = await readFile(new URL("src/components/datasets/DatasetActionControls.tsx", ROOT), "utf8");

const OWNER = { userId: "user_owner", displayName: "Owner", role: "data_scientist" };
const STRANGER = { userId: "user_reader", displayName: "Reader", role: "data_scientist" };
const ADMIN = { userId: "local-user", displayName: "Admin", role: "admin" };

/** A registered, versioned CLASS_TRAIN-shaped dataset owned by OWNER. */
function classTrain(overrides = {}) {
  return {
    datasetId: "ds_class_train_982c7a7d_35930",
    name: "CLASS_TRAIN",
    ownerUserId: "user_owner",
    archived: false,
    versionCount: 1,
    access: [],
    latestVersion: { versionId: "v_1784989835930_982c7a7d", createdAt: "", rowCount: 170884, columnCount: 31 },
    linkedProjects: [],
    ...overrides,
  };
}

function ctx(overrides = {}) {
  // canAccessCurrentProject: null = undetermined (never blocks); false = the
  // server proved this caller cannot reach the project.
  return { currentUser: OWNER, currentProjectId: "atlas-abc123", isScoredOutput: false, canAccessCurrentProject: null, ...overrides };
}

const build = (dataset, context) => model.buildDatasetActions(dataset, context);
const ids = (actions) => model.datasetActionIds(actions);

// Detailed View renders every action; Card View splits the same array.
const detailedIds = (dataset, context) => ids(build(dataset, context));
const cardIds = (dataset, context) => [
  ...ids(model.primaryDatasetActions(build(dataset, context))),
  ...ids(model.overflowDatasetActions(build(dataset, context))),
];

// ---------------------------------------------------------------- 1, 2, 3 ---
test("1. Detailed View exposes the full inventory of real actions", () => {
  const actions = detailedIds(classTrain(), ctx());
  assert.deepEqual(actions, [
    "open",
    "link-project",
    "sql-studio",
    "analytics",
    "chart-studio",
    "share",
    "export-metadata",
    "archive",
  ]);
});

test("2. Card View exposes the same inventory across primary + More Actions", () => {
  const primary = ids(model.primaryDatasetActions(build(classTrain(), ctx())));
  const overflow = ids(model.overflowDatasetActions(build(classTrain(), ctx())));
  assert.deepEqual(primary, ["open", "link-project", "sql-studio"]);
  assert.deepEqual(overflow, ["analytics", "chart-studio", "share", "export-metadata", "archive"]);
});

test("3. both views expose the SAME action IDs for the same dataset and user", () => {
  for (const dataset of [
    classTrain(),
    classTrain({ archived: true }),
    classTrain({ latestVersion: undefined }),
    classTrain({ access: [{ userId: "user_reader", role: "viewer" }] }),
  ]) {
    for (const context of [ctx(), ctx({ currentUser: STRANGER }), ctx({ currentUser: ADMIN }), ctx({ currentProjectId: null })]) {
      assert.deepEqual(
        [...cardIds(dataset, context)].sort(),
        [...detailedIds(dataset, context)].sort(),
        `parity broken for ${dataset.datasetId} archived=${dataset.archived}`,
      );
    }
  }
});

test("3b. a scored output adds Model Diagnostics to BOTH views, not just one", () => {
  const scored = ctx({ isScoredOutput: true });
  assert.ok(detailedIds(classTrain(), scored).includes("model-diagnostics"));
  assert.ok(cardIds(classTrain(), scored).includes("model-diagnostics"));
  assert.ok(!detailedIds(classTrain(), ctx()).includes("model-diagnostics"));
  assert.ok(!cardIds(classTrain(), ctx()).includes("model-diagnostics"));
});

// ------------------------------------------------------------------- 4-10 ---
test("4. Card View More Actions contains every secondary action", () => {
  const overflow = model.overflowDatasetActions(build(classTrain(), ctx()));
  for (const id of ["analytics", "chart-studio", "share", "export-metadata", "archive"]) {
    assert.ok(overflow.some((action) => action.id === id), `${id} missing from More Actions`);
  }
});

/** Every field that determines behaviour must be identical across views. */
function assertBehaviourIdentical(actionId, dataset = classTrain(), context = ctx()) {
  const all = build(dataset, context);
  const fromDetailed = all.find((action) => action.id === actionId);
  const fromCard = [...model.primaryDatasetActions(all), ...model.overflowDatasetActions(all)].find(
    (action) => action.id === actionId,
  );
  assert.ok(fromDetailed, `${actionId} absent from Detailed View`);
  assert.ok(fromCard, `${actionId} absent from Card View`);
  // Same object identity: both views literally render the same action.
  assert.equal(fromDetailed, fromCard, `${actionId} is a different object per view`);
  for (const key of ["navigateTo", "handlerId", "enabled", "disabledReason", "requiresConfirmation", "confirmationMessage", "requiredCapability", "destructive", "tooltip", "accessibleLabel"]) {
    assert.deepEqual(fromCard[key], fromDetailed[key], `${actionId}.${key} diverges between views`);
  }
}

test("5. Open behaves identically from both views", () => {
  assertBehaviourIdentical("open");
  const open = build(classTrain(), ctx()).find((a) => a.id === "open");
  assert.equal(open.navigateTo, "/datasets/ds_class_train_982c7a7d_35930");
});

test("6. SQL Data Studio behaves identically and carries the dataset identity", () => {
  assertBehaviourIdentical("sql-studio");
  const sql = build(classTrain(), ctx()).find((a) => a.id === "sql-studio");
  assert.equal(sql.navigateTo, "/sql-data-studio?datasetId=ds_class_train_982c7a7d_35930");
});

test("7. Link to Project behaves identically from both views", () => {
  assertBehaviourIdentical("link-project");
  const link = build(classTrain(), ctx()).find((a) => a.id === "link-project");
  assert.equal(link.handlerId, "link-project");
  assert.equal(link.enabled, true);
});

test("8. Share behaves identically from both views", () => {
  assertBehaviourIdentical("share");
  const share = build(classTrain(), ctx()).find((a) => a.id === "share");
  assert.equal(share.handlerId, "share");
  assert.equal(share.requiredCapability, "write");
});

test("9. Export metadata behaves identically from both views", () => {
  assertBehaviourIdentical("export-metadata");
  const exportAction = build(classTrain(), ctx()).find((a) => a.id === "export-metadata");
  assert.equal(exportAction.handlerId, "export-metadata");
});

test("10. Archive carries the SAME confirmation for both views", () => {
  assertBehaviourIdentical("archive");
  const archive = build(classTrain(), ctx()).find((a) => a.id === "archive");
  assert.equal(archive.destructive, true);
  assert.equal(archive.requiresConfirmation, true);
  assert.match(archive.confirmationMessage, /^Delete "CLASS_TRAIN" from the Dataset Library\?/);
  // Confirmation is executed once, centrally -- not duplicated per view.
  assert.equal(
    (library.match(/window\.confirm\(/g) || []).length,
    1,
    "window.confirm must appear exactly once, in the shared dispatcher",
  );
  assert.match(library, /if \(action\.requiresConfirmation && action\.confirmationMessage\)/);
});

// --------------------------------------------------------------- 11 and 12 ---
test("11. disabled actions AND their reasons match across views", () => {
  const cases = [
    { dataset: classTrain({ latestVersion: undefined }), context: ctx(), id: "sql-studio", reason: /no registered version/ },
    { dataset: classTrain({ latestVersion: undefined }), context: ctx(), id: "link-project", reason: /no registered version to link/ },
    { dataset: classTrain(), context: ctx({ currentProjectId: null }), id: "link-project", reason: /No project is currently open/ },
    { dataset: classTrain({ archived: true }), context: ctx(), id: "archive", reason: /already archived/ },
    { dataset: classTrain(), context: ctx({ canAccessCurrentProject: false }), id: "link-project", reason: /do not have access to link datasets to this project/ },
    { dataset: classTrain(), context: ctx({ currentUser: STRANGER }), id: "share", reason: /read-only access/ },
  ];
  for (const { dataset, context, id, reason } of cases) {
    const all = build(dataset, context);
    const action = all.find((entry) => entry.id === id);
    assert.equal(action.enabled, false, `${id} should be disabled`);
    assert.match(action.disabledReason, reason);
    // The disabled action is still PRESENT in both views -- never silently
    // dropped from one of them, which is how divergence starts.
    assert.ok(cardIds(dataset, context).includes(id));
    assert.ok(detailedIds(dataset, context).includes(id));
  }
});

test("12. a permission-restricted user sees the same allowed set in both views", () => {
  const dataset = classTrain();
  const context = ctx({ currentUser: STRANGER });
  const all = build(dataset, context);
  const enabled = all.filter((action) => action.enabled).map((action) => action.id);
  // Read-only: write actions are offered but disabled, identically in both views.
  assert.ok(!enabled.includes("share"));
  assert.ok(!enabled.includes("archive"));
  assert.ok(enabled.includes("open"));
  assert.ok(enabled.includes("sql-studio"));
  assert.deepEqual([...cardIds(dataset, context)].sort(), [...detailedIds(dataset, context)].sort());
});

test("12b. capability mirrors the server ACL exactly (presentation hint only)", () => {
  assert.equal(model.datasetCapability(classTrain(), OWNER), "write", "owner writes");
  assert.equal(model.datasetCapability(classTrain(), ADMIN), "write", "admin writes");
  assert.equal(model.datasetCapability(classTrain(), STRANGER), "read", "non-grantee reads");
  assert.equal(model.datasetCapability(classTrain(), null), "read", "anonymous reads");
  for (const role of ["owner", "editor"]) {
    assert.equal(model.datasetCapability(classTrain({ access: [{ userId: "user_reader", role }] }), STRANGER), "write", `${role} writes`);
  }
  for (const role of ["viewer", "auditor"]) {
    assert.equal(model.datasetCapability(classTrain({ access: [{ userId: "user_reader", role }] }), STRANGER), "read", `${role} reads only`);
  }
  // The hint must never be presented as authorization.
  const source = library + controls;
  assert.doesNotMatch(source, /ATLAS_LOCAL_DEV|X-ATLAS-USER-ID/, "no dev-user bypass in the Dataset Library UI");
});

// ------------------------------------------------------------------ 13-15 ---
test("13. switching views changes only the view mode -- not search, filters, or scope", () => {
  const setter = library.match(/const setDatasetViewMode = \(mode: ViewMode\) => \{[\s\S]*?\n {2}\};/);
  assert.ok(setter, "setDatasetViewMode not found");
  const body = setter[0];
  assert.match(body, /setViewMode\(mode\)/);
  assert.match(body, /localStorage\.setItem/, "view preference is persisted");
  for (const forbidden of ["setQuery", "setDatasetFilter", "setOwnerFilter", "setSort", "refresh", "setShareDataset"]) {
    assert.ok(!body.includes(forbidden), `switching views must not call ${forbidden}`);
  }
  // Both branches render from the SAME filtered+sorted array.
  assert.match(library, /datasets=\{filtered\}/);
  assert.match(library, /\{filtered\.map\(\(dataset\)/);
});

test("14. the More Actions menu is fully keyboard operable", () => {
  assert.match(controls, /aria-haspopup="menu"/);
  assert.match(controls, /aria-expanded=\{open\}/);
  assert.match(controls, /role="menu"/);
  assert.match(controls, /role: "menuitem" as const/);
  for (const key of ["ArrowDown", "ArrowUp", "Home", "End", "Escape", "Tab"]) {
    assert.ok(controls.includes(`"${key}"`), `menu must handle ${key}`);
  }
  assert.match(controls, /triggerRef\.current\?\.focus\(\)/, "focus returns to the trigger");
  assert.match(controls, /document\.addEventListener\("mousedown", onPointerDown\)/, "outside click closes");
  assert.match(controls, /document\.removeEventListener\("mousedown", onPointerDown\)/, "listener is cleaned up");
  assert.match(controls, /tabIndex: index === activeIndex \? 0 : -1/, "roving tabindex");
  // Not colour alone: destructive items carry a text marker.
  assert.match(controls, /Destructive<\/span>/);
  // Icon-only Detailed View controls always carry an accessible name.
  assert.match(controls, /aria-label=\{actionAccessibleName\(action\)\}/);
  assert.match(controls, /title=\{actionTitle\(action\)\}/);
});

test("15. one action cannot fire two mutations", () => {
  assert.match(library, /const inFlightKey = `\$\{dataset\.datasetId\}:\$\{action\.id\}`/);
  assert.match(library, /if \(pendingActions\.has\(inFlightKey\)\) return;/);
  assert.match(library, /finally \{[\s\S]*?next\.delete\(inFlightKey\)/, "the guard is always released");
  assert.match(library, /if \(!action\.enabled \|\| !action\.handlerId\) return;/, "disabled actions never mutate");
});

test("15b. neither view builds its own action list", () => {
  // Exactly one construction site, consumed by both views.
  assert.equal((library.match(/buildDatasetActions\(/g) || []).length, 1);
  assert.match(library, /actionsFor=\{actionsFor\}/, "the table receives the shared builder");
  assert.match(library, /function actionsFor\(dataset: DatasetSummary\): DatasetAction\[\]/);
  // The old inline duplicates are gone.
  assert.doesNotMatch(library, /title="Open in Chart Studio"/, "inline Chart Studio link still duplicated");
  assert.doesNotMatch(library, /title="Export metadata"/, "inline export button still duplicated");
  assert.doesNotMatch(library, /onClick=\{\(\) => setShareDataset\(dataset\)\}/, "inline share handler still duplicated");
});

// ------------------------------------------------------- project-link authz ---
test("16. Link to Project is disabled with the SERVER'S reason when the caller cannot reach the project", () => {
  const denied = ctx({ canAccessCurrentProject: false });
  const action = build(classTrain(), denied).find((entry) => entry.id === "link-project");
  assert.equal(action.enabled, false);
  assert.equal(action.disabledReason, model.PROJECT_LINK_DENIED_REASON);
  // The wording is the backend's own, so the UI explains the real reason.
  assert.equal(model.PROJECT_LINK_DENIED_REASON, "You do not have access to link datasets to this project.");
  // Identical in both views.
  assertBehaviourIdentical("link-project", classTrain(), denied);
});

test("16b. an undetermined probe never blocks -- the backend stays authoritative", () => {
  for (const value of [null, true]) {
    const action = build(classTrain(), ctx({ canAccessCurrentProject: value })).find((e) => e.id === "link-project");
    assert.equal(action.enabled, true, `canAccessCurrentProject=${value} must not disable the action`);
    assert.equal(action.disabledReason, null);
  }
});

test("16c. the probe can only DISABLE -- it can never grant a capability", () => {
  // With a real blocker present, claiming project access must not re-enable.
  const noVersion = build(classTrain({ latestVersion: undefined }), ctx({ canAccessCurrentProject: true }))
    .find((e) => e.id === "link-project");
  assert.equal(noVersion.enabled, false);
  assert.match(noVersion.disabledReason, /no registered version to link/);
  const noProject = build(classTrain(), ctx({ currentProjectId: null, canAccessCurrentProject: true }))
    .find((e) => e.id === "link-project");
  assert.equal(noProject.enabled, false);
  assert.match(noProject.disabledReason, /No project is currently open/);
});

test("16d. the page derives project access from the SERVER, not from local belief", () => {
  assert.match(library, /listProjectsFromDatabase\(\)/, "must ask the authorized projects endpoint");
  assert.match(library, /setCanAccessCurrentProject\(reachable\)/);
  assert.match(library, /setCanAccessCurrentProject\(null\)/, "probe failure must be undetermined, not blocked");
  assert.match(library, /canAccessCurrentProject,/, "the flag reaches the shared action model");
});

// ------------------------------------------------- mutation feedback (defect) ---
test("17. a mutation's outcome message is not erased by the refresh that follows", () => {
  // PROVEN DEFECT: refresh() called setMessage("") unconditionally, so
  //   setMessage(`Linked ...`); await refresh();
  // succeeded and then silently cleared its own confirmation. The credentialed
  // browser run showed exactly this: "Working..." and then no confirmation.
  assert.match(library, /async function refresh\(options\?: \{ preserveMessage\?: boolean \}\)/);
  assert.match(library, /if \(!options\?\.preserveMessage\) setMessage\(""\);/);
  for (const outcome of ["Linked", "Deleted"]) {
    const block = library.slice(library.indexOf(`setMessage(\`${outcome}`));
    assert.match(block.slice(0, 200), /await refresh\(\{ preserveMessage: true \}\)/,
      `${outcome} must preserve its confirmation across the refresh`);
  }
  // A refresh FAILURE must still be able to report itself.
  assert.match(library, /catch \(error\) \{\s*setMessage\(error instanceof Error \? error\.message : "ATLAS could not load the dataset library\."\)/);
});

test("18. linked-to-current-project is durable state, shown identically in both views", () => {
  assert.match(library, /function isLinkedToCurrentProject\(dataset: DatasetSummary\): boolean/);
  // Derived from the SERVER's persisted linkedProjects, not from a local flag.
  assert.match(library, /dataset\.linkedProjects\?\.some\(\(link\) => link\.projectId === currentProjectId\)/);
  // Both views expose the same durable attribute and badge.
  assert.equal((library.match(/data-linked-to-current-project=/g) || []).length, 2);
  assert.equal((library.match(/data-testid="dataset-linked-badge"/g) || []).length, 2);
  // The table cannot compute its own answer -- it is injected.
  assert.match(library, /isLinkedToCurrent: \(dataset: DatasetSummary\) => boolean;/);
  assert.match(library, /isLinkedToCurrent=\{isLinkedToCurrentProject\}/);
});

// ------------------------------------------------------- layout (Parts A/B) ---
test("19. Detailed View gives the Actions column a deliberate width and cannot overlap", () => {
  // The action group was being squeezed by `table-fixed` because the Actions
  // column had no width while every other column did.
  assert.match(library, /w-\[352px\] min-w-\[352px\]/, "Actions column needs an explicit width");
  assert.equal((library.match(/w-\[352px\] min-w-\[352px\]/g) || []).length, 2, "header AND cell must be sized");
  assert.match(library, /min-w-\[1360px\]/, "table must be wide enough for the sized Actions column");
  assert.match(library, /flex-nowrap items-center justify-end gap-1 whitespace-nowrap \[&>\*\]:shrink-0/,
    "controls must not wrap or shrink into neighbouring cells");
  // Horizontal scrolling remains available when the viewport cannot fit it.
  assert.match(library, /overflow-x-auto/);
});

test("20. Card View has one deliberate action footer with no floating control", () => {
  // `ml-auto` on the lone More Actions button is what made it look detached.
  assert.ok(!library.includes("ml-auto"), "no control may float to an arbitrary right edge");
  assert.match(library, /data-testid="dataset-card-primary-group"/, "primary actions are one group");
  // More Actions sits inside that same group, so it aligns as a peer.
  const group = library.slice(library.indexOf('data-testid="dataset-card-primary-group"'));
  const menuAt = group.indexOf("<DatasetActionMenu");
  const closeAt = group.indexOf("</div>");
  assert.ok(menuAt > 0 && menuAt < closeAt, "More Actions must live inside the primary group");
  // Menu stays anchored to its trigger.
  assert.match(controls, /className="relative"/);
  assert.match(controls, /absolute right-0 z-30 mt-1/);
});
