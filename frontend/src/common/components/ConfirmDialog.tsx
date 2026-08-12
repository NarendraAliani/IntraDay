// frontend/src/common/components/ConfirmDialog.tsx
//
// Checkpoint 10: reusable confirmation dialog for state-changing actions
// (currently only risk-configuration activation, but written generically
// so a later universe/strategy activation workflow can reuse it rather
// than duplicating dialog/focus/keyboard logic).
//
// Accessibility: `role="dialog"` + `aria-modal="true"` + `aria-labelledby`
// pointing at the heading. Focus moves to the dialog's cancel button on
// open (a safe default action) and Escape closes it (treated as Cancel).
// Processing state disables both actions and is announced via
// `aria-busy`/`role="status"` text rather than color alone.
import { useEffect, useRef } from "react";

export type ConfirmDialogStatus = "idle" | "submitting" | "error";

export interface ConfirmDialogProps {
  titleId: string;
  title: string;
  /** Structured description content (not vague "Are you sure?" text). */
  children: React.ReactNode;
  confirmLabel: string;
  cancelLabel?: string;
  status: ConfirmDialogStatus;
  errorMessage?: string;
  onConfirm: () => void;
  onCancel: () => void;
}

export function ConfirmDialog({
  titleId,
  title,
  children,
  confirmLabel,
  cancelLabel = "Cancel",
  status,
  errorMessage,
  onConfirm,
  onCancel,
}: ConfirmDialogProps): JSX.Element {
  const cancelButtonRef = useRef<HTMLButtonElement>(null);
  const submitting = status === "submitting";

  useEffect(() => {
    cancelButtonRef.current?.focus();
  }, []);

  useEffect(() => {
    function handleKeyDown(event: KeyboardEvent): void {
      if (event.key === "Escape" && !submitting) {
        onCancel();
      }
    }
    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [onCancel, submitting]);

  return (
    <div className="dialog-backdrop">
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        aria-busy={submitting}
        className="dialog"
      >
        <h3 id={titleId}>{title}</h3>
        <div className="dialog__body">{children}</div>

        {status === "error" && errorMessage && (
          <p role="alert" className="dialog__error">
            {errorMessage}
          </p>
        )}
        {submitting && (
          <p role="status" className="dialog__status">
            Processing…
          </p>
        )}

        <div className="dialog__actions">
          <button
            ref={cancelButtonRef}
            type="button"
            onClick={onCancel}
            disabled={submitting}
          >
            {cancelLabel}
          </button>
          <button type="button" onClick={onConfirm} disabled={submitting} autoFocus={false}>
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
