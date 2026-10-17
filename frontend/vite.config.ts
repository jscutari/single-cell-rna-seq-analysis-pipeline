import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// FastAPI runs on :8080 (vLLM owns :8000). The client uses relative /api URLs,
// so a production build served by FastAPI works without changes.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": { target: "http://localhost:8080", changeOrigin: true },
    },
  },
});
