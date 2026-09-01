from decimal import Decimal
from pathlib import Path

import pytest
import sqlite3

from finance_controller.agent.orchestrator import orchestrate
from finance_controller.config import ReconConfig
from finance_controller.data.synthetic import generate
from finance_controller.reconciliation.engine import reconcile
from finance_controller.reporting.report import build_report, compute_cash
from finance_controller.store.audit import append_event
from finance_controller.store.cli import main as store_cli_main
from finance_controller.store.db import DEFAULT_DB_PATH, connect, db_path
from finance_controller.store.notes import add_note, notes_for_batch, resolve_exception
from finance_controller.store.runs import aging_for, identity_key, persist_run


def _report(config: ReconConfig):
    batch = generate(config)
    result = reconcile(batch.all_records, config)
    bench = orchestrate(result, config)
    report = build_report(
        config=config,
        source_counts={"ledger": len(batch.ledger), "bank": len(batch.bank), "psp": len(batch.psp)},
        result=result,
        ground_truth=batch.ground_truth,
        llm_used=False,
        investigations=bench.investigations,
    )
    return report, result


def test_audit_events_reject_update_and_delete(tmp_path: Path):
    db = tmp_path / "store.db"
    event_id = append_event(actor="rules", event="escalate", rationale="test", path=db)
    conn = connect(db)
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        conn.execute("UPDATE audit_events SET rationale = 'nope' WHERE id = ?", (event_id,))
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        conn.execute("DELETE FROM audit_events WHERE id = ?", (event_id,))
    conn.close()


def test_amount_at_risk_round_trips_as_decimal_text(tmp_path: Path):
    db = tmp_path / "store.db"
    config = ReconConfig(seed=42, num_records=60, use_llm=False)
    report, result = _report(config)
    persist_run(report, result, batch_key="generated:42:60:12:6:16", path=db)
    conn = connect(db)
    row = conn.execute("SELECT amount_at_risk FROM run_exceptions LIMIT 1").fetchone()
    conn.close()
    assert row is not None
    value = Decimal(row["amount_at_risk"])
    assert value == value.quantize(Decimal("0.01"))


def test_aging_accumulates_for_same_batch_key(tmp_path: Path):
    db = tmp_path / "store.db"
    config = ReconConfig(seed=7, num_records=50, inject_exceptions=8, inject_resolvable=0, inject_edges=0, use_llm=False)
    report, result = _report(config)
    key = "same-batch"
    persist_run(report, result, batch_key=key, path=db)
    persist_run(report, result, batch_key=key, path=db)
    keys = [identity_key(exc, result.closed_keys) for exc in report.exceptions]
    aging = aging_for(key, keys, path=db)
    assert keys
    sample = aging[keys[0]]
    assert sample["runs_open"] == 2
    first = sample["first_seen"]
    persist_run(report, result, batch_key=key, path=db)
    again = aging_for(key, keys, path=db)
    assert again[keys[0]]["first_seen"] == first
    assert again[keys[0]]["runs_open"] == 3


def test_different_batch_keys_do_not_share_history(tmp_path: Path):
    db = tmp_path / "store.db"
    config = ReconConfig(seed=7, num_records=50, use_llm=False)
    report, result = _report(config)
    persist_run(report, result, batch_key="a", path=db)
    persist_run(report, result, batch_key="b", path=db)
    keys = [identity_key(exc, result.closed_keys) for exc in report.exceptions]
    aging_a = aging_for("a", keys, path=db)
    aging_b = aging_for("b", keys, path=db)
    assert keys
    assert aging_a[keys[0]]["runs_open"] == 1
    assert aging_b[keys[0]]["runs_open"] == 1


def test_note_writes_analyst_audit_event(tmp_path: Path):
    db = tmp_path / "store.db"
    add_note(batch_key="k", exception_key="TXN-1", author="ops", note="looked at bank", path=db)
    conn = connect(db)
    row = conn.execute("SELECT actor, event, rationale FROM audit_events").fetchone()
    conn.close()
    assert row["actor"] == "analyst"
    assert row["event"] == "note"
    assert "looked at bank" in row["rationale"]


