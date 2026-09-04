from __future__ import annotations

from decimal import ROUND_HALF_EVEN, ROUND_HALF_UP, Decimal

GST_RATE = Decimal("0.18")
GST_TOLERANCE = Decimal("0.05")


def gst_half_up(gross: Decimal) -> Decimal:
    return (gross * GST_RATE).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def gst_bankers(gross: Decimal) -> Decimal:
    return (gross * GST_RATE).quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN)


def gst_on_mdr(mdr: Decimal) -> Decimal:
    return (mdr * GST_RATE).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
