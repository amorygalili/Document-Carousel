import { defineConfig } from "vite";

// Builds a single, self-contained IIFE bundle at dist/loader.js that bundles
// the AppBridge host SDK + a minimal MCP client. Drop the output into
// Open WebUI's static dir as `static/loader.js` (no source changes required).
export default defineConfig({
  define: {
    "process.env.NODE_ENV": '"production"',
  },
  build: {
    target: "es2020",
    lib: {
      entry: "src/loader.ts",
      formats: ["iife"],
      name: "OpenWebUIMcpAppBridge",
      fileName: () => "loader.js",
    },
    outDir: "dist",
    emptyOutDir: true,
    minify: true,
    rollupOptions: {
      output: { inlineDynamicImports: true },
    },
  },
});
