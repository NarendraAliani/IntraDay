/// <reference types="vite/client" />

// Checkpoint 9: augments Vite's built-in ImportMetaEnv with the one
// client-visible env var this app reads. Keeps `import.meta.env.*` access
// type-checked under strict mode instead of falling back to `any`.
interface ImportMetaEnv {
  readonly VITE_API_BASE_URL?: string;
}
