import pytest

from finance_controller.agent.orchestrator import orchestrate
from finance_controller.config import ReconConfig
from finance_controller.data.synthetic import generate
from finance_controller.models import ExpectedStatus, GroundTruth
from finance_controller.reconciliation.engine import predicted_exception_keys, reconcile
from finance_controller.reporting.report import compute_accuracy, compute_match_precision
from finance_controller.reporting.kpis import compute_explanation_precision

# seed, records, exceptions, resolvable, edges
GRID = [
    (42, 60, 12, 0, 0),
    (42, 80, 12, 6, 16),
    (7, 90, 14, 8, 20),
    (99, 120, 10, 5, 12),
    (2026, 55, 9, 4, 10),
    (1, 50, 8, 4, 8),
    (555, 200, 20, 10, 24),
    (3, 64, 10, 6, 18),
]


def test_seeded_run_detects_injected_exceptions_with_high_f1():
    config = ReconConfig(
        seed=42, num_records=60, inject_exceptions=12, inject_resolvable=0, inject_edges=0, use_llm=False
    )
    batch = generate(config)
    result = reconcile(batch.all_records, config)
    actual = {g.key for g in batch.ground_truth if g.expected_status == ExpectedStatus.EXCEPTION}
    predicted = predicted_exception_keys(result)
    metrics = compute_accuracy(batch.ground_truth, result)
    assert actual - predicted == set()
    assert metrics.recall == 1.0
    assert metrics.false_negatives == 0
    assert metrics.type_accuracy == 1.0
    assert result.exceptions
    assert result.closed_group_count >= 40


@pytest.mark.parametrize("seed,records,excs,resolvable,edges", GRID)
def test_detection_is_exact_on_every_seeded_config(seed, records, excs, resolvable, edges):
    """Detection must be exact end to end: nothing missed, nothing over-flagged.

    The resolvable cases put identity in the bank memo. The engine recovers a
    unique token; the agent still cannot invent a close. What must be exact is
    the full loop: engine, then any agent close through the validator.
    """
    config = ReconConfig(
        seed=seed,
        num_records=records,
        inject_exceptions=excs,
        inject_resolvable=resolvable,
        inject_edges=edges,
        use_llm=False,
    )
    batch = generate(config)
    result = reconcile(batch.all_records, config)
    actual = {g.key for g in batch.ground_truth if g.expected_status == ExpectedStatus.EXCEPTION}
    assert actual, "config must inject something to detect"
    # The engine must never miss, before the agent gets involved.
    assert actual - predicted_exception_keys(result) == set()
    assert compute_accuracy(batch.ground_truth, result).recall == 1.0

    orchestrate(result, config)
    predicted = predicted_exception_keys(result)
    metrics = compute_accuracy(batch.ground_truth, result)
    assert actual - predicted == set(), f"missed: {sorted(actual - predicted)}"
    assert predicted - actual == set(), f"over-flagged: {sorted(predicted - actual)}"
    assert metrics.precision == 1.0
    assert metrics.recall == 1.0
    assert metrics.f1 == 1.0
    assert metrics.false_positives == 0
    assert metrics.false_negatives == 0
    assert compute_match_precision(batch.ground_truth, result.closed_keys) >= 0.90
    assert compute_explanation_precision(batch.ground_truth, result) >= 0.90
    assert all(exc.hypothesis and exc.hypothesis.explanation for exc in result.exceptions)


def test_engine_alone_never_misses_before_the_agent_runs():
    """Recall is the engine's responsibility; precision is the pipeline's."""
    for seed, records, excs, resolvable, edges in GRID:
        config = ReconConfig(
            seed=seed,
            num_records=records,
            inject_exceptions=excs,
            inject_resolvable=resolvable,
            inject_edges=edges,
            use_llm=False,
        )
        batch = generate(config)
        result = reconcile(batch.all_records, config)
        metrics = compute_accuracy(batch.ground_truth, result)
        assert metrics.recall == 1.0, f"seed {seed} missed an exception before the agent"
        assert metrics.false_negatives == 0


def test_match_precision_is_not_detection_precision():
    """Closing an EXCEPTION-labeled key hurts match precision; detection can still be 1.0."""
    gt = [
        GroundTruth(key="A", expected_status=ExpectedStatus.MATCHED),
        GroundTruth(key="B", expected_status=ExpectedStatus.EXCEPTION),
    ]
    assert compute_match_precision(gt, {"A"}) == 1.0
    assert compute_match_precision(gt, {"A", "B"}) == 0.5
    assert compute_match_precision(gt, set()) is None


def test_group_match_rate_is_closed_over_groups_not_num_records():
    from finance_controller.reporting.report import group_match_rate

    assert group_match_rate(56, 23) == 0.7089
    assert group_match_rate(66, 12) == round(66 / 78, 4)
    assert group_match_rate(66, 12) != 0.825
    assert group_match_rate(0, 0) == 0.0
