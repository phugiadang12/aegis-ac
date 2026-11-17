import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The analysis API (aegis_soc.api) runs on :8008; proxy /api to it in dev so
// the frontend and backend share an origin and CORS is a non-issue.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8008",
        changeOrigin: true,
      },
    },
  },
});
