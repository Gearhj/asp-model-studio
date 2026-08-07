import assert from "node:assert/strict";
import crypto from "node:crypto";
import fs from "node:fs";
import { createRequire } from "node:module";
import path from "node:path";
import test from "node:test";
import ts from "typescript";

import { validateConfig } from "../scripts/hermetic_node_guard.mjs";

function validEnvironment() {
  const root = process.env.ATLAS_HERMETIC_ROOT;
  return {
    ATLAS_HERMETIC_MODE: "HERMETIC_REGRESSION",
    ATLAS_TEST_MODE: "1",
    ATLAS_PROCESS_ROLE: "test",
    ATLAS_RUN_ID: process.env.ATLAS_RUN_ID,
    ATLAS_TEST_NAME: "hermetic-node-guard",
    ATLAS_HERMETIC_ROOT: root,
    ATLAS_HERMETIC_SOURCE_ROOT: process.env.ATLAS_HERMETIC_SOURCE_ROOT,
    ATLAS_HERMETIC_NODE_MODULES_ROOT: process.env.ATLAS_HERMETIC_NODE_MODULES_ROOT,
    ATLAS_HERMETIC_NODE_CACHE_ROOT: process.env.ATLAS_HERMETIC_NODE_CACHE_ROOT,
    ATLAS_HERMETIC_PACKAGE_JSON: process.env.ATLAS_HERMETIC_PACKAGE_JSON,
    ATLAS_HERMETIC_PACKAGE_JSON_SHA256: process.env.ATLAS_HERMETIC_PACKAGE_JSON_SHA256,
    ATLAS_LIVE_REPOSITORY_ROOT: process.env.ATLAS_LIVE_REPOSITORY_ROOT,
    ATLAS_BROWSER_STORAGE_ROOT: process.env.ATLAS_BROWSER_STORAGE_ROOT,
    ATLAS_PLAYWRIGHT_OUTPUT_ROOT: process.env.ATLAS_PLAYWRIGHT_OUTPUT_ROOT,
    ATLAS_TEST_BACKEND_URL: "http://atlas-hermetic.invalid",
    NODE_COMPILE_CACHE: process.env.NODE_COMPILE_CACHE,
  };
}

function beneath(candidate, root) {
  const relative = path.relative(path.resolve(root), path.resolve(candidate));
  return relative === "" || (!relative.startsWith("..") && !path.isAbsolute(relative));
}

function digest(file) {
  return crypto.createHash("sha256").update(fs.readFileSync(file)).digest("hex");
}

test("accepts isolated browser roots and a non-live backend category", () => {
  const result = validateConfig(validEnvironment());
  assert.equal(result.mode, "HERMETIC_REGRESSION");
  assert.equal(result.runtimePackages, 1);
  assert.equal(result.nodeCacheRoots, 1);
  assert.equal(result.rootPackageFiles, 1);
  assert.equal(result.workingDirectories, 1);
});

test("uses only the verified child-local root package metadata", () => {
  const packageFile = fs.realpathSync(process.env.ATLAS_HERMETIC_PACKAGE_JSON);
  const metadata = JSON.parse(fs.readFileSync(packageFile, "utf8"));
  assert.equal(fs.realpathSync(process.cwd()), fs.realpathSync(process.env.ATLAS_HERMETIC_SOURCE_ROOT));
  assert.equal(beneath(packageFile, process.env.ATLAS_HERMETIC_SOURCE_ROOT), true);
  assert.equal(beneath(packageFile, process.env.ATLAS_LIVE_REPOSITORY_ROOT), false);
  assert.equal(path.dirname(packageFile), fs.realpathSync(process.env.ATLAS_HERMETIC_SOURCE_ROOT));
  assert.equal(path.basename(packageFile), "package.json");
  assert.equal(digest(packageFile), process.env.ATLAS_HERMETIC_PACKAGE_JSON_SHA256);
  assert.equal(metadata.name, "atlas");
  assert.equal(metadata.type, "module");
  assert.equal(metadata.private, true);
});

test("loads the copied TypeScript compiler API", () => {
  assert.equal(process.env.ATLAS_HERMETIC_NODE_GUARD_PASSED, "1");
  const source = ts.createSourceFile(
    "synthetic.ts",
    "const answer: number = 42;",
    ts.ScriptTarget.Latest,
    true,
  );
  assert.equal(source.statements.length, 1);
});

