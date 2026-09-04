from finance_controller.run_finance_controller import run_finance_controller

EXCEPTION_KEYS = {
    "id",
    "type",
    "reason",
    "refs",
    "amounts",
    "sources",
    "explanation",
    "suggested_action",
    "confidence",
    "hypothesis_by",
    "evidence",
    "validator_passed",
    "checked_records",
}


def test_run_finance_controller_payload_shape():
    payload = run_finance_controller(seed=42, num_records=60, use_llm=False)
    assert payload["seed"] == 42
    assert payload["num_records"] == 60
    assert payload["exception_count"] == len(payload["exceptions"])
    total = payload["matched"] + payload["exception_count"]
    assert total >= 1
    assert payload["total_groups"] == total
    assert payload["match_rate"] == round(payload["matched"] / total, 4)
    assert 0 <= payload["match_rate"] <= 1
    assert 0 <= payload["baseline_match_rate"] <= 1
    assert payload["advanced_match_rate"] == payload["match_rate"]
    assert payload["advanced_match_rate"] >= payload["baseline_match_rate"]
    assert payload["match_precision"] is not None
    assert 0 <= payload["match_precision"] <= 1
    assert "exception_precision" in payload
    assert payload["match_precision"] == 1.0
    assert payload["exception_precision"] == 1.0
    kpis = payload["kpis"]
    assert kpis["match_precision"] == 1.0
    assert kpis["match_precision_pass"] is True
    assert kpis["match_precision_threshold"] == 0.90
    assert kpis["exceptions_before"] >= kpis["exceptions_after"]
    assert kpis["exceptions_reduced"] == kpis["exceptions_before"] - kpis["exceptions_after"]
    assert kpis["elapsed_ms"] >= 0
    assert kpis["elapsed_ms"] < 30_000
    assert kpis["explanation_precision"] >= 0.90
    assert kpis["explanation_precision_pass"] is True
    assert "closed_bank_net" in payload["cash"]
    assert "in_flight_amount" in payload["cash"]
    assert "in_flight_count" in payload["cash"]
    assert "aged_out_count" in payload["cash"]
    assert "bank_credited_total" in payload["cash"]
    assert "unmatched_bank_net" in payload["cash"]
    assert "variance" in payload["cash"]
    assert "expected_not_credited" in payload["cash"]
    assert "false_positives" in payload["accuracy"]
    assert "false_negatives" in payload["accuracy"]
    assert "type_accuracy" in payload["accuracy"]
    assert isinstance(payload["source_files"], dict)
    assert isinstance(payload["matches"], list)
    assert "llm_used" in payload
    if payload["value"]:
        assert "auto_closed_by_rules" in payload["value"]
        assert "auto_closed_by_llm" in payload["value"]
        assert payload["value"]["auto_closed_by_rules"] + payload["value"]["auto_closed_by_llm"] == payload["value"]["auto_closed_by_ai"]
    if payload["matched"] > 0:
        assert len(payload["matches"]) >= 1
    if payload["matches"]:
        match = payload["matches"][0]
        assert {"id", "tier", "reason", "refs"} <= set(match)
    if payload["exceptions"]:
        row = payload["exceptions"][0]
        assert EXCEPTION_KEYS <= set(row)
        assert "amount_at_risk" in row
        assert "records" in row
        assert "key" in row
        assert row["explanation"]
        if row["refs"]:
            assert any(ref in row["explanation"] for ref in row["refs"]) or (
                row["reason"] and row["reason"] in row["explanation"]
            )
    assert "store" in payload
    assert "available" in payload["store"]
    assert payload["total_exposure"] == payload["cash"]["in_flight_amount"]
    if payload["exceptions"]:
        from decimal import Decimal

        total = sum((Decimal(r["amount_at_risk"]) for r in payload["exceptions"]), Decimal("0.00"))
        assert total == Decimal(payload["total_exposure"])


def test_run_finance_controller_exceptions_carry_investigation_fields():
    payload = run_finance_controller(seed=42, num_records=60, use_llm=False)
    by_id = {item["id"]: item for item in payload["investigations"]}
    for exc in payload["exceptions"]:
        assert "evidence" in exc
        assert "validator_passed" in exc
        assert isinstance(exc["evidence"], list)
        assert isinstance(exc["validator_passed"], bool)
        if exc["id"] in by_id:
            assert exc["validator_passed"] is False or exc["checked_records"] is not None


