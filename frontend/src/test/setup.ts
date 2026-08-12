// frontend/src/test/setup.ts
//
// Checkpoint 9: Vitest global setup, referenced by vite.config.ts's
// `test.setupFiles`. Registers jest-dom's DOM matchers (toBeInTheDocument,
// etc.) for use in component tests.
import "@testing-library/jest-dom/vitest";
