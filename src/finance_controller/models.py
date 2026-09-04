from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class Source(str, Enum):
    LEDGER = "ledger"
    BANK = "bank"
    PSP = "psp"


class MatchTier(str, Enum):
    EXACT = "exact"
    TOLERANT = "tolerant"
    MANY_TO_ONE = "many_to_one"
    ONE_TO_MANY = "one_to_many"
    AGENT_VALIDATED = "agent_validated"


class PaymentStatus(str, Enum):
    SUCCESS = "success"
    FAILED = "failed"
    PENDING = "pending"
    REFUNDED = "refunded"


class AgentAction(str, Enum):
    RECONCILE = "reconcile"
    ESCALATE = "escalate"


class ExceptionType(str, Enum):
    MISSING_IN_BANK = "missing_in_bank"
    MISSING_IN_LEDGER = "missing_in_ledger"
    AMOUNT_MISMATCH = "amount_mismatch"
    DUPLICATE = "duplicate"
    FX_MISMATCH = "fx_mismatch"
    UNMATCHED = "unmatched"
    PARTIAL_REFUND = "partial_refund"
    ZERO_OR_NEGATIVE_NET = "zero_or_negative_net"
    STATUS_MISMATCH = "status_mismatch"
    DATE_INVERTED = "date_inverted"
    LATE_SETTLEMENT = "late_settlement"
    EMPTY_UTR = "empty_utr"
    MALFORMED_UTR = "malformed_utr"
    GST_ZERO_BUG = "gst_zero_bug"
    GST_MISMATCH = "gst_mismatch"
    MALFORMED_AMOUNT = "malformed_amount"
    DUPLICATE_UTR = "duplicate_utr"


class ExpectedStatus(str, Enum):
    MATCHED = "matched"
    EXCEPTION = "exception"


class CaseCategory(str, Enum):
    CLEAN = "clean"
    IRRESOLVABLE = "irresolvable"
    RESOLVABLE_AMBIGUOUS = "resolvable_ambiguous"


class Record(BaseModel):
    id: str
    source: Source
    reference: str
    amount: Decimal
    currency: str
    txn_date: date
    fee: Decimal = Decimal("0.00")
    payee: str = ""
    description: str = ""
    batch_id: str | None = None
    split_id: str | None = None
    utr: str = ""
    status: PaymentStatus = PaymentStatus.SUCCESS
    gst: Decimal = Decimal("0.00")
    created_date: date | None = None
    extra: dict[str, Any] = Field(default_factory=dict)

    @property
    def net_amount(self) -> Decimal:
        return (self.amount - self.fee).quantize(Decimal("0.01"))


class MatchResult(BaseModel):
    match_id: str
    tier: MatchTier
    record_ids: list[str]
    references: list[str]
    reason: str


class ExceptionHypothesis(BaseModel):
    hypothesis_type: ExceptionType
    explanation: str
    suggested_action: str
    confidence: float = Field(ge=0.0, le=1.0)
    produced_by: str = "rules"


class ToolCallLog(BaseModel):
    tool: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    result_summary: str = ""


class Investigation(BaseModel):
    exception_id: str
    decision: AgentAction
    action: AgentAction
    classification: ExceptionType | None = None
    evidence: list[str] = Field(default_factory=list)
    tool_calls: list[ToolCallLog] = Field(default_factory=list)
    proposed_record_ids: list[str] = Field(default_factory=list)
    validator_passed: bool = False
    rationale: str = ""
    produced_by: str = "rules"


class ReconException(BaseModel):
    exception_id: str
    exception_type: ExceptionType
    record_ids: list[str]
    references: list[str]
    sources_involved: list[Source]
    amounts: dict[str, Decimal]
    reason: str
    hypothesis: ExceptionHypothesis | None = None


class GroundTruth(BaseModel):
    key: str
    expected_status: ExpectedStatus
    exception_type: ExceptionType | None = None
    defect: str = ""
    category: CaseCategory = CaseCategory.CLEAN
    record_ids: list[str] = Field(default_factory=list)


class KpiScorecard(BaseModel):
    """Four evaluation bars: match precision, exception reduction, speed, explanation precision."""

    match_precision: float | None = None
    match_precision_threshold: float = 0.90
    match_precision_pass: bool | None = None
    exceptions_before: int = 0
    exceptions_after: int = 0
    exceptions_reduced: int = 0
    elapsed_ms: int = 0
    explanation_precision: float | None = None
    explanation_precision_threshold: float = 0.90
    explanation_precision_pass: bool | None = None


class AccuracyMetrics(BaseModel):
    true_positives: int
    false_positives: int
    false_negatives: int
    precision: float
    recall: float
    f1: float
    type_accuracy: float | None = None


class CashPosition(BaseModel):
    closed_bank_net: Decimal
    in_flight_count: int
    in_flight_gross: Decimal
    negative: bool
    in_flight_aged_out: int = 0


class ValueMetrics(BaseModel):
    auto_closed_by_ai: int
    auto_closed_by_rules: int = 0
    auto_closed_by_llm: int = 0
    sent_to_analyst: int
    auto_close_rate: float
    in_flight_amount: Decimal
    est_analyst_minutes_saved: int
    assumed_minutes_per_item: int
    assumption: str


class BatchSource(str, Enum):
    GENERATED = "generated"
    RAZORPAY_RECON = "razorpay_recon"
    CSV_DIR = "csv_dir"
    ZIP = "zip"


class RunMeta(BaseModel):
    seed: int
    batch_source: BatchSource = BatchSource.GENERATED
    source_files: dict[str, str] = Field(default_factory=dict)
    num_records: int
    inject_exceptions: int
    inject_resolvable: int = 0
    inject_edges: int = 0
    timestamp: datetime
    source_counts: dict[str, int]
    model: str
    llm_used: bool
    agent_reconciled: int = 0
    agent_escalated: int = 0
    agent_warnings: list[str] = Field(default_factory=list)


class Report(BaseModel):
    run: RunMeta
    total_groups: int
    matched: int
    match_rate: float
    matches: list[MatchResult]
    exceptions: list[ReconException]
    investigations: list[Investigation] = Field(default_factory=list)
    accuracy: AccuracyMetrics
    kpis: KpiScorecard | None = None
    cash: CashPosition | None = None
    value: ValueMetrics | None = None
    ground_truth: list[GroundTruth]
