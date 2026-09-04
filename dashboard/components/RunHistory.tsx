import { formatInr, formatPct, humanizeType } from "@/lib/format";
import type { StoreHistory } from "@/lib/types";

import { Panel } from "./ui/Panel";
import { Section } from "./ui/Section";

export function RunHistory({ store }: { store?: StoreHistory }) {
  if (!store?.available) {
    return (
      <Section title="Earlier runs">
        <p className="text-sm text-muted">
          History is saved on this machine. It shows up after the first successful review of this file.
        </p>
      </Section>
    );
  }
  const runs = store.recent_runs;
  if (!runs.length) {
    return (
      <Section title="Earlier runs">
        <p className="text-sm text-muted">
          Review the same upload again to see aging. A different file starts a new history.
        </p>
      </Section>
    );
  }
  return (
    <Section title="Earlier runs" subtitle="Prior reviews of this same file, newest first.">
      <Panel className="overflow-x-auto">
        <table className="min-w-full text-left text-sm">
          <thead className="border-b border-line bg-wash text-xs text-muted">
            <tr>
              <th className="px-3 py-2 font-medium">When</th>
              <th className="px-3 py-2 font-medium">Matched</th>
              <th className="px-3 py-2 font-medium">Needs you</th>
              <th className="px-3 py-2 font-medium">Waiting</th>
              <th className="px-3 py-2 font-medium">Precision</th>
              <th className="px-3 py-2 font-medium">Recall</th>
            </tr>
          </thead>
          <tbody>
            {runs.map((run) => (
              <tr key={run.id} className="border-b border-line last:border-0">
                <td className="px-3 py-2 text-muted">{run.created_at.slice(0, 19).replace("T", " ")}</td>
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
          <h3 className="text-sm font-medium text-ink">Still coming back</h3>
          <ul className="mt-1 space-y-1 text-sm text-ink">
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
