from pathlib import Path

from finance_controller.run_finance_controller import run_finance_controller

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "low_match_rate.zip"


def test_low_match_rate_fixture_stays_under_twenty_percent():
    payload = run_finance_controller(zip_path=str(FIXTURE), use_llm=False, match_tax=False)
    assert payload.get("error") is None
    assert payload["num_records"] >= 50
    assert payload["matched"] + payload["exception_count"] == payload["total_groups"]
    assert payload["match_rate"] < 0.20
    assert payload["exception_count"] == len(payload["exceptions"])
    kpis = payload["kpis"]
    assert kpis["explanation_precision_pass"] is True
    assert kpis["elapsed_ms"] < 30_000
    assert kpis["exceptions_after"] == payload["exception_count"]
