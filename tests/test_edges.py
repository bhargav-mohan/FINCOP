from datetime import date
from decimal import Decimal

from finance_controller.cli import parse_args, run
from finance_controller.config import ReconConfig
from finance_controller.data.synthetic import generate
from finance_controller.models import ExceptionType, ExpectedStatus, MatchTier, PaymentStatus, Record, Source
from finance_controller.reconciliation.dates import banking_days_between
from finance_controller.reconciliation.engine import predicted_exception_keys, reconcile
from finance_controller.reconciliation.gst import gst_bankers, gst_half_up
from finance_controller.reconciliation.matchers import one_to_many_matches
from finance_controller.reporting.report import compute_accuracy, compute_cash


def _rec(**kwargs) -> Record:
    base = dict(
        fee=Decimal("0.00"),
        description="",
        payee="",
        batch_id=None,
        txn_date=date(2026, 1, 10),
        currency="INR",
    )
    base.update(kwargs)
    return Record(**base)


def test_one_to_many_split_credits():
    records = [
        _rec(id="P1", source=Source.PSP, reference="TXN-1", amount=Decimal("100.00"), fee=Decimal("2.00"), split_id="S1"),
        _rec(id="B1", source=Source.BANK, reference="TXN-1", amount=Decimal("40.00"), split_id="S1", txn_date=date(2026, 1, 11)),
        _rec(id="B2", source=Source.BANK, reference="TXN-1", amount=Decimal("58.00"), split_id="S1", txn_date=date(2026, 1, 11)),
    ]
    used: set[str] = set()
    matches = one_to_many_matches(records, used, ReconConfig())
    assert len(matches) == 1
    assert matches[0].tier == MatchTier.ONE_TO_MANY
    assert set(matches[0].record_ids) == {"P1", "B1", "B2"}


def test_split_closes_with_ledger():
    records = [
        _rec(id="L1", source=Source.LEDGER, reference="TXN-1", amount=Decimal("100.00"), split_id="S1"),
        _rec(id="P1", source=Source.PSP, reference="TXN-1", amount=Decimal("100.00"), fee=Decimal("2.00"), split_id="S1"),
        _rec(id="B1", source=Source.BANK, reference="TXN-1", amount=Decimal("40.00"), split_id="S1", txn_date=date(2026, 1, 11)),
        _rec(id="B2", source=Source.BANK, reference="TXN-1", amount=Decimal("58.00"), split_id="S1", txn_date=date(2026, 1, 11)),
    ]
    result = reconcile(records, ReconConfig())
    assert result.closed_group_count == 1


def test_split_early_credit_does_not_close():
    records = [
        _rec(id="L1", source=Source.LEDGER, reference="TXN-1", amount=Decimal("100.00"), split_id="S1", txn_date=date(2026, 1, 10)),
        _rec(id="P1", source=Source.PSP, reference="TXN-1", amount=Decimal("100.00"), fee=Decimal("2.00"), split_id="S1", txn_date=date(2026, 1, 10)),
        _rec(id="B1", source=Source.BANK, reference="TXN-1", amount=Decimal("40.00"), split_id="S1", txn_date=date(2026, 1, 8)),
        _rec(id="B2", source=Source.BANK, reference="TXN-1", amount=Decimal("58.00"), split_id="S1", txn_date=date(2026, 1, 11)),
    ]
    result = reconcile(records, ReconConfig())
    assert result.closed_group_count == 0
    assert any(e.exception_type == ExceptionType.DATE_INVERTED for e in result.exceptions)


def test_zero_and_negative_net_do_not_close():
    records = [
        _rec(id="L1", source=Source.LEDGER, reference="Z", amount=Decimal("100.00")),
        _rec(id="P1", source=Source.PSP, reference="Z", amount=Decimal("100.00"), fee=Decimal("100.00")),
        _rec(id="B1", source=Source.BANK, reference="Z", amount=Decimal("0.00"), extra={"refund": True}),
        _rec(id="L2", source=Source.LEDGER, reference="N", amount=Decimal("100.00")),
        _rec(id="P2", source=Source.PSP, reference="N", amount=Decimal("100.00"), fee=Decimal("2.00")),
        _rec(id="B2", source=Source.BANK, reference="N", amount=Decimal("-10.00"), extra={"chargeback": True}),
    ]
    result = reconcile(records, ReconConfig())
    assert result.closed_group_count == 0
    types = {e.exception_type for e in result.exceptions}
    assert ExceptionType.ZERO_OR_NEGATIVE_NET in types


