import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// In development the API runs on :8081; in production FastAPI serves the built files.
// VITE_STATIC=1 builds the online version (GitHub Pages): relative paths, data from JSON files.
export default defineConfig({
  base: process.env.VITE_STATIC === "1" ? "./" : "/",
  plugins: [react()],
  server: { proxy: { "/api": "http://localhost:8081" } },
  build: {
    chunkSizeWarningLimit: 700,
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (/node_modules[\\/](echarts|zrender)[\\/]/.test(id)) return "echarts";
          return undefined;
        },
      },
    },
  },
});
