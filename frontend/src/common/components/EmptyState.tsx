// frontend/src/common/components/EmptyState.tsx
//
// Checkpoint 9: shared "no data" display. Used when the API responds
// successfully with an empty list - never fabricates sample/placeholder
// records to fill the gap.
export function EmptyState({ message }: { message: string }): JSX.Element {
  return (
    <div className="state state--empty">
      <p>{message}</p>
    </div>
  );
}
