import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Built into the FastAPI static folder and served at /app/ (same origin as the API, so the
// SameSite=Strict session cookie and the X-CCT CSRF header keep working).
export default defineConfig({
  base: "/app/",
  plugins: [react()],
  build: { outDir: "../server/static/app", emptyOutDir: true },
  server: { proxy: { "/api": "http://127.0.0.1:8080" } },
});
