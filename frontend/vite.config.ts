import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";

// Dedicated ports so this app does not collide with Collective or other local projects
// (common Vite 5173/5180 / FastAPI 8000/8010).
//   UI:  http://localhost:5190
//   API: http://127.0.0.1:8020  (proxied as /api)
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "");
  const apiTarget = env.VITE_PROXY_TARGET || "http://127.0.0.1:8020";
  const uiPort = Number(env.VITE_DEV_PORT || 5190);

  return {
    plugins: [react()],
    server: {
      port: uiPort,
      strictPort: true,
      host: "127.0.0.1",
      proxy: {
        // Backend serves domain routes under /api/* — do not strip the prefix.
        "/api": {
          target: apiTarget,
          changeOrigin: true,
          timeout: 180_000,
          proxyTimeout: 180_000,
        },
      },
    },
  };
});
