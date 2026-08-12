// vite.config.ts
// frontend/vite.config.ts
//
// Minimal Vite build configuration (Checkpoint 4 §28). No dev-server
// proxy to a backend API is configured yet — there is no backend API
// contract to proxy to (see application/contracts, not yet implemented).
// Add a proxy entry here only when the first real API endpoint exists.
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
  },
});
