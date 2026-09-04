from pathlib import Path

from finance_controller.reporting.published import PUBLISHED_PATH, drift, expected, measure


def test_published_metrics_have_not_drifted():
    failures = drift(measure(), expected())
    assert failures == [], "\n".join(failures)


def test_readme_quotes_the_published_figures():
    text = (Path(__file__).resolve().parents[1] / "README.md").read_text(encoding="utf-8")
    want = expected()
    assert "87.72%" in text
    assert "82.46%" in text
    assert "70.89%" in text
    assert "97.69%" in text
    assert "973" in text
    assert want["razorpay_zip"]["cash"]["settled_bank"] in text.replace(",", "")
    assert str(want["razorpay_zip"]["matched"]) in text
    assert str(want["seed_42_80_edges"]["exceptions"]) in text
    assert PUBLISHED_PATH.exists()
