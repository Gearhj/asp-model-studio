import assert from "node:assert/strict";
import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { randomUUID } from "node:crypto";
import { tmpdir } from "node:os";
import path from "node:path";
import { pathToFileURL } from "node:url";
import test, { after } from "node:test";
import ts from "typescript";

const ROOT = new URL("..", import.meta.url);
const TEMP = await mkdtemp(path.join(tmpdir(), `atlas-auth-return-${randomUUID()}-`));
const source = await readFile(new URL("src/lib/authReturnPath.ts", ROOT), "utf8");
const output = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.ES2022, target: ts.ScriptTarget.ES2022 },
}).outputText;
const target = path.join(TEMP, "authReturnPath.mjs");
await writeFile(target, output, "utf8");
const authReturn = await import(pathToFileURL(target).href);

after(async () => {
  await rm(TEMP, { recursive: true, force: true });
});

test("project-scoped workflow deep links survive authentication", () => {
  const pathValue = "/projects/atlas-a/step02?panel=target#development";
  assert.equal(authReturn.safeAuthReturnPath(pathValue), pathValue);
  assert.equal(
    authReturn.loginPathForReturnTo("/projects/atlas-a/step02", "?panel=target", "#development"),
    `/login?returnTo=${encodeURIComponent(pathValue)}`,
  );
});

test("external, protocol-relative, and backslash redirects are rejected", () => {
  assert.equal(authReturn.safeAuthReturnPath("https://example.test/steal"), null);
  assert.equal(authReturn.safeAuthReturnPath("//example.test/steal"), null);
  assert.equal(authReturn.safeAuthReturnPath("/\\example.test/steal"), null);
});

test("authentication routes are rejected to prevent loops", () => {
  assert.equal(authReturn.safeAuthReturnPath("/login"), null);
  assert.equal(authReturn.safeAuthReturnPath("/register"), null);
});

test("missing return paths fall back to the login page", () => {
  assert.equal(authReturn.safeAuthReturnPath(null), null);
  assert.equal(authReturn.loginPathForReturnTo(""), "/login");
});

