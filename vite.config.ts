import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { resolve } from "node:path";

const apiProxyTarget = process.env.VITE_API_PROXY_TARGET || "http://127.0.0.1:8001";

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
    port: 5174,
    strictPort: true,
    proxy: {
      // Allow fetch('/api/...') during local dev; proxied to FastAPI on 8001
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
    port: 4174,
    strictPort: true,
  },
});
