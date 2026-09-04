"use client";

import type { DashboardException, DashboardRun } from "@/lib/types";
import { confidenceLabel, csvEscape, formatInr, formatPct, humanizeType, sourceLabel } from "@/lib/format";

import { Button } from "./ui/Button";

function downloadBlob(filename: string, blob: Blob) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  URL.revokeObjectURL(url);
}

function exceptionsCsv(rows: DashboardException[]): string {
  const header = [
    "Item",
    "Issue",
    "Details",
    "Related records",
    "Why",
    "What to do next",
    "Confidence",
    "Evidence",
  ];
  const body = rows.map((row) =>
    [
      row.id,
      humanizeType(row.type),
      row.reason,
      row.refs.join("; "),
      row.explanation ?? "",
      row.suggested_action ?? "",
      confidenceLabel(row.confidence) ?? "",
      (row.evidence ?? []).join("; "),
    ]
      .map(csvEscape)
      .join(",")
  );
  return [header.join(","), ...body].join("\n");
}

function summaryText(data: DashboardRun): string {
  const lines = [
    "Settlement review summary",
    `Source: ${sourceLabel(data.batch_source)}`,
    data.batch_source === "generated"
      ? `Source: generated (CLI only)`
      : "Same file reproduces this review",
    `Reconciled: ${formatPct(data.match_rate)} (${data.matched} of ${data.total_groups || data.matched + data.exception_count})`,
    `Closed: ${data.matched}`,
    `Needs review: ${data.exception_count}`,
    `Match precision (closed vs MATCHED labels): ${data.match_precision == null ? "n/a" : formatPct(data.match_precision)}`,
    data.kpis
      ? `Exceptions reduced: ${data.kpis.exceptions_reduced} (${data.kpis.exceptions_before} → ${data.kpis.exceptions_after})`
      : "",
    data.kpis ? `Processing speed: ${data.kpis.elapsed_ms} ms` : "",
    data.kpis
      ? `Explanation precision: ${data.kpis.explanation_precision == null ? "n/a" : formatPct(data.kpis.explanation_precision)}`
      : "",
    `Detection precision: ${formatPct(data.exception_precision)}`,
    `Detection recall: ${formatPct(data.exception_recall)}`,
    `Settled in bank: ${formatInr(data.cash.closed_bank_net)}`,
    `Still in transit: ${formatInr(data.cash.in_flight_amount)}`,
    `Overdue items: ${data.cash.aged_out_count}`,
  ];
  if (data.accuracy) {
    lines.push(
      `False flags: ${data.accuracy.false_positives}`,
      `Missed items: ${data.accuracy.false_negatives}`
    );
  }
  if (data.value) {
    lines.push(
      `Auto-closed: ${data.value.auto_closed_by_ai}`,
      `Estimate (not measured): ${data.value.est_analyst_minutes_saved} minutes — ${data.value.assumption}`
    );
  }
  return `${lines.filter(Boolean).join("\n")}\n`;
}

export function DownloadReport({ data }: { data: DashboardRun }) {
  return (
    <div className="flex flex-wrap gap-2">
      <Button
        variant="secondary"
        onClick={() => {
          const csv = exceptionsCsv(data.exceptions);
          downloadBlob(
            "unresolved-items.csv",
            new Blob([csv], { type: "text/csv;charset=utf-8" })
          );
        }}
      >
        Download leftovers
      </Button>
      <Button
        variant="secondary"
        onClick={() => {
          downloadBlob(
            "review-summary.txt",
            new Blob([summaryText(data)], { type: "text/plain;charset=utf-8" })
          );
        }}
      >
        Download summary
      </Button>
      <Button
        variant="secondary"
        onClick={() => {
          downloadBlob(
            "reconciliation-report.json",
            new Blob([JSON.stringify(data, null, 2)], { type: "application/json" })
          );
        }}
      >
        Download JSON
      </Button>
    </div>
  );
}
