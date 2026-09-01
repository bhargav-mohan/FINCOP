from datetime import date
from decimal import Decimal
from pathlib import Path
import zipfile

from finance_controller.config import ReconConfig
from finance_controller.ingestion.detect import FileRole, detect_role
from finance_controller.ingestion.pipeline import ingest_zip
from finance_controller.ingestion.zipfile_extract import IngestError
from finance_controller.models import Record, Source
from finance_controller.run_finance_controller import run_finance_controller
from finance_controller.tax_matching.match import match_tax_lines
from finance_controller.tax_matching.models import TaxLine
from finance_controller.tax_matching.validate import validate_tax_match
import pytest


def _ledger(**kwargs) -> Record:
    base = dict(
        id="L1",
        source=Source.LEDGER,
        reference="PAY0001",
        amount=Decimal("100.00"),
        currency="INR",
        txn_date=date(2026, 6, 1),
        payee="ACME",
    )
    base.update(kwargs)
    return Record(**base)


def test_detect_role_from_headers_and_name():
    assert detect_role("neft_credits.csv", ["utr", "credited_amount", "credited_date"]) == FileRole.BANK
    assert detect_role("payments.csv", ["payment_id", "amount", "customer"]) == FileRole.LEDGER
    assert detect_role("settlements.csv", ["settlement_id", "payment_ids", "gross_amount"]) == FileRole.PSP
    assert detect_role("gstr.csv", ["invoice_id", "taxable_value", "gst_amount"]) == FileRole.TAX


def test_ingest_directory_of_csvs(tmp_path: Path, csv_fixture_dir: Path):
    src = csv_fixture_dir
    dest = tmp_path / "upload"
    dest.mkdir()
    for name in ("payments.csv", "settlements.csv", "bank.csv", "ground_truth.json"):
        (dest / name).write_bytes((src / name).read_bytes())
    ingested = ingest_zip(dest, work_dir=tmp_path / "out")
    assert len(ingested.batch.ledger) >= 50
    assert ingested.files["ledger"] == "payments.csv"
    payload = run_finance_controller(zip_path=str(dest), use_llm=False)
    assert payload.get("error") is None
    assert payload["num_records"] >= 50


def test_ingest_zip_runs_controller(tmp_path: Path, csv_fixture_dir: Path):
    src = csv_fixture_dir
    zpath = tmp_path / "batch.zip"
    with zipfile.ZipFile(zpath, "w") as zf:
        for name in ("payments.csv", "settlements.csv", "bank.csv", "ground_truth.json"):
            zf.write(src / name, name)
        zf.writestr(
            "tax.csv",
            "invoice_id,payment_id,taxable_value,gst_rate,gst_amount,hsn\n"
            "INV-1,PAY0001,100.00,0.18,18.00,9983\n",
        )
    ingested = ingest_zip(zpath, work_dir=tmp_path / "out")
    assert ingested.batch.ledger
    assert ingested.batch.bank
    assert ingested.batch.psp
    assert ingested.tax_lines
    payload = run_finance_controller(zip_path=str(zpath), use_llm=False)
    assert payload["exception_count"] == len(payload["exceptions"])
    assert payload["ingestion"]["files"]
    assert payload["tax"] is not None


def test_ingest_rejects_incomplete_zip(tmp_path: Path):
    zpath = tmp_path / "bad.zip"
    with zipfile.ZipFile(zpath, "w") as zf:
        zf.writestr("bank.csv", "utr,credited_amount,credited_date,raw_description\nU,1,2026-01-01,x\n")
    with pytest.raises(IngestError):
        ingest_zip(zpath, work_dir=tmp_path / "out")


def test_tax_line_unique_match_and_rounding():
    tax = TaxLine(
        id="T1",
        invoice_id="INV",
        payment_id="PAY0001",
        taxable_value=Decimal("100.00"),
        gst_rate=Decimal("0.18"),
        gst_amount=Decimal("18.00"),
    )
    ledger = _ledger()
    config = ReconConfig()
    assert validate_tax_match(tax, ledger, config).valid
    report = match_tax_lines([tax], [ledger], config)
    assert len(report.matches) == 1
    assert report.exceptions == []


