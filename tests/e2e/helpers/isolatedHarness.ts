import path from "node:path";
import { fileURLToPath } from "node:url";

const LIVE_PORTS = new Set(["5174", "8001"]);
const LOOPBACK_HOST = "127.0.0.1";
const helperDir = path.dirname(fileURLToPath(import.meta.url));
const repositoryRoot = path.resolve(helperDir, "../../..");

function requiredEnvironment(name: string): string {
  const value = process.env[name]?.trim();
  if (!value) throw new Error(`ISOLATED_HARNESS_CONFIG:${name}`);
  return value;
}

function isolatedOrigin(name: string): string {
  const raw = requiredEnvironment(name);
  let value: URL;
  try {
    value = new URL(raw);
  } catch {
    throw new Error(`ISOLATED_HARNESS_CONFIG:${name}`);
  }
  if (
    value.protocol !== "http:" ||
    value.hostname !== LOOPBACK_HOST ||
    !value.port ||
    LIVE_PORTS.has(value.port) ||
    value.username ||
    value.password ||
    (value.pathname !== "/" && value.pathname !== "") ||
    value.search ||
    value.hash
  ) {
    throw new Error(`ISOLATED_HARNESS_CONFIG:${name}`);
  }
  return value.origin;
}

function externalDirectory(name: string): string {
  const resolved = path.resolve(requiredEnvironment(name));
  const relative = path.relative(repositoryRoot, resolved);
  if (!path.isAbsolute(resolved) || relative === "" || (!relative.startsWith("..") && !path.isAbsolute(relative))) {
    throw new Error(`ISOLATED_HARNESS_CONFIG:${name}`);
  }
  return resolved;
}

function pathsOverlap(left: string, right: string): boolean {
  const relativeLeft = path.relative(left, right);
  const relativeRight = path.relative(right, left);
  const nested = (value: string) => value === "" || (!value.startsWith("..") && !path.isAbsolute(value));
  return nested(relativeLeft) || nested(relativeRight);
}

export type IsolatedHarnessEnvironment = {
  runId: string;
  frontendOrigin: string;
  backendOrigin: string;
  proxyOrigin: string;
  outputRoot: string;
  browserStorageRoot: string;
  headless: boolean;
};

export function isolatedHarnessEnvironment(): IsolatedHarnessEnvironment {
  const frontendOrigin = isolatedOrigin("ATLAS_E2E_BASE_URL");
  const backendOrigin = isolatedOrigin("ATLAS_E2E_BACKEND_URL");
  const proxyOrigin = isolatedOrigin("ATLAS_E2E_NETWORK_GUARD_PROXY");
  if (new Set([frontendOrigin, backendOrigin, proxyOrigin]).size !== 3) {
    throw new Error("ISOLATED_HARNESS_CONFIG:duplicate-origins");
  }
  const outputRoot = externalDirectory("ATLAS_PLAYWRIGHT_OUTPUT_ROOT");
  const browserStorageRoot = externalDirectory("ATLAS_BROWSER_STORAGE_ROOT");
  if (pathsOverlap(outputRoot, browserStorageRoot)) {
    throw new Error("ISOLATED_HARNESS_CONFIG:overlapping-browser-authorities");
  }
  const runId = requiredEnvironment("ATLAS_E2E_RUN_ID");
  if (!/^atlas-hrt-[0-9]{8}-[0-9]{6}-[a-f0-9]{10}$/i.test(runId)) {
    throw new Error("ISOLATED_HARNESS_CONFIG:ATLAS_E2E_RUN_ID");
  }
  return {
    runId,
    frontendOrigin,
    backendOrigin,
    proxyOrigin,
    outputRoot,
    browserStorageRoot,
    headless: process.env.ATLAS_E2E_HEADLESS !== "0",
  };
}

export const isolatedChromiumArguments = [
  "--disable-background-networking",
  "--disable-component-update",
  "--disable-default-apps",
  "--disable-sync",
  "--metrics-recording-only",
  "--no-first-run",
  "--proxy-bypass-list=<-loopback>",
  "--safebrowsing-disable-auto-update",
];
