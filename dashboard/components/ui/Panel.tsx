import type { ReactNode } from "react";

export function Panel({
  children,
  className = "",
  dashed = false,
}: {
  children: ReactNode;
  className?: string;
  dashed?: boolean;
}) {
  return (
    <div
      className={`rounded-lg border bg-white ${
        dashed ? "border-dashed border-slate-300" : "border-slate-200"
      } ${className}`}
    >
      {children}
    </div>
  );
}
