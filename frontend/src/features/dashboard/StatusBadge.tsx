// frontend/src/features/dashboard/StatusBadge.tsx
//
// Checkpoint 64.80-F Phase 12: ONE semantic status treatment for every
// dashboard card. Renders an existing design-system `badge--*` class
// (never a new hard-coded color) plus an icon and the status word, so
// status is conveyed by shape + text + color rather than color alone.
//
// Checkpoint 64.80-F2 Phase 8/11: the leading glyph is now an SVG from
// the single icon system instead of a Unicode character. The badge
// classes, the tone vocabulary and every status WORD are unchanged -
// only the rendering of the marker changed.
import type { JSX } from "react";

import { Icon } from "../../common/icons/Icon";
import { TONE_BADGE_CLASS, TONE_ICON_NAME } from "./dashboardModel";
import type { StatusDescriptor } from "./dashboardModel";

export function StatusBadge({ status }: { status: StatusDescriptor }): JSX.Element {
  return (
    <span className={`badge ${TONE_BADGE_CLASS[status.tone]}`} data-tone={status.tone}>
      <Icon name={TONE_ICON_NAME[status.tone]} /> {status.label}
    </span>
  );
}
