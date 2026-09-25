import { CheckCircle, Info, WarningCircle, X } from "@phosphor-icons/react";
import type { Icon } from "@phosphor-icons/react";

export type ToastKind = "info" | "success" | "error";

export interface Toast {
  id: number;
  kind: ToastKind;
  message: string;
}

const TOAST_ICONS: Record<ToastKind, Icon> = {
  info: Info,
  success: CheckCircle,
  error: WarningCircle,
};

interface ToastStackProps {
  toasts: Toast[];
  onDismiss: (id: number) => void;
}

/** Side stack (top-right, under the top bar) so notices never cover the editor's caret. */
export function ToastStack({ toasts, onDismiss }: ToastStackProps) {
  return (
    <div className="toast-stack" role="region" aria-live="polite" aria-label="Notificações">
      {toasts.map((toast) => {
        const ToastIcon = TOAST_ICONS[toast.kind];
        return (
          <div className={`toast is-${toast.kind}`} key={toast.id}>
            <ToastIcon size={15} weight="bold" className="toast-icon" />
            <span className="toast-message">{toast.message}</span>
            <button
              type="button"
              className="toast-close"
              onClick={() => onDismiss(toast.id)}
              aria-label="Fechar aviso"
            >
              <X size={12} weight="bold" />
            </button>
          </div>
        );
      })}
    </div>
  );
}
