from __future__ import annotations

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "finance_controller"

CORE_PATHS = [
    SRC / "reconciliation",
    SRC / "ingestion",
    SRC / "razorpay",
    SRC / "models.py",
    SRC / "config.py",
    SRC / "qa",
    SRC / "reporting" / "report.py",
    SRC / "reporting" / "exposure.py",
    SRC / "reporting" / "citations.py",
    SRC / "reporting" / "forecast.py",
    SRC / "tax_matching" / "validate.py",
    SRC / "tax_matching" / "match.py",
]


def _py_files(path: Path) -> list[Path]:
    if path.is_file():
        return [path]
    return sorted(p for p in path.rglob("*.py") if p.name != "__pycache__")


def _imported_modules(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.append(node.module)
    return names


@pytest.mark.parametrize("path", [p for root in CORE_PATHS for p in _py_files(root)])
def test_core_does_not_import_the_agent_layer(path: Path):
    for name in _imported_modules(path):
        assert not name.startswith("finance_controller.agent"), f"{path} imports {name}"


def test_qa_does_not_import_reconcile_or_engine_close():
    ask = SRC / "qa" / "ask.py"
    names = _imported_modules(ask)
    assert "finance_controller.agent.tools" not in names
    assert "finance_controller.agent.orchestrator" not in names
    assert "finance_controller.reconciliation.engine" not in names
    src = ask.read_text(encoding="utf-8")
    assert "closed_record_ids" not in src
    assert "validate_proposed_match" not in src


def test_engine_import_does_not_load_agent(monkeypatch):
    import sys
    import subprocess

    code = (
        "import sys\n"
        "from finance_controller.reconciliation import engine  # noqa: F401\n"
        "loaded = [k for k in sys.modules if k.startswith('finance_controller.agent')]\n"
        "raise SystemExit(0 if not loaded else 'loaded: ' + ','.join(loaded))\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=ROOT,
        capture_output=True,
        text=True,
        env={**__import__("os").environ, "PYTHONPATH": str(ROOT / "src")},
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
