// frontend/src/app/theme/theme.quality.test.ts
//
// Checkpoint 64.80-F2 Phase 15: the CSS quality gate for the THEME
// layer. `styles.quality.test.ts` guards the structural stylesheet and
// is unchanged; this file guards the rule that matters for a multi-theme
// system and that no amount of care can enforce by hand:
//
//   EVERY theme must define EVERY token in the canonical set.
//
// A theme that omits one token does not fail loudly - it silently
// inherits that colour from `styles.css`'s light-mode `:root`, which in
// a dark theme means (for example) white-on-white text in one component
// that nobody notices until a user hits it. This test is the reason that
// cannot ship.
import { readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

import { THEMES } from "./themeRegistry";

const THEME_CSS = readFileSync(join(__dirname, "theme.css"), "utf-8");

/** The canonical token set. Derived from the Focus block, which is the
 * default theme - so "what tokens must exist" has exactly one source of
 * truth in the CSS itself rather than a hand-maintained list here that
 * could drift out of sync with the stylesheet. */
function tokensDefinedFor(themeId: string): string[] {
  const pattern = new RegExp(`\\[data-theme="${themeId}"\\][^{]*\\{([^}]*)\\}`);
  const block = THEME_CSS.match(pattern);
  if (!block) return [];
  return [...block[1].matchAll(/(--[a-z0-9-]+)\s*:/g)].map((match) => match[1]).sort();
}

const CANONICAL_TOKENS = tokensDefinedFor("focus");

describe("theme.css - token completeness", () => {
  it("the default (focus) theme defines a substantial token set", () => {
    // Sanity check for the gate itself: if the regex above stops
    // matching, every other assertion here would trivially pass.
    expect(CANONICAL_TOKENS.length).toBeGreaterThan(25);
  });

  it("every registered theme has a matching [data-theme] block in theme.css", () => {
    for (const theme of THEMES) {
      expect(THEME_CSS).toContain(`[data-theme="${theme.id}"]`);
    }
  });

  it("every theme defines EVERY canonical token - no theme may inherit a stale colour", () => {
    for (const theme of THEMES) {
      const defined = tokensDefinedFor(theme.id);
      const missing = CANONICAL_TOKENS.filter((token) => !defined.includes(token));
      expect({ theme: theme.id, missing }).toEqual({ theme: theme.id, missing: [] });
    }
  });

  it("every theme defines the same token set exactly (no theme-only extras either)", () => {
    for (const theme of THEMES) {
      expect(tokensDefinedFor(theme.id)).toEqual(CANONICAL_TOKENS);
    }
  });

  it("every theme's swatch preview renders from that theme's own tokens", () => {
    // Phase 12: the picker preview must not be hand-copied hex, or it
    // will silently misrepresent the theme it claims to preview.
    for (const theme of THEMES) {
      expect(THEME_CSS).toContain(`.theme-swatch--${theme.id}`);
    }
    expect(THEME_CSS).toMatch(/\.theme-swatch__surface\s*\{[^}]*var\(--color-surface\)/);
    expect(THEME_CSS).toMatch(/\.theme-swatch__accent\s*\{[^}]*var\(--color-accent\)/);
  });
});

describe("theme.css - discipline", () => {
  it("declares no colour literal OUTSIDE a theme token block", () => {
    // Strip every `[data-theme=…]`/`:root` token block, then assert the
    // remaining visual-identity rules are entirely var()-driven. This is
    // the multi-theme equivalent of styles.css's "no hex outside :root".
    const withoutThemeBlocks = THEME_CSS.replace(
      /(\[data-theme="[a-z]+"\]|:root)[^{]*\{[^}]*\}/g,
      "",
    );
    const hexes = withoutThemeBlocks.match(/#[0-9a-fA-F]{3,8}\b/g) ?? [];
    const rgbs = withoutThemeBlocks.match(/rgba?\([^)]*\)/g) ?? [];
    expect({ hexes, rgbs }).toEqual({ hexes: [], rgbs: [] });
  });

  it("contains no continuous/infinite animation (Phase 10: no hypnosis, no loops)", () => {
    expect(THEME_CSS).not.toMatch(/@keyframes/);
    expect(THEME_CSS).not.toMatch(/infinite/);
    expect(THEME_CSS).not.toMatch(/animation\s*:/);
  });

  it("honours prefers-reduced-motion by removing transitions AND transforms", () => {
    const block = THEME_CSS.match(
      /@media \(prefers-reduced-motion: reduce\)\s*\{[\s\S]*$/,
    );
    expect(block).not.toBeNull();
    expect(block?.[0]).toMatch(/transform:\s*none/);
    expect(block?.[0]).toMatch(/transition:\s*none/);
  });

  it("defines responsive rules for the theme control", () => {
    expect(THEME_CSS).toMatch(/@media \(max-width: 640px\)[\s\S]*?theme-selector/);
  });
});

describe("Iconography - one system only", () => {
  function collectSourceFiles(dir: string): string[] {
    const files: string[] = [];
    for (const entry of readdirSync(dir, { withFileTypes: true })) {
      if (entry.name === "node_modules" || entry.name.startsWith(".")) continue;
      const fullPath = join(dir, entry.name);
      if (entry.isDirectory()) {
        files.push(...collectSourceFiles(fullPath));
      } else if (entry.name.endsWith(".tsx") && !entry.name.endsWith(".test.tsx")) {
        files.push(fullPath);
      }
    }
    return files;
  }

  const SRC_ROOT = join(__dirname, "..", "..");
  const ICON_MODULE = join(SRC_ROOT, "common", "icons", "Icon.tsx");

  it("no component authors a raw <svg> outside the single icon module", () => {
    const violations = collectSourceFiles(SRC_ROOT).filter(
      (file) => file !== ICON_MODULE && /<svg/i.test(readFileSync(file, "utf-8")),
    );
    // EquityChart is the one documented exception: it is a DATA
    // rendering (an equity curve), not an icon, so it is not part of the
    // iconography system and must not be forced into it.
    const unexpected = violations.filter((file) => !file.endsWith("EquityChart.tsx"));
    expect(unexpected).toEqual([]);
  });

  // SCOPE, stated honestly: 64.80-F2 redesigns the application SHELL,
  // the DASHBOARD, and the four SHARED status components every screen
  // renders (ActiveBadge, ConnectionStatusBadge, CapabilityStatus,
  // StatusBadge). Those are migrated to the icon system and are gated
  // below. Individual feature pages still contain their own inline
  // Unicode markers; migrating ~40 further files was judged a larger,
  // riskier change than this checkpoint should make in one step, and is
  // recorded as a Remaining Gap rather than quietly claimed as done.
  const ICONOGRAPHY_GATED_FILES = [
    join(SRC_ROOT, "app", "App.tsx"),
    join(SRC_ROOT, "common", "components", "ActiveBadge.tsx"),
    join(SRC_ROOT, "common", "components", "ConnectionStatusBadge.tsx"),
    join(SRC_ROOT, "common", "components", "CapabilityStatus.tsx"),
    join(SRC_ROOT, "features", "dashboard", "StatusBadge.tsx"),
    join(SRC_ROOT, "features", "dashboard", "dashboardModel.ts"),
  ];

  it("the shell, dashboard and shared status components use no Unicode glyph icons", () => {
    const banned = /[●○◐✕✖✓✔⚠⚙]/u;
    const violations = ICONOGRAPHY_GATED_FILES.filter((file) =>
      banned.test(readFileSync(file, "utf-8")),
    );
    expect(violations).toEqual([]);
  });

  it("no source file anywhere contains emoji", () => {
    const emoji = /[\u{1F300}-\u{1FAFF}\u{2600}-\u{26FF}]/u;
    const violations = collectSourceFiles(SRC_ROOT).filter((file) =>
      emoji.test(readFileSync(file, "utf-8")),
    );
    expect(violations).toEqual([]);
  });
});
