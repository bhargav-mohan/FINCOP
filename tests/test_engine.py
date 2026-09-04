import random
from datetime import date
from decimal import Decimal

from finance_controller.agent.orchestrator import orchestrate
from finance_controller.config import ReconConfig
from finance_controller.data.synthetic import generate
from finance_controller.models import ExceptionType, ExpectedStatus, Record, Source
from finance_controller.reconciliation.engine import EngineResult, reconcile
from finance_controller.reconciliation.matchers import exact_matches, many_to_one_matches, tolerant_matches


def _closed_groups(result: EngineResult) -> frozenset[frozenset[str]]:
    return frozenset(frozenset(m.record_ids) for m in result.closed_matches)


def _exception_groups(result: EngineResult) -> frozenset[tuple]:
    return frozenset(
        (exc.exception_id, exc.exception_type.value, tuple(exc.record_ids), exc.reason)
        for exc in result.exceptions
    )


def _match_ids(result: EngineResult) -> tuple[tuple[str, str, tuple[str, ...]], ...]:
    return tuple((m.match_id, m.tier.value, tuple(m.record_ids)) for m in result.matches)


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


def test_exact_matches_ledger_to_psp():
    records = [
        _rec(id="L1", source=Source.LEDGER, reference="TXN-1", amount=Decimal("100.00")),
        _rec(id="P1", source=Source.PSP, reference="TXN-1", amount=Decimal("100.00"), fee=Decimal("2.00")),
    ]
    used: set[str] = set()
    matches = exact_matches(records, used)
    assert len(matches) == 1
    assert set(matches[0].record_ids) == {"L1", "P1"}


def test_tolerant_matches_bank_net_of_fee():
    records = [
        _rec(id="P1", source=Source.PSP, reference="TXN-1", amount=Decimal("100.00"), fee=Decimal("2.00")),
        _rec(id="B1", source=Source.BANK, reference="TXN-1", amount=Decimal("98.00"), txn_date=date(2026, 1, 11)),
    ]
    used: set[str] = set()
    matches = tolerant_matches(records, used, ReconConfig())
    assert len(matches) == 1
    assert set(matches[0].record_ids) == {"P1", "B1"}


def test_many_to_one_sums_psp_nets():
    records = [
        _rec(id="P1", source=Source.PSP, reference="TXN-1", amount=Decimal("50.00"), fee=Decimal("1.00"), batch_id="BATCH-01"),
        _rec(id="P2", source=Source.PSP, reference="TXN-2", amount=Decimal("70.00"), fee=Decimal("1.40"), batch_id="BATCH-01"),
        _rec(
            id="B1",
            source=Source.BANK,
            reference="BATCH-01",
            amount=Decimal("117.60"),
            batch_id="BATCH-01",
            txn_date=date(2026, 1, 11),
        ),
    ]
    used: set[str] = set()
    matches = many_to_one_matches(records, used, ReconConfig())
    assert len(matches) == 1
    assert set(matches[0].record_ids) == {"P1", "P2", "B1"}


def test_many_to_one_claims_the_paired_ledger_rows():
    """The tier must claim the whole cash loop. With ledgers left out, the
    component fails is_closed_group's len(ledgers) == len(psps) check and the
    batch lands back on the exception queue."""
    records = [
        _rec(id="L1", source=Source.LEDGER, reference="TXN-1", amount=Decimal("50.00"), batch_id="BATCH-01"),
        _rec(id="L2", source=Source.LEDGER, reference="TXN-2", amount=Decimal("70.00"), batch_id="BATCH-01"),
        _rec(id="P1", source=Source.PSP, reference="TXN-1", amount=Decimal("50.00"), fee=Decimal("1.00"), batch_id="BATCH-01"),
        _rec(id="P2", source=Source.PSP, reference="TXN-2", amount=Decimal("70.00"), fee=Decimal("1.40"), batch_id="BATCH-01"),
        _rec(
            id="B1",
            source=Source.BANK,
            reference="BATCH-01",
            amount=Decimal("117.60"),
            batch_id="BATCH-01",
            txn_date=date(2026, 1, 11),
        ),
    ]
    used: set[str] = set()
    matches = many_to_one_matches(records, used, ReconConfig())
    assert len(matches) == 1
    assert set(matches[0].record_ids) == {"L1", "L2", "P1", "P2", "B1"}
    assert used == {"L1", "L2", "P1", "P2", "B1"}
    assert "ledger bookings" in matches[0].reason


