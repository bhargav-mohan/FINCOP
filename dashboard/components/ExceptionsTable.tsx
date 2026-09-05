"use client";

import { useId, useMemo, useState } from "react";

import { formatInr, humanizeType } from "@/lib/format";
import type { DashboardException } from "@/lib/types";

import { ExceptionFilters } from "./ExceptionFilters";
import { ExceptionNote } from "./ExceptionNote";
import { RecordTable } from "./RecordTable";

type SortKey = "type" | "amount" | "age";
type SortDir = "asc" | "desc";

function matchesQuery(row: DashboardException, query: string): boolean {
  if (!query) {
    return true;
  }
  const hay = [row.id, row.reason, row.refs.join(" "), row.explanation ?? "", row.suggested_action ?? ""]
    .join(" ")
    .toLowerCase();
  return hay.includes(query);
}

function compare(a: DashboardException, b: DashboardException, key: SortKey, dir: SortDir): number {
  let result = 0;
  if (key === "type") {
    result = humanizeType(a.type).localeCompare(humanizeType(b.type));
  } else if (key === "amount") {
    result = Number(a.amount_at_risk ?? 0) - Number(b.amount_at_risk ?? 0);
  } else {
    result = (a.days_open ?? 0) - (b.days_open ?? 0);
  }
  return dir === "asc" ? result : -result;
}

function ageLabel(row: DashboardException): string {
  const days = row.days_open ?? 0;
  const runs = row.runs_open ?? 1;
  if (days <= 0) {
    return runs > 1 ? `${runs} runs` : "New";
  }
  return `${days}d / ${runs} runs`;
}