def test_run_finance_controller_rejects_under_50():
    payload = run_finance_controller(seed=1, num_records=49)
    assert payload["error"]
    assert "50" in payload["error"]
    assert payload["matches"] == []
    assert payload["total_groups"] == 0
    assert payload["accuracy"]["false_positives"] == 0


def test_run_finance_controller_llm_used_false_without_key(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    payload = run_finance_controller(seed=42, num_records=60, use_llm=True)
    assert payload["llm_used"] is False


def test_dashboard_and_cli_agree_on_seed_42(tmp_path):
    """Headline match rate is groups closed / (closed + leftovers), not matched/num_records.

    The dashboard used to generate without inject_edges and then show matched/80,
    which is 66/80 = 82.5%. The CLI with edges reports 56/79 = 70.89%. Both entry
    points now share execute_loop, the same inject mix, and group_match_rate.
    """
    import json
    import os
    import subprocess
    import sys
    from pathlib import Path

    from finance_controller.cli import run as cli_run
    from finance_controller.config import ReconConfig
    from finance_controller.reporting.report import group_match_rate

    payload = run_finance_controller(seed=42, num_records=80, use_llm=False)
    config = ReconConfig(
        seed=42,
        num_records=80,
        inject_exceptions=12,
        inject_resolvable=6,
        inject_edges=16,
        use_llm=False,
    )
    cli_run(config, str(tmp_path / "report"))
    report = json.loads((tmp_path / "report.json").read_text())

    total = payload["matched"] + payload["exception_count"]
    assert payload["total_groups"] == total == 79
    assert payload["matched"] == report["matched"]
    assert payload["exception_count"] == len(report["exceptions"])
    assert payload["match_rate"] == report["match_rate"]
    assert payload["match_rate"] == group_match_rate(payload["matched"], payload["exception_count"])
    assert payload["num_records"] == 80
    assert payload["match_rate"] != round(payload["matched"] / payload["num_records"], 4)
    assert payload["match_rate"] != 0.825
    assert payload["matched"] == 56
    assert payload["exception_count"] == 23
    assert payload["match_rate"] == 0.7089
    assert payload["kpis"]["exceptions_reduced"] >= 0
    assert payload["kpis"]["match_precision_pass"] is True
    assert payload["kpis"]["explanation_precision_pass"] is True

    root = Path(__file__).resolve().parents[1]
    env = {**os.environ, "PYTHONPATH": str(root / "src"), "FC_DB_PATH": str(tmp_path / "spawn.db")}
    spawned = subprocess.run(
        [
            sys.executable,
            "-m",
            "finance_controller.run_finance_controller",
            "--seed",
            "42",
            "--num-records",
            "80",
            "--no-llm",
        ],
        cwd=root,
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    start = spawned.stdout.index("{")
    end = spawned.stdout.rindex("}")
    spawned_payload = json.loads(spawned.stdout[start : end + 1])
    assert spawned_payload["match_rate"] == 0.7089
    assert spawned_payload["matched"] == 56
    assert spawned_payload["total_groups"] == 79


def test_csv_dir_cli_and_dashboard_agree(tmp_path, csv_fixture_dir):
    """payments.csv/settlements.csv/bank.csv is a different batch than generate(seed=42)."""
    import json

    from finance_controller.cli import run as cli_run
    from finance_controller.config import ReconConfig

    payload = run_finance_controller(seed=42, data_dir=str(csv_fixture_dir), use_llm=False)
    cli_run(ReconConfig(seed=42, num_records=80, use_llm=False), str(tmp_path / "report"), data_dir=str(csv_fixture_dir))
    report = json.loads((tmp_path / "report.json").read_text())
    assert payload["matched"] == report["matched"] == 47
    assert payload["exception_count"] == len(report["exceptions"]) == 10
    assert payload["total_groups"] == 57
    assert payload["match_rate"] == report["match_rate"] == 0.8246
    assert payload["value"]["est_analyst_minutes_saved"] == 47 * 8
