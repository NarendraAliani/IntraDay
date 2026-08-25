// frontend/src/app/theme/theme.test.tsx
//
// Checkpoint 64.80-F2 Phase 15: theme system behaviour tests.
//
// These are deterministic and real: they drive the ACTUAL ThemeProvider
// and ThemeSelector, assert against the ACTUAL `data-theme` attribute the
// CSS keys off, and use a real in-memory localStorage stub rather than
// asserting that a mock function "was called" (which would prove nothing
// about whether the preference actually survives a reload).
import { fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ThemeProvider, useTheme } from "./ThemeProvider";
import { ThemeSelector } from "./ThemeSelector";
import { DEFAULT_DARK_THEME_ID, DEFAULT_THEME_ID, THEMES, isThemeId } from "./themeRegistry";
import { THEME_STORAGE_KEY, readStoredTheme, resolveInitialTheme } from "./themeStorage";

/** A real, working localStorage - not a spy. Assertions can therefore
 * check what was actually persisted, and a "reload" can be simulated by
 * unmounting and re-mounting against the same store. */
function installStorage(seed: Record<string, string> = {}): Map<string, string> {
  const store = new Map(Object.entries(seed));
  vi.stubGlobal("localStorage", {
    getItem: (key: string) => store.get(key) ?? null,
    setItem: (key: string, value: string) => void store.set(key, value),
    removeItem: (key: string) => void store.delete(key),
    clear: () => store.clear(),
    key: () => null,
    length: 0,
  });
  return store;
}

function setSystemPrefersDark(dark: boolean): void {
  vi.stubGlobal(
    "matchMedia",
    vi.fn((query: string) => ({
      matches: dark && query.includes("dark"),
      media: query,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      addListener: vi.fn(),
      removeListener: vi.fn(),
      dispatchEvent: vi.fn(),
      onchange: null,
    })),
  );
}

function activeTheme(): string | null {
  return document.documentElement.getAttribute("data-theme");
}

beforeEach(() => {
  installStorage();
  setSystemPrefersDark(false);
});

afterEach(() => {
  vi.unstubAllGlobals();
  document.documentElement.removeAttribute("data-theme");
  document.documentElement.removeAttribute("data-theme-scheme");
});

// --------------------------------------------------------------------
describe("theme registry", () => {
  it("ships at least four distinct, individually named themes", () => {
    expect(THEMES.length).toBeGreaterThanOrEqual(4);
    expect(new Set(THEMES.map((theme) => theme.id)).size).toBe(THEMES.length);
    expect(new Set(THEMES.map((theme) => theme.name)).size).toBe(THEMES.length);
  });

  it("covers both light and dark schemes, so a system preference can be honoured", () => {
    const schemes = new Set(THEMES.map((theme) => theme.scheme));
    expect(schemes.has("light")).toBe(true);
    expect(schemes.has("dark")).toBe(true);
  });

  it("rejects unknown ids rather than writing them through to data-theme", () => {
    expect(isThemeId("midnight")).toBe(true);
    expect(isThemeId("hot-pink")).toBe(false);
    expect(isThemeId(null)).toBe(false);
    expect(isThemeId(42)).toBe(false);
  });
});

// --------------------------------------------------------------------
describe("theme preference resolution (Phase 5 priority order)", () => {
  it("uses the application default when nothing is stored and the system asks for light", () => {
    expect(resolveInitialTheme()).toBe(DEFAULT_THEME_ID);
  });

  it("uses the dark default when nothing is stored and the system asks for dark", () => {
    setSystemPrefersDark(true);
    expect(resolveInitialTheme()).toBe(DEFAULT_DARK_THEME_ID);
  });

  it("lets a stored preference OVERRIDE the system preference", () => {
    installStorage({ [THEME_STORAGE_KEY]: "aurora" });
    setSystemPrefersDark(true);
    expect(resolveInitialTheme()).toBe("aurora");
  });

  it("lets an explicit choice override both storage and system preference", () => {
    installStorage({ [THEME_STORAGE_KEY]: "aurora" });
    setSystemPrefersDark(true);
    expect(resolveInitialTheme("obsidian")).toBe("obsidian");
  });

  it("ignores a corrupted or unknown stored value and falls back to the default", () => {
    installStorage({ [THEME_STORAGE_KEY]: "not-a-real-theme" });
    expect(readStoredTheme()).toBeNull();
    expect(resolveInitialTheme()).toBe(DEFAULT_THEME_ID);
  });

  it("survives localStorage throwing outright (private-mode browsers)", () => {
    vi.stubGlobal("localStorage", {
      getItem: () => {
        throw new Error("SecurityError");
      },
      setItem: () => {
        throw new Error("SecurityError");
      },
    });
    expect(readStoredTheme()).toBeNull();
    expect(() => resolveInitialTheme()).not.toThrow();
    expect(resolveInitialTheme()).toBe(DEFAULT_THEME_ID);
  });
});

// --------------------------------------------------------------------
describe("ThemeProvider", () => {
  function Probe(): JSX.Element {
    const { themeId } = useTheme();
    return <span data-testid="probe">{themeId}</span>;
  }

  it("applies the default theme to the document root on mount", () => {
    render(
      <ThemeProvider>
        <Probe />
      </ThemeProvider>,
    );
    expect(activeTheme()).toBe(DEFAULT_THEME_ID);
    expect(screen.getByTestId("probe")).toHaveTextContent(DEFAULT_THEME_ID);
  });

  it("applies a previously stored theme on mount, without a flash of the default", () => {
    installStorage({ [THEME_STORAGE_KEY]: "obsidian" });
    render(
      <ThemeProvider>
        <Probe />
      </ThemeProvider>,
    );
    expect(activeTheme()).toBe("obsidian");
  });

  it("also publishes the light/dark scheme so native controls match the theme", () => {
    installStorage({ [THEME_STORAGE_KEY]: "midnight" });
    render(
      <ThemeProvider>
        <Probe />
      </ThemeProvider>,
    );
    expect(document.documentElement.getAttribute("data-theme-scheme")).toBe("dark");
  });

  it("throws when useTheme is used outside a provider, rather than silently defaulting", () => {
    // React logs the error boundary output; silence it for this one case.
    const consoleError = vi.spyOn(console, "error").mockImplementation(() => {});
    expect(() => render(<Probe />)).toThrow(/ThemeProvider/);
    consoleError.mockRestore();
  });
});

