// frontend/src/common/components/ActiveBadge.tsx
//
// Checkpoint 9: visually distinguishes active vs. historical versions using
// the API's existing `is_active` field (never a new frontend-invented
// field). Distinction is conveyed by both text and shape/border, not color
// alone, per the accessibility requirement (no color-only status).
export function ActiveBadge({ isActive }: { isActive: boolean }): JSX.Element {
  if (isActive) {
    return (
      <span className="badge badge--active" title="This is the currently active version">
        ● Active
      </span>
    );
  }
  return (
    <span className="badge badge--historical" title="Historical version, not currently active">
      ○ Historical
    </span>
  );
}
