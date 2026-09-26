import type { ReactNode } from "react";

export function Key({ children }: { children: ReactNode }) {
  return <kbd className="keycap">{children}</kbd>;
}

export function EmptyState({
  title,
  hint,
  action,
}: {
  title: string;
  hint: string;
  action?: ReactNode;
}) {
  return (
    <div className="empty">
      <p className="empty-title">{title}</p>
      <p className="empty-hint">{hint}</p>
      {action}
    </div>
  );
}

export function Spinner({ label }: { label: string }) {
  return (
    <div className="loading" role="status" aria-live="polite">
      <span className="loading-mark" aria-hidden="true">
        {">"}
        <span className="loading-caret">_</span>
      </span>
      <p>{label}</p>
    </div>
  );
}
