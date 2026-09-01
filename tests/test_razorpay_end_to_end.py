from pathlib import Path

from finance_controller.agent.orchestrator import orchestrate
from finance_controller.ingestion.pipeline import ingest_zip
from finance_controller.models import ExpectedStatus
from finance_controller.reconciliation.engine import reconcile
from finance_controller.reconciliation.validate import validate_proposed_match
from finance_controller.reporting.report import compute_accuracy
from finance_controller.config import ReconConfig
from finance_controller.run_finance_controller import run_finance_controller

FIXTURE_ZIP = Path(__file__).resolve().parents[1] / "fixtures" / "razorpay_sample" / "batch.zip"


def test_razorpay_fixture_end_to_end_full_recall():
    ingested = ingest_zip(FIXTURE_ZIP)
    assert len(ingested.batch.ledger) >= 50
    assert ingested.files.get("razorpay_recon") == "settlement_recon.csv"
    assert any("adjustment" in w or "transfer" in w for w in ingested.warnings)
    config = ReconConfig(num_records=max(len(ingested.batch.ledger), 50), date_lag_days=5, use_llm=False)
    result = reconcile(ingested.batch.all_records, config)
    metrics = compute_accuracy(ingested.batch.ground_truth, result)
    actual = {g.key for g in ingested.batch.ground_truth if g.expected_status == ExpectedStatus.EXCEPTION}
    assert actual
    assert metrics.recall == 1.0
    assert metrics.false_negatives == 0

    # The narration-only settlements are matchable but invisible to the
    # deterministic tiers, so exactness is only expected after the agent stage.
    orchestrate(result, config)
    after = compute_accuracy(ingested.batch.ground_truth, result)
    assert after.precision == 1.0
    assert after.recall == 1.0
    assert after.f1 == 1.0
    assert after.false_positives == 0
    assert after.false_negatives == 0

    payload = run_finance_controller(zip_path=str(FIXTURE_ZIP), use_llm=False)
    assert payload.get("error") is None
    assert payload["exception_count"] == len(payload["exceptions"])
    assert payload["value"] is not None
    assert payload["value"]["auto_closed_by_ai"] + payload["value"]["sent_to_analyst"] == len(
        payload["investigations"]
    )


def test_razorpay_fixture_agent_auto_closes_narration_only_settlements():
    """The demo must show the agent earning its keep, and every close must be
    one the deterministic validator independently accepts."""
    ingested = ingest_zip(FIXTURE_ZIP)
    memo_banks = [r for r in ingested.batch.bank if r.extra.get("narration_only")]
    assert len(memo_banks) >= 6
    for bank in memo_banks:
        true_ref = bank.extra["true_reference"]
        assert bank.reference != true_ref, "reference must not give the match away"
        assert not bank.payee, "payee must be blank"
        assert true_ref in bank.description, "identity lives in the narration only"

    config = ReconConfig(num_records=max(len(ingested.batch.ledger), 50), date_lag_days=5, use_llm=False)
    result = reconcile(ingested.batch.all_records, config)
    unclaimed = {r.id for r in memo_banks} - result.closed_record_ids
    assert unclaimed == {r.id for r in memo_banks}, "deterministic tiers must not claim these"

    bench = orchestrate(result, config)
    closes = [i for i in bench.investigations if i.action.value == "reconcile"]
    assert len(closes) >= 5, "agent must auto-close the narration-only settlements"
    by_id = {r.id: r for r in result.records}
    for item in closes:
        members = [by_id[rid] for rid in item.proposed_record_ids]
        assert validate_proposed_match(members, config, set()).valid, (
            f"{item.exception_id} closed without passing the validator"
        )

    payload = run_finance_controller(zip_path=str(FIXTURE_ZIP), use_llm=False)
    assert payload["value"]["auto_closed_by_ai"] >= 5
    assert payload["value"]["auto_close_rate"] > 0.0