def test_many_to_one_still_matches_when_a_ledger_booking_is_missing():
    """A missing ledger booking is a real exception, so the tier claims what it
    can and lets is_closed_group refuse the close."""
    records = [
        _rec(id="L1", source=Source.LEDGER, reference="TXN-1", amount=Decimal("50.00"), batch_id="BATCH-01"),
        _rec(id="P1", source=Source.PSP, reference="TXN-1", amount=Decimal("50.00"), fee=Decimal("1.00"), batch_id="BATCH-01"),
        _rec(id="P2", source=Source.PSP, reference="TXN-2", amount=Decimal("70.00"), fee=Decimal("1.40"), batch_id="BATCH-01"),
        _rec(
            id="B1",
            source=Source.BANK,
            reference="BATCH-01",
            amount=Decimal("117.60"),
            batch_id="BATCH-01",
            txn_date=date(2026, 1, 11),
        ),
    ]
    matches = many_to_one_matches(records, set(), ReconConfig())
    assert len(matches) == 1
    assert set(matches[0].record_ids) == {"L1", "P1", "P2", "B1"}
    result = reconcile(records, ReconConfig())
    assert result.closed_group_count == 0
    assert result.exceptions


def test_many_to_one_does_not_reuse_psp_across_banks():
    records = [
        _rec(id="P1", source=Source.PSP, reference="TXN-1", amount=Decimal("50.00"), fee=Decimal("1.00"), batch_id="BATCH-01"),
        _rec(id="P2", source=Source.PSP, reference="TXN-2", amount=Decimal("70.00"), fee=Decimal("1.40"), batch_id="BATCH-01"),
        _rec(id="B1", source=Source.BANK, reference="BATCH-01", amount=Decimal("117.60"), batch_id="BATCH-01", txn_date=date(2026, 1, 11)),
        _rec(id="B2", source=Source.BANK, reference="BATCH-01b", amount=Decimal("117.60"), batch_id="BATCH-01", txn_date=date(2026, 1, 11)),
    ]
    used: set[str] = set()
    matches = many_to_one_matches(records, used, ReconConfig())
    assert len(matches) == 1
    assert "B1" in matches[0].record_ids
    assert "B2" not in matches[0].record_ids
    assert used == {"P1", "P2", "B1"}


def test_amount_mismatch_is_not_matched():
    records = [
        _rec(id="L1", source=Source.LEDGER, reference="TXN-1", amount=Decimal("100.00")),
        _rec(id="P1", source=Source.PSP, reference="TXN-1", amount=Decimal("100.00"), fee=Decimal("2.00")),
        _rec(id="B1", source=Source.BANK, reference="TXN-1", amount=Decimal("113.00"), txn_date=date(2026, 1, 11)),
    ]
    result = reconcile(records, ReconConfig())
    assert result.closed_group_count == 0
    mismatch = next(e for e in result.exceptions if e.exception_type == ExceptionType.AMOUNT_MISMATCH)
    assert "expected net" in mismatch.reason
    assert "98.00" in mismatch.reason


def test_engine_on_seeded_batch_reports_exceptions():
    config = ReconConfig(seed=42, num_records=60, inject_exceptions=12, inject_edges=0)
    batch = generate(config)
    result = reconcile(batch.all_records, config)
    assert result.closed_group_count >= 1
    assert result.exceptions
    expected_exc = {g.key for g in batch.ground_truth if g.expected_status == ExpectedStatus.EXCEPTION}
    assert expected_exc
    from finance_controller.reconciliation.engine import predicted_exception_keys

    predicted = predicted_exception_keys(result)
    assert expected_exc - predicted == set()


def test_engine_closes_unique_narration_identity():
    from finance_controller.models import CaseCategory

    config = ReconConfig(seed=42, num_records=60, inject_exceptions=12, inject_resolvable=6, inject_edges=0)
    batch = generate(config)
    result = reconcile(batch.all_records, config)
    keys = {g.key for g in batch.ground_truth if g.category == CaseCategory.RESOLVABLE_AMBIGUOUS}
    assert len(keys) == 6
    assert keys <= result.closed_keys


