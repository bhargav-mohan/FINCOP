from finance_controller.agent.orchestrator import orchestrate
from finance_controller.config import ReconConfig
from finance_controller.data.csv_batch import load_csv_batch
from finance_controller.models import ExpectedStatus
from finance_controller.reconciliation.engine import predicted_exception_keys, reconcile
from finance_controller.reporting.report import compute_accuracy


def test_external_csv_batch_reconciles(csv_fixture_dir):
    batch = load_csv_batch(csv_fixture_dir)
    assert len(batch.ledger) >= 50
    assert batch.bank
    assert batch.psp
    config = ReconConfig(date_lag_days=5, use_llm=False)
    result = reconcile(batch.all_records, config)
    assert result.closed_group_count >= 1
    assert result.exceptions
    metrics = compute_accuracy(batch.ground_truth, result)
    actual = {g.key for g in batch.ground_truth if g.expected_status == ExpectedStatus.EXCEPTION}
    predicted = predicted_exception_keys(result)
    assert actual
    assert metrics.false_negatives == 0
    assert metrics.recall == 1.0
    # This dataset labels duplicates under plain keys, so the scorer must not
    # invent "#dup" keys for conflicts where no primary loop closed.
    assert predicted - actual == set(), f"over-flagged: {sorted(predicted - actual)}"
    assert metrics.precision == 1.0
    assert metrics.f1 == 1.0


def test_external_csv_agent_cannot_close_a_utr_conflict(csv_fixture_dir):
    """The agent found a completing bank candidate for a UTR reused across two
    settlements. _block_close now gates on the duplicate_utr flag, so the
    validator refuses what the engine would have refused."""
    batch = load_csv_batch(csv_fixture_dir)
    config = ReconConfig(num_records=max(len(batch.ledger), 80), date_lag_days=5, use_llm=False)
    result = reconcile(batch.all_records, config)
    before = predicted_exception_keys(result)
    actual = {g.key for g in batch.ground_truth if g.expected_status == ExpectedStatus.EXCEPTION}
    orchestrate(result, config)
    after = predicted_exception_keys(result)
    metrics = compute_accuracy(batch.ground_truth, result)
    assert (before & actual) - after == set(), "agent must not close a labelled exception"
    assert metrics.recall == 1.0
    assert metrics.false_negatives == 0
