// frontend/src/app/styles.quality.test.ts
//
// Checkpoint 35 Part 19: a CSS/design quality gate - the simplest
// maintainable mechanism, not a fragile CSS parser. Runs as a normal
// vitest test (same toolchain already in place), reading `styles.css`'s
// raw text directly via Node's `fs` (Vitest runs under Node, so this is
// the simplest reliable way to get the file's exact source - Vite's
// `?raw`/`import.meta.glob` query imports were tried first but returned
// empty content under this project's jsdom test environment).
import { readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

const STYLES_PATH = join(__dirname, "styles.css");
const STYLES = readFileSync(STYLES_PATH, "utf-8");

const ROOT_BLOCK_MATCH = STYLES.match(/:root\s*{([\s\S]*?)\n}/);
const ROOT_BLOCK = ROOT_BLOCK_MATCH ? ROOT_BLOCK_MATCH[1] : "";

describe("CSS quality gate", () => {
  it("styles.css is actually readable and non-empty (sanity check for this gate itself)", () => {
    expect(STYLES.length).toBeGreaterThan(1000);
  });

  it("defines every color token exactly once inside :root", () => {
    const tokenNames = [...ROOT_BLOCK.matchAll(/--color-[a-z0-9-]+:/g)].map(
      (match) => match[0],
    );
    const counts = new Map<string, number>();
    for (const name of tokenNames) {
      counts.set(name, (counts.get(name) ?? 0) + 1);
    }
    const duplicates = [...counts.entries()].filter(([, count]) => count > 1);
    expect(duplicates).toEqual([]);
  });

  it("contains no hardcoded hex colors outside the :root token block", () => {
    const withoutRoot = STYLES.replace(/:root\s*{[\s\S]*?\n}/, "");
    const hexMatches = withoutRoot.match(/#[0-9a-fA-F]{3,8}\b/g) ?? [];
    expect(hexMatches).toEqual([]);
  });

  it("contains no raw rgba()/rgb() literals outside :root", () => {
    const withoutRoot = STYLES.replace(/:root\s*{[\s\S]*?\n}/, "");
    const rgbMatches = withoutRoot.match(/rgba?\([^)]*\)/g) ?? [];
    expect(rgbMatches).toEqual([]);
  });

  it("has no exact-duplicate CSS rule blocks (same selector + declarations twice)", () => {
    // A lightweight, intentionally simple duplicate-block check - not a
    // full CSS parser (Part 19's own "do not create a fragile parser").
    const ruleBlocks = STYLES.match(/[^{}]+\{[^{}]*\}/g) ?? [];
    const normalized = ruleBlocks.map((block) => block.replace(/\s+/g, " ").trim());
    const seen = new Map<string, number>();
    for (const block of normalized) {
      seen.set(block, (seen.get(block) ?? 0) + 1);
    }
    const duplicates = [...seen.entries()].filter(([, count]) => count > 1);
    expect(duplicates).toEqual([]);
  });

  it("defines at least one responsive (@media max-width) rule", () => {
    // Checkpoint 35's own headline finding: zero @media rules existed
    // before this checkpoint. This test exists specifically so that
    // finding can never silently regress back to zero.
    expect(STYLES).toMatch(/@media \(max-width: \d+px\)/);
  });

  it("defines a visible focus state for keyboard users", () => {
    expect(STYLES).toMatch(/:focus-visible/);
  });
});

describe("No inline style= usage in frontend components", () => {
  function collectTsxFiles(dir: string): string[] {
    const entries = readdirSync(dir, { withFileTypes: true });
    const files: string[] = [];
    for (const entry of entries) {
      if (entry.name === "node_modules" || entry.name.startsWith(".")) continue;
      const fullPath = join(dir, entry.name);
      if (entry.isDirectory()) {
        files.push(...collectTsxFiles(fullPath));
      } else if (entry.name.endsWith(".tsx") && !entry.name.endsWith(".test.tsx")) {
        files.push(fullPath);
      }
    }
    return files;
  }

  it("no component uses an inline style={{ ... }} prop", () => {
    const srcRoot = join(__dirname, "..");
    const violations: string[] = [];
    for (const file of collectTsxFiles(srcRoot)) {
      const content = readFileSync(file, "utf-8");
      if (/style=\{\{/.test(content)) {
        violations.push(file);
      }
    }
    expect(violations).toEqual([]);
  });
});
