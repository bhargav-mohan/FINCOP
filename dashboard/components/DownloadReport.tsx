"use client";

import type { DashboardException, DashboardRun } from "@/lib/types";
import { confidenceLabel, csvEscape, formatInr, formatPct, humanizeType, sourceLabel } from "@/lib/format";

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
      ? `Seed: ${data.seed} (same seed reproduces this batch)`
      : "Same file reproduces this review",
    `Reconciled: ${formatPct(data.match_rate)} (${data.matched} of ${data.total_groups || data.matched + data.exception_count})`,
    `Closed: ${data.matched}`,
    `Needs review: ${data.exception_count}`,
    `Match precision (closed vs MATCHED labels): ${data.match_precision == null ? "n/a" : formatPct(data.match_precision)}`,
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
  return `${lines.join("\n")}\n`;
}

export function DownloadReport({ data }: { data: DashboardRun }) {
  return (
    <div className="flex flex-wrap gap-2">
      <button
        type="button"
        className="rounded border border-slate-300 bg-white px-4 py-2 text-sm font-medium text-slate-800"
        onClick={() => {
          const csv = exceptionsCsv(data.exceptions);
          downloadBlob(
            "unresolved-items.csv",
            new Blob([csv], { type: "text/csv;charset=utf-8" })
          );
        }}
      >
        Download CSV
      </button>
      <button
        type="button"
        className="rounded border border-slate-300 bg-white px-4 py-2 text-sm font-medium text-slate-800"
        onClick={() => {
          downloadBlob(
            "review-summary.txt",
            new Blob([summaryText(data)], { type: "text/plain;charset=utf-8" })
          );
        }}
      >
        Download summary
      </button>
      <button
        type="button"
        className="rounded border border-slate-300 bg-white px-4 py-2 text-sm font-medium text-slate-800"
        onClick={() => {
          downloadBlob(
            "reconciliation-report.json",
            new Blob([JSON.stringify(data, null, 2)], { type: "application/json" })
          );
        }}
      >
        Download JSON
      </button>
    </div>
  );
}
