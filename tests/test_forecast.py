from datetime import date

from finance_controller.config import ReconConfig
from finance_controller.data.synthetic import generate
from finance_controller.reconciliation.dates import add_banking_days, banking_days_between
from finance_controller.reconciliation.engine import reconcile
from finance_controller.reporting.forecast import compute_forward_cash
from finance_controller.reporting.report import compute_accuracy, compute_cash, group_match_rate


def test_add_banking_days_skips_weekend():
    friday = date(2026, 1, 9)
    assert add_banking_days(friday, 1, frozenset()) == date(2026, 1, 12)
    assert banking_days_between(friday, date(2026, 1, 12), frozenset()) == 1


def test_forward_cash_partitions_blocked_ledger():
    config = ReconConfig(seed=42, num_records=80, inject_exceptions=12, inject_resolvable=6, inject_edges=16)
    batch = generate(config)
    result = reconcile(batch.all_records, config)
    cash = compute_cash(result)
    forward = compute_forward_cash(result, config)
    assert forward.due_within_window + forward.stuck_past_window == cash.in_flight_gross
    assert forward.lag_days == config.date_lag_days
    assert forward.as_of == max(r.txn_date for r in result.records)


def test_same_inject_on_1000_payments_still_leaves_23_breaks():
    """97% auto-match here is the same 23 leftovers on a larger clean pile."""
    config = ReconConfig(
        seed=42,
        num_records=1000,
        inject_exceptions=12,
        inject_resolvable=6,
        inject_edges=16,
        use_llm=False,
    )
    batch = generate(config)
    result = reconcile(batch.all_records, config)
    metrics = compute_accuracy(batch.ground_truth, result)
    rate = group_match_rate(result.closed_group_count, len(result.exceptions))
    assert len(result.exceptions) == 23
    assert result.closed_group_count == 973
    assert rate == 0.9769
    assert metrics.f1 == 1.0
    assert metrics.false_positives == 0
    assert metrics.false_negatives == 0
