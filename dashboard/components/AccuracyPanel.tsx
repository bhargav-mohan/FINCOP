import { formatPct } from "@/lib/format";
import type { DashboardRun } from "@/lib/types";

import { Metric } from "./ui/Metric";
import { Panel } from "./ui/Panel";
import { Section } from "./ui/Section";

export function AccuracyPanel({ data }: { data: DashboardRun }) {
  const acc = data.accuracy;
  return (
    <Section
      title="Quality and value"
      subtitle="How automatic matching compared with the full review, and time saved on auto-closed items."
    >
      <div className="grid gap-3 lg:grid-cols-2">
        <Panel className="px-4 py-3">
          <p className="mb-3 text-[10px] font-medium uppercase tracking-wide text-slate-400">Accuracy</p>
          <div className="flex flex-wrap gap-x-8 gap-y-4">
            <Metric
              label="Rules alone"
              title="Automatic matching"
              value={formatPct(data.baseline_match_rate)}
            />
            <Metric
              label="With investigator"
              title="After smart review"
              value={formatPct(data.advanced_match_rate)}
            />
            <Metric
              label="Matches correct"
              title="Match precision"
              value={data.match_precision == null ? "n/a" : formatPct(data.match_precision)}
            />
            <Metric
              label="Flagged correctly"
              title="Detection precision"
              value={formatPct(data.exception_precision)}
            />
            <Metric
              label="Issues caught"
              title="Detection recall"
              value={formatPct(data.exception_recall)}
            />
            {acc ? (
              <>
                <Metric label="False flags" value={String(acc.false_positives)} />
                <Metric label="Missed items" value={String(acc.false_negatives)} />
              </>
            ) : null}
          </div>
        </Panel>
        <Panel className="px-4 py-3">
          <p className="mb-3 text-[10px] font-medium uppercase tracking-wide text-slate-400">Efficiency</p>
          <div className="flex flex-wrap gap-x-8 gap-y-4">
            {data.value ? (
              <>
                <Metric
                  label="Closed by rules"
                  value={String(data.value.auto_closed_by_rules ?? data.value.auto_closed_by_ai)}
                />
                <Metric label="Closed by AI" value={String(data.value.auto_closed_by_llm ?? 0)} />
                <Metric label="Sent to analyst" value={String(data.value.sent_to_analyst)} />
                <Metric label="Est. minutes saved" value={String(data.value.est_analyst_minutes_saved)} />
              </>
            ) : (
              <Metric label="Auto-close estimate" value="n/a" />
            )}
          </div>
        </Panel>
      </div>
      {data.value?.assumption ? (
        <p className="text-xs text-slate-500">{data.value.assumption}</p>
      ) : (
        <p className="text-xs text-slate-500">No auto-close estimate for this run.</p>
      )}
    </Section>
  );
}
