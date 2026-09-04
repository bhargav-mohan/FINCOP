import { formatInr, formatPct } from "@/lib/format";
import type { DashboardRun } from "@/lib/types";

import { Panel } from "./ui/Panel";

export function Verdict({ data }: { data: DashboardRun }) {
  const total = data.total_groups || data.matched + data.exception_count;
  const closedPct = (data.match_rate || 0) * 100;
  const minutes = data.value?.est_analyst_minutes_saved;
  const leftover = data.exception_count;

  const chips = [
    { label: "Matched", value: String(data.matched) },
    { label: "Needs you", value: String(leftover) },
    { label: "In the bank", value: formatInr(data.cash.closed_bank_net) },
    { label: "Waiting", value: formatInr(data.cash.in_flight_amount) },
    { label: "Overdue", value: String(data.cash.aged_out_count) },
    { label: "Time saved", value: minutes == null ? "n/a" : `${minutes} min` },
  ];

  return (
    <section className="space-y-2">
      <div>
        <h2 className="text-base font-semibold tracking-tight text-ink">How this review went</h2>
        <p className="mt-0.5 text-sm text-muted">
          {leftover === 0
            ? `Everything matched — ${data.matched} of ${total} items closed.`
            : leftover === 1
              ? `${formatPct(data.match_rate)} matched. One item still needs you.`
              : `${formatPct(data.match_rate)} matched. ${leftover} items still need you.`}
        </p>
      </div>
      <Panel className="grid gap-6 p-5 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.2fr)]">
        <div>
          <p className="text-sm text-muted">Matched</p>
          <p className="mt-1 text-5xl font-semibold tabular-nums tracking-tight text-ink">
            {formatPct(data.match_rate)}
          </p>
          <p className="mt-2 text-sm text-muted">
            {data.matched} of {total} closed
            {leftover ? ` · ${leftover} open` : ""}.
          </p>
          <div className="mt-4 h-1.5 overflow-hidden rounded-full bg-line" aria-hidden>
            <div className="h-full rounded-full bg-ink" style={{ width: `${closedPct}%` }} />
          </div>
        </div>
        <div className="grid grid-cols-2 gap-4 sm:grid-cols-3">
          {chips.map((chip) => (
            <div key={chip.label}>
              <p className="text-sm text-muted">{chip.label}</p>
              <p className="mt-0.5 text-lg font-semibold tabular-nums text-ink">{chip.value}</p>
            </div>
          ))}
        </div>
      </Panel>
    </section>
  );
}
