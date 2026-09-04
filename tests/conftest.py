from __future__ import annotations

from pathlib import Path

import pytest

CSV_FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "finance_synthetic_data"


@pytest.fixture(scope="session")
def csv_fixture_dir() -> Path:
    return CSV_FIXTURE_DIR


@pytest.fixture(autouse=True)
def isolate_llm_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tests must not pick up a real key from the developer's .env."""
    for name in (
        "GEMINI_API_KEY",
        "GOOGLE_API_KEY",
        "OPENAI_API_KEY",
        "OPENROUTER_API_KEY",
        "ZAI_API_KEY",
        "GLM_API_KEY",
    ):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture(autouse=True)
def isolate_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point every test at its own SQLite file.

    Tests that go through run_finance_controller or the CLI do not pass an explicit
    path, so without this they would write run history and audit events into the
    real data/finance_controller.db and pollute a reviewer's aging counts.
    """
    db = tmp_path / "fc_test.db"
    monkeypatch.setenv("FC_DB_PATH", str(db))
    return db
