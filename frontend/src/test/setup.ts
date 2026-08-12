// frontend/src/test/setup.ts
//
// Checkpoint 9: Vitest global setup, referenced by vite.config.ts's
// `test.setupFiles`. Registers jest-dom's DOM matchers (toBeInTheDocument,
// etc.) for use in component tests.
//
// Checkpoint 10: also registers React Testing Library's `cleanup()` after
// every test. RTL normally does this automatically, but only when it can
// see a global `afterEach` - this project's `vite.config.ts` deliberately
// sets `test.globals: false` (Checkpoint 9), so it must be wired up
// explicitly here instead. Without this, multiple `render()` calls across
// tests in the same file leak DOM nodes into each other.
import { afterEach } from "vitest";
import { cleanup } from "@testing-library/react";

import "@testing-library/jest-dom/vitest";

afterEach(() => {
  cleanup();
});
