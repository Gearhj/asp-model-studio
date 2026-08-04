/** Pre-import guard for Node and browser-oriented hermetic test children. */
import path from "node:path";
import process from "node:process";
import { fileURLToPath } from "node:url";

const LIVE_PORTS = new Set(["5174", "8001"]);

function fail(code) {
  const error = new Error(`HERMETIC_NODE_GUARD_REJECTED:${code}`);
  error.code = code;
  throw error;
}

function identity(value) {
  return path.resolve(String(value || "")).replaceAll("/", "\\").toLocaleLowerCase("en-US");
}

function isBeneath(candidate, root) {
  const relative = path.relative(root, candidate);
  return relative === "" || (!relative.startsWith("..") && !path.isAbsolute(relative));
}

export function validateConfig(environment = process.env) {
  if (environment.ATLAS_HERMETIC_MODE !== "HERMETIC_REGRESSION") fail("mode");
  if (environment.ATLAS_TEST_MODE !== "1") fail("test-mode");
  if (environment.ATLAS_PROCESS_ROLE !== "test") fail("process-role");
  if (!String(environment.ATLAS_RUN_ID || "").startsWith("atlas-hrt-")) fail("run-id");
  if (!environment.ATLAS_TEST_NAME) fail("test-name");

  const rootRaw = String(environment.ATLAS_HERMETIC_ROOT || "");
  if (!path.isAbsolute(rootRaw)) fail("root");
  const root = identity(rootRaw);
  for (const key of ["ATLAS_BROWSER_STORAGE_ROOT", "ATLAS_PLAYWRIGHT_OUTPUT_ROOT"]) {
    const raw = String(environment[key] || "");
    if (!path.isAbsolute(raw) || !isBeneath(identity(raw), root)) fail("browser-root");
  }

  const backend = String(environment.ATLAS_TEST_BACKEND_URL || "");
  if (!backend) fail("backend-url");
  let parsed;
  try {
    parsed = new URL(backend);
  } catch {
    fail("backend-url");
  }
  const host = parsed.hostname.toLocaleLowerCase("en-US");
  const port = parsed.port || (parsed.protocol === "https:" ? "443" : "80");
  if ((host === "127.0.0.1" || host === "localhost" || host === "::1" || host === "[::1]") && LIVE_PORTS.has(port)) {
    fail("live-backend");
  }
  return {
    mode: "HERMETIC_REGRESSION",
    backendCategory: "non-live",
    browserRoots: 2,
  };
}

const invoked = process.argv[1] && path.resolve(process.argv[1]) === path.resolve(fileURLToPath(import.meta.url));
if (invoked) {
  try {
    const result = validateConfig();
    process.stdout.write(`${JSON.stringify(result)}\n`);
  } catch (error) {
    process.stderr.write(`${error?.message || "HERMETIC_NODE_GUARD_REJECTED:unknown"}\n`);
    process.exitCode = 86;
  }
}
