from finance_controller.agent.exception_agent import rule_hypothesis
from finance_controller.models import ExceptionType, ReconException, Source


def test_fallback_never_clears_an_exception():
    exc = ReconException(
        exception_id="X0001",
        exception_type=ExceptionType.UNMATCHED,
        record_ids=["B1"],
        references=["UNK-1"],
        sources_involved=[Source.BANK],
        amounts={},
        reason="orphan",
    )
    hyp = rule_hypothesis(exc)
    assert hyp.produced_by == "rules"
    assert hyp.hypothesis_type == ExceptionType.UNMATCHED
    assert "UNK-1" in hyp.explanation
    assert "orphan" in hyp.explanation
    assert "auto-clear" not in hyp.suggested_action.lower() or "do not" in hyp.suggested_action.lower()
