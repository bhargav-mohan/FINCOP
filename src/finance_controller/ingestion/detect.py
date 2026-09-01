from __future__ import annotations

from enum import Enum


class FileRole(str, Enum):
    BANK = "bank"
    LEDGER = "ledger"
    PSP = "psp"
    TAX = "tax"
    GROUND_TRUTH = "ground_truth"
    RAZORPAY_RECON = "razorpay_recon"
    UNKNOWN = "unknown"


_NAME_HINTS: dict[FileRole, tuple[str, ...]] = {
    FileRole.BANK: ("bank", "statement", "neft", "credits"),
    FileRole.LEDGER: ("ledger", "payment", "books", "journal"),
    FileRole.PSP: ("psp", "settlement", "settle"),
    FileRole.TAX: ("tax", "gst", "gstr", "invoice"),
    FileRole.GROUND_TRUTH: ("ground_truth", "ground-truth", "labels"),
    FileRole.RAZORPAY_RECON: ("settlement_recon", "razorpay", "recon"),
}

_HEADER_HINTS: dict[FileRole, tuple[str, ...]] = {
    FileRole.BANK: ("utr", "credited_amount", "credited_date", "raw_description"),
    FileRole.LEDGER: ("payment_id", "customer", "timestamp", "status"),
    FileRole.PSP: ("settlement_id", "payment_ids", "gross_amount", "net_amount", "mdr_fee"),
    FileRole.TAX: ("taxable_value", "gst_amount", "gst_rate", "hsn", "invoice_id"),
    FileRole.GROUND_TRUTH: ("label", "expected_status", "exception_type", "expected_handling"),
    FileRole.RAZORPAY_RECON: (
        "settlement_utr",
        "entity_id",
        "order_id",
        "settled_at",
        "method",
    ),
}

CANONICAL_NAMES = {
    FileRole.BANK: "bank.csv",
    FileRole.LEDGER: "payments.csv",
    FileRole.PSP: "settlements.csv",
    FileRole.TAX: "tax.csv",
    FileRole.GROUND_TRUTH: "ground_truth.json",
}


def _norm_headers(headers: list[str]) -> set[str]:
    return {h.strip().lower().replace(" ", "_") for h in headers if h}


def detect_role(filename: str, headers: list[str] | None = None) -> FileRole:
    name = filename.lower().replace(" ", "_")
    if name.endswith(".json") and "ground" in name:
        return FileRole.GROUND_TRUTH
    scores: dict[FileRole, int] = {role: 0 for role in FileRole if role != FileRole.UNKNOWN}
    for role, hints in _NAME_HINTS.items():
        if any(h in name for h in hints):
            scores[role] += 3
    header_set = _norm_headers(headers or [])
    for role, hints in _HEADER_HINTS.items():
        hit = sum(1 for h in hints if h in header_set)
        scores[role] += hit
    best = max(scores, key=lambda r: scores[r])
    if scores[best] <= 0:
        return FileRole.UNKNOWN
    return best
