import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { resolve } from "node:path";

const apiProxyTarget = process.env.VITE_API_PROXY_TARGET || "http://127.0.0.1:8101";
const frontendPort = Number(process.env.ASP_MODEL_STUDIO_FRONTEND_PORT || "5274");
const previewPort = Number(process.env.ASP_MODEL_STUDIO_PREVIEW_PORT || "4274");

export default defineConfig({
  plugins: [react()],
  build: {
    rollupOptions: {
      input: {
        main: resolve(__dirname, "index.html"),
      },
    },
  },
  server: {
    host: "127.0.0.1",
    port: frontendPort,
    strictPort: true,
    proxy: {
      // Allow fetch('/api/...') during local dev; proxied to the isolated backend.
      "/api": {
        target: apiProxyTarget,
        changeOrigin: true,
        // keep the path as-is (/api/...) so backend routes don’t change
        rewrite: (path) => path,
      },
    },
  },
  preview: {
    host: "127.0.0.1",
    port: previewPort,
    strictPort: true,
  },
});
