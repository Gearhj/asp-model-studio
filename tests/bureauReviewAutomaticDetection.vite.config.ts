import { resolve } from "node:path";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react()],
  define: {
    "import.meta.env.VITE_API_BASE": JSON.stringify("/api"),
  },
  build: {
    rollupOptions: {
      input: {
        bureauReviewAutomaticDetection: resolve(
          __dirname,
          "bureauReviewAutomaticDetection.isolated.entry.html",
        ),
      },
    },
  },
});
