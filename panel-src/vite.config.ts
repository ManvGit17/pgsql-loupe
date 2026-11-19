import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// The build is committed into the Python package, so users never need Node.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  build: {
    outDir: "../src/pgsql_loupe/panel",
    emptyOutDir: true,
    cssCodeSplit: false,
    assetsInlineLimit: 0,
    rolldownOptions: {
      input: "src/main.tsx",
      output: {
        entryFileNames: "panel.js",
        chunkFileNames: "panel-[name].js",
        assetFileNames: "panel[extname]",
      },
    },
  },
  // `npm run dev` talks to an app running pgsql-loupe on port 8000.
  server: { proxy: { "/__lens/api": "http://127.0.0.1:8000" } },
});
