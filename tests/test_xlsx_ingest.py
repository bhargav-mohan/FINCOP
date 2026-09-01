from pathlib import Path

from finance_controller.ingestion.pipeline import ingest_zip
from finance_controller.run_finance_controller import run_finance_controller


FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "finance_ops_reconciliation_seeded_v2.zip"


def test_seeded_xlsx_zip_ingests_payments_settlements_and_bank():
    ingested = ingest_zip(FIXTURE)
    assert len(ingested.batch.ledger) == 60
    assert len(ingested.batch.bank) == 60
    assert len(ingested.batch.psp) >= 60
    assert ingested.batch.ground_truth
    assert any(g.expected_status.value == "exception" for g in ingested.batch.ground_truth)


def test_seeded_xlsx_zip_runs_controller():
    payload = run_finance_controller(zip_path=str(FIXTURE), use_llm=False)
    assert payload.get("error") is None
    assert payload["num_records"] >= 50
    assert payload["exception_count"] == len(payload["exceptions"])
    assert payload["matched"] + payload["exception_count"] >= 1
    assert payload["matched"] >= 30
