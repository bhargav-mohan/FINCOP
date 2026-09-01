from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

from finance_controller.models import Report
from finance_controller.reconciliation.engine import EngineResult, keys_for_exception
from finance_controller.reporting.exposure import exception_exposure
from finance_controller.store.audit import append_event
from finance_controller.store.db import connect
from finance_controller.store.notes import notes_for_batch


def identity_key(exc, closed_keys: set[str]) -> str:
    keys = sorted(keys_for_exception(exc, closed_keys))
    return keys[0] if keys else exc.exception_id


def persist_run(
    report: Report,
    result: EngineResult,
    *,
    batch_key: str,
    baseline_match_rate: float | None = None,
    path: Path | None = None,
) -> int:
    by_id = {r.id: r for r in result.records}
    cash = report.cash
    value = report.value
    conn = connect(path)
    try:
        cur = conn.execute(
            """
            INSERT INTO runs (
                created_at, batch_key, batch_source, seed, matched, exception_count,
                match_rate, baseline_match_rate, precision, recall, f1,
                false_positives, false_negatives, closed_bank_net, in_flight_gross,
                llm_used, model, auto_closed_by_rules, auto_closed_by_llm
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                datetime.now(timezone.utc).isoformat(),
                batch_key,
                report.run.batch_source.value,
                report.run.seed,
                report.matched,
                len(report.exceptions),
                report.match_rate,
                baseline_match_rate,
                report.accuracy.precision,
                report.accuracy.recall,
                report.accuracy.f1,
                report.accuracy.false_positives,
                report.accuracy.false_negatives,
                str(cash.closed_bank_net if cash else Decimal("0.00")),
                str(cash.in_flight_gross if cash else Decimal("0.00")),
                int(report.run.llm_used),
                report.run.model,
                value.auto_closed_by_rules if value else 0,
                value.auto_closed_by_llm if value else 0,
            ),
        )
        run_id = int(cur.lastrowid)
        for exc in report.exceptions:
            conn.execute(
                """
                INSERT INTO run_exceptions (
                    run_id, exception_id, exception_key, exception_type, reason,
                    refs, amount_at_risk, confidence, hypothesis_by
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    exc.exception_id,
                    identity_key(exc, result.closed_keys),
                    exc.exception_type.value,
                    exc.reason,
                    json.dumps(list(exc.references)),
                    str(exception_exposure(exc, by_id)),
                    exc.hypothesis.confidence if exc.hypothesis else None,
                    exc.hypothesis.produced_by if exc.hypothesis else None,
                ),
            )
        for match in report.matches:
            conn.execute(
                """
                INSERT INTO run_matches (run_id, match_id, tier, reason, refs)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    match.match_id,
                    match.tier.value,
                    match.reason,
                    json.dumps(list(match.references)),
                ),
            )
        conn.commit()
    finally:
        conn.close()

    for item in report.investigations:
        actor = "llm" if item.produced_by == "llm" else "rules"
        append_event(
            run_id=run_id,
            actor=actor,
            event=item.action.value,
            exception_id=item.exception_id,
            validator_passed=item.validator_passed,
            proposed_record_ids=list(item.proposed_record_ids),
            evidence=list(item.evidence),
            rationale=item.rationale,
            path=path,
        )
        for call in item.tool_calls:
            if call.tool != "validate_proposed_match":
                continue
            summary = (call.result_summary or "").lower()
            append_event(
                run_id=run_id,
                actor="validator",
                event="validate",
                exception_id=item.exception_id,
                validator_passed="valid" in summary and "invalid" not in summary,
                proposed_record_ids=list(call.arguments.get("record_ids") or []),
                evidence=[call.result_summary],
                rationale=call.result_summary,
                path=path,
            )
    return run_id


def recent_runs(batch_key: str, *, limit: int = 12, path: Path | None = None) -> list[dict[str, Any]]:
    conn = connect(path)
    try:
        rows = conn.execute(
            """
            SELECT id, created_at, matched, exception_count, match_rate,
                   precision, recall, in_flight_gross, llm_used
            FROM runs
            WHERE batch_key = ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (batch_key, limit),
        ).fetchall()
    finally:
        conn.close()
    return [
        {
            "id": row["id"],
            "created_at": row["created_at"],
            "matched": row["matched"],
            "exception_count": row["exception_count"],
            "match_rate": row["match_rate"],
            "precision": row["precision"],
            "recall": row["recall"],
            "in_flight_gross": row["in_flight_gross"],
            "llm_used": bool(row["llm_used"]),
        }
        for row in rows
    ]


def aging_for(batch_key: str, keys: list[str], path: Path | None = None) -> dict[str, dict[str, Any]]:
    if not keys:
        return {}
    conn = connect(path)
    try:
        placeholders = ",".join("?" * len(keys))
        rows = conn.execute(
            f"""
            SELECT e.exception_key, MIN(r.created_at) AS first_seen, COUNT(DISTINCT r.id) AS runs_open
            FROM run_exceptions e
            JOIN runs r ON r.id = e.run_id
            WHERE r.batch_key = ? AND e.exception_key IN ({placeholders})
            GROUP BY e.exception_key
            """,
            (batch_key, *keys),
        ).fetchall()
    finally:
        conn.close()
    now = datetime.now(timezone.utc)
    out: dict[str, dict[str, Any]] = {}
    for row in rows:
        first = datetime.fromisoformat(row["first_seen"])
        if first.tzinfo is None:
            first = first.replace(tzinfo=timezone.utc)
        out[row["exception_key"]] = {
            "first_seen": row["first_seen"],
            "runs_open": int(row["runs_open"]),
            "days_open": max(0, (now - first).days),
        }
    return out


def repeat_offenders(batch_key: str, *, limit: int = 8, path: Path | None = None) -> list[dict[str, Any]]:
    conn = connect(path)
    try:
        rows = conn.execute(
            """
            SELECT e.exception_key, e.exception_type, COUNT(DISTINCT r.id) AS runs_open,
                   MAX(e.amount_at_risk) AS amount_at_risk
            FROM run_exceptions e
            JOIN runs r ON r.id = e.run_id
            WHERE r.batch_key = ?
            GROUP BY e.exception_key
            HAVING COUNT(DISTINCT r.id) > 1
            ORDER BY runs_open DESC, e.exception_key
            LIMIT ?
            """,
            (batch_key, limit),
        ).fetchall()
    finally:
        conn.close()
    return [
        {
            "key": row["exception_key"],
            "type": row["exception_type"],
            "runs_open": int(row["runs_open"]),
            "amount_at_risk": row["amount_at_risk"],
        }
        for row in rows
    ]


def history_block(batch_key: str, exception_keys: list[str], path: Path | None = None) -> dict[str, Any]:
    return {
        "batch_key": batch_key,
        "recent_runs": recent_runs(batch_key, path=path),
        "repeat_offenders": repeat_offenders(batch_key, path=path),
        "aging": aging_for(batch_key, exception_keys, path=path),
        "notes": notes_for_batch(batch_key, path=path),
    }
