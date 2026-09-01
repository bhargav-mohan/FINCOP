from decimal import Decimal

from finance_controller.config import ReconConfig
from finance_controller.data.synthetic import generate
from finance_controller.reconciliation.engine import reconcile
from finance_controller.reporting.exposure import exception_exposure
from finance_controller.reporting.report import compute_cash


def test_in_flight_gross_equals_sum_of_exception_exposure():
    config = ReconConfig(seed=42, num_records=80, use_llm=False)
    batch = generate(config)
    result = reconcile(batch.all_records, config)
    by_id = {r.id: r for r in result.records}
    total = sum((exception_exposure(exc, by_id) for exc in result.exceptions), Decimal("0.00")).quantize(
        Decimal("0.01")
    )
    cash = compute_cash(result)
    assert cash.in_flight_gross == total
    assert cash.in_flight_count == len(result.exceptions)
