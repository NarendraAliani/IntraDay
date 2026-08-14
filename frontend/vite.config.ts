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
    // Explicit host (Checkpoint 24A-finalization): without this, Vite
    // binds to whatever "localhost" resolves to on the host OS - on
    // this machine that is the IPv6 loopback ([::1]) only, NOT
    // 127.0.0.1. That silently broke both app.bat's own startup health
    // check (which correctly caught it) and, more importantly, matches
    // a real class of user-facing connectivity failure: the backend's
    // CORS_ALLOWED_ORIGINS/CSRF_TRUSTED_ORIGINS (settings/development.py)
    // explicitly trust BOTH "localhost:5173" and "127.0.0.1:5173" -
    // binding only to the IPv6 loopback silently made one of those two
    // documented, supported URLs simply unreachable rather than merely
    // untrusted.
    host: "127.0.0.1",
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
