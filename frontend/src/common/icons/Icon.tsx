// frontend/src/common/icons/Icon.tsx
//
// Checkpoint 64.80-F2 Phase 8: ONE icon system for the whole frontend.
//
// DECISION — hand-authored inline SVG, no new npm dependency.
// Rationale, recorded here because Phase 8 asks for a reasoned choice:
//   * `package.json` has exactly TWO runtime dependencies (react,
//     react-dom). Adding an icon package would be a 100% increase in the
//     runtime dependency count, plus a supply-chain surface, for roughly
//     sixteen glyphs.
//   * The set below is small, closed, and drawn on ONE grammar (24x24
//     box, stroke-only, `currentColor`, 1.5 stroke width, round caps and
//     joins, no fills), which is exactly the consistency Phase 8 asks
//     for - and it is enforceable by a unit test, which an external
//     library's glyphs would not be.
//   * `currentColor` means every icon is automatically theme-correct
//     under all four themes with no per-theme icon work.
//
// ACCESSIBILITY (Phase 8/14): icons are decorative by default -
// `aria-hidden="true"` and `focusable="false"`, because in every current
// usage the adjacent text already carries the meaning. Passing `label`
// promotes the icon to `role="img"` with an accessible name, for the
// case where an icon must stand alone.
import type { JSX } from "react";

/** The closed set of semantic icon names. Adding a name here is the ONLY
 * way to add an icon to the application - which is what stops Font
 * Awesome, stray SVGs, Unicode symbols and emoji from re-appearing as
 * competing icon systems. */
export type IconName =
  | "dashboard"
  | "market"
  | "archive"
  | "paper-trading"
  | "research"
  | "system-health"
  | "settings"
  | "security"
  | "gainz"
  | "refresh"
  | "warning"
  | "success"
  | "error"
  | "info"
  | "navigation"
  | "theme"
  | "check"
  | "chevron-down"
  | "signal";

/** Path geometry only - every shared attribute (size, stroke, colour,
 * caps) is applied once by the renderer below so no glyph can drift off
 * the common grammar. */
const ICON_PATHS: Record<IconName, JSX.Element> = {
  // Four-quadrant panel layout: the canonical "overview" mark.
  dashboard: (
    <>
      <rect x="3" y="3" width="7" height="7" rx="1.5" />
      <rect x="14" y="3" width="7" height="7" rx="1.5" />
      <rect x="3" y="14" width="7" height="7" rx="1.5" />
      <rect x="14" y="14" width="7" height="7" rx="1.5" />
    </>
  ),
  // A price series over an axis.
  market: (
    <>
      <path d="M3 20h18" />
      <path d="M4 16l5-6 4 4 6-8" />
      <path d="M19 6h-4m4 0v4" />
    </>
  ),
  // Stacked storage with a retrieval handle.
  archive: (
    <>
      <rect x="3" y="4" width="18" height="4" rx="1" />
      <path d="M5 8v10a2 2 0 002 2h10a2 2 0 002-2V8" />
      <path d="M10 12h4" />
    </>
  ),
  // A half-filled disc: the established "simulated, not live" motif.
  "paper-trading": (
    <>
      <circle cx="12" cy="12" r="8.5" />
      <path d="M12 3.5v17" />
      <path d="M12 6.5a5.5 5.5 0 010 11" />
    </>
  ),
  // Lens over a data field.
  research: (
    <>
      <circle cx="11" cy="11" r="6.5" />
      <path d="M20 20l-4.6-4.6" />
      <path d="M8.5 11h5M11 8.5v5" />
    </>
  ),
  // Vital-sign trace inside a container.
  "system-health": (
    <>
      <rect x="3" y="5" width="18" height="14" rx="2" />
      <path d="M6.5 12h3l1.5-3 2 6 1.5-3h3" />
    </>
  ),
  // Adjustment sliders - a settings mark that stays legible at 16px.
  settings: (
    <>
      <path d="M4 7h10M18 7h2M4 17h4M12 17h8" />
      <circle cx="16" cy="7" r="2" />
      <circle cx="10" cy="17" r="2" />
    </>
  ),
  security: (
    <>
      <path d="M12 3l7 3v6c0 4.2-2.9 7.6-7 9-4.1-1.4-7-4.8-7-9V6z" />
      <path d="M9.5 12l1.8 1.8L15 10" />
    </>
  ),
  // Concentric growth arc - future scope, deliberately quiet.
  gainz: (
    <>
      <path d="M4 18a8 8 0 0116 0" />
      <path d="M8 18a4 4 0 018 0" />
      <path d="M12 18V6" />
      <path d="M9 9l3-3 3 3" />
    </>
  ),
  refresh: (
    <>
      <path d="M20 12a8 8 0 10-2.6 5.9" />
      <path d="M20 5v5h-5" />
    </>
  ),
  warning: (
    <>
      <path d="M12 4.5l8.2 14.2H3.8z" />
      <path d="M12 10v4" />
      <path d="M12 17h.01" />
    </>
  ),
  success: (
    <>
      <circle cx="12" cy="12" r="8.5" />
      <path d="M8.5 12.3l2.4 2.4 4.6-5" />
    </>
  ),
  error: (
    <>
      <circle cx="12" cy="12" r="8.5" />
      <path d="M9.2 9.2l5.6 5.6M14.8 9.2l-5.6 5.6" />
    </>
  ),
  info: (
    <>
      <circle cx="12" cy="12" r="8.5" />
      <path d="M12 11v5" />
      <path d="M12 8h.01" />
    </>
  ),
  navigation: (
    <>
      <path d="M4 7h16M4 12h16M4 17h16" />
    </>
  ),
  // Overlapping tonal discs - the theme/palette control.
  theme: (
    <>
      <circle cx="9.5" cy="12" r="5.5" />
      <circle cx="14.5" cy="12" r="5.5" />
    </>
  ),
  check: (
    <>
      <path d="M5 12.8l4.2 4.2L19 7" />
    </>
  ),
  "chevron-down": (
    <>
      <path d="M6 9.5l6 6 6-6" />
    </>
  ),
  // The signal-detection motif used by the cerebral visual language.
  signal: (
    <>
      <path d="M3 12h3.5l2.5-6 3 12 2.5-6H21" />
    </>
  ),
};

export interface IconProps {
  name: IconName;
  /** Accessible name. Omit for decorative icons (the default), which are
   * hidden from assistive technology. */
  label?: string;
  /** Optional extra class for sizing/placement. Colour always comes from
   * `currentColor`, i.e. from the theme, never from a prop. */
  className?: string;
}

export function Icon({ name, label, className }: IconProps): JSX.Element {
  const decorative = label === undefined;
  return (
    <svg
      className={className ? `icon ${className}` : "icon"}
      viewBox="0 0 24 24"
      width="1em"
      height="1em"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.5"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden={decorative ? "true" : undefined}
      role={decorative ? undefined : "img"}
      aria-label={decorative ? undefined : label}
      focusable="false"
    >
      {ICON_PATHS[name]}
    </svg>
  );
}

/** Exposed for the icon-consistency unit test. */
export const ICON_NAMES = Object.keys(ICON_PATHS) as IconName[];