export function ExceptionsTable({
  rows,
  title = "Needs you",
  subtitle = "Open See why for the suggested next step.",
  batchKey,
  totalExposure,
}: {
  rows: DashboardException[];
  title?: string;
  subtitle?: string;
  batchKey?: string;
  totalExposure?: string;
}) {
  const [sortKey, setSortKey] = useState<SortKey>("amount");
  const [dir, setDir] = useState<SortDir>("desc");
  const [query, setQuery] = useState("");
  const [typeFilter, setTypeFilter] = useState<string | null>(null);
  const [openId, setOpenId] = useState<string | null>(null);
  const tableId = useId();

  const uniqueRows = useMemo(() => {
    const seen = new Set<string>();
    return rows.filter((row) => {
      if (!row.id || seen.has(row.id)) {
        return false;
      }
      seen.add(row.id);
      return true;
    });
  }, [rows]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return uniqueRows.filter((row) => (typeFilter ? row.type === typeFilter : true) && matchesQuery(row, q));
  }, [uniqueRows, query, typeFilter]);

  const sorted = useMemo(() => {
    const copy = [...filtered];
    copy.sort((a, b) => compare(a, b, sortKey, dir));
    return copy;
  }, [filtered, sortKey, dir]);

  function toggle(next: SortKey) {
    if (sortKey === next) {
      setDir((d) => (d === "asc" ? "desc" : "asc"));
      return;
    }
    setSortKey(next);
    setDir(next === "type" ? "asc" : "desc");
  }

  function aria(next: SortKey) {
    if (sortKey !== next) {
      return "none" as const;
    }
    return dir === "asc" ? ("ascending" as const) : ("descending" as const);
  }

  return (
    <section className="space-y-2">
      <div>
        <h2 className="text-base font-semibold tracking-tight text-ink">{title}</h2>
        <p className="mt-0.5 text-sm text-muted">
          {subtitle}
          {totalExposure ? ` Money still at risk: ${formatInr(totalExposure)}.` : ""}
        </p>
      </div>
      {uniqueRows.length > 0 ? (
        <ExceptionFilters
          rows={uniqueRows}
          query={query}
          onQuery={setQuery}
          typeFilter={typeFilter}
          onTypeFilter={setTypeFilter}
          shown={sorted.length}
        />
      ) : null}
      <div className="overflow-x-auto rounded-uber border border-line bg-white">
        <table className="min-w-full text-left text-sm">
          <thead className="border-b border-line bg-wash text-xs text-muted">
            <tr>
              <th className="px-3 py-2.5 font-medium">Item</th>
              <th className="px-3 py-2.5 font-medium" aria-sort={aria("type")}>
                <button type="button" className="underline-offset-2 hover:underline" onClick={() => toggle("type")}>
                  What happened {sortKey === "type" ? (dir === "asc" ? "↑" : "↓") : ""}
                </button>
              </th>
              <th className="px-3 py-2.5 font-medium" aria-sort={aria("amount")}>
                <button type="button" className="underline-offset-2 hover:underline" onClick={() => toggle("amount")}>
                  Money at risk {sortKey === "amount" ? (dir === "asc" ? "↑" : "↓") : ""}
                </button>
              </th>
              <th className="px-3 py-2.5 font-medium" aria-sort={aria("age")}>
                <button type="button" className="underline-offset-2 hover:underline" onClick={() => toggle("age")}>
                  How long {sortKey === "age" ? (dir === "asc" ? "↑" : "↓") : ""}
                </button>
              </th>
              <th className="px-3 py-2.5 font-medium">Why it is open</th>
              <th className="px-3 py-2.5 font-medium">Tied to</th>
              <th className="px-3 py-2.5 font-medium">
                <span className="sr-only">See why</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {sorted.length === 0 ? (
              <tr>
                <td className="px-3 py-6 text-muted" colSpan={7}>
                  {uniqueRows.length === 0}
                    ? "Nothing left for you — every item matched."
                    : "Nothing matches that search. Clear filters to see the list again."}
                </td>
              </tr>
            ) : (
              sorted.map((row) => {
                const expanded = openId === row.id;
                return (
                  <ExceptionRow
                    key={row.id}
                    row={row}
                    whyId={`${tableId}-${row.id}-why`}
                    expanded={expanded}
                    batchKey={batchKey}
                    onToggle={() => setOpenId(expanded ? null : row.id)}
                  />
                );
              })
            )}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function ExceptionRow({
  row,
  whyId,
  expanded,
  batchKey,
  onToggle,
}: {
  row: DashboardException;
  whyId: string;
  expanded: boolean;
  batchKey?: string;
  onToggle: () => void;
}) {
  return (
    <>
      <tr className="border-b border-line last:border-0">
        <td className="px-3 py-3 font-medium text-ink">{row.id}</td>
        <td className="px-3 py-3">{humanizeType(row.type)}</td>
        <td className="px-3 py-3 tabular-nums">{formatInr(row.amount_at_risk ?? "0")}</td>
        <td className="px-3 py-3 text-muted">{ageLabel(row)}</td>
        <td className="px-3 py-3 text-ink">{row.reason}</td>
        <td className="px-3 py-3 text-muted">{row.refs.join(", ")}</td>
        <td className="px-3 py-3">
          <button
            type="button"
            className="text-sm font-medium text-ink underline-offset-2 hover:underline"
            aria-expanded={expanded}
            aria-controls={whyId}
            onClick={onToggle}
          >
            {expanded ? "Hide" : "See why"}
          </button>
        </td>
      </tr>
      {expanded ? (
        <tr className="border-b border-line bg-wash">
          <td id={whyId} className="px-3 py-4" colSpan={7}>
            <div className="space-y-3 text-sm text-ink">
              <p>{row.explanation || row.reason}</p>
              {row.suggested_action ? (
                <p>
                  <span className="font-medium">What to do next: </span>
                  {row.suggested_action}
                </p>
              ) : null}
              {row.evidence && row.evidence.length > 0 ? (
                <div>
                  <p className="font-medium">What we looked at</p>
                  <ul className="mt-1 list-disc space-y-0.5 pl-5">
                    {row.evidence.map((item) => (
                      <li key={item}>{item}</li>
                    ))}
                  </ul>
                </div>
              ) : null}
              {row.validator_passed ? (
                <p className="text-xs font-medium text-ok">Checked against the source rows</p>
              ) : null}
              <RecordTable records={row.records ?? []} />
              <ExceptionNote row={row} batchKey={batchKey} />
            </div>
          </td>
        </tr>
      ) : null}
    </>
  );
}
