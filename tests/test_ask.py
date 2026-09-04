from finance_controller.config import ReconConfig
from finance_controller.models import Report
from finance_controller.qa.ask import ask, route
from finance_controller.run_finance_controller import close_finance_loop

import pytest


@pytest.fixture(scope="module")
def report() -> Report:
    config = ReconConfig(seed=42, num_records=60, inject_exceptions=12, use_llm=False)
    built, _, _ = close_finance_loop(config=config)
    return built


def test_cash_answer_is_copied_from_the_report(report: Report):
    answer = ask("how much money is stuck?", report)
    assert answer.tool == "get_cash_position"
    assert report.cash is not None
    assert answer.data["settled_bank"] == str(report.cash.closed_bank_net)
    assert answer.data["blocked_ledger"] == str(report.cash.in_flight_gross)
    assert answer.data["blocked_count"] == report.cash.in_flight_count
    assert answer.data["variance"] == str(report.cash.variance)


def test_match_rate_answer_is_copied_from_the_report(report: Report):
    answer = ask("what is the match rate?", report)
    assert answer.tool == "get_match_rate"
    assert answer.data["matched"] == report.matched
    assert answer.data["match_rate"] == report.match_rate
    assert answer.data["f1"] == report.accuracy.f1


def test_mutate_requests_are_refused(report: Report):
    for question in (
        "change the status of X0001 to matched",
        "re-run matching and close the leftovers",
        "set the amount of the bank row to 100",
    ):
        answer = ask(question, report)
        assert answer.tool == "refuse"
        assert answer.data["ok"] is False


def test_unknown_id_does_not_invent_a_record(report: Report):
    answer = ask("why is TXN_DOES_NOT_EXIST unresolved?", report)
    assert answer.tool == "get_evidence"
    assert answer.data.get("found") is False
    assert "No open exception" in answer.prose


def test_open_exception_evidence_uses_engine_reason(report: Report):
    assert report.exceptions
    exc = report.exceptions[0]
    answer = ask(f"why is {exc.exception_id} unresolved?", report)
    assert answer.tool == "get_evidence"
    assert answer.data["id"] == exc.exception_id
    assert answer.data["reason"] == exc.reason
    assert answer.data["type"] == exc.exception_type.value


def test_route_cash_vs_mutate():
    assert route("how much cash is blocked?") == "cash"
    assert route("mark this as matched") == "refuse"
