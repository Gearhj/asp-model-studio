import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const read = (path) => readFile(new URL(`../${path}`, import.meta.url), "utf8");

const [
  packageJsonText,
  migration,
  notificationRepo,
  collaborationRepo,
  notificationRouter,
  adminRouter,
  sharingService,
  adminService,
  adminClient,
  adminConsole,
  notificationCenter,
  shareDialog,
  resultShareActions,
  accessControl,
  accessDenied,
  auditPage,
  modelingApp,
  sidebar,
] = await Promise.all([
  read("package.json"),
  read("server/persistence/migrations/0007_enterprise_collaboration_hardening.sql"),
  read("server/persistence/repositories/notification_repository.py"),
  read("server/persistence/repositories/collaboration_repository.py"),
  read("server/notifications/router.py"),
  read("server/admin/router.py"),
  read("server/sharing/sharing_service.py"),
  read("server/admin/admin_service.py"),
  read("src/lib/adminSharing.ts"),
  read("src/steps/AdminConsole.tsx"),
  read("src/steps/NotificationCenter.tsx"),
  read("src/components/sharing/ShareResourceDialog.tsx"),
  read("src/components/sharing/ResultShareActions.tsx"),
  read("src/lib/accessControl.ts"),
  read("src/components/sharing/AccessDeniedRequest.tsx"),
  read("src/steps/AuthPages.tsx"),
  read("src/apps/ModelingApp.tsx"),
  read("src/components/Sidebar.tsx"),
]);

test("enterprise collaboration migration adds notifications, ownership, and access reviews", () => {
  for (const table of ["notifications", "ownership_transfers", "access_reviews", "access_review_items"]) {
    assert.match(migration, new RegExp(`CREATE TABLE IF NOT EXISTS ${table}`));
  }
  for (const index of ["idx_notifications_recipient", "idx_ownership_transfers_resource", "idx_access_reviews_resource", "idx_access_review_items_review"]) {
    assert.ok(migration.includes(index), `Missing index ${index}`);
  }
});

test("notification backend supports lifecycle endpoints and persistence", () => {
  assert.match(notificationRepo, /class NotificationRepository/);
  for (const method of ["create", "list_for_user", "unread_count", "mark_read", "dismiss", "mark_all_read"]) {
    assert.ok(notificationRepo.includes(method), `Missing notification repository method ${method}`);
  }
  for (const path of ["/notifications", "/notifications/unread-count", "/notifications/{notification_id}/read", "/notifications/{notification_id}/dismiss", "/notifications/mark-all-read"]) {
    assert.ok(notificationRouter.includes(path), `Missing notification route ${path}`);
  }
});

test("admin backend exposes audit export, ownership transfer, access review, and bulk access", () => {
  for (const method of ["audit_log", "audit_csv", "request_ownership_transfer", "complete_ownership_transfer", "create_access_review", "decide_access_review_item", "bulk_permission_preview", "bulk_permission_apply"]) {
    assert.ok(adminService.includes(method), `Missing admin service method ${method}`);
  }
  for (const route of ["/admin/audit-log", "/admin/audit-log/export.csv", "/admin/audit-log/export.json", "/admin/ownership-transfers", "/admin/access-reviews", "/admin/bulk-access/preview", "/admin/bulk-access/apply"]) {
    assert.ok(adminRouter.includes(route), `Missing admin route ${route}`);
  }
  assert.match(collaborationRepo, /class CollaborationRepository/);
});

test("sharing and access request workflow creates notifications", () => {
  for (const token of ["_shared", "access_requested", "access_request_approved", "access_request_denied", "_notify"]) {
    assert.ok(sharingService.includes(token), `Sharing service missing ${token}`);
  }
});

test("frontend exposes Notification Center and admin collaboration controls", () => {
  assert.ok(modelingApp.includes('path="/notifications"'));
  assert.ok(sidebar.includes("Notifications"));
  assert.ok(notificationCenter.includes("Notification Center"));
  assert.ok(notificationCenter.includes("Notification delivery is local to ATLAS. Email delivery is not enabled."));
  for (const label of ["Bulk Access", "Preview affected resources", "Access Reviews", "Ownership Transfer", "Create access review", "Transfer ownership"]) {
    assert.ok(adminConsole.includes(label), `Admin Console missing ${label}`);
  }
});

test("audit log page renders filters, details, and real export links", () => {
  for (const label of ["Permission and sharing events only", "Admin actions only", "Export filtered audit log CSV", "Export filtered audit log JSON", "Audit Detail Drawer"]) {
    assert.ok(auditPage.includes(label), `Audit page missing ${label}`);
  }
  assert.ok(adminClient.includes("/admin/audit-log/export."));
});

test("share dialog has regulated warning, search, expiration, current access, and history", () => {
  for (const label of ["Search", "7 days", "30 days", "Custom date", "Sharing regulated datasets", "Current access", "Sharing history", "Granted by", "Expires"]) {
    assert.ok(shareDialog.includes(label), `Share dialog missing ${label}`);
  }
});

test("access-aware helpers and access denied request state exist", () => {
  assert.ok(accessControl.includes("filterAccessControlledResources"));
  assert.ok(accessControl.includes("canUserAccessResource"));
  assert.ok(accessDenied.includes("Request Access"));
  assert.ok(accessDenied.includes("Requested permission"));
});

test("specialized result/export share action labels are available without fake resource IDs", () => {
  for (const label of [
    "Share Optimization Solution",
    "Share Allocation CSV/export",
    "Share Sensitivity Results",
    "Share Validation Result",
    "Share Model Run",
    "Share Model Comparison",
    "Share Evaluation Results",
    "Share Scored Dataset",
    "Share Forecast Result",
    "Share Backtest Results",
    "Share Forecast CSV/export",
    "Share Prompt Package",
    "Share Source Inventory",
    "Share Safety Review",
    "Share Documentation Package",
  ]) {
    assert.ok(resultShareActions.includes(label), `Missing specialized share action ${label}`);
  }
});

test("enterprise collaboration test script is registered", () => {
  const packageJson = JSON.parse(packageJsonText);
  assert.equal(packageJson.scripts["test:enterprise-collaboration"], "node tests/enterpriseCollaboration.test.mjs && .\\.venv\\Scripts\\python.exe tests\\enterprise_collaboration_backend_test.py");
});
