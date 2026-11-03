import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Builds the single-file embeddable bundle (dist/widget.js). Runs after the
// regular SPA build, so it must not empty the output directory.
export default defineConfig({
  plugins: [react()],
  define: { "process.env.NODE_ENV": JSON.stringify("production") },
  build: {
    emptyOutDir: false,
    cssCodeSplit: false,
    lib: {
      entry: "src/embed.tsx",
      name: "LaDolceSaveurWidget",
      formats: ["iife"],
      fileName: () => "widget.js",
    },
  },
});
