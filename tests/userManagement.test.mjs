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
  ["enterprise roles", ["validator", "manager", "viewer"].every((role) => securityStore.includes(`"${role}"`))],
  ["demo users", ["demo_ds_1", "demo_validator", "demo_manager"].every((userId) => securityStore.includes(userId))],
  ["development header is explicit and fail closed", securityStore.includes("ATLAS_ENABLE_DEV_USER_HEADER") && securityStore.includes('os.getenv("ATLAS_ENABLE_DEV_USER_HEADER", "false")')],
  ["user activity metrics", [">Projects<", ">Evidence<", ">Validations<", ">Exports<", "Last active"].every((label) => authPages.includes(label))],
  ["login routes", modelingApp.includes('path="/login"') && modelingApp.includes('path="/register"')],
  ["account routes", modelingApp.includes('path="/account"') && modelingApp.includes('path="/admin/users"') && modelingApp.includes('path="/audit"')],
  ["auth guard", modelingApp.includes("Loading ATLAS security context") && modelingApp.includes("Navigate to=\"/login\"")],
  ["header shows signed-in user", modelingApp.includes("HeaderUserMenu") && modelingApp.includes("Signed in as") && modelingApp.includes("Sign out")],
  ["auth pages", authPages.includes("LoginPage") && authPages.includes("AdminUsersPage") && authPages.includes("AuditPage")],
  ["keep signed in checkbox", authPages.includes("Keep me Signed In") && authPages.includes("KEEP_SIGNED_IN_EMAIL_KEY") && authPages.includes("keepSignedIn")],
  ["register password confirmation", authPages.includes("confirmPassword") && authPages.includes("Passwords do not match.")],
  ["register uses 8 character helper", authPages.includes("Use at least 8 characters. Longer passphrases are recommended.")],
  ["ordinary register has no role input", !authPages.slice(authPages.indexOf("export function RegisterPage"), authPages.indexOf("export function AccountPage")).includes("role")],
  ["backend accepts 8 character passwords", securityStore.includes("len(password) < 8") && securityStore.includes("Password must be at least 8 characters.")],
  ["default registration role", authPages.includes("register(email, displayName, password)")],
  ["account test checklist", authPages.includes("Account Test Checklist") && authPages.includes("Session") && authPages.includes("Dataset access")],
  ["dataset sharing UI", datasetDetail.includes("Share Dataset") && datasetDetail.includes("grantDatasetAccess")],
  ["dataset delete UI", datasetDetail.includes("Delete Dataset") && datasetDetail.includes("archiveDataset")],
];

const failures = assertions.filter(([, ok]) => !ok);
if (failures.length) {
  console.error("User management checks failed:");
  for (const [name] of failures) console.error(`- ${name}`);
  process.exit(1);
}

console.log(`User management checks passed (${assertions.length} assertions).`);
