from datetime import date
from decimal import Decimal

from finance_controller.config import ReconConfig
from finance_controller.models import Record, Source
from finance_controller.reconciliation.validate import validate_proposed_match


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


def test_validate_accepts_fee_net_trio():
    records = [
        _rec(id="L1", source=Source.LEDGER, reference="T1", amount=Decimal("100.00"), payee="ALICE"),
        _rec(id="P1", source=Source.PSP, reference="T1", amount=Decimal("100.00"), fee=Decimal("2.00"), payee="ALICE"),
        _rec(id="B1", source=Source.BANK, reference="T1", amount=Decimal("98.00"), txn_date=date(2026, 1, 11), payee="ALICE"),
    ]
    result = validate_proposed_match(records, ReconConfig(), set())
    assert result.valid


def test_validate_rejects_amount_break():
    records = [
        _rec(id="L1", source=Source.LEDGER, reference="T1", amount=Decimal("100.00"), payee="ALICE"),
        _rec(id="P1", source=Source.PSP, reference="T1", amount=Decimal("100.00"), fee=Decimal("2.00"), payee="ALICE"),
        _rec(id="B1", source=Source.BANK, reference="T1", amount=Decimal("113.00"), txn_date=date(2026, 1, 11), payee="ALICE"),
    ]
    result = validate_proposed_match(records, ReconConfig(), set())
    assert not result.valid


def test_validate_rejects_already_closed():
    records = [
        _rec(id="L1", source=Source.LEDGER, reference="T1", amount=Decimal("100.00"), payee="ALICE"),
        _rec(id="P1", source=Source.PSP, reference="T1", amount=Decimal("100.00"), fee=Decimal("2.00"), payee="ALICE"),
        _rec(id="B1", source=Source.BANK, reference="T1", amount=Decimal("98.00"), txn_date=date(2026, 1, 11), payee="ALICE"),
    ]
    result = validate_proposed_match(records, ReconConfig(), {"L1"})
    assert not result.valid
