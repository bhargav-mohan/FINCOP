from pathlib import Path

from finance_controller.config import ReconConfig
from finance_controller.data.synthetic import generate
from finance_controller.reconciliation.engine import reconcile
from finance_controller.models import BatchSource
from finance_controller.reporting.report import build_report, render_text, write_report


def test_write_report_emits_exception_and_match_csvs(tmp_path: Path):
    config = ReconConfig(seed=42, num_records=60, inject_exceptions=12, inject_resolvable=0, inject_edges=0, use_llm=False)
    batch = generate(config)
    result = reconcile(batch.all_records, config)
    report = build_report(
        config=config,
        source_counts={"ledger": len(batch.ledger), "bank": len(batch.bank), "psp": len(batch.psp)},
        result=result,
        ground_truth=batch.ground_truth,
        llm_used=False,
        investigations=[],
    )
    json_path, text_path, exceptions_csv, matches_csv = write_report(report, str(tmp_path / "report"))
    assert json_path.exists()
    assert text_path.exists()
    assert exceptions_csv.name == "report_exceptions.csv"
    assert matches_csv.name == "report_matches.csv"
    exc_header = exceptions_csv.read_text(encoding="utf-8").splitlines()[0]
    match_header = matches_csv.read_text(encoding="utf-8").splitlines()[0]
    assert exc_header == "id,type,references,reason,hypothesis,confidence"
    assert match_header == "match_id,tier,record_ids,references"
    assert len(exceptions_csv.read_text(encoding="utf-8").splitlines()) == 1 + len(report.exceptions)
    assert len(matches_csv.read_text(encoding="utf-8").splitlines()) == 1 + len(report.matches)


def test_render_text_states_overflag_policy_and_false_positive_count():
    config = ReconConfig(seed=42, num_records=60, inject_exceptions=12, use_llm=False)
    batch = generate(config)
    result = reconcile(batch.all_records, config)
    report = build_report(
        config=config,
        source_counts={"ledger": len(batch.ledger), "bank": len(batch.bank), "psp": len(batch.psp)},
        result=result,
        ground_truth=batch.ground_truth,
        llm_used=False,
        batch_source=BatchSource.GENERATED,
    )
    text = render_text(report)
    assert "over-flagged on purpose" in text
    assert "false close corrupts the ledger" in text
    assert f"false_positives={report.accuracy.false_positives}" in text
    assert "injected=" in text
    assert "match_precision=" in text
    assert "explanation_precision=" in text
    assert "elapsed_ms=" in text
    assert "reduced=" in text


def test_render_text_omits_injection_knobs_for_ingested_runs():
    config = ReconConfig(seed=42, num_records=60, inject_exceptions=12, use_llm=False)
    batch = generate(config)
    result = reconcile(batch.all_records, config)
    report = build_report(
        config=config,
        source_counts={"ledger": len(batch.ledger), "bank": len(batch.bank), "psp": len(batch.psp)},
        result=result,
        ground_truth=batch.ground_truth,
        llm_used=False,
        batch_source=BatchSource.RAZORPAY_RECON,
        source_files={"razorpay_recon": "settlement_recon.csv"},
    )
    text = render_text(report)
    assert "source=razorpay_recon" in text
    assert "injected=" not in text
    assert "resolvable=" not in text
    assert "settlement_recon.csv" in text
    assert "over-flagged on purpose" in text