// --------------------------------------------------------------------
describe("ThemeSelector - switching and persistence", () => {
  function renderSelector(): void {
    render(
      <ThemeProvider>
        <ThemeSelector />
      </ThemeProvider>,
    );
  }

  function openPicker(): HTMLElement {
    fireEvent.click(screen.getByRole("button", { expanded: false }));
    return screen.getByRole("radiogroup", { name: "Colour theme" });
  }

  it("exposes a user-facing Theme control in the UI", () => {
    renderSelector();
    const trigger = screen.getByRole("button", { name: /Theme/i });
    expect(trigger).toHaveAttribute("aria-expanded", "false");
  });

  it("offers every registered theme as an accessible radio option", () => {
    renderSelector();
    const group = openPicker();
    const options = within(group).getAllByRole("radio");
    expect(options).toHaveLength(THEMES.length);
    for (const theme of THEMES) {
      expect(within(group).getByRole("radio", { name: new RegExp(theme.name) })).toBeInTheDocument();
    }
  });

  it("switches the applied theme immediately, with no page reload", () => {
    renderSelector();
    const group = openPicker();
    fireEvent.click(within(group).getByRole("radio", { name: /Aurora/ }));
    expect(activeTheme()).toBe("aurora");
  });

  it("persists the chosen theme to the namespaced localStorage key", () => {
    const store = installStorage();
    renderSelector();
    const group = openPicker();
    fireEvent.click(within(group).getByRole("radio", { name: /Obsidian/ }));
    expect(store.get(THEME_STORAGE_KEY)).toBe("obsidian");
  });

  it("restores the chosen theme after a simulated reload", () => {
    const store = installStorage();
    const first = render(
      <ThemeProvider>
        <ThemeSelector />
      </ThemeProvider>,
    );
    fireEvent.click(screen.getByRole("button", { expanded: false }));
    fireEvent.click(screen.getByRole("radio", { name: /Midnight/ }));
    expect(activeTheme()).toBe("midnight");

    // "Reload": tear the whole tree down, keep only what a real reload
    // would keep - the contents of localStorage.
    first.unmount();
    document.documentElement.removeAttribute("data-theme");
    expect(store.get(THEME_STORAGE_KEY)).toBe("midnight");

    render(
      <ThemeProvider>
        <ThemeSelector />
      </ThemeProvider>,
    );
    expect(activeTheme()).toBe("midnight");
  });

  it("keeps working when the theme cannot be persisted", () => {
    vi.stubGlobal("localStorage", {
      getItem: () => null,
      setItem: () => {
        throw new Error("QuotaExceededError");
      },
    });
    renderSelector();
    const group = openPicker();
    expect(() =>
      fireEvent.click(within(group).getByRole("radio", { name: /Aurora/ })),
    ).not.toThrow();
    expect(activeTheme()).toBe("aurora");
  });
});

// --------------------------------------------------------------------
describe("ThemeSelector - accessibility (Phase 12/14)", () => {
  function renderAndOpen(): HTMLElement {
    render(
      <ThemeProvider>
        <ThemeSelector />
      </ThemeProvider>,
    );
    fireEvent.click(screen.getByRole("button", { expanded: false }));
    return screen.getByRole("radiogroup", { name: "Colour theme" });
  }

  it("marks exactly one option as checked, readable by a screen reader", () => {
    const group = renderAndOpen();
    const checked = within(group)
      .getAllByRole("radio")
      .filter((option) => option.getAttribute("aria-checked") === "true");
    expect(checked).toHaveLength(1);
    expect(checked[0]).toHaveAccessibleName(new RegExp(DEFAULT_THEME_ID, "i"));
  });

  it("does not convey selection by colour alone - the word 'Selected' is present", () => {
    const group = renderAndOpen();
    expect(within(group).getByText("Selected")).toBeInTheDocument();
  });

  it("supports arrow-key navigation per the WAI-ARIA radiogroup pattern", () => {
    const group = renderAndOpen();
    fireEvent.keyDown(group, { key: "ArrowDown" });
    expect(activeTheme()).toBe(THEMES[1].id);
    fireEvent.keyDown(group, { key: "End" });
    expect(activeTheme()).toBe(THEMES[THEMES.length - 1].id);
    fireEvent.keyDown(group, { key: "Home" });
    expect(activeTheme()).toBe(THEMES[0].id);
  });

  it("closes on Escape and returns focus to the trigger", () => {
    const group = renderAndOpen();
    fireEvent.keyDown(group, { key: "Escape" });
    expect(screen.queryByRole("radiogroup")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Theme/i })).toHaveFocus();
  });

  it("uses a real button for the trigger, never a clickable div", () => {
    render(
      <ThemeProvider>
        <ThemeSelector />
      </ThemeProvider>,
    );
    const trigger = screen.getByRole("button", { name: /Theme/i });
    expect(trigger.tagName).toBe("BUTTON");
    expect(trigger).toHaveAttribute("aria-haspopup", "true");
  });
});