def test_same_amount_different_payees_are_not_fcfs():
    payees = ("ALICE", "BOB", "CAROL")
    records: list[Record] = []
    for i, payee in enumerate(payees, start=1):
        records.extend(
            [
                _rec(
                    id=f"L{i}",
                    source=Source.LEDGER,
                    reference="PMT",
                    amount=Decimal("100.00"),
                    payee=payee,
                ),
                _rec(
                    id=f"P{i}",
                    source=Source.PSP,
                    reference="PMT",
                    amount=Decimal("100.00"),
                    fee=Decimal("2.00"),
                    payee=payee,
                ),
                _rec(
                    id=f"B{i}",
                    source=Source.BANK,
                    reference="PMT",
                    amount=Decimal("98.00"),
                    txn_date=date(2026, 1, 11),
                    payee=payee,
                ),
            ]
        )
    result = reconcile(records, ReconConfig())
    assert result.closed_group_count == 3
    by_id = {r.id: r for r in result.records}
    for match in result.closed_matches:
        payees_in_match = {by_id[rid].payee for rid in match.record_ids}
        assert len(payees_in_match) == 1


def test_same_amount_same_payee_is_ambiguous_not_fcfs():
    records = []
    for i in (1, 2):
        records.extend(
            [
                _rec(
                    id=f"L{i}",
                    source=Source.LEDGER,
                    reference="PMT",
                    amount=Decimal("100.00"),
                    payee="ALICE",
                ),
                _rec(
                    id=f"P{i}",
                    source=Source.PSP,
                    reference="PMT",
                    amount=Decimal("100.00"),
                    fee=Decimal("2.00"),
                    payee="ALICE",
                ),
                _rec(
                    id=f"B{i}",
                    source=Source.BANK,
                    reference="PMT",
                    amount=Decimal("98.00"),
                    txn_date=date(2026, 1, 11),
                    payee="ALICE",
                ),
            ]
        )
    used: set[str] = set()
    exact = exact_matches(records, used)
    assert exact == []
    tolerant = tolerant_matches(records, used, ReconConfig())
    assert tolerant == []


def test_same_seed_run_twice_yields_identical_groupings():
    """Reproducibility is groupings, not just counts. Same seed must replay
    closed groups, leftover groups, and match ids — not merely match_rate."""
    config = ReconConfig(
        seed=42, num_records=80, inject_exceptions=12, inject_resolvable=6, inject_edges=16, use_llm=False
    )
    first = generate(config)
    second = generate(config)
    a = reconcile(first.all_records, config)
    b = reconcile(second.all_records, config)
    assert _closed_groups(a) == _closed_groups(b)
    assert _exception_groups(a) == _exception_groups(b)
    assert _match_ids(a) == _match_ids(b)
    assert a.closed_record_ids == b.closed_record_ids
    assert a.closed_keys == b.closed_keys
    assert a.closed_group_count == b.closed_group_count

    orchestrate(a, config)
    orchestrate(b, config)
    assert _closed_groups(a) == _closed_groups(b)
    assert _exception_groups(a) == _exception_groups(b)
    assert a.closed_record_ids == b.closed_record_ids


def test_shuffled_input_yields_identical_groupings():
    """Tier priority is fixed (M→E→T→S) and pairing is unique-or-drop.
    Shuffling the list must not change who closed with whom — only match
    emission ids may move. If this fails, claiming has become input-order greedy."""
    config = ReconConfig(
        seed=7, num_records=80, inject_exceptions=12, inject_resolvable=6, inject_edges=16, use_llm=False
    )
    batch = generate(config)
    baseline = reconcile(batch.all_records, config)
    shuffled = list(batch.all_records)
    random.Random(0).shuffle(shuffled)
    other = reconcile(shuffled, config)
    assert _closed_groups(baseline) == _closed_groups(other)
    assert _exception_groups(baseline) == _exception_groups(other)
    assert baseline.closed_record_ids == other.closed_record_ids
    assert baseline.closed_keys == other.closed_keys
    assert baseline.closed_group_count == other.closed_group_count
