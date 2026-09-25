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
    <div className="loading">
      <p>{label}</p>
    </div>
  );
}
