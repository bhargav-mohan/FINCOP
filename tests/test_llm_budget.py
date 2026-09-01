import time

import pytest

from finance_controller.agent import orchestrator as orch
from finance_controller.agent.llm import (
    LLM_TIMEOUT_SEC,
    LlmBudget,
    LlmBudgetExhausted,
    _openai_call,
)
from finance_controller.config import ReconConfig
from finance_controller.data.synthetic import generate
from finance_controller.reconciliation.engine import reconcile


def test_budget_check_raises_once_exhausted():
    budget = LlmBudget(total_seconds=0.0)
    assert budget.exhausted() is True
    with pytest.raises(LlmBudgetExhausted):
        budget.check()


def test_openai_call_caps_timeout_to_remaining_budget():
    captured = {}

    class _Client:
        class chat:  # noqa: N801
            class completions:  # noqa: N801
                @staticmethod
                def create(**kwargs):
                    captured.update(kwargs)
                    return "ok"

    assert _openai_call(_Client(), budget=LlmBudget(total_seconds=5.0), model="m") == "ok"
    assert captured["timeout"] <= 5.0
    assert captured["timeout"] <= LLM_TIMEOUT_SEC


def test_exhausted_budget_falls_back_to_rules_and_investigates_every_exception(monkeypatch):
    config = ReconConfig(
        seed=42, num_records=60, inject_exceptions=12, inject_resolvable=6, inject_edges=8, use_llm=True
    )
    batch = generate(config)
    result = reconcile(batch.all_records, config)
    expected_exception_ids = {e.exception_id for e in result.exceptions}
    assert expected_exception_ids

    calls = {"n": 0}

    def _slow_llm(bench, exception_id, cfg, budget=None):
        calls["n"] += 1
        time.sleep(0.01)
        raise LlmBudgetExhausted("LLM budget of 90s exhausted; falling back to rules")

    monkeypatch.setattr(orch, "investigate_with_llm", _slow_llm)

    def _no_network(*_a, **_k):  # pragma: no cover
        raise AssertionError("annotate_exceptions must not call the LLM after fallback")

    monkeypatch.setattr(orch, "annotate_exceptions", _no_network)

    bench = orch.orchestrate(result, config)

    assert calls["n"] == 1, "must stop trying the LLM after the budget is gone"
    assert bench.warnings, "fallback must be visible, not silent"
    assert any("rule" in w.lower() for w in bench.warnings)
    investigated = {item.exception_id for item in bench.investigations}
    open_ids = {e.exception_id for e in result.exceptions}
    assert open_ids <= investigated, "every unresolved exception must still be investigated"
    assert all(item.produced_by == "rules" for item in bench.investigations)
    reconciled = sum(1 for item in bench.investigations if item.action.value == "reconcile")
    escalated = sum(1 for item in bench.investigations if item.action.value == "escalate")
    assert escalated + reconciled == len(result.exceptions) + reconciled
    assert escalated == len(result.exceptions)


def test_llm_progress_is_printed_before_fallback(monkeypatch, capsys):
    config = ReconConfig(seed=42, num_records=50, inject_exceptions=8, inject_resolvable=0, use_llm=True)
    batch = generate(config)
    result = reconcile(batch.all_records, config)

    def _fail(bench, exception_id, cfg, budget=None):
        raise LlmBudgetExhausted("LLM budget of 90s exhausted; falling back to rules")

    monkeypatch.setattr(orch, "investigate_with_llm", _fail)
    monkeypatch.setattr(orch, "annotate_exceptions", lambda *a, **k: result.exceptions)
    orch.orchestrate(result, config)
    err = capsys.readouterr().err
    assert "[agent] investigating" in err
    assert "leftovers stay on rules" in err or "switching to rules" in err


def test_quota_error_is_named_not_swallowed():
    from finance_controller.agent.llm import _llm_error_text

    text = _llm_error_text(
        RuntimeError("Error code: 429 - quota exceeded for metric generate_content_free_tier_requests")
    )
    assert "quota" in text.lower()


def test_client_bounds_match_plan():
    from finance_controller.agent.llm import LLM_MAX_RETRIES, LLM_TIMEOUT_SEC

    assert LLM_TIMEOUT_SEC == 20.0
    assert LLM_MAX_RETRIES == 1
