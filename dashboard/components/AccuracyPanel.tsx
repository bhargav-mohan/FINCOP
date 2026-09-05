import { formatMs, formatPct, gateLabel } from "@/lib/format";
import type { DashboardRun } from "@/lib/types";

import { Metric } from "./ui/Metric";
import { Panel } from "./ui/Panel";
import { Section } from "./ui/Section";

function investigatorDeltaPp(baseline: number, advanced: number): string {
  const pp = (advanced - baseline) * 100;
  const sign = pp >= 0 ? "+" : "";
  return `${sign}${pp.toFixed(1)}pp`;
}

export function AccuracyPanel({ data }: { data: DashboardRun }) {
  const acc = data.accuracy;
  const kpis = data.kpis;
  const openBefore = kpis?.exceptions_before ?? data.exception_count;
  return (
    <Section
      title="Quality"
      subtitle="How correct the matches were, and how the investigator did on leftovers."
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
              label="Explanations right"
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
              label="Match rate"
              title="Closed groups after the investigator, versus rules alone"
              value={`${formatPct(data.advanced_match_rate)} (investigator added ${investigatorDeltaPp(data.baseline_match_rate, data.advanced_match_rate)})`}
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
          <p className="mb-3 text-xs font-medium text-muted">
            Of the {openBefore} open items
          </p>
          <p className="-mt-2 mb-3 text-xs text-muted">
            Investigator pass on leftovers — not the {data.matched} already closed by the engine.
          </p>
          <div className="flex flex-wrap gap-x-8 gap-y-4">
            {data.value ? (
              <>
                <Metric
                  label="Closed by rules"
                  title="Leftovers the rule investigator closed"
                  value={String(data.value.auto_closed_by_rules ?? 0)}
                />
                <Metric
                  label="Closed by AI"
                  title="Leftovers the LLM closed"
                  value={String(data.value.auto_closed_by_llm ?? 0)}
                />
                <Metric
                  label="Still need you"
                  title="Leftovers still open after the investigator"
                  value={String(data.value.sent_to_analyst)}
                />
              </>
            ) : (
              <Metric label="Investigator on leftovers" value="n/a" />
            )}
          </div>
        </Panel>
      </div>
    </Section>
  );
}
