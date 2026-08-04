import { fileURLToPath } from "node:url";
import path from "node:path";
import { defineConfig } from "vite";

const configDirectory = path.dirname(fileURLToPath(import.meta.url));
const repositoryRoot = path.resolve(configDirectory, "../..");
const backendTarget = process.env.ATLAS_RESTART_BACKEND_URL;

if (!backendTarget) {
  throw new Error("ATLAS_RESTART_BACKEND_URL is required for the isolated restart preview.");
}

/**
 * Production-composition preview used only by the isolated backend restart test.
 *
 * The normal preview server intentionally has no API proxy. This dedicated
 * test configuration keeps the production bundle on a disposable port while
 * sending same-origin /api requests to the UUID-scoped FastAPI process.
 */
export default defineConfig({
  root: repositoryRoot,
  preview: {
    host: "127.0.0.1",
    strictPort: true,
    proxy: {
      "/api": {
        target: backendTarget,
        changeOrigin: true,
      },
    },
  },
});
