from decimal import Decimal

from finance_controller.agent.exception_agent import rule_hypothesis
from finance_controller.models import ExceptionType, ExpectedStatus, GroundTruth, ReconException, Source
from finance_controller.reconciliation.engine import EngineResult
from finance_controller.reporting.kpis import compute_explanation_precision, compute_kpis
from finance_controller.reporting.report import compute_match_precision


def _exc(**kwargs) -> ReconException:
    base = dict(
        exception_id="X0001",
        exception_type=ExceptionType.AMOUNT_MISMATCH,
        record_ids=["B1"],
        references=["PAY0001"],
        sources_involved=[Source.BANK],
        amounts={"B1": Decimal("95.00")},
        reason="bank 95.00 does not match expected net 98.00",
    )
    base.update(kwargs)
    return ReconException(**base)


def test_explanation_precision_requires_instance_citation_and_type():
    labeled = [
        GroundTruth(key="PAY0001", expected_status=ExpectedStatus.EXCEPTION, exception_type=ExceptionType.AMOUNT_MISMATCH)
    ]
    with_facts = _exc(hypothesis=rule_hypothesis(_exc()))
    result = EngineResult(
        matches=[],
        closed_matches=[],
        closed_record_ids=set(),
        closed_keys=set(),
        closed_group_count=0,
        exceptions=[with_facts],
        records=[],
    )
    assert compute_explanation_precision(labeled, result) == 1.0

    generic = _exc(
        hypothesis=rule_hypothesis(_exc()).model_copy(
            update={"explanation": "Linked rows disagree on amount beyond fee/rounding tolerance."}
        )
    )
    result.exceptions = [generic]
    assert compute_explanation_precision(labeled, result) == 0.0

    wrong_type = _exc(
        hypothesis=rule_hypothesis(_exc()).model_copy(update={"hypothesis_type": ExceptionType.UNMATCHED})
    )
    result.exceptions = [wrong_type]
    assert compute_explanation_precision(labeled, result) == 0.0


def test_match_precision_gate_is_ninety_percent():
    gt = [
        GroundTruth(key="A", expected_status=ExpectedStatus.MATCHED),
        GroundTruth(key="B", expected_status=ExpectedStatus.MATCHED),
        GroundTruth(key="C", expected_status=ExpectedStatus.EXCEPTION, exception_type=ExceptionType.UNMATCHED),
    ]
    result = EngineResult(
        matches=[],
        closed_matches=[],
        closed_record_ids=set(),
        closed_keys={"A", "B"},
        closed_group_count=2,
        exceptions=[],
        records=[],
    )
    kpis = compute_kpis(
        result=result,
        ground_truth=gt,
        exceptions_before=4,
        elapsed_ms=120,
        match_precision=compute_match_precision(gt, result.closed_keys),
    )
    assert kpis.match_precision == 1.0
    assert kpis.match_precision_pass is True
    assert kpis.exceptions_before == 4
    assert kpis.exceptions_after == 0
    assert kpis.exceptions_reduced == 4
    assert kpis.elapsed_ms == 120
    assert kpis.explanation_precision == 1.0
    assert kpis.explanation_precision_pass is True

    below = compute_kpis(
        result=result,
        ground_truth=gt,
        exceptions_before=0,
        elapsed_ms=10,
        match_precision=0.89,
    )
    assert below.match_precision_pass is False
