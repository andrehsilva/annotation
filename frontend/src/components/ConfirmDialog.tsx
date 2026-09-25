import { WarningCircle } from "@phosphor-icons/react";
import { useEffect, useRef } from "react";

export interface ConfirmRequest {
  title: string;
  message: string;
  confirmLabel?: string;
  danger?: boolean;
  action: () => void | Promise<void>;
}

interface ConfirmDialogProps extends Omit<ConfirmRequest, "action"> {
  cancelLabel?: string;
  onConfirm: () => void;
  onCancel: () => void;
}

/** Keyboard-first replacement for window.confirm: Esc cancels, Enter confirms. */
export function ConfirmDialog({
  title,
  message,
  confirmLabel = "Confirmar",
  cancelLabel = "Cancelar",
  danger = false,
  onConfirm,
  onCancel,
}: ConfirmDialogProps) {
  const confirmRef = useRef<HTMLButtonElement | null>(null);

  useEffect(() => {
    confirmRef.current?.focus();
  }, []);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        onCancel();
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [onCancel]);

  return (
    <div
      className="overlay is-centered"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onCancel();
      }}
    >
      <div
        className="confirm"
        role="alertdialog"
        aria-modal="true"
        aria-labelledby="confirm-title"
        aria-describedby="confirm-message"
      >
        <div className="confirm-head">
          {danger && <WarningCircle size={18} weight="bold" className="confirm-icon" />}
          <p className="confirm-title" id="confirm-title">
            {title}
          </p>
        </div>
        <p className="confirm-message" id="confirm-message">
          {message}
        </p>
        <div className="confirm-actions">
          <button type="button" className="btn btn-ghost" onClick={onCancel}>
            {cancelLabel}
          </button>
          <button
            ref={confirmRef}
            type="button"
            className={danger ? "btn btn-primary is-danger" : "btn btn-primary"}
            onClick={onConfirm}
          >
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
