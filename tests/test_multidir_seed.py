from pathlib import Path

from finance_controller.data.multidir_seed import LAYOUT, write_multidir_seed
from finance_controller.ingestion.pipeline import ingest_zip
from finance_controller.run_finance_controller import run_finance_controller

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "seed_multidir"


def test_nested_folders_ingest_and_score(tmp_path: Path):
    root = tmp_path / "seed"
    written = write_multidir_seed(root)
    assert (root / LAYOUT["payments"]).exists()
    assert (root / LAYOUT["settlements"]).exists()
    assert (root / LAYOUT["bank"]).exists()
    assert len({Path(p).parent for p in written.values()}) >= 5

    ingested = ingest_zip(root, work_dir=tmp_path / "out")
    assert len(ingested.batch.ledger) >= 50
    assert ingested.files["ledger"] == "payments.csv"
    assert ingested.files["psp"] == "settlements.csv"
    assert ingested.files["bank"] == "neft_credits.csv"

    payload = run_finance_controller(zip_path=str(root), use_llm=False)
    assert payload.get("error") is None
    assert payload["num_records"] >= 50
    total = payload["matched"] + payload["exception_count"]
    assert total >= 50
    assert payload["match_rate"] == round(payload["matched"] / total, 4)
    assert payload["exception_count"] == len(payload["exceptions"])
    for row in payload["exceptions"]:
        assert row["id"]
        assert row["reason"]


def test_committed_multidir_fixture_if_present():
    if not (FIXTURE / LAYOUT["payments"]).exists():
        return
    payload = run_finance_controller(zip_path=str(FIXTURE), use_llm=False)
    assert payload.get("error") is None
    assert payload["num_records"] >= 50
