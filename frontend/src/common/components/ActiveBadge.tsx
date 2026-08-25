// frontend/src/common/components/ActiveBadge.tsx
//
// Checkpoint 9: visually distinguishes active vs. historical versions using
// the API's existing `is_active` field (never a new frontend-invented
// field). Distinction is conveyed by both text and shape/border, not color
// alone, per the accessibility requirement (no color-only status).
//
// Checkpoint 64.80-F2 Phase 8: the leading Unicode glyph is replaced by
// an SVG from the single icon system. Text, badge classes and semantics
// are unchanged - only the marker's rendering.
import { Icon } from "../icons/Icon";

export function ActiveBadge({ isActive }: { isActive: boolean }): JSX.Element {
  if (isActive) {
    return (
      <span className="badge badge--active" title="This is the currently active version">
        <Icon name="success" /> Active
      </span>
    );
  }
  return (
    <span className="badge badge--historical" title="Historical version, not currently active">
      <Icon name="info" /> Historical
    </span>
  );
}