def test_tests_never_touch_the_real_store(isolate_store: Path):
    """The autouse fixture must redirect writes away from data/finance_controller.db."""
    from finance_controller.run_finance_controller import run_finance_controller

    assert db_path() == isolate_store
    before = DEFAULT_DB_PATH.stat().st_mtime_ns if DEFAULT_DB_PATH.exists() else None

    payload = run_finance_controller(seed=11, num_records=50, use_llm=False)
    assert payload.get("error") is None
    assert payload["store"]["available"] is True

    conn = connect(isolate_store)
    runs = conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0]
    conn.close()
    assert runs == 1, "the run should land in the isolated database"

    after = DEFAULT_DB_PATH.stat().st_mtime_ns if DEFAULT_DB_PATH.exists() else None
    assert after == before, f"tests wrote to the real store at {DEFAULT_DB_PATH}"


def test_resolve_carries_an_unsaved_note(tmp_path: Path):
    """Clicking Mark resolved with typed-but-unsaved text must keep the text."""
    db = tmp_path / "store.db"
    resolve_exception(
        batch_key="k",
        exception_key="TXN-1",
        author="analyst",
        note="bank confirmed credit on the 12th",
        assignee="riya",
        path=db,
    )
    stored = notes_for_batch("k", path=db)["TXN-1"]
    assert stored["note"] == "bank confirmed credit on the 12th"
    assert stored["assignee"] == "riya"
    assert stored["resolved_at"] is not None


def test_resolve_without_a_note_keeps_the_saved_one(tmp_path: Path):
    db = tmp_path / "store.db"
    add_note(
        batch_key="k",
        exception_key="TXN-1",
        author="ops",
        note="called the bank, trace pending",
        assignee="riya",
        path=db,
    )
    resolve_exception(batch_key="k", exception_key="TXN-1", author="analyst", path=db)
    stored = notes_for_batch("k", path=db)["TXN-1"]
    assert stored["note"] == "called the bank, trace pending"
    assert stored["assignee"] == "riya"
    assert stored["resolved_at"] is not None


def test_a_blank_note_cannot_erase_an_earlier_one(tmp_path: Path):
    db = tmp_path / "store.db"
    add_note(
        batch_key="k",
        exception_key="TXN-1",
        author="ops",
        note="checked the statement",
        assignee="riya",
        path=db,
    )
    add_note(batch_key="k", exception_key="TXN-1", author="ops", note="", assignee="", path=db)
    stored = notes_for_batch("k", path=db)["TXN-1"]
    assert stored["note"] == "checked the statement"
    assert stored["assignee"] == "riya"


def test_store_cli_resolve_accepts_a_note(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    db = tmp_path / "cli.db"
    monkeypatch.setenv("FC_DB_PATH", str(db))
    store_cli_main(
        [
            "resolve",
            "--batch-key",
            "k",
            "--exception-key",
            "TXN-9",
            "--author",
            "analyst",
            "--note",
            "matched against the remittance advice",
        ]
    )
    stored = notes_for_batch("k", path=db)["TXN-9"]
    assert stored["note"] == "matched against the remittance advice"
    assert stored["resolved_at"] is not None


def test_exposure_totals_match_cash(tmp_path: Path):
    config = ReconConfig(seed=42, num_records=60, use_llm=False)
    report, result = _report(config)
    assert report.cash is not None
    assert report.cash.in_flight_gross == compute_cash(result).in_flight_gross
    persist_run(report, result, batch_key="exp", path=tmp_path / "s.db")
    conn = connect(tmp_path / "s.db")
    stored = conn.execute("SELECT in_flight_gross FROM runs").fetchone()[0]
    conn.close()
    assert Decimal(stored) == report.cash.in_flight_gross
