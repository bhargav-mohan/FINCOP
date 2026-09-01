"use client";

import { useState, type ReactNode } from "react";

export function Disclosure({
  preview,
  total,
  children,
}: {
  preview: number;
  total: number;
  children: (expanded: boolean) => ReactNode;
}) {
  const [expanded, setExpanded] = useState(false);
  return (
    <>
      {children(expanded)}
      {total > preview ? (
        <button
          type="button"
          className="text-sm text-slate-600 underline-offset-2 hover:underline"
          onClick={() => setExpanded((v) => !v)}
        >
          {expanded ? "Show less" : `Show all ${total}`}
        </button>
      ) : null}
    </>
  );
}
