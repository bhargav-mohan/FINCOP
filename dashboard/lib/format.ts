const TYPE_LABELS: Record<string, string> = {
  missing_in_bank: "Missing bank credit",
  missing_in_ledger: "Missing from books",
  amount_mismatch: "Amount mismatch",
  duplicate: "Duplicate entry",
  fx_mismatch: "Currency mismatch",
  unmatched: "Unmatched",
  partial_refund: "Partial refund",
  zero_or_negative_net: "Zero or negative amount",
  status_mismatch: "Status mismatch",
  date_inverted: "Date out of order",
  late_settlement: "Late settlement",
  empty_utr: "Missing bank reference",
  malformed_utr: "Invalid bank reference",
  gst_zero_bug: "Tax amount missing",
  gst_mismatch: "Tax amount mismatch",
  malformed_amount: "Invalid amount",
  duplicate_utr: "Duplicate reference",
  unmatched_tax: "Unmatched tax line",
};

export function humanizeType(value: string): string {
  if (TYPE_LABELS[value]) {
    return TYPE_LABELS[value];
  }
  return value
    .split(/[_-]+/)
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

export function friendlyError(raw: string | undefined): string {
  const text = (raw || "").toLowerCase();
  if (
    text.includes("zip") ||
    text.includes("ingest") ||
    text.includes("utf") ||
    text.includes("decode") ||
    text.includes("csv") ||
    text.includes("corrupt")
  ) {
    return "We couldn't read those files. Upload CSVs, a folder, an Excel workbook, or a ZIP, then try again.";
  }
  if (text.includes("50") || text.includes("num_records")) {
    return "There isn't enough data to run a review. Please try again.";
  }
  return "Something went wrong. Please try again.";
}

export function humanizeDecision(value: string): string {
  if (value === "reconcile") {
    return "Auto-closed";
  }
  if (value === "escalate") {
    return "Sent for review";
  }
  return humanizeType(value);
}

export function humanizeSource(value: string): string {
  if (value === "llm") {
    return "AI assist";
  }
  return "Automatic";
}

export function friendlyWarning(raw: string): string | null {
  const text = raw.toLowerCase();
  // "not settled" contains "not set" — check payouts before any key-missing heuristic.
  if (text.includes("not settled")) {
    return "Some payouts had not settled yet, so no bank credit was expected for them.";
  }
  if (text.includes("503") || text.includes("high demand") || text.includes("overloaded")) {
    return "The model provider is busy right now. Rules finished the leftovers. Wait a minute and run again.";
  }
  if (text.includes("quota") || text.includes("429") || text.includes("resource_exhausted")) {
    return "The model quota was used up, so rules finished the leftovers. Wait about a minute and run again.";
  }
  if (text.includes("budget") || text.includes("exhausted") || text.includes("time cap")) {
    return "GLM hit the time cap for this review. Rules finished the remaining leftovers.";
  }
  if (text.includes("timed out") || text.includes("timeout")) {
    return "GLM 5.2 took too long on a leftover. Rules finished the rest.";
  }
  if (text.includes("openrouter_api_key") || text.includes("z-ai/glm") || text.includes("zai_api_key")) {
    return "No GLM key loaded. Add OPENROUTER_API_KEY (or ZAI_API_KEY) to the repo .env and restart the dashboard.";
  }
  if (
    text.includes("gemini_api_key") ||
    text.includes("google_api_key")
  ) {
    return "No Gemini key loaded. Add GEMINI_API_KEY to the repo .env and restart the dashboard.";
  }
  if (text.includes("api key")) {
    return "No LLM key loaded. Add OPENROUTER_API_KEY for GLM 5.2, or GEMINI_API_KEY, then restart the dashboard.";
  }
  if (text.includes("model") && text.includes("not found")) {
    return "The model name in .env was not found. For GLM 5.2 set GLM_MODEL=z-ai/glm-5.2 and LLM_PROVIDER=glm.";
  }
  if (text.includes("hypotheses came from rules")) {
    return null;
  }
  if (text.includes("llm") || text.includes("rule engine") || text.includes("leftovers stay")) {
    return "The AI assistant was unavailable, so leftovers were reviewed by built-in rules instead.";
  }
  if (text.includes("no tax") || (text.includes("tax") && text.includes("skipped"))) {
    return null;
  }
  if (text.includes("readme")) {
    return null;
  }
  if (text.includes("adjustment") || text.includes("transfer")) {
    return "Some rows were adjustments or transfers and were left out of the review.";
  }
  if (text.includes("unknown-role") || text.includes("non-csv")) {
    return "A file in the export was not payment, settlement, or bank data and was ignored.";
  }
  return "Some rows in this export were left out of the review.";
}

export function csvEscape(value: string): string {
  if (/[",\n\r]/.test(value)) {
    return `"${value.replace(/"/g, '""')}"`;
  }
  return value;
}

const inr = new Intl.NumberFormat("en-IN", {
  style: "currency",
  currency: "INR",
  maximumFractionDigits: 0,
});

export function formatInr(value: string | number): string {
  const n = typeof value === "number" ? value : Number(value);
  if (!Number.isFinite(n)) {
    return "—";
  }
  return inr.format(n);
}

export function formatPct(value: number): string {
  return `${(value * 100).toFixed(2)}%`;
}

export function formatMs(ms: number): string {
  if (!Number.isFinite(ms) || ms < 0) {
    return "—";
  }
  if (ms < 1000) {
    return `${Math.round(ms)} ms`;
  }
  return `${(ms / 1000).toFixed(2)} s`;
}

export function gateLabel(passed: boolean | null | undefined): "Pass" | "Fail" | "n/a" {
  if (passed === true) {
    return "Pass";
  }
  if (passed === false) {
    return "Fail";
  }
  return "n/a";
}

export function confidenceLabel(value: number | null | undefined): "High" | "Medium" | "Low" | null {
  if (value == null || Number.isNaN(value)) {
    return null;
  }
  if (value >= 0.8) {
    return "High";
  }
  if (value >= 0.5) {
    return "Medium";
  }
  return "Low";
}

const TIER_LABELS: Record<string, string> = {
  exact: "Reference matched exactly",
  tolerant: "Matched within fee tolerance",
  many_to_one: "Batched settlement",
  one_to_many: "Split payout",
  agent_validated: "AI-proposed, validator-approved",
};

export function humanizeTier(value: string): string {
  return TIER_LABELS[value] ?? humanizeType(value);
}

export function sourceLabel(value: BatchSourceLike): string {
  if (value === "razorpay_recon") {
    return "Razorpay settlement export";
  }
  if (value === "zip" || value === "csv_dir") {
    return "Uploaded file";
  }
  return "Sample data";
}

type BatchSourceLike = "generated" | "razorpay_recon" | "csv_dir" | "zip" | string;
