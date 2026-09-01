from finance_controller.config import ReconConfig
from finance_controller.data.synthetic import generate
from finance_controller.models import CaseCategory, ExceptionType, ExpectedStatus


def test_generator_is_deterministic():
    for seed in (1, 7, 42, 99):
        config = ReconConfig(seed=seed, num_records=60, inject_exceptions=12, inject_edges=0)
        a = generate(config)
        b = generate(config)
        assert [r.model_dump() for r in a.all_records] == [r.model_dump() for r in b.all_records]
        assert [g.model_dump() for g in a.ground_truth] == [g.model_dump() for g in b.ground_truth]


def test_batch_has_50_plus_records_and_injected_exceptions():
    config = ReconConfig(seed=7, num_records=60, inject_exceptions=12, inject_edges=0)
    batch = generate(config)
    assert len(batch.ledger) >= 1
    assert len(batch.bank) >= 1
    assert len(batch.psp) >= 1
    assert len(batch.all_records) >= 50
    exceptions = [g for g in batch.ground_truth if g.expected_status == ExpectedStatus.EXCEPTION]
    assert len(exceptions) >= 12
    types = {g.exception_type for g in exceptions}
    assert ExceptionType.MISSING_IN_BANK in types
    assert ExceptionType.AMOUNT_MISMATCH in types


def test_resolvable_ambiguous_category_is_present_and_distinct():
    config = ReconConfig(seed=42, num_records=60, inject_exceptions=12, inject_resolvable=6, inject_edges=0)
    batch = generate(config)
    resolvable = [g for g in batch.ground_truth if g.category == CaseCategory.RESOLVABLE_AMBIGUOUS]
    irresolvable = [g for g in batch.ground_truth if g.category == CaseCategory.IRRESOLVABLE]
    assert len(resolvable) == 6
    assert all(g.expected_status == ExpectedStatus.MATCHED for g in resolvable)
    assert irresolvable
    assert all(g.expected_status == ExpectedStatus.EXCEPTION for g in irresolvable)
    banks = {r.id: r for r in batch.bank}
    for g in resolvable:
        bank_rows = [banks[i] for i in g.record_ids if i in banks]
        assert bank_rows
        bank = bank_rows[0]
        assert bank.payee == ""
        assert g.key in bank.description
        assert not bank.reference.startswith("TXN-")
