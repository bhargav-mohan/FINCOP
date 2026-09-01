from decimal import Decimal

from finance_controller.razorpay.adapter import razorpay_recon_to_canonical
from finance_controller.razorpay.schema import paise_to_decimal, parse_razorpay_amount


def test_paise_to_decimal():
    assert paise_to_decimal(100000) == Decimal("1000.00")
    assert paise_to_decimal("97100") == Decimal("971.00")
    assert parse_razorpay_amount("1000.50") == Decimal("1000.50")
    assert parse_razorpay_amount("") == Decimal("0.00")


def _pay(**overrides) -> dict[str, str]:
    row = {
        "entity_id": "pay_AAA",
        "type": "payment",
        "payment_id": "pay_AAA",
        "order_id": "order_AAA",
        "amount": "100000",
        "fee": "2360",
        "tax": "360",
        "debit": "0",
        "credit": "97640",
        "currency": "INR",
        "settlement_id": "setl_ONE",
        "settlement_utr": "UTR0001",
        "created_at": "1767600000",
        "settled_at": "1767772800",
        "method": "card",
        "settled": "true",
        "notes": "ACME",
    }
    row.update(overrides)
    return row


def test_recon_explodes_to_canonical_and_groups_by_settlement_id():
    rows = [
        _pay(),
        _pay(
            entity_id="pay_BBB",
            payment_id="pay_BBB",
            order_id="order_BBB",
            amount="50000",
            fee="1180",
            tax="180",
            credit="48820",
        ),
    ]
    adapted = razorpay_recon_to_canonical(rows)
    assert len(adapted.payments) == 2
    assert len(adapted.settlements) == 1
    stl = adapted.settlements[0]
    assert stl["settlement_id"] == "setl_ONE"
    assert set(stl["payment_ids"].split("|")) == {"pay_AAA", "pay_BBB"}
    assert stl["gross_amount"] == "1500.00"
    assert stl["mdr_fee"] == "30.00"
    assert stl["gst_on_fee"] == "5.40"
    assert stl["net_amount"] == "1464.60"
    assert stl["utr"] == "UTR0001"
    assert len(adapted.bank) == 1
    assert adapted.bank[0]["utr"] == "UTR0001"
    assert adapted.bank[0]["credited_amount"] == "1464.60"
    assert adapted.batch.psp[0].extra["settlement_id"] == "setl_ONE"
    assert adapted.batch.psp[0].batch_id == "setl_ONE"
    assert adapted.batch.bank[0].batch_id == "setl_ONE"


def test_adjustment_and_transfer_become_warnings():
    rows = [
        _pay(),
        _pay(entity_id="adj_1", type="adjustment", payment_id="pay_ADJ"),
        _pay(entity_id="trf_1", type="transfer", payment_id="pay_TRF"),
    ]
    adapted = razorpay_recon_to_canonical(rows)
    assert len(adapted.payments) == 1
    kinds = " ".join(adapted.warnings)
    assert "adjustment" in kinds
    assert "transfer" in kinds


def test_unsettled_row_skips_bank_credit():
    adapted = razorpay_recon_to_canonical([_pay(settled="false")])
    assert adapted.bank == []
    assert any("not settled" in w for w in adapted.warnings)
