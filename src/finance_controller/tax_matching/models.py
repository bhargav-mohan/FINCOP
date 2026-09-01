from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from finance_controller.reconciliation.normalize import parse_amount


@dataclass
class TaxLine:
    id: str
    invoice_id: str
    payment_id: str
    taxable_value: Decimal
    gst_rate: Decimal
    gst_amount: Decimal
    hsn: str = ""

    @classmethod
    def from_row(cls, row: dict[str, str], *, index: int) -> TaxLine:
        rate_raw = (row.get("gst_rate") or "").strip()
        if not rate_raw:
            raise ValueError(f"tax row {index} missing gst_rate")
        rate = parse_amount(rate_raw)
        if rate > 1:
            rate = (rate / Decimal("100")).quantize(Decimal("0.0001"))
        invoice = (row.get("invoice_id") or "").strip()
        payment = (row.get("payment_id") or "").strip()
        return cls(
            id=invoice or payment or f"TAX-{index:04d}",
            invoice_id=invoice,
            payment_id=payment,
            taxable_value=parse_amount(row.get("taxable_value") or "0"),
            gst_rate=rate,
            gst_amount=parse_amount(row.get("gst_amount") or "0"),
            hsn=(row.get("hsn") or "").strip(),
        )
