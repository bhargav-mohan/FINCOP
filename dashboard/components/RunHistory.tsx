import { formatInr, formatPct, humanizeType } from "@/lib/format";
import type { StoreHistory } from "@/lib/types";

import { Panel } from "./ui/Panel";
import { Section } from "./ui/Section";

export function RunHistory({ store }: { store?: StoreHistory }) {
  if (!store?.available) {
    return (
      <Section title="Run history">
        <p className="text-sm text-slate-500">
          History is stored locally in SQLite. It will appear after the first successful review of this dataset.
        </p>
      </Section>
    );
  }
  const runs = store.recent_runs;
  if (!runs.length) {
    return (
      <Section title="Run history">
        <p className="text-sm text-slate-500">
          Re-review the same dataset to build aging and repeat-offender history. A new seed starts a new dataset.
        </p>
      </Section>
    );
  }
  return (
    <Section title="Run history" subtitle="Prior reviews of this same dataset, newest first.">
      <Panel className="overflow-x-auto">
        <table className="min-w-full text-left text-sm">
          <thead className="border-b border-slate-200 bg-slate-50 text-xs uppercase tracking-wide text-slate-500">
            <tr>
              <th className="px-3 py-2 font-medium">When</th>
              <th className="px-3 py-2 font-medium">Reconciled</th>
              <th className="px-3 py-2 font-medium">Needs review</th>
              <th className="px-3 py-2 font-medium">In transit</th>
              <th className="px-3 py-2 font-medium">Precision</th>
              <th className="px-3 py-2 font-medium">Recall</th>
            </tr>
          </thead>
          <tbody>
            {runs.map((run) => (
              <tr key={run.id} className="border-b border-slate-100 last:border-0">
                <td className="px-3 py-2 text-slate-600">{run.created_at.slice(0, 19).replace("T", " ")}</td>
                <td className="px-3 py-2 tabular-nums">{formatPct(run.match_rate)}</td>
                <td className="px-3 py-2 tabular-nums">{run.exception_count}</td>
                <td className="px-3 py-2 tabular-nums">{formatInr(run.in_flight_gross)}</td>
                <td className="px-3 py-2 tabular-nums">
                  {run.precision == null ? "n/a" : formatPct(run.precision)}
                </td>
                <td className="px-3 py-2 tabular-nums">
                  {run.recall == null ? "n/a" : formatPct(run.recall)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </Panel>
      {store.repeat_offenders.length ? (
        <div>
          <h3 className="text-xs font-medium uppercase tracking-wide text-slate-500">Repeat items</h3>
          <ul className="mt-1 space-y-1 text-sm text-slate-700">
            {store.repeat_offenders.map((item) => (
              <li key={item.key}>
                {item.key} · {humanizeType(item.type)} · open {item.runs_open} runs ·{" "}
                {formatInr(item.amount_at_risk)}
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </Section>
  );
}
