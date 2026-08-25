// frontend/src/app/theme/ThemeProvider.tsx
//
// Checkpoint 64.80-F2 Phase 2/4/5: the runtime half of the theme system.
//
// The provider owns exactly one piece of state - the active theme id -
// and has exactly one side effect: stamping `data-theme` (and a
// `data-theme-scheme` hint for `color-scheme`) onto the document root.
// Every colour decision is then made by CSS in `theme.css`. No component
// anywhere reads a theme colour in JavaScript, which is what keeps the
// system token-driven rather than a second, parallel design system.
//
// Switching is instantaneous and does NOT reload the page (Phase 3):
// changing an attribute on <html> re-resolves the custom properties for
// the whole tree in one paint.
import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import type { JSX, ReactNode } from "react";

import type { ThemeDefinition, ThemeId } from "./themeRegistry";
import { getTheme } from "./themeRegistry";
import { resolveInitialTheme, writeStoredTheme } from "./themeStorage";

export interface ThemeContextValue {
  themeId: ThemeId;
  theme: ThemeDefinition;
  /** Records an EXPLICIT user choice: applies it and persists it. */
  setTheme: (id: ThemeId) => void;
}

const ThemeContext = createContext<ThemeContextValue | null>(null);

export interface ThemeProviderProps {
  children: ReactNode;
  /** Test seam only: forces the initial theme, bypassing storage and
   * system preference. Production code never passes this. */
  initialThemeId?: ThemeId;
}

export function ThemeProvider({ children, initialThemeId }: ThemeProviderProps): JSX.Element {
  // Lazy initialiser: storage and matchMedia are read exactly once, on
  // mount, so a stored preference is applied on the first paint rather
  // than flashing the default theme first.
  const [themeId, setThemeId] = useState<ThemeId>(() => resolveInitialTheme(initialThemeId));

  useEffect(() => {
    const root = document.documentElement;
    root.setAttribute("data-theme", themeId);
    // Tells the browser which built-in form/scrollbar palette to use, so
    // native controls do not stay light-on-light inside a dark theme.
    root.setAttribute("data-theme-scheme", getTheme(themeId).scheme);
    root.style.colorScheme = getTheme(themeId).scheme;
  }, [themeId]);

  const setTheme = useCallback((id: ThemeId) => {
    setThemeId(id);
    writeStoredTheme(id);
  }, []);

  const value = useMemo<ThemeContextValue>(
    () => ({ themeId, theme: getTheme(themeId), setTheme }),
    [themeId, setTheme],
  );

  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
}

/** Throws rather than silently falling back to a default, so a component
 * rendered outside the provider is caught in tests instead of shipping
 * an un-themed subtree. */
export function useTheme(): ThemeContextValue {
  const value = useContext(ThemeContext);
  if (!value) {
    throw new Error("useTheme must be used inside a <ThemeProvider>.");
  }
  return value;
}
