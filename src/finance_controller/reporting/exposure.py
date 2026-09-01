from __future__ import annotations

from decimal import Decimal

from finance_controller.models import Record, ReconException, Source


def exception_exposure(exc: ReconException, by_id: dict[str, Record]) -> Decimal:
    """Ledger-side gross for one exception. Dedupes record ids inside the exception."""
    seen: set[str] = set()
    total = Decimal("0.00")
    for rid in exc.record_ids:
        rec = by_id.get(rid)
        if rec is None or rec.source != Source.LEDGER or rec.id in seen:
            continue
        seen.add(rec.id)
        total += rec.amount
    return total.quantize(Decimal("0.01"))
