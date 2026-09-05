"use client";

import { useLayoutEffect, useRef, type ReactNode } from "react";

/** Keep the last copy when Next streams the same review more than once. */
export function MountOnce({ name, children }: { name: string; children: ReactNode }) {
  const ref = useRef<HTMLDivElement>(null);
  useLayoutEffect(() => {
    const nodes = document.querySelectorAll<HTMLElement>(`[data-mount-once="${name}"]`);
    if (nodes.length < 2) {
      return;
    }
    nodes.forEach((node, i) => {
      const keep = i === nodes.length - 1;
      node.hidden = !keep;
      if (keep) {
        node.removeAttribute("inert");
      } else {
        node.setAttribute("inert", "");
      }
    });
  }, [name]);
  return (
    <div ref={ref} data-mount-once={name}>
      {children}
    </div>
  );
}
