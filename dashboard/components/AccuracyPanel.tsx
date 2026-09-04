import { formatMs, formatPct, gateLabel } from "@/lib/format";
import type { DashboardRun } from "@/lib/types";

import { Metric } from "./ui/Metric";
import { Panel } from "./ui/Panel";
import { Section } from "./ui/Section";

export function AccuracyPanel({ data }: { data: DashboardRun }) {
  const acc = data.accuracy;
  const kpis = data.kpis;
  return (
    <Section
      title="Quality and time saved"
      subtitle="How correct the matches were, how many leftovers closed, and how long the review took."
    >
      {kpis ? (
        <Panel className="px-4 py-3">
          <p className="mb-3 text-xs font-medium text-muted">Quality checks</p>
          <div className="flex flex-wrap gap-x-8 gap-y-4">
            <Metric
              label="Matches correct"
              title="Closed items whose ground-truth label is MATCHED"
              value={kpis.match_precision == null ? "n/a" : formatPct(kpis.match_precision)}
              hint={`${gateLabel(kpis.match_precision_pass)} · ≥${formatPct(kpis.match_precision_threshold)}`}
            />
            <Metric
              label="Exceptions reduced"
              title="Engine leftovers closed by the investigator"
              value={String(kpis.exceptions_reduced)}
              hint={`${kpis.exceptions_before} → ${kpis.exceptions_after}`}
            />
            <Metric
              label="Processing speed"
              title="Wall time for matching plus investigation"
              value={formatMs(kpis.elapsed_ms)}
            />
            <Metric
              label="Explanation precision"
              title="Flagged items whose explanation cites this row and matches the labeled type"
              value={kpis.explanation_precision == null ? "n/a" : formatPct(kpis.explanation_precision)}
              hint={`${gateLabel(kpis.explanation_precision_pass)} · ≥${formatPct(kpis.explanation_precision_threshold)}`}
            />
          </div>
        </Panel>
      ) : null}
      <div className="grid gap-3 lg:grid-cols-2">
        <Panel className="px-4 py-3">
          <p className="mb-3 text-xs font-medium text-muted">Accuracy</p>
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
          <p className="mb-3 text-xs font-medium text-muted">Who closed what</p>
          <div className="flex flex-wrap gap-x-8 gap-y-4">
            {data.value ? (
              <>
                <Metric
                  label="Closed by rules"
                  title="Leftovers closed by the rule investigator"
                  value={String(data.value.auto_closed_by_rules ?? 0)}
                />
                <Metric
                  label="Closed by AI"
                  title="Leftovers closed by the LLM"
                  value={String(data.value.auto_closed_by_llm ?? 0)}
                />
                <Metric
                  label="Sent to analyst"
                  title="Investigator escalations"
                  value={String(data.value.sent_to_analyst)}
                />
                <Metric
                  label="Est. minutes saved"
                  title="Rules-closed loops × assumed minutes"
                  value={`${data.value.est_analyst_minutes_saved} min`}
                />
              </>
            ) : (
              <Metric label="Auto-close estimate" value="n/a" />
            )}
          </div>
        </Panel>
      </div>
      {data.value?.assumption ? (
        <p className="text-xs text-muted">{data.value.assumption}</p>
      ) : (
        <p className="text-xs text-muted">No time-saved estimate for this run.</p>
      )}
    </Section>
  );
}
