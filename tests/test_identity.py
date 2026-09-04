from datetime import date
from decimal import Decimal

from finance_controller.config import ReconConfig
from finance_controller.ingestion.detect import FileRole
from finance_controller.ingestion.normalize import remap_row
from finance_controller.models import Record, Source
from finance_controller.reconciliation.engine import reconcile
from finance_controller.reconciliation.identity import canonical_payee, compact_reference, payee_key
from finance_controller.reconciliation.narration import enrich_from_narration, memo_compacts
from finance_controller.tax_matching.match import match_tax_lines
from finance_controller.tax_matching.models import TaxLine


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


def _loop(prefix: str, *, ledger_ref: str, bank_ref: str, payee: str, bank_payee: str = "", desc: str = ""):
    return [
        _rec(id=f"L-{prefix}", source=Source.LEDGER, reference=ledger_ref, amount=Decimal("100.00"), payee=payee),
        _rec(
            id=f"P-{prefix}",
            source=Source.PSP,
            reference=ledger_ref,
            amount=Decimal("100.00"),
            fee=Decimal("2.00"),
            payee=payee,
        ),
        _rec(
            id=f"B-{prefix}",
            source=Source.BANK,
            reference=bank_ref,
            amount=Decimal("98.00"),
            payee=bank_payee,
            description=desc,
            txn_date=date(2026, 1, 11),
        ),
    ]


def test_compact_reference_ignores_separators():
    assert compact_reference("PAY-0001") == compact_reference("pay 0001") == compact_reference("PAY_0001")
    assert compact_reference("PAY1") != compact_reference("PAY12")


def test_canonical_payee_strips_legal_suffixes():
    assert canonical_payee("Acme Pvt. Ltd.") == "ACME"
    assert canonical_payee("ACME PRIVATE LIMITED") == "ACME"
    assert canonical_payee("The ACME Co") == "ACME"
    assert payee_key("Acme Pvt Ltd") == payee_key("ACME PRIVATE LIMITED")


def test_inconsistent_refs_close_when_compact_form_is_unique():
    result = reconcile(_loop("a", ledger_ref="PAY-0001", bank_ref="PAY 0001", payee="ACME"), ReconConfig())
    assert result.closed_group_count == 1
    assert "PAY-0001" in result.closed_keys


def test_unstructured_bank_memo_recovers_unique_payment_id():
    records = _loop(
        "a",
        ledger_ref="TXN-0042",
        bank_ref="NEFT-9999",
        payee="ACME",
        desc="NEFT CR HDFC payout ACME TXN-0042",
    )
    enriched = enrich_from_narration(records)
    bank = next(r for r in enriched if r.source == Source.BANK)
    assert bank.reference == "TXN-0042"
    assert bank.extra.get("ref_from_narration")
    result = reconcile(records, ReconConfig())
    assert result.closed_group_count == 1
    assert "TXN-0042" in result.closed_keys


def test_memo_does_not_substring_match_similar_refs():
    assert "PAY1" not in memo_compacts("NEFT PAY12 ACME")
    records = [
        *_loop("a", ledger_ref="PAY1", bank_ref="NEFT-A", payee="ACME", desc="NEFT CR PAY12 decoy"),
        *_loop("b", ledger_ref="PAY12", bank_ref="PAY12", payee="BETA"),
    ]
    bank_a = next(r for r in enrich_from_narration(records) if r.id == "B-a")
    assert bank_a.reference != "PAY1"


def test_column_aliases_map_messy_headers():
    bank = remap_row(
        FileRole.BANK,
        {"Narration": "NEFT CR ACME", "Credit": "98.00", "Value Date": "2026-01-11", "Sender Name": "Acme", "UTR No": "UTR0000000001"},
    )
    assert bank["raw_description"] == "NEFT CR ACME"
    assert bank["credited_amount"] == "98.00"
    assert bank["credited_date"] == "2026-01-11"
    assert bank["customer"] == "Acme"
    assert bank["utr"] == "UTR0000000001"
    ledger = remap_row(FileRole.LEDGER, {"Order ID": "PAY-1", "Gross": "100", "Buyer": "Acme", "Invoice Date": "2026-01-10"})
    assert ledger["payment_id"] == "PAY-1"
    assert ledger["customer"] == "Acme"


