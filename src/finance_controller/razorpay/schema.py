from __future__ import annotations

from decimal import Decimal, InvalidOperation

# Razorpay Settlement Recon / GET /v1/settlements/recon/combined columns.
# Amounts on the API are integer paise. CSV exports may be paise or rupees with a decimal.
RECON_COLUMNS = (
    "entity_id",
    "type",
    "payment_id",
    "order_id",
    "amount",
    "fee",
    "tax",
    "debit",
    "credit",
    "currency",
    "settlement_id",
    "settlement_utr",
    "created_at",
    "settled_at",
    "method",
    "settled",
    "notes",
)

SKIP_TYPES = frozenset({"adjustment", "transfer"})
PAYMENT_TYPE = "payment"
REFUND_TYPE = "refund"

# Razorpay field -> canonical finance-controller field.
# Join key is settlement_id (the Razorpay payout batch). settlement_utr is the
# correspondent-bank NEFT reference, not the primary match key.
FIELD_MAPPING: dict[str, str] = {
    "entity_id": "ledger.payment_id / psp payment id (when payment_id empty)",
    "payment_id": "ledger.payment_id",
    "order_id": "ledger extra / description",
    "amount": "ledger.amount / psp.gross_amount (paise -> rupees)",
    "fee": "psp.mdr_fee (tax stripped when tax is included in fee)",
    "tax": "psp.gst_on_fee (GST on MDR)",
    "credit": "psp.net_amount contribution (payment)",
    "debit": "psp.net_amount reduction (refund)",
    "settlement_id": "psp.settlement_id and bank grouping key",
    "settlement_utr": "bank.utr (NEFT reference)",
    "created_at": "ledger.timestamp",
    "settled_at": "psp.settled_date / bank.credited_date",
    "method": "ledger.customer fallback / description",
    "type": "payment|refund mapped; adjustment|transfer -> warning, skipped",
    "currency": "INR (passed through)",
    "settled": "false/empty -> no bank credit for that settlement",
    "notes": "ledger.customer when present",
}


def paise_to_decimal(value: object) -> Decimal:
    """Convert Razorpay integer paise to rupees. 100000 -> 1000.00."""
    try:
        raw = Decimal(str(value).strip())
    except (InvalidOperation, AttributeError) as exc:
        raise ValueError(f"invalid paise amount: {value!r}") from exc
    if not raw.is_finite():
        raise ValueError(f"non-finite paise amount: {value!r}")
    return (raw / Decimal(100)).quantize(Decimal("0.01"))


def parse_razorpay_amount(value: object) -> Decimal:
    """API integers are paise; a decimal point means the value is already rupees."""
    if value in (None, ""):
        return Decimal("0.00")
    text = str(value).strip()
    if "." in text:
        try:
            amount = Decimal(text)
        except InvalidOperation as exc:
            raise ValueError(f"invalid rupee amount: {value!r}") from exc
        if not amount.is_finite():
            raise ValueError(f"non-finite rupee amount: {value!r}")
        return amount.quantize(Decimal("0.01"))
    return paise_to_decimal(text)
