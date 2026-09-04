from __future__ import annotations

from finance_controller.agent.exception_agent import cites_instance
from finance_controller.models import ExpectedStatus, GroundTruth, KpiScorecard, ReconException
from finance_controller.reconciliation.engine import EngineResult, keys_for_exception

MATCH_PRECISION_THRESHOLD = 0.90
EXPLANATION_PRECISION_THRESHOLD = 0.90


def _gt_types_for(exc: ReconException, ground_truth: list[GroundTruth], closed_keys: set[str]) -> list:
    by_key = {g.key: g for g in ground_truth}
    types = []
    for key in keys_for_exception(exc, closed_keys):
        row = by_key.get(key)
        if row is not None and row.expected_status == ExpectedStatus.EXCEPTION and row.exception_type:
            types.append(row.exception_type)
    return types


def explanation_is_precise(
    exc: ReconException,
    ground_truth: list[GroundTruth],
    closed_keys: set[str],
) -> bool:
    hyp = exc.hypothesis
    if hyp is None or not (hyp.explanation or "").strip():
        return False
    if not cites_instance(hyp.explanation, exc):
        return False
    gt_types = _gt_types_for(exc, ground_truth, closed_keys)
    if gt_types and hyp.hypothesis_type not in gt_types:
        return False
    return True


def compute_explanation_precision(
    ground_truth: list[GroundTruth],
    result: EngineResult,
) -> float:
    """Share of flagged items whose explanation cites this row and matches GT type when labeled."""
    if not result.exceptions:
        return 1.0
    precise = sum(
        1
        for exc in result.exceptions
        if explanation_is_precise(exc, ground_truth, result.closed_keys)
    )
    return round(precise / len(result.exceptions), 4)


def _pass(value: float | None, threshold: float) -> bool | None:
    if value is None:
        return None
    return value >= threshold


def compute_kpis(
    *,
    result: EngineResult,
    ground_truth: list[GroundTruth],
    exceptions_before: int,
    elapsed_ms: int,
    match_precision: float | None,
) -> KpiScorecard:
    after = len(result.exceptions)
    before = max(exceptions_before, after)
    expl = compute_explanation_precision(ground_truth, result)
    return KpiScorecard(
        match_precision=match_precision,
        match_precision_threshold=MATCH_PRECISION_THRESHOLD,
        match_precision_pass=_pass(match_precision, MATCH_PRECISION_THRESHOLD),
        exceptions_before=before,
        exceptions_after=after,
        exceptions_reduced=max(0, before - after),
        elapsed_ms=max(0, elapsed_ms),
        explanation_precision=expl,
        explanation_precision_threshold=EXPLANATION_PRECISION_THRESHOLD,
        explanation_precision_pass=_pass(expl, EXPLANATION_PRECISION_THRESHOLD),
    )
