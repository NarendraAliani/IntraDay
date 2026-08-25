// frontend/src/app/theme/themeStorage.ts
//
// Checkpoint 64.80-F2 Phase 4/5: theme preference persistence and the
// preference-resolution order.
//
// SCOPE RULE (Phase 4, non-negotiable): the theme preference is a
// per-browser display preference. It is stored in `localStorage` under
// an explicitly namespaced key and NOWHERE else - no backend endpoint,
// no database column, no cookie sent to the server.
//
// Every access is wrapped in try/catch: `localStorage` throws outright
// in some privacy modes and embedded contexts, and a display preference
// must never be able to break the application shell.
import type { ThemeId } from "./themeRegistry";
import { DEFAULT_DARK_THEME_ID, DEFAULT_THEME_ID, isThemeId } from "./themeRegistry";

/** Namespaced, versioned key. `intraday.` scopes it to this app on a
 * shared origin; `.v1` lets a future token-set change invalidate stale
 * values instead of silently mis-reading them. */
export const THEME_STORAGE_KEY = "intraday.ui.theme.v1";

/** Reads the stored preference, or null when none is stored, the stored
 * value is not a known theme, or storage is unavailable. */
export function readStoredTheme(): ThemeId | null {
  try {
    const raw = window.localStorage.getItem(THEME_STORAGE_KEY);
    return isThemeId(raw) ? raw : null;
  } catch {
    return null;
  }
}

/** Persists an explicit user choice. Failure is non-fatal: the theme
 * still applies for this session, it simply will not survive a reload. */
export function writeStoredTheme(id: ThemeId): void {
  try {
    window.localStorage.setItem(THEME_STORAGE_KEY, id);
  } catch {
    /* Storage unavailable - the in-memory selection still applies. */
  }
}

/** True when the operating system asks for a dark UI. Guarded because
 * `matchMedia` is absent in some test/SSR environments. */
export function prefersDarkScheme(): boolean {
  try {
    return typeof window.matchMedia === "function"
      ? window.matchMedia("(prefers-color-scheme: dark)").matches
      : false;
  } catch {
    return false;
  }
}

/**
 * Phase 5's priority order, in one place:
 *
 *   1. explicit user choice (handled by the provider's state - the
 *      caller passes it here as `explicit` when re-resolving)
 *   2. stored preference (localStorage)
 *   3. system preference (`prefers-color-scheme`) - initial default ONLY
 *   4. application default (Focus)
 *
 * The system preference can only ever pick the *initial* theme. Once a
 * value is stored, a later OS theme change never overrides it.
 */
export function resolveInitialTheme(explicit?: ThemeId | null): ThemeId {
  if (explicit) return explicit;
  const stored = readStoredTheme();
  if (stored) return stored;
  return prefersDarkScheme() ? DEFAULT_DARK_THEME_ID : DEFAULT_THEME_ID;
}
