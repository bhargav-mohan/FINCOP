"use client";

import { useMemo, useState } from "react";

import { confidenceLabel, formatInr, humanizeType } from "@/lib/format";
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
  title = "Needs a person",
  subtitle = "Items that still need a person. Open Why? for the suggested next step.",
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

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return rows.filter((row) => (typeFilter ? row.type === typeFilter : true) && matchesQuery(row, q));
  }, [rows, query, typeFilter]);

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
        <h2 className="text-sm font-medium text-slate-700">{title}</h2>
        <p className="text-xs text-slate-500">
          {subtitle}
          {totalExposure ? ` Exposure ${formatInr(totalExposure)}.` : ""}
        </p>
      </div>
      {rows.length > 0 ? (
        <ExceptionFilters
          rows={rows}
          query={query}
          onQuery={setQuery}
          typeFilter={typeFilter}
          onTypeFilter={setTypeFilter}
          shown={sorted.length}
        />
      ) : null}
      <div className="overflow-x-auto rounded-lg border border-slate-200 bg-white">
        <table className="min-w-full text-left text-sm">
          <thead className="border-b border-slate-200 bg-slate-50 text-xs uppercase tracking-wide text-slate-500">
            <tr>
              <th className="px-3 py-2 font-medium">Item</th>
              <th className="px-3 py-2 font-medium" aria-sort={aria("type")}>
                <button type="button" className="underline-offset-2 hover:underline" onClick={() => toggle("type")}>
                  Issue {sortKey === "type" ? (dir === "asc" ? "↑" : "↓") : ""}
                </button>
              </th>
              <th className="px-3 py-2 font-medium" aria-sort={aria("amount")}>
                <button type="button" className="underline-offset-2 hover:underline" onClick={() => toggle("amount")}>
                  Amount {sortKey === "amount" ? (dir === "asc" ? "↑" : "↓") : ""}
                </button>
              </th>
              <th className="px-3 py-2 font-medium" aria-sort={aria("age")}>
                <button type="button" className="underline-offset-2 hover:underline" onClick={() => toggle("age")}>
                  Open for {sortKey === "age" ? (dir === "asc" ? "↑" : "↓") : ""}
                </button>
              </th>
              <th className="px-3 py-2 font-medium">Details</th>
              <th className="px-3 py-2 font-medium">Related records</th>
              <th className="px-3 py-2 font-medium">Confidence</th>
              <th className="px-3 py-2 font-medium">
                <span className="sr-only">Explain</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {sorted.length === 0 ? (
              <tr>
                <td className="px-3 py-4 text-slate-500" colSpan={8}>
                  {rows.length === 0
                    ? "Everything reconciled — no unresolved items."
                    : "No items match this filter."}
                </td>
              </tr>
            ) : (
              sorted.map((row) => {
                const conf = confidenceLabel(row.confidence);
                const expanded = openId === row.id;
                return (
                  <ExceptionRow
                    key={row.id}
                    row={row}
                    conf={conf}
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
  conf,
  expanded,
  batchKey,
  onToggle,
}: {
  row: DashboardException;
  conf: ReturnType<typeof confidenceLabel>;
  expanded: boolean;
  batchKey?: string;
  onToggle: () => void;
}) {
  const whyId = `${row.id}-why`;
  return (
    <>
      <tr className="border-b border-slate-100 last:border-0">
        <td className="px-3 py-2 font-medium text-slate-800">{row.id}</td>
        <td className="px-3 py-2">{humanizeType(row.type)}</td>
        <td className="px-3 py-2 tabular-nums">{formatInr(row.amount_at_risk ?? "0")}</td>
        <td className="px-3 py-2 text-slate-600">{ageLabel(row)}</td>
        <td className="px-3 py-2 text-slate-700">{row.reason}</td>
        <td className="px-3 py-2 text-slate-600">{row.refs.join(", ")}</td>
        <td className="px-3 py-2">
          {conf ? (
            <span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs text-slate-700">{conf}</span>
          ) : (
            <span className="text-xs text-slate-400">—</span>
          )}
        </td>
        <td className="px-3 py-2">
          <button
            type="button"
            className="text-sm text-slate-700 underline-offset-2 hover:underline"
            aria-expanded={expanded}
            aria-controls={whyId}
            onClick={onToggle}
          >
            Why?
          </button>
        </td>
      </tr>
      {expanded ? (
        <tr className="border-b border-slate-100 bg-slate-50">
          <td id={whyId} className="px-3 py-3" colSpan={8}>
            <div className="space-y-3 text-sm text-slate-700">
              <p>{row.explanation || row.reason}</p>
              {row.suggested_action ? (
                <p>
                  <span className="font-medium text-slate-800">What to do next: </span>
                  {row.suggested_action}
                </p>
              ) : null}
              {row.evidence && row.evidence.length > 0 ? (
                <div>
                  <p className="font-medium text-slate-800">Evidence</p>
                  <ul className="mt-1 list-disc space-y-0.5 pl-5">
                    {row.evidence.map((item) => (
                      <li key={item}>{item}</li>
                    ))}
                  </ul>
                </div>
              ) : null}
              {row.validator_passed ? (
                <p className="text-xs font-medium text-emerald-800">Checked by validator</p>
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
