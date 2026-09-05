import { formatMs, formatPct, gateLabel } from "@/lib/format";
import type { DashboardRun } from "@/lib/types";

import { Metric } from "./ui/Metric";
import { Panel } from "./ui/Panel";

function gateClass(passed: boolean | null | undefined): string {
  if (passed === true) {
    return "text-ok";
  }
  if (passed === false) {
    return "text-red-800";
  }
  return "text-muted";
}

export function KpiStrip({ data }: { data: DashboardRun }) {
  const kpis = data.kpis;
  if (!kpis) {
    return null;
  }
  const explValue = kpis.explanation_precision == null ? "n/a" : formatPct(kpis.explanation_precision);
  return (
    <section className="space-y-2">
      <div>
        <h2 className="text-base font-semibold tracking-tight text-ink">How sure is this?</h2>
        <p className="mt-0.5 text-sm text-muted">
          We score matches against labeled rows. Unresolved items stay on the list — never auto-passed.
        </p>
      </div>
      <Panel className="grid gap-4 px-5 py-4 sm:grid-cols-2 lg:grid-cols-3">
        <Metric
          label="Fewer leftovers"
          title="Engine leftovers minus items still open after the investigator"
          value={String(kpis.exceptions_reduced)}
          hint={`${kpis.exceptions_before} → ${kpis.exceptions_after} still open`}
        />
        <Metric
          label="Time to review"
          title="Wall time for matching plus investigation"
          value={formatMs(kpis.elapsed_ms)}
          hint="Match + investigate"
        />
        <Metric
          label="Explanations right"
          title="Flagged items whose explanation cites this row and matches the labeled type"
          value={explValue}
          hint={`${gateLabel(kpis.explanation_precision_pass)} · target ≥${formatPct(kpis.explanation_precision_threshold)}`}
          className={`min-w-[7rem] ${gateClass(kpis.explanation_precision_pass)}`}
        />
      </Panel>
    </section>
  );
}
