import fs from "node:fs";
import path from "node:path";

const root = process.cwd();
const read = (file) => fs.readFileSync(path.join(root, file), "utf8");

const securityStore = read("server/security/security_store.py");
const securityRouter = read("server/security/security_router.py");
const datasetRouter = read("server/datasets/dataset_router.py");
const datasetRegistry = read("server/datasets/dataset_registry.py");
const modelingApp = read("src/apps/ModelingApp.tsx");
const authPages = read("src/steps/AuthPages.tsx");
const datasetDetail = read("src/steps/DatasetDetail.tsx");

const assertions = [
  ["security db path", securityStore.includes("atlas_security.db")],
  ["passwords are hashed", securityStore.includes("pbkdf2_hmac") && !securityStore.includes("plaintext")],
  ["session cookie", securityStore.includes("atlas_session") && securityRouter.includes("httponly=True")],
  ["login endpoint", securityRouter.includes('@router.post("/auth/login")')],
  ["logout endpoint", securityRouter.includes('@router.post("/auth/logout")')],
  ["me endpoint", securityRouter.includes('@router.get("/auth/me")')],
  ["admin users endpoint", securityRouter.includes('@router.get("/admin/users")')],
  ["project access endpoint", securityRouter.includes("/projects/{project_id}/access/grant")],
  ["dataset router requires auth", datasetRouter.includes("APIRouter(dependencies=[Depends(require_user)])")],
  ["dataset access endpoints", datasetRouter.includes("/datasets/{dataset_id}/access/grant") && datasetRouter.includes("/datasets/{dataset_id}/access/revoke")],
  ["dataset owner current user", datasetRegistry.includes('"ownerUserId": user.get("userId")')],
  ["audit logging", securityStore.includes("audit_events") && datasetRegistry.includes("audit_event(")],
  ["login routes", modelingApp.includes('path="/login"') && modelingApp.includes('path="/register"')],
  ["account routes", modelingApp.includes('path="/account"') && modelingApp.includes('path="/admin/users"') && modelingApp.includes('path="/audit"')],
  ["auth guard", modelingApp.includes("Loading ATLAS security context") && modelingApp.includes("Navigate to=\"/login\"")],
  ["auth pages", authPages.includes("LoginPage") && authPages.includes("AdminUsersPage") && authPages.includes("AuditPage")],
  ["dataset sharing UI", datasetDetail.includes("Share Dataset") && datasetDetail.includes("grantDatasetAccess")],
];

const failures = assertions.filter(([, ok]) => !ok);
if (failures.length) {
  console.error("User management checks failed:");
  for (const [name] of failures) console.error(`- ${name}`);
  process.exit(1);
}

console.log(`User management checks passed (${assertions.length} assertions).`);
