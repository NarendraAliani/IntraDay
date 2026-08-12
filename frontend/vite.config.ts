// vite.config.ts
// frontend/vite.config.ts
//
// Vite build + dev-server + Vitest configuration.
//
// Checkpoint 9: no dev-server proxy is configured — the API client
// (src/common/api/client.ts) talks directly to VITE_API_BASE_URL
// (defaults to the local Django dev server) rather than relying on a
// Vite proxy, keeping the base-URL logic in one documented place instead
// of split between here and the client.
/// <reference types="vitest/config" />
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
  },
  test: {
    environment: "jsdom",
    // globals intentionally false: test files import describe/it/expect
    // explicitly from "vitest" rather than relying on injected globals,
    // avoiding a tsconfig "types" change for the sake of this checkpoint.
    globals: false,
    setupFiles: ["./src/test/setup.ts"],
  },
});