def test_same_amount_different_payees_still_close_to_the_right_name():
    records = [
        *_loop("a", ledger_ref="PMT", bank_ref="PMT", payee="ALICE", bank_payee="ALICE"),
        *_loop("b", ledger_ref="PMT", bank_ref="PMT", payee="BOB", bank_payee="BOB"),
    ]
    result = reconcile(records, ReconConfig())
    assert result.closed_group_count == 2
    by_id = {r.id: r for r in result.records}
    for match in result.closed_matches:
        names = {payee_key(by_id[rid]) for rid in match.record_ids}
        assert len(names) == 1


def test_same_amount_same_payee_stays_on_the_queue():
    records = [
        *_loop("a", ledger_ref="PMT", bank_ref="PMT", payee="ALICE"),
        *_loop("b", ledger_ref="PMT", bank_ref="PMT", payee="ALICE"),
    ]
    result = reconcile(records, ReconConfig())
    assert result.closed_group_count == 0
    assert result.exceptions


def test_legal_name_variants_close():
    records = _loop(
        "a",
        ledger_ref="T1",
        bank_ref="NEFT-X",
        payee="Acme Pvt Ltd",
        bank_payee="ACME PRIVATE LIMITED",
    )
    result = reconcile(records, ReconConfig())
    assert result.closed_group_count == 1


def test_contained_and_similar_names_close_when_unique():
    records = _loop(
        "a",
        ledger_ref="NEFT-L",
        bank_ref="NEFT-B",
        payee="ACME RETAIL",
        bank_payee="Acme Retail India",
    )
    result = reconcile(records, ReconConfig())
    assert result.closed_group_count == 1


def test_similar_name_collision_stays_on_the_queue():
    records = [
        *_loop("a", ledger_ref="A", bank_ref="BA", payee="ACME RETAIL", bank_payee="ACME"),
        *_loop("b", ledger_ref="B", bank_ref="BB", payee="ACME INDIA", bank_payee="ACME"),
    ]
    result = reconcile(records, ReconConfig())
    assert result.closed_group_count == 0
    assert result.exceptions


def test_invoice_with_two_equal_ledgers_stays_ambiguous():
    tax = TaxLine(
        id="T1",
        invoice_id="",
        payment_id="PAY-0001",
        taxable_value=Decimal("100.00"),
        gst_rate=Decimal("0.18"),
        gst_amount=Decimal("18.00"),
    )
    ledgers = [
        _rec(id="L1", source=Source.LEDGER, reference="PAY0001", amount=Decimal("100.00"), payee="ACME"),
        _rec(id="L2", source=Source.LEDGER, reference="PAY0001", amount=Decimal("100.00"), payee="ACME"),
    ]
    report = match_tax_lines([tax], ledgers, ReconConfig())
    assert report.matches == []
    assert report.ambiguous


def test_invoice_picks_the_unique_amount_among_plausible_ledgers():
    tax = TaxLine(
        id="T1",
        invoice_id="",
        payment_id="PAY-0001",
        taxable_value=Decimal("250.00"),
        gst_rate=Decimal("0.18"),
        gst_amount=Decimal("45.00"),
    )
    ledgers = [
        _rec(id="L1", source=Source.LEDGER, reference="PAY0001", amount=Decimal("100.00"), payee="ACME"),
        _rec(id="L2", source=Source.LEDGER, reference="PAY0001", amount=Decimal("250.00"), payee="ACME"),
    ]
    report = match_tax_lines([tax], ledgers, ReconConfig())
    assert len(report.matches) == 1
    assert report.matches[0].ledger_id == "L2"
    assert report.ambiguous == []


def test_alt_id_order_id_joins_when_payment_id_differs():
    records = [
        _rec(
            id="L1",
            source=Source.LEDGER,
            reference="pay_abc",
            amount=Decimal("100.00"),
            payee="ACME",
            extra={"order_id": "order_99"},
        ),
        _rec(
            id="P1",
            source=Source.PSP,
            reference="pay_abc",
            amount=Decimal("100.00"),
            fee=Decimal("2.00"),
            payee="ACME",
        ),
        _rec(
            id="B1",
            source=Source.BANK,
            reference="order_99",
            amount=Decimal("98.00"),
            payee="ACME",
            txn_date=date(2026, 1, 11),
        ),
    ]
    result = reconcile(records, ReconConfig())
    assert result.closed_group_count == 1
