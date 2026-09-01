import type { DashboardRun } from "@/lib/types";

import { ExceptionsTable } from "./ExceptionsTable";
import { Metric } from "./ui/Metric";
import { Panel } from "./ui/Panel";
import { Section } from "./ui/Section";

export function TaxResults({ data }: { data: DashboardRun }) {
  if (!data.tax || data.tax.skipped) {
    return (
      <Section title="Tax review">
        <p className="text-sm text-slate-500">
          {data.tax?.reason === "no tax lines in zip"
            ? "No tax file in this upload — tax review skipped."
            : "No tax lines in this review."}
        </p>
      </Section>
    );
  }
  const tax = data.tax;
  return (
    <Section title="Tax review" subtitle="GST lines matched against booked payments.">
      <div className="grid grid-cols-3 gap-3">
        <Panel className="p-4">
          <Metric
            label="Tax reconciled"
            value={tax.match_rate == null ? "n/a" : `${(tax.match_rate * 100).toFixed(1)}%`}
          />
        </Panel>
        <Panel className="p-4">
          <Metric label="Tax closed" value={String(tax.matched)} />
        </Panel>
        <Panel className="p-4">
          <Metric label="Tax needs review" value={String(tax.exception_count)} />
        </Panel>
      </div>
      <ExceptionsTable rows={tax.exceptions} title="Unresolved tax items" subtitle="Tax lines that did not match a payment." />
    </Section>
  );
}
