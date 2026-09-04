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


def _traced(records):
    hits: list[str] = []

    def tracer(frame, event, arg):
        if event == "call" and frame.f_code.co_name in {
            "_block_close",
            "_gst_block",
            "_amounts_ok",
        }:
            hits.append(frame.f_code.co_name)
        return tracer

    import sys

    sys.settrace(tracer)
    try:
        result = validate_proposed_match(records, ReconConfig(), set())
    finally:
        sys.settrace(None)
    return result, hits


def test_validate_gst_date_amount_reuse_engine_close_gates():
    gst = [
        _rec(id="L1", source=Source.LEDGER, reference="T1", amount=Decimal("100.00"), payee="ALICE", gst=Decimal("50.00"), extra={"taxable": True}),
        _rec(id="P1", source=Source.PSP, reference="T1", amount=Decimal("100.00"), fee=Decimal("2.00"), payee="ALICE", gst=Decimal("50.00"), extra={"taxable": True}),
        _rec(id="B1", source=Source.BANK, reference="T1", amount=Decimal("98.00"), txn_date=date(2026, 1, 12), payee="ALICE"),
    ]
    late = [
        _rec(id="L1", source=Source.LEDGER, reference="T1", amount=Decimal("100.00"), payee="ALICE"),
        _rec(id="P1", source=Source.PSP, reference="T1", amount=Decimal("100.00"), fee=Decimal("2.00"), payee="ALICE"),
        _rec(id="B1", source=Source.BANK, reference="T1", amount=Decimal("98.00"), txn_date=date(2026, 1, 20), payee="ALICE"),
    ]
    amt = [
        _rec(id="L1", source=Source.LEDGER, reference="T1", amount=Decimal("100.00"), payee="ALICE"),
        _rec(id="P1", source=Source.PSP, reference="T1", amount=Decimal("100.00"), fee=Decimal("2.00"), payee="ALICE"),
        _rec(id="B1", source=Source.BANK, reference="T1", amount=Decimal("113.00"), txn_date=date(2026, 1, 12), payee="ALICE"),
    ]
    r_gst, h_gst = _traced(gst)
    r_date, h_date = _traced(late)
    r_amt, h_amt = _traced(amt)
    assert not r_gst.valid and "_block_close" in h_gst and "_gst_block" in h_gst
    assert not r_date.valid and "_block_close" in h_date
    assert not r_amt.valid and "_block_close" in h_amt and "_amounts_ok" in h_amt


def test_validate_rejects_already_closed():
    records = [
        _rec(id="L1", source=Source.LEDGER, reference="T1", amount=Decimal("100.00"), payee="ALICE"),
        _rec(id="P1", source=Source.PSP, reference="T1", amount=Decimal("100.00"), fee=Decimal("2.00"), payee="ALICE"),
        _rec(id="B1", source=Source.BANK, reference="T1", amount=Decimal("98.00"), txn_date=date(2026, 1, 11), payee="ALICE"),
    ]
    result = validate_proposed_match(records, ReconConfig(), {"L1"})
    assert not result.valid
