export type DashboardRecord = {
  id: string;
  source: string;
  reference: string;
  amount: string;
  currency: string;
  date: string;
  fee: string;
  gst: string;
  utr: string;
  status: string;
  description: string;
  payee: string;
};

export type DashboardException = {
  id: string;
  key?: string;
  type: string;
  reason: string;
  refs: string[];
  amounts?: Record<string, string>;
  amount_at_risk?: string;
  sources?: string[];
  records?: DashboardRecord[];
  explanation?: string | null;
  suggested_action?: string | null;
  confidence?: number | null;
  hypothesis_by?: string | null;
  evidence?: string[];
  validator_passed?: boolean;
  checked_records?: string[];
  first_seen?: string | null;
  runs_open?: number;
  days_open?: number;
  note?: string | null;
  assignee?: string;
  resolved_at?: string | null;
};

export type DashboardMatch = {
  id: string;
  tier: string;
  reason: string;
  refs: string[];
};

export type BatchSource = "generated" | "razorpay_recon" | "csv_dir" | "zip";

export type StoreHistory = {
  available: boolean;
  reason?: string;
  batch_key: string;
  recent_runs: {
    id: number;
    created_at: string;
    matched: number;
    exception_count: number;
    match_rate: number;
    precision: number | null;
    recall: number | null;
    in_flight_gross: string;
    llm_used: boolean;
  }[];
  repeat_offenders: {
    key: string;
    type: string;
    runs_open: number;
    amount_at_risk: string;
  }[];
  aging?: Record<string, { first_seen: string; runs_open: number; days_open: number }>;
  notes?: Record<string, { author: string; note: string; assignee: string; resolved_at: string | null }>;
};

export type DashboardRun = {
  error?: string;
  seed: number;
  batch_source: BatchSource;
  source_files?: Record<string, string>;
  agent_warnings: string[];
  num_records: number;
  match_rate: number;
  matched: number;
  exception_count: number;
  total_groups: number;
  match_precision: number | null;
  exception_precision: number;
  exception_recall: number;
  baseline_match_rate: number;
  advanced_match_rate: number;
  llm_used: boolean;
  cash: {
    closed_bank_net: string;
    in_flight_amount: string;
    in_flight_count?: number;
    aged_out_count: number;
  };
  accuracy?: {
    false_positives: number;
    false_negatives: number;
    type_accuracy: number | null;
    f1?: number;
  };
  total_exposure?: string;
  exceptions: DashboardException[];
  matches?: DashboardMatch[];
  investigations?: { id: string; decision: string; by: string; rationale: string }[];
  tax: {
    skipped?: boolean;
    reason?: string;
    matched: number;
    exception_count: number;
    match_rate: number | null;
    exceptions: DashboardException[];
    matches: DashboardException[];
  } | null;
  ingestion: { files: Record<string, string>; warnings: string[] } | null;
  store?: StoreHistory;
  value: {
    auto_closed_by_ai: number;
    auto_closed_by_rules?: number;
    auto_closed_by_llm?: number;
    sent_to_analyst: number;
    auto_close_rate: number;
    in_flight_amount: string;
    est_analyst_minutes_saved: number;
    assumed_minutes_per_item: number;
    assumption: string;
  } | null;
};
