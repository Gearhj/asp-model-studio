import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const read = (path) => readFile(new URL(`../${path}`, import.meta.url), "utf8");

const [
  packageJsonText,
  serverMain,
  migration,
  accessRepository,
  sharingRepository,
  adminRouter,
  sharingRouter,
  adminService,
  sharingService,
  adminClient,
  shareDialog,
  adminConsole,
  sharingCenter,
  modelingApp,
  sidebar,
  projectOverview,
  registryDetail,
  datasetLibrary,
  evidenceGraph,
  documentationStudio,
] = await Promise.all([
  read("package.json"),
  read("server/main.py"),
  read("server/persistence/migrations/0006_admin_access_sharing.sql"),
  read("server/persistence/repositories/access_repository.py"),
  read("server/persistence/repositories/sharing_repository.py"),
  read("server/admin/router.py"),
  read("server/sharing/router.py"),
  read("server/admin/admin_service.py"),
  read("server/sharing/sharing_service.py"),
  read("src/lib/adminSharing.ts"),
  read("src/components/sharing/ShareResourceDialog.tsx"),
  read("src/steps/AdminConsole.tsx"),
  read("src/steps/SharingCenter.tsx"),
  read("src/apps/ModelingApp.tsx"),
  read("src/components/Sidebar.tsx"),
  read("src/steps/ProjectOverview.tsx"),
  read("src/steps/RegistryAssetDetail.tsx"),
  read("src/steps/DatasetLibrary.tsx"),
  read("src/steps/EvidenceGraph.tsx"),
  read("src/steps/ModelDocumentationStudio.tsx"),
]);

test("admin access sharing migration creates required tables and indexes", () => {
  for (const table of [
    "user_groups",
    "user_group_members",
    "access_policies",
    "resource_permissions",
    "sharing_events",
    "share_links",
    "access_requests",
    "project_collaborators",
  ]) {
    assert.match(migration, new RegExp(`CREATE TABLE IF NOT EXISTS ${table}`));
  }
  for (const index of [
    "idx_resource_permissions_resource",
    "idx_resource_permissions_principal",
    "idx_user_group_members_group",
    "idx_user_group_members_user",
    "idx_sharing_events_resource",
    "idx_access_requests_requester",
    "idx_access_requests_status",
    "idx_project_collaborators_project",
  ]) {
    assert.ok(migration.includes(index), `Missing migration index ${index}`);
  }
});

test("backend repositories and services support users, groups, resources, requests, and audits", () => {
  assert.match(accessRepository, /class AccessRepository/);
  assert.match(sharingRepository, /class SharingRepository/);
  for (const method of ["upsert_group", "add_group_member", "grant_permission", "create_access_request", "resolve_access_request"]) {
    assert.ok(accessRepository.includes(method), `Missing access repository method ${method}`);
  }
  for (const method of ["create_event", "create_share_link", "revoke_share_link"]) {
    assert.ok(sharingRepository.includes(method), `Missing sharing repository method ${method}`);
  }
  for (const token of ["resource_shared", "share_revoked", "access_requested", "access_request_approved", "access_request_denied"]) {
    assert.ok(sharingService.includes(token), `Missing sharing audit action ${token}`);
  }
  for (const role of ["admin", "data_scientist", "validator", "manager", "business_owner", "viewer"]) {
    assert.ok(adminService.includes(role), `Missing platform role ${role}`);
  }
});

test("admin and sharing API routes are registered under /api", () => {
  assert.match(serverMain, /include_router\(admin_router, prefix="\/api"/);
  assert.match(serverMain, /include_router\(sharing_router, prefix="\/api"/);
  for (const route of [
    "/admin/users",
    "/admin/groups",
    "/admin/permissions/grant",
    "/admin/permissions/revoke",
    "/admin/access-requests",
    "/admin/summary",
  ]) {
    assert.ok(adminRouter.includes(route), `Missing admin route ${route}`);
  }
  for (const route of [
    "/sharing/resources/{resource_type}/{resource_id}",
    "/share",
    "/revoke",
    "/shared-with-me",
    "/shared-by-me",
    "/request-access",
    "/access-check/{resource_type}/{resource_id}",
    "/share-link",
  ]) {
    assert.ok(sharingRouter.includes(route), `Missing sharing route ${route}`);
  }
});

test("frontend client exposes admin and sharing endpoints", () => {
  for (const path of [
    "/admin/summary",
    "/admin/users",
    "/admin/groups",
    "/admin/access-requests",
    "/sharing/shared-with-me",
    "/sharing/shared-by-me",
    "/sharing/resources/",
  ]) {
    assert.ok(adminClient.includes(path), `Missing client path ${path}`);
  }
});

test("admin console, sharing center, and share dialog expose required user workflows", () => {
  for (const label of ["ATLAS Admin Console", "User Management", "Add User", "Groups and Teams", "Access Requests", "Permission Audit", "Platform Access Policies"]) {
    assert.ok(adminConsole.includes(label), `Admin Console missing ${label}`);
  }
  for (const label of ["Sharing Center", "Shared with Me", "Shared by Me", "Access Requests"]) {
    assert.ok(sharingCenter.includes(label), `Sharing Center missing ${label}`);
  }
  for (const label of ["Share", "Share with", "Recipient", "Permission level", "Current access", "Revoke"]) {
    assert.ok(shareDialog.includes(label), `Share dialog missing ${label}`);
  }
  assert.ok(shareDialog.includes("Notification delivery is local to ATLAS. Email delivery is not enabled."));
});

test("navigation and resource pages include access management entry points", () => {
  assert.ok(modelingApp.includes('path="/admin"'));
  assert.ok(modelingApp.includes('path="/sharing"'));
  assert.match(sidebar, />Admin Console</);
  assert.match(sidebar, />Shared with Me</);
  assert.ok(projectOverview.includes("Access & Sharing"));
  assert.ok(projectOverview.includes("Share Project"));
  assert.ok(registryDetail.includes("Asset access panel"));
  assert.ok(registryDetail.includes("Share Asset"));
  assert.ok(datasetLibrary.includes("Share Dataset"));
  assert.ok(evidenceGraph.includes("Share Evidence"));
  assert.ok(documentationStudio.includes("Share Documentation"));
});

test("visible copy added for admin and sharing contains no em dash", () => {
  for (const source of [adminConsole, sharingCenter, shareDialog, projectOverview, registryDetail, datasetLibrary, evidenceGraph, documentationStudio]) {
    assert.doesNotMatch(source, /—|–|â€”/);
  }
});

test("admin sharing test command is registered", () => {
  const packageJson = JSON.parse(packageJsonText);
  assert.equal(packageJson.scripts["test:admin-sharing"], "node tests/adminSharing.test.mjs && .\\.venv\\Scripts\\python.exe tests\\admin_sharing_backend_test.py");
});
