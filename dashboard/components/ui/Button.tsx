import type { ReactNode } from "react";

export function Button({
  children,
  variant = "primary",
  type = "button",
  disabled,
  className = "",
  onClick,
}: {
  children: ReactNode;
  variant?: "primary" | "secondary" | "ghost";
  type?: "button" | "submit";
  disabled?: boolean;
  className?: string;
  onClick?: () => void;
}) {
  const kind = variant === "primary" ? "btn-primary" : variant === "secondary" ? "btn-secondary" : "btn-ghost";
  return (
    <button type={type} disabled={disabled} onClick={onClick} className={`${kind} ${className}`.trim()}>
      {children}
    </button>
  );
}
