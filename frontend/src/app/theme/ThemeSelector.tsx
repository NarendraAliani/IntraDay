// frontend/src/app/theme/ThemeSelector.tsx
//
// Checkpoint 64.80-F2 Phase 3/12/13/14: the user-facing theme control.
//
// It is a real, discoverable product control in the application header -
// not a developer toggle, not a query parameter.
//
// ACCESSIBILITY (Phase 14) - the pattern, deliberately chosen:
//   * The trigger is a `<button>` with `aria-expanded`/`aria-haspopup`,
//     never a clickable div.
//   * The popover body is a `role="radiogroup"` of `role="radio"`
//     buttons with `aria-checked` - a screen reader announces both the
//     option name AND whether it is the selected one.
//   * Roving tabindex + Arrow/Home/End keys, per the WAI-ARIA radiogroup
//     pattern; Escape closes and returns focus to the trigger.
//   * Selection is NEVER conveyed by colour alone (Phase 12): the chosen
//     theme carries a check icon and the literal word "Selected".
import { useCallback, useEffect, useRef, useState } from "react";
import type { JSX, KeyboardEvent } from "react";

import { Icon } from "../../common/icons/Icon";
import { THEMES } from "./themeRegistry";
import type { ThemeId } from "./themeRegistry";
import { useTheme } from "./ThemeProvider";

export function ThemeSelector(): JSX.Element {
  const { themeId, theme, setTheme } = useTheme();
  const [open, setOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement | null>(null);
  const triggerRef = useRef<HTMLButtonElement | null>(null);
  const optionRefs = useRef<Record<string, HTMLButtonElement | null>>({});

  const close = useCallback(
    (returnFocus: boolean) => {
      setOpen(false);
      if (returnFocus) triggerRef.current?.focus();
    },
    [],
  );

  // Dismiss on outside click. Registered only while open so the app does
  // not carry a permanent document-level listener.
  useEffect(() => {
    if (!open) return undefined;
    function onPointerDown(event: MouseEvent): void {
      if (!containerRef.current?.contains(event.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", onPointerDown);
    return () => document.removeEventListener("mousedown", onPointerDown);
  }, [open]);

  // Move focus onto the selected option when the popover opens, so a
  // keyboard user lands inside the group rather than behind it.
  useEffect(() => {
    if (open) optionRefs.current[themeId]?.focus();
  }, [open, themeId]);

  function choose(id: ThemeId): void {
    setTheme(id);
    close(true);
  }

  function onGroupKeyDown(event: KeyboardEvent<HTMLDivElement>): void {
    const ids = THEMES.map((entry) => entry.id);
    const index = ids.indexOf(themeId);
    let next: ThemeId | null = null;
    if (event.key === "ArrowDown" || event.key === "ArrowRight") {
      next = ids[(index + 1) % ids.length];
    } else if (event.key === "ArrowUp" || event.key === "ArrowLeft") {
      next = ids[(index - 1 + ids.length) % ids.length];
    } else if (event.key === "Home") {
      next = ids[0];
    } else if (event.key === "End") {
      next = ids[ids.length - 1];
    } else if (event.key === "Escape") {
      event.preventDefault();
      close(true);
      return;
    } else {
      return;
    }
    event.preventDefault();
    // Radiogroup convention: arrow keys move selection, not just focus.
    setTheme(next);
    optionRefs.current[next]?.focus();
  }

  return (
    <div className="theme-selector" ref={containerRef}>
      <button
        type="button"
        ref={triggerRef}
        className="theme-selector__trigger"
        aria-haspopup="true"
        aria-expanded={open}
        onClick={() => setOpen((value) => !value)}
      >
        <Icon name="theme" />
        <span className="theme-selector__trigger-label">Theme</span>
        <span className="theme-selector__trigger-value">{theme.name}</span>
        <Icon name="chevron-down" className="theme-selector__chevron" />
      </button>

      {open && (
        <div
          className="theme-selector__popover"
          role="radiogroup"
          aria-label="Colour theme"
          onKeyDown={onGroupKeyDown}
        >
          <p className="theme-selector__popover-title">Colour theme</p>
          {THEMES.map((entry) => {
            const selected = entry.id === themeId;
            return (
              <button
                key={entry.id}
                type="button"
                role="radio"
                aria-checked={selected}
                tabIndex={selected ? 0 : -1}
                ref={(node) => {
                  optionRefs.current[entry.id] = node;
                }}
                className={
                  selected
                    ? "theme-selector__option theme-selector__option--selected"
                    : "theme-selector__option"
                }
                onClick={() => choose(entry.id)}
              >
                {/* Phase 12: surface + accent preview, rendered from the
                    theme's own tokens via a per-theme CSS class. */}
                <span className={`theme-swatch theme-swatch--${entry.id}`} aria-hidden="true">
                  <span className="theme-swatch__surface" />
                  <span className="theme-swatch__accent" />
                </span>
                <span className="theme-selector__option-text">
                  <span className="theme-selector__option-name">{entry.name}</span>
                  <span className="theme-selector__option-description">{entry.description}</span>
                </span>
                {selected ? (
                  <span className="theme-selector__selected-mark">
                    <Icon name="check" />
                    <span className="theme-selector__selected-word">Selected</span>
                  </span>
                ) : null}
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}
