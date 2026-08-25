// frontend/src/app/theme/themeRegistry.ts
//
// Checkpoint 64.80-F2 Phase 2: the ONE registry of user-selectable
// themes. This module is deliberately data-only (no React, no DOM, no
// storage) so the theme list can be asserted by unit tests and consumed
// by both the provider and the selector UI without duplication.
//
// DESIGN RULE (Phase 2): no theme colour value lives here. Colour is
// declared exactly once, in `theme.css`, as a `[data-theme="…"]` block
// of CSS custom properties. This registry carries only identity,
// human-readable naming, and the light/dark *scheme* hint the
// `prefers-color-scheme` default (Phase 5) needs. Swatch previews
// (Phase 12) are rendered from CSS classes keyed off `id`, again so no
// hex literal is ever duplicated into TypeScript.

/** Stable, storage-safe theme identifiers. Never renamed casually - a
 * rename invalidates every user's stored preference. */
export type ThemeId = "focus" | "midnight" | "obsidian" | "aurora";

/** Whether a theme reads as a light or dark surface. Used ONLY to pick
 * an initial default from `prefers-color-scheme` when the user has made
 * no explicit choice (Phase 5). It never overrides a stored choice. */
export type ThemeScheme = "light" | "dark";

export interface ThemeDefinition {
  id: ThemeId;
  /** Display name shown in the theme picker. */
  name: string;
  /** One short sentence describing the theme's visual character. */
  description: string;
  scheme: ThemeScheme;
}

/** The four shipped themes, in picker order. Each is a genuinely
 * distinct surface/accent system rather than a tint of its neighbour. */
export const THEMES: readonly ThemeDefinition[] = [
  {
    id: "focus",
    name: "Focus",
    description: "Daylight analytical. Cool paper surfaces with a deep indigo signal accent.",
    scheme: "light",
  },
  {
    id: "midnight",
    name: "Midnight",
    description: "Deep navy terminal. Low-glare surfaces with a cool cyan signal accent.",
    scheme: "dark",
  },
  {
    id: "obsidian",
    name: "Obsidian",
    description: "Near-black, near-neutral. Maximum contrast, minimum chroma, amber accent.",
    scheme: "dark",
  },
  {
    id: "aurora",
    name: "Aurora",
    description: "Slate-teal depth. Cool graphite surfaces with a restrained jade/violet accent.",
    scheme: "dark",
  },
] as const;

/** The application default when nothing is stored and no system
 * preference can be read. Focus is the light, highest-legibility theme
 * and matches the palette every screen before 64.80-F2 was designed
 * against, so an unconfigured install looks exactly as it did. */
export const DEFAULT_THEME_ID: ThemeId = "focus";

/** The default chosen for a first-time visitor whose OS asks for dark. */
export const DEFAULT_DARK_THEME_ID: ThemeId = "midnight";

const THEME_IDS = new Set<string>(THEMES.map((theme) => theme.id));

/** Narrow an untrusted string (localStorage content, a URL, an old
 * build's value) to a known theme id. Unknown input is rejected rather
 * than written through to `data-theme`. */
export function isThemeId(value: unknown): value is ThemeId {
  return typeof value === "string" && THEME_IDS.has(value);
}

export function getTheme(id: ThemeId): ThemeDefinition {
  const found = THEMES.find((theme) => theme.id === id);
  // THEMES is exhaustive over ThemeId; this guard exists so a future
  // id added to the union without a registry entry fails loudly.
  if (!found) throw new Error(`Unknown theme id: ${id}`);
  return found;
}
