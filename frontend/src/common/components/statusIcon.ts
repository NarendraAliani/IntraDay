// frontend/src/common/components/statusIcon.ts
//
// Checkpoint FRONTEND-4: a single, reused mapping from an existing
// `badge--*` design-system class to the icon that already exists in the
// closed icon system (`src/common/icons/Icon.tsx`) for that semantic
// tone. This is the SAME success/warning/error/info vocabulary already
// used by `ActiveBadge`, `ConnectionStatusBadge` and `CapabilityStatus`
// (Checkpoint 64.80-F2 Phase 8) - this module exists only so every
// OTHER color-only badge site in the app (worker/session health,
// readiness checklists, scanner/token status) can reuse that exact
// mapping instead of re-deriving its own per-file icon table, which
// would risk drifting from the established convention.
//
// No new icon is introduced here - `badgeIconName()` only ever returns
// a name already defined in `IconName`.
import type { IconName } from "../icons/Icon";

/** Maps a `badge--*` CSS class (the class alone, not the leading
 * `"badge "` prefix) to the semantic icon already used for that tone
 * elsewhere in the app. Falls back to "info" for an unrecognized or
 * neutral class, matching `ConnectionStatusBadge`'s own fallback tone. */
export function badgeIconName(badgeClass: string | undefined): IconName {
  switch (badgeClass) {
    case "badge--active":
    case "badge--ok":
      return "success";
    case "badge--danger":
      return "error";
    case "badge--pending":
      return "warning";
    case "badge--paper":
      return "paper-trading";
    case "badge--historical":
    default:
      return "info";
  }
}
