import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    host: true,
    port: 5173,
    // Dev proxy: same-origin /api + /docs — refresh cookies just work.
    // (In production the reverse proxy serves the frontend and API on one
    // origin, or VITE_API_BASE_URL points at the API with proper CORS.)
    proxy: {
      "/api": {
        target: (globalThis as Record<string, any>).process?.env?.DEV_API_TARGET ||
          "http://127.0.0.1:8010",
        changeOrigin: true,
        ws: true,
      },
    },
  },
  build: {
    outDir: "dist",
    sourcemap: false,
    chunkSizeWarningLimit: 900,
  },
  test: {
    environment: "node",
    include: ["src/**/*.test.ts"],
  },
});
