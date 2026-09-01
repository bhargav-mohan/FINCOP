import { formatInr, formatPct } from "@/lib/format";
import type { DashboardRun } from "@/lib/types";

import { Panel } from "./ui/Panel";

export function Verdict({ data }: { data: DashboardRun }) {
  const total = data.total_groups || data.matched + data.exception_count;
  const closedPct = (data.match_rate || 0) * 100;
  const minutes = data.value?.est_analyst_minutes_saved;

  const chips = [
    {
      label: "Closed",
      value: String(data.matched),
      rail: "border-l-emerald-500",
      labelColor: "text-emerald-700",
      valueColor: "text-emerald-800",
    },
    {
      label: "Needs review",
      value: String(data.exception_count),
      rail: "border-l-amber-500",
      labelColor: "text-amber-700",
      valueColor: "text-amber-800",
    },
    {
      label: "Settled in bank",
      value: formatInr(data.cash.closed_bank_net),
      rail: "border-l-slate-300",
      labelColor: "text-slate-500",
      valueColor: "text-slate-900",
    },
    {
      label: "Still in transit",
      value: formatInr(data.cash.in_flight_amount),
      rail: "border-l-slate-300",
      labelColor: "text-slate-500",
      valueColor: "text-slate-900",
    },
    {
      label: "Overdue items",
      value: String(data.cash.aged_out_count),
      rail: "border-l-slate-300",
      labelColor: "text-slate-500",
      valueColor: "text-slate-900",
    },
    {
      label: "Est. minutes saved",
      value: minutes == null ? "n/a" : String(minutes),
      rail: "border-l-indigo-400",
      labelColor: "text-indigo-600",
      valueColor: "text-indigo-900",
    },
  ];

  return (
    <section className="space-y-2">
      <div>
        <h2 className="text-sm font-medium text-slate-700">Did this review close?</h2>
        <p className="text-xs text-slate-500">Headline outcome of matching payments to settlements.</p>
      </div>
      <Panel className="grid gap-6 p-5 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.2fr)]">
        <div>
          <p className="text-xs uppercase tracking-wide text-indigo-600">Reconciled</p>
          <p className="mt-1 text-5xl font-semibold tabular-nums text-indigo-900">{formatPct(data.match_rate)}</p>
          <p className="mt-2 text-sm text-slate-600">
            {data.matched} of {total} loops closed. {data.exception_count} need a person.
          </p>
          <div className="mt-4 h-1.5 overflow-hidden rounded-full bg-amber-200" aria-hidden>
            <div className="h-full rounded-full bg-emerald-500" style={{ width: `${closedPct}%` }} />
          </div>
        </div>
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
          {chips.map((chip) => (
            <div key={chip.label} className={`border-l-4 pl-3 ${chip.rail}`}>
              <p className={`text-xs uppercase tracking-wide ${chip.labelColor}`}>{chip.label}</p>
              <p className={`mt-0.5 text-lg font-semibold tabular-nums ${chip.valueColor}`}>{chip.value}</p>
            </div>
          ))}
        </div>
      </Panel>
    </section>
  );
}