def test_tax_line_gst_mismatch_is_not_closed():
    tax = TaxLine(
        id="T1",
        invoice_id="INV",
        payment_id="PAY0001",
        taxable_value=Decimal("100.00"),
        gst_rate=Decimal("0.18"),
        gst_amount=Decimal("9.00"),
    )
    report = match_tax_lines([tax], [_ledger()], ReconConfig())
    assert report.matches == []
    assert report.exceptions[0].exception_type == "gst_mismatch"


def test_ambiguous_tax_is_not_auto_cleared():
    tax = TaxLine(
        id="T1",
        invoice_id="",
        payment_id="PAY0001",
        taxable_value=Decimal("100.00"),
        gst_rate=Decimal("0.18"),
        gst_amount=Decimal("18.00"),
    )
    ledgers = [_ledger(id="L1"), _ledger(id="L2")]
    report = match_tax_lines([tax], ledgers, ReconConfig())
    assert report.matches == []
    assert report.ambiguous


def test_resolve_ambiguous_tax_does_not_reuse_ledger():
    from finance_controller.tax_matching.investigator import resolve_ambiguous_tax

    tax_a = TaxLine(
        id="T1",
        invoice_id="",
        payment_id="PAY0001",
        taxable_value=Decimal("100.00"),
        gst_rate=Decimal("0.18"),
        gst_amount=Decimal("18.00"),
    )
    tax_b = TaxLine(
        id="T2",
        invoice_id="",
        payment_id="PAY0001",
        taxable_value=Decimal("100.00"),
        gst_rate=Decimal("0.18"),
        gst_amount=Decimal("18.00"),
    )
    ledgers = [_ledger(id="L1"), _ledger(id="L2")]
    report = match_tax_lines([tax_a, tax_b], ledgers, ReconConfig())
    report = resolve_ambiguous_tax(report, config=ReconConfig(), use_llm=False)
    ledger_ids = [m.ledger_id for m in report.matches]
    assert len(ledger_ids) == len(set(ledger_ids))
    assert report.ambiguous == []
    assert len(report.matches) + len(report.exceptions) == 2


def test_tax_line_missing_rate_is_invalid():
    with pytest.raises(ValueError, match="gst_rate"):
        TaxLine.from_row(
            {"invoice_id": "INV", "payment_id": "PAY0001", "taxable_value": "100", "gst_amount": "18"},
            index=1,
        )


def test_unmatched_tax_line():
    tax = TaxLine(
        id="T1",
        invoice_id="INV",
        payment_id="MISSING",
        taxable_value=Decimal("100.00"),
        gst_rate=Decimal("0.18"),
        gst_amount=Decimal("18.00"),
    )
    report = match_tax_lines([tax], [_ledger()], ReconConfig())
    assert report.exceptions[0].exception_type == "unmatched"


def test_ingest_rejects_corrupt_and_duplicate_role(tmp_path: Path):
    corrupt = tmp_path / "not.zip"
    corrupt.write_bytes(b"not a zip")
    with pytest.raises(IngestError):
        ingest_zip(corrupt, work_dir=tmp_path / "out1")

    zpath = tmp_path / "dup.zip"
    with zipfile.ZipFile(zpath, "w") as zf:
        zf.writestr("bank.csv", "utr,credited_amount,credited_date,raw_description\nU,1,2026-01-01,x\n")
        zf.writestr("bank2.csv", "utr,credited_amount,credited_date,raw_description\nU,1,2026-01-01,x\n")
        zf.writestr("payments.csv", "payment_id,amount,customer,timestamp,status\nP,1,A,2026-01-01,success\n")
        zf.writestr(
            "settlements.csv",
            "settlement_id,payment_ids,gross_amount,mdr_fee,gst_on_fee,net_amount,utr,settled_date\n"
            "S,P,1,0,0,1,U,2026-01-01\n",
        )
    with pytest.raises(IngestError, match="duplicate"):
        ingest_zip(zpath, work_dir=tmp_path / "out2")
