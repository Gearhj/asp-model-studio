/** Pre-import guard for Node and browser-oriented hermetic test children. */
import crypto from "node:crypto";
import fs from "node:fs";
import { createRequire } from "node:module";
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

function existingDirectoryIdentity(raw, code) {
  if (!path.isAbsolute(String(raw || ""))) fail(code);
  try {
    const stat = fs.lstatSync(raw);
    if (!stat.isDirectory() || stat.isSymbolicLink()) fail(code);
    return identity(fs.realpathSync.native(raw));
  } catch (error) {
    if (error?.code === code) throw error;
    fail(code);
  }
}

function existingFileIdentity(raw, code) {
  if (!path.isAbsolute(String(raw || ""))) fail(code);
  try {
    const stat = fs.lstatSync(raw);
    if (!stat.isFile() || stat.isSymbolicLink()) fail(code);
    return identity(fs.realpathSync.native(raw));
  } catch (error) {
    if (error?.code === code) throw error;
    fail(code);
  }
}

function fileDigest(file) {
  return crypto.createHash("sha256").update(fs.readFileSync(file)).digest("hex");
}

export function validateConfig(environment = process.env) {
  if (environment.ATLAS_HERMETIC_MODE !== "HERMETIC_REGRESSION") fail("mode");
  if (environment.ATLAS_TEST_MODE !== "1") fail("test-mode");
  if (environment.ATLAS_PROCESS_ROLE !== "test") fail("process-role");
  if (!String(environment.ATLAS_RUN_ID || "").startsWith("atlas-hrt-")) fail("run-id");
  if (!environment.ATLAS_TEST_NAME) fail("test-name");

  const rootRaw = String(environment.ATLAS_HERMETIC_ROOT || "");
  const sourceRaw = String(environment.ATLAS_HERMETIC_SOURCE_ROOT || "");
  const modulesRaw = String(environment.ATLAS_HERMETIC_NODE_MODULES_ROOT || "");
  const cacheRaw = String(environment.ATLAS_HERMETIC_NODE_CACHE_ROOT || "");
  const root = existingDirectoryIdentity(rootRaw, "root");
  const source = existingDirectoryIdentity(sourceRaw, "source-root");
  if (source === root || !isBeneath(source, root)) fail("source-root");
  if (identity(process.cwd()) !== source) fail("working-directory");
  const packageRaw = String(environment.ATLAS_HERMETIC_PACKAGE_JSON || "");
  if (identity(packageRaw) !== identity(path.join(sourceRaw, "package.json"))) {
    fail("package-json-root");
  }
  const packageFile = existingFileIdentity(packageRaw, "package-json-root");
  if (!isBeneath(packageFile, source)) fail("package-json-root");
  const expectedPackageHash = String(
    environment.ATLAS_HERMETIC_PACKAGE_JSON_SHA256 || "",
  ).toLocaleLowerCase("en-US");
  if (!/^[a-f0-9]{64}$/.test(expectedPackageHash)) fail("package-json-hash");
  if (fileDigest(packageFile) !== expectedPackageHash) fail("package-json-integrity");
  try {
    const packageMetadata = JSON.parse(fs.readFileSync(packageFile, "utf8"));
    if (
      packageMetadata?.name !== "atlas"
      || packageMetadata?.private !== true
      || packageMetadata?.type !== "module"
      || !packageMetadata?.scripts
      || typeof packageMetadata.scripts !== "object"
      || Array.isArray(packageMetadata.scripts)
    ) {
      fail("package-json-metadata");
    }
  } catch (error) {
    if (error?.code === "package-json-metadata") throw error;
    fail("package-json-metadata");
  }
  if (identity(modulesRaw) !== identity(path.join(sourceRaw, "node_modules"))) {
    fail("node-modules-root");
  }
  const modules = existingDirectoryIdentity(modulesRaw, "node-modules-root");
  if (!isBeneath(modules, source)) fail("node-modules-root");
  if (identity(cacheRaw) !== identity(path.join(rootRaw, "authorities", "node-cache"))) {
    fail("node-cache-root");
  }
  const cache = existingDirectoryIdentity(cacheRaw, "node-cache-root");
  if (!isBeneath(cache, root)) fail("node-cache-root");
  if (identity(environment.NODE_COMPILE_CACHE) !== identity(cacheRaw)) {
    fail("node-cache-root");
  }
  let typescriptEntry;
  try {
    const runtimeRequire = createRequire(path.join(sourceRaw, "package.json"));
    typescriptEntry = runtimeRequire.resolve("typescript");
  } catch {
    fail("typescript-unavailable");
  }
  const resolvedTypeScript = existingFileIdentity(typescriptEntry, "typescript-unavailable");
  if (!isBeneath(resolvedTypeScript, modules)) fail("typescript-resolution-root");
  const packageRoot = existingDirectoryIdentity(
    path.join(modulesRaw, "typescript"),
    "typescript-resolution-root",
  );
  if (!isBeneath(resolvedTypeScript, packageRoot)) fail("typescript-resolution-root");
  const liveRepository = String(environment.ATLAS_LIVE_REPOSITORY_ROOT || "");
  if (liveRepository && isBeneath(packageFile, identity(liveRepository))) {
    fail("package-json-live-resolution");
  }
  if (liveRepository && isBeneath(resolvedTypeScript, identity(liveRepository))) {
    fail("typescript-live-resolution");
  }
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
    nodeCacheRoots: 1,
    rootPackageFiles: 1,
    runtimePackages: 1,
    workingDirectories: 1,
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
