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
      className={`rounded-uber border bg-white ${
        dashed ? "border-dashed border-line" : "border-line"
      } ${className}`}
    >
      {children}
    </div>
  );
}