def test_partial_refund_classified():
    records = [
        _rec(id="L1", source=Source.LEDGER, reference="T", amount=Decimal("100.00")),
        _rec(id="P1", source=Source.PSP, reference="T", amount=Decimal("100.00"), fee=Decimal("2.00")),
        _rec(id="B1", source=Source.BANK, reference="T", amount=Decimal("40.00"), extra={"refund": True}),
    ]
    result = reconcile(records, ReconConfig())
    assert any(e.exception_type == ExceptionType.PARTIAL_REFUND for e in result.exceptions)


def test_failed_status_is_not_matched():
    records = [
        _rec(id="L1", source=Source.LEDGER, reference="T", amount=Decimal("100.00")),
        _rec(id="P1", source=Source.PSP, reference="T", amount=Decimal("100.00"), fee=Decimal("2.00"), status=PaymentStatus.FAILED),
        _rec(id="B1", source=Source.BANK, reference="T", amount=Decimal("98.00"), txn_date=date(2026, 1, 11)),
    ]
    result = reconcile(records, ReconConfig())
    assert result.closed_group_count == 0
    assert any(e.exception_type == ExceptionType.STATUS_MISMATCH for e in result.exceptions)


def test_friday_to_monday_is_one_banking_day():
    holidays = ReconConfig().holidays
    assert banking_days_between(date(2026, 1, 9), date(2026, 1, 12), holidays) == 1
    records = [
        _rec(id="L1", source=Source.LEDGER, reference="T", amount=Decimal("100.00"), txn_date=date(2026, 1, 9)),
        _rec(id="P1", source=Source.PSP, reference="T", amount=Decimal("100.00"), fee=Decimal("2.00"), txn_date=date(2026, 1, 9)),
        _rec(id="B1", source=Source.BANK, reference="T", amount=Decimal("98.00"), txn_date=date(2026, 1, 12)),
    ]
    result = reconcile(records, ReconConfig())
    assert result.closed_group_count == 1


def test_t0_same_day_closes():
    records = [
        _rec(id="L1", source=Source.LEDGER, reference="T", amount=Decimal("100.00"), txn_date=date(2026, 1, 9)),
        _rec(id="P1", source=Source.PSP, reference="T", amount=Decimal("100.00"), fee=Decimal("2.00"), txn_date=date(2026, 1, 9)),
        _rec(id="B1", source=Source.BANK, reference="T", amount=Decimal("98.00"), txn_date=date(2026, 1, 9)),
    ]
    result = reconcile(records, ReconConfig())
    assert result.closed_group_count == 1


def test_late_and_inverted_dates_are_exceptions():
    late = [
        _rec(id="L1", source=Source.LEDGER, reference="LATE", amount=Decimal("100.00"), txn_date=date(2026, 1, 7)),
        _rec(id="P1", source=Source.PSP, reference="LATE", amount=Decimal("100.00"), fee=Decimal("2.00"), txn_date=date(2026, 1, 7)),
        _rec(id="B1", source=Source.BANK, reference="LATE", amount=Decimal("98.00"), txn_date=date(2026, 1, 17)),
    ]
    inv = [
        _rec(id="L2", source=Source.LEDGER, reference="INV", amount=Decimal("50.00"), txn_date=date(2026, 1, 10)),
        _rec(id="P2", source=Source.PSP, reference="INV", amount=Decimal("50.00"), fee=Decimal("1.00"), txn_date=date(2026, 1, 10)),
        _rec(id="B2", source=Source.BANK, reference="INV", amount=Decimal("49.00"), txn_date=date(2026, 1, 8)),
    ]
    result = reconcile(late + inv, ReconConfig())
    types = {e.exception_type for e in result.exceptions}
    assert ExceptionType.LATE_SETTLEMENT in types
    assert ExceptionType.DATE_INVERTED in types


def test_gst_half_up_vs_bankers_and_zero_bug():
    gross = Decimal("10.05")
    assert gst_half_up(gross) == Decimal("1.81")
    assert gst_bankers(gross) == Decimal("1.81")
    split = Decimal("10.25")
    assert gst_half_up(split) == Decimal("1.85")
    assert gst_bankers(split) == Decimal("1.84")
    ok = [
        _rec(id="L1", source=Source.LEDGER, reference="G", amount=Decimal("100.00"), gst=gst_bankers(Decimal("100.00"))),
        _rec(id="P1", source=Source.PSP, reference="G", amount=Decimal("100.00"), fee=Decimal("2.00"), gst=gst_bankers(Decimal("100.00"))),
        _rec(id="B1", source=Source.BANK, reference="G", amount=Decimal("98.00"), txn_date=date(2026, 1, 11)),
    ]
    bug = [
        _rec(id="L2", source=Source.LEDGER, reference="Z", amount=Decimal("100.00"), gst=Decimal("0.00"), extra={"gst_zero_bug": True, "taxable": True}),
        _rec(id="P2", source=Source.PSP, reference="Z", amount=Decimal("100.00"), fee=Decimal("2.00"), gst=Decimal("0.00"), extra={"gst_zero_bug": True, "taxable": True}),
        _rec(id="B2", source=Source.BANK, reference="Z", amount=Decimal("98.00"), txn_date=date(2026, 1, 11)),
    ]
    result = reconcile(ok + bug, ReconConfig())
    assert "G" in result.closed_keys
    assert any(e.exception_type == ExceptionType.GST_ZERO_BUG for e in result.exceptions)


