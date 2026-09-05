import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";

// Vite config.
// - Dev server on port 5173
// - `/api` requests are proxied to the FastAPI backend on :8000, so the
//   frontend never needs to know the absolute backend URL.
// - `VITE_API_BASE` env is respected as an override (used in prod builds).
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "");
  const apiBase = env.VITE_API_BASE ?? "http://localhost:8000";

  return {
    plugins: [react()],
    server: {
      port: 5173,
      strictPort: true,
      proxy: {
        "/api": {
          target: apiBase,
          changeOrigin: true,
        },
      },
    },
    build: {
      outDir: "dist",
      sourcemap: true,
    },
  };
});
