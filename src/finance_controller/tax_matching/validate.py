from __future__ import annotations

from decimal import Decimal

from finance_controller.config import ReconConfig
from finance_controller.models import Record
from finance_controller.reconciliation.gst import GST_TOLERANCE, gst_half_up
from finance_controller.reconciliation.validate import ValidationResult
from finance_controller.tax_matching.models import TaxLine


def expected_gst(taxable: Decimal, rate: Decimal) -> Decimal:
    if rate == Decimal("0.18"):
        return gst_half_up(taxable)
    return (taxable * rate).quantize(Decimal("0.01"))


def validate_tax_match(tax: TaxLine, ledger: Record, config: ReconConfig) -> ValidationResult:
    ids = [tax.id, ledger.id]
    expected = expected_gst(tax.taxable_value, tax.gst_rate)
    if abs(tax.gst_amount - expected) > GST_TOLERANCE:
        return ValidationResult(
            False,
            [f"gst {tax.gst_amount} != half_up {expected} of taxable {tax.taxable_value} (tol {GST_TOLERANCE})"],
            ids,
        )
    exclusive = abs(ledger.amount - tax.taxable_value) <= config.amount_tolerance
    inclusive = abs(ledger.amount - (tax.taxable_value + tax.gst_amount)) <= config.amount_tolerance
    if not exclusive and not inclusive:
        return ValidationResult(
            False,
            [
                f"ledger {ledger.amount} matches neither taxable {tax.taxable_value} "
                f"nor taxable+gst {(tax.taxable_value + tax.gst_amount)}"
            ],
            ids,
        )
    return ValidationResult(True, ["tax amount/rate/rounding accepted"], ids)
