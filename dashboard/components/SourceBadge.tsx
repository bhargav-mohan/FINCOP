import { sourceLabel } from "@/lib/format";
import type { BatchSource } from "@/lib/types";

export function SourceBadge({
  batchSource,
  sourceFiles,
}: {
  batchSource: BatchSource;
  sourceFiles?: Record<string, string>;
}) {
  const names = sourceFiles ? Object.values(sourceFiles).filter(Boolean) : [];
  return (
    <p className="text-xs text-muted">
      {sourceLabel(batchSource)}
      {names.length ? ` · ${names.join(", ")}` : null}
    </p>
  );
}
