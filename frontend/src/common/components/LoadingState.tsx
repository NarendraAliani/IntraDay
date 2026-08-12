// frontend/src/common/components/LoadingState.tsx
//
// Checkpoint 9: shared loading indicator. Uses `role="status"` so screen
// readers announce it without the app needing a separate visually-hidden
// live region per screen.
export function LoadingState({ label }: { label: string }): JSX.Element {
  return (
    <div className="state state--loading" role="status">
      <span aria-hidden="true" className="state__spinner" />
      <span>{label}</span>
    </div>
  );
}
