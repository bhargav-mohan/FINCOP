from finance_controller.cli import main
from finance_controller.models import AccuracyMetrics
from finance_controller.reporting.accuracy_gate import failing_metric


def test_failing_metric_none_when_at_threshold():
    acc = AccuracyMetrics(
        true_positives=10,
        false_positives=0,
        false_negatives=0,
        precision=1.0,
        recall=1.0,
        f1=1.0,
    )
    assert failing_metric(acc, 1.0) is None


def test_failing_metric_names_first_breach():
    acc = AccuracyMetrics(
        true_positives=5,
        false_positives=5,
        false_negatives=0,
        precision=0.5,
        recall=1.0,
        f1=0.6667,
    )
    assert failing_metric(acc, 1.0) == "precision"
    acc2 = AccuracyMetrics(
        true_positives=5,
        false_positives=0,
        false_negatives=5,
        precision=1.0,
        recall=0.5,
        f1=0.6667,
    )
    assert failing_metric(acc2, 1.0) == "recall"


def test_cli_fail_under_exits_2_when_threshold_impossible(tmp_path, monkeypatch):
    monkeypatch.setenv("FC_DB_PATH", str(tmp_path / "fc.db"))
    out = tmp_path / "report"
    try:
        main(
            [
                "--seed",
                "42",
                "--num-records",
                "50",
                "--no-llm",
                "--fail-under",
                "1.1",
                "--out",
                str(out),
            ]
        )
    except SystemExit as exc:
        assert exc.code == 2
    else:
        raise AssertionError("expected SystemExit")


def test_cli_fail_under_passes_at_one(tmp_path, monkeypatch):
    monkeypatch.setenv("FC_DB_PATH", str(tmp_path / "fc.db"))
    out = tmp_path / "report"
    try:
        main(
            [
                "--seed",
                "42",
                "--num-records",
                "50",
                "--no-llm",
                "--fail-under",
                "1.0",
                "--out",
                str(out),
            ]
        )
    except SystemExit as exc:
        assert exc.code == 0
    else:
        raise AssertionError("expected SystemExit")
