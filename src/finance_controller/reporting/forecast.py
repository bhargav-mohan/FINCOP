from __future__ import annotations

from datetime import date
from decimal import Decimal

from finance_controller.config import ReconConfig
from finance_controller.models import ForwardCash, Source
from finance_controller.reconciliation.dates import add_banking_days
from finance_controller.reconciliation.engine import EngineResult
from finance_controller.reporting.exposure import exception_exposure


def compute_forward_cash(
    result: EngineResult,
    config: ReconConfig,
    *,
    as_of: date | None = None,
) -> ForwardCash:
    """Expected inflows from open ledger rows, using the configured settlement lag.

    as_of defaults to the latest date in the batch (statement date), not wall-clock today.
    """
    records = result.records
    statement = as_of or (max((r.txn_date for r in records), default=date.min))
    by_id = {r.id: r for r in records}
    due = Decimal("0.00")
    stuck = Decimal("0.00")
    by_day: dict[date, Decimal] = {}
    for exc in result.exceptions:
        members = [by_id[i] for i in exc.record_ids if i in by_id]
        ledgers = [r for r in members if r.source == Source.LEDGER]
        if not ledgers:
            continue
        gross = exception_exposure(exc, by_id)
        if gross == 0:
            continue
        start = max(r.txn_date for r in ledgers)
        expected = add_banking_days(start, config.date_lag_days, config.holidays)
        by_day[expected] = (by_day.get(expected, Decimal("0.00")) + gross).quantize(Decimal("0.01"))
        if expected <= statement:
            stuck += gross
        else:
            due += gross
    return ForwardCash(
        as_of=statement,
        lag_days=config.date_lag_days,
        due_within_window=due.quantize(Decimal("0.01")),
        stuck_past_window=stuck.quantize(Decimal("0.01")),
        expected_by_day={d.isoformat(): str(amt) for d, amt in sorted(by_day.items())},
    )