test("resolves TypeScript only from the approved child package root", () => {
  const runtimeRequire = createRequire(import.meta.url);
  const resolved = fs.realpathSync(runtimeRequire.resolve("typescript"));
  assert.equal(beneath(resolved, process.env.ATLAS_HERMETIC_NODE_MODULES_ROOT), true);
  assert.equal(beneath(resolved, process.env.ATLAS_LIVE_REPOSITORY_ROOT), false);
});

test("uses a writable cache isolated beneath this child", () => {
  const cache = fs.realpathSync(process.env.ATLAS_HERMETIC_NODE_CACHE_ROOT);
  assert.equal(beneath(cache, process.env.ATLAS_HERMETIC_ROOT), true);
  assert.equal(beneath(cache, process.env.ATLAS_LIVE_REPOSITORY_ROOT), false);
  assert.equal(path.resolve(process.env.NODE_COMPILE_CACHE), path.resolve(cache));
  const marker = path.join(cache, `node-cache-canary-${process.pid}.txt`);
  fs.writeFileSync(marker, "child-only", { encoding: "utf8", flag: "wx" });
  assert.equal(fs.readFileSync(marker, "utf8"), "child-only");
});

test("compiler use does not modify the live dependency authority", () => {
  const liveEntry = path.join(
    process.env.ATLAS_LIVE_REPOSITORY_ROOT,
    "node_modules",
    "typescript",
    "lib",
    "typescript.js",
  );
  const before = fs.statSync(liveEntry);
  const beforeHash = digest(liveEntry);
  const transpiled = ts.transpileModule("const value: number = 1;", {
    compilerOptions: { module: ts.ModuleKind.ESNext },
  });
  assert.match(transpiled.outputText, /value = 1/);
  const after = fs.statSync(liveEntry);
  assert.equal(digest(liveEntry), beforeHash);
  assert.equal(after.size, before.size);
  assert.equal(after.mtimeMs, before.mtimeMs);
});

for (const backend of ["http://127.0.0.1:8001", "http://localhost:5174", "http://[::1]:8001"]) {
  test(`rejects live development endpoint ${new URL(backend).port}`, () => {
    assert.throws(
      () => validateConfig({ ...validEnvironment(), ATLAS_TEST_BACKEND_URL: backend }),
      /HERMETIC_NODE_GUARD_REJECTED:live-backend/,
    );
  });
}

test("rejects browser storage outside the child root", () => {
  assert.throws(
    () => validateConfig({
      ...validEnvironment(),
      ATLAS_BROWSER_STORAGE_ROOT: process.env.ATLAS_LIVE_REPOSITORY_ROOT,
    }),
    /HERMETIC_NODE_GUARD_REJECTED:browser-root/,
  );
});

test("rejects a node_modules root outside the child source", () => {
  assert.throws(
    () => validateConfig({
      ...validEnvironment(),
      ATLAS_HERMETIC_NODE_MODULES_ROOT: path.join(
        process.env.ATLAS_LIVE_REPOSITORY_ROOT,
        "node_modules",
      ),
    }),
    /HERMETIC_NODE_GUARD_REJECTED:node-modules-root/,
  );
});

test("rejects live repository package metadata instead of falling back", () => {
  assert.throws(
    () => validateConfig({
      ...validEnvironment(),
      ATLAS_HERMETIC_PACKAGE_JSON: path.join(
        process.env.ATLAS_LIVE_REPOSITORY_ROOT,
        "package.json",
      ),
    }),
    /HERMETIC_NODE_GUARD_REJECTED:package-json-root/,
  );
});

test("rejects a root package whose immutable digest does not match", () => {
  assert.throws(
    () => validateConfig({
      ...validEnvironment(),
      ATLAS_HERMETIC_PACKAGE_JSON_SHA256: "0".repeat(64),
    }),
    /HERMETIC_NODE_GUARD_REJECTED:package-json-integrity/,
  );
});

test("rejects a Node cache outside the child root", () => {
  const outside = path.join(process.env.ATLAS_LIVE_REPOSITORY_ROOT, ".tmp");
  assert.throws(
    () => validateConfig({
      ...validEnvironment(),
      ATLAS_HERMETIC_NODE_CACHE_ROOT: outside,
      NODE_COMPILE_CACHE: outside,
    }),
    /HERMETIC_NODE_GUARD_REJECTED:node-cache-root/,
  );
});