def test_empty_and_malformed_utr():
    records = [
        _rec(id="L1", source=Source.LEDGER, reference="E", amount=Decimal("100.00")),
        _rec(id="P1", source=Source.PSP, reference="E", amount=Decimal("100.00"), fee=Decimal("2.00")),
        _rec(id="B1", source=Source.BANK, reference="E", amount=Decimal("98.00"), utr="", extra={"empty_utr": True, "expect_utr": True}),
        _rec(id="L2", source=Source.LEDGER, reference="M", amount=Decimal("80.00")),
        _rec(id="P2", source=Source.PSP, reference="M", amount=Decimal("80.00"), fee=Decimal("1.60")),
        _rec(id="B2", source=Source.BANK, reference="M", amount=Decimal("78.40"), utr="!!", extra={"malformed_utr": True}),
    ]
    result = reconcile(records, ReconConfig())
    types = {e.exception_type for e in result.exceptions}
    assert ExceptionType.EMPTY_UTR in types
    assert ExceptionType.MALFORMED_UTR in types


def test_same_amount_different_utr_does_not_steal():
    records = [
        _rec(id="L1", source=Source.LEDGER, reference="TXN-1", amount=Decimal("100.00"), payee="ACME"),
        _rec(id="P1", source=Source.PSP, reference="TXN-1", amount=Decimal("100.00"), fee=Decimal("2.00"), payee="ACME"),
        _rec(id="B1", source=Source.BANK, reference="TXN-1", amount=Decimal("98.00"), utr="UTR0000000000001", payee="ACME", txn_date=date(2026, 1, 11)),
        _rec(id="B2", source=Source.BANK, reference="UNK-TXN-1", amount=Decimal("98.00"), utr="UTR9999999999999", extra={"orphan": True}, txn_date=date(2026, 1, 11)),
    ]
    result = reconcile(records, ReconConfig())
    assert "TXN-1" in result.closed_keys
    assert any(e.exception_type == ExceptionType.UNMATCHED for e in result.exceptions)


def test_empty_batch_is_zero_not_crash():
    result = reconcile([], ReconConfig())
    assert result.closed_group_count == 0
    assert result.exceptions == []


def test_cli_rejects_under_50(tmp_path):
    args = parse_args(["--num-records", "49", "--out", str(tmp_path / "r")])
    config = ReconConfig(seed=args.seed, num_records=args.num_records, inject_exceptions=args.inject_exceptions)
    assert run(config, args.out) == 2


def test_multi_seed_exception_f1():
    for seed in (1, 7, 42, 99):
        config = ReconConfig(seed=seed, num_records=60, inject_exceptions=12, inject_resolvable=0, inject_edges=0)
        batch = generate(config)
        result = reconcile(batch.all_records, config)
        metrics = compute_accuracy(batch.ground_truth, result)
        assert metrics.recall == 1.0, seed
        assert metrics.false_negatives == 0, seed


def test_large_batch_smoke():
    config = ReconConfig(seed=3, num_records=200, inject_exceptions=20, inject_resolvable=0, inject_edges=0)
    batch = generate(config)
    result = reconcile(batch.all_records, config)
    assert len(batch.all_records) >= 50
    assert result.closed_group_count >= 1
    cash = compute_cash(result)
    assert cash.in_flight_count == len(result.exceptions)
    assert cash.negative is (cash.closed_bank_net < 0)


def test_injected_edges_are_labeled():
    config = ReconConfig(seed=42, num_records=80, inject_exceptions=12, inject_resolvable=0, inject_edges=16)
    batch = generate(config)
    kinds = {g.exception_type for g in batch.ground_truth if g.exception_type}
    assert ExceptionType.PARTIAL_REFUND in kinds
    assert ExceptionType.GST_ZERO_BUG in kinds
    result = reconcile(batch.all_records, config)
    predicted = predicted_exception_keys(result)
    actual = {g.key for g in batch.ground_truth if g.expected_status == ExpectedStatus.EXCEPTION}
    assert actual
    assert actual - predicted == set()
