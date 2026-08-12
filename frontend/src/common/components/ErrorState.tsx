// frontend/src/common/components/ErrorState.tsx
//
// Checkpoint 9: shared error display. Renders only the `ApiError.message`
// text (or the caller's own safe fallback) - never raw response bodies,
// stack traces, or SQL/Django internals. `role="alert"` so assistive tech
// announces it immediately.
export function ErrorState({ message }: { message: string }): JSX.Element {
  return (
    <div className="state state--error" role="alert">
      <strong>Something went wrong.</strong>
      <p>{message}</p>
    </div>
  );
}
