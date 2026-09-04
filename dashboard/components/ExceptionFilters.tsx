"use client";

import { humanizeType } from "@/lib/format";
import type { DashboardException } from "@/lib/types";

export function ExceptionFilters({
  rows,
  query,
  onQuery,
  typeFilter,
  onTypeFilter,
  shown,
}: {
  rows: DashboardException[];
  query: string;
  onQuery: (value: string) => void;
  typeFilter: string | null;
  onTypeFilter: (value: string | null) => void;
  shown: number;
}) {
  const counts = new Map<string, number>();
  for (const row of rows) {
    counts.set(row.type, (counts.get(row.type) ?? 0) + 1);
  }
  const types = [...counts.entries()].sort((a, b) => humanizeType(a[0]).localeCompare(humanizeType(b[0])));

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-3">
        <label className="text-sm text-muted">
          <span className="sr-only">Search unresolved items</span>
          <input
            type="search"
            value={query}
            onChange={(e) => onQuery(e.target.value)}
            placeholder="Search item, details, or records"
            className="w-64 rounded-uber border border-line bg-white px-3 py-2 text-sm"
          />
        </label>
        <p className="text-xs text-muted">
          Showing {shown} of {rows.length}
        </p>
      </div>
      {types.length > 1 ? (
        <div className="flex flex-wrap gap-1.5">
          <button
            type="button"
            onClick={() => onTypeFilter(null)}
            className={`rounded-full px-2.5 py-1 text-xs ${
              typeFilter === null ? "bg-black text-white" : "bg-white text-ink ring-1 ring-line"
            }`}
          >
            All ({rows.length})
          </button>
          {types.map(([type, count]) => (
            <button
              key={type}
              type="button"
              onClick={() => onTypeFilter(typeFilter === type ? null : type)}
              className={`rounded-full px-2.5 py-1 text-xs ${
                typeFilter === type ? "bg-black text-white" : "bg-white text-ink ring-1 ring-line"
              }`}
            >
              {humanizeType(type)} ({count})
            </button>
          ))}
        </div>
      ) : null}
    </div>
  );
}
