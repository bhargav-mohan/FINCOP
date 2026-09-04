from __future__ import annotations

from decimal import Decimal
from typing import Any

from finance_controller.models import Investigation, Record, ReconException, Report, Source
from finance_controller.reconciliation.engine import EngineResult
from finance_controller.reporting.exposure import exception_exposure
from finance_controller.store.runs import identity_key


def _money(value: Decimal | None) -> str:
    if value is None:
        return "0.00"
    return str(value)


def _empty_store(batch_key: str = "", reason: str = "") -> dict[str, Any]:
    return {
        "available": False,
        "reason": reason,
        "batch_key": batch_key,
        "recent_runs": [],
        "repeat_offenders": [],
        "aging": {},
        "notes": {},
    }


def _empty_kpis() -> dict[str, Any]:
    return {
        "match_precision": None,
        "match_precision_threshold": 0.90,
        "match_precision_pass": None,
        "exceptions_before": 0,
        "exceptions_after": 0,
        "exceptions_reduced": 0,
        "elapsed_ms": 0,
        "explanation_precision": None,
        "explanation_precision_threshold": 0.90,
        "explanation_precision_pass": None,
    }


def _kpis_payload(report: Report) -> dict[str, Any]:
    kpis = report.kpis
    if kpis is None:
        return _empty_kpis()
    return {
        "match_precision": kpis.match_precision,
        "match_precision_threshold": kpis.match_precision_threshold,
        "match_precision_pass": kpis.match_precision_pass,
        "exceptions_before": kpis.exceptions_before,
        "exceptions_after": kpis.exceptions_after,
        "exceptions_reduced": kpis.exceptions_reduced,
        "elapsed_ms": kpis.elapsed_ms,
        "explanation_precision": kpis.explanation_precision,
        "explanation_precision_threshold": kpis.explanation_precision_threshold,
        "explanation_precision_pass": kpis.explanation_precision_pass,
    }


def error_payload(*, seed: int, num_records: int, error: str) -> dict[str, Any]:
    return {
        "error": error,
        "seed": seed,
        "batch_source": "generated",
        "source_files": {},
        "agent_warnings": [],
        "num_records": num_records,
        "match_rate": 0.0,
        "matched": 0,
        "exception_count": 0,
        "total_groups": 0,
        "match_precision": None,
        "exception_precision": 0.0,
        "exception_recall": 0.0,
        "baseline_match_rate": 0.0,
        "advanced_match_rate": 0.0,
        "llm_used": False,
        "cash": {
            "closed_bank_net": "0.00",
            "in_flight_amount": "0.00",
            "in_flight_count": 0,
            "aged_out_count": 0,
        },
        "accuracy": {
            "false_positives": 0,
            "false_negatives": 0,
            "type_accuracy": None,
        },
        "kpis": _empty_kpis(),
        "value": None,
        "exceptions": [],
        "matches": [],
        "investigations": [],
        "tax": None,
        "ingestion": None,
        "total_exposure": "0.00",
        "store": _empty_store(),
    }


def _latest_investigation(investigations: list[Investigation]) -> dict[str, Investigation]:
    by_id: dict[str, Investigation] = {}
    for item in investigations:
        by_id[item.exception_id] = item
    return by_id


def _record_row(rec: Record) -> dict[str, Any]:
    return {
        "id": rec.id,
        "source": rec.source.value,
        "reference": rec.reference,
        "amount": _money(rec.amount),
        "currency": rec.currency,
        "date": rec.txn_date.isoformat(),
        "fee": _money(rec.fee),
        "gst": _money(rec.gst),
        "utr": rec.utr,
        "status": rec.status.value,
        "description": rec.description,
        "payee": rec.payee,
    }


def _exception_row(
    exc: ReconException,
    investigation: Investigation | None,
    *,
    by_id: dict[str, Record],
    closed_keys: set[str],
) -> dict[str, Any]:
    hyp = exc.hypothesis
    members = [by_id[rid] for rid in exc.record_ids if rid in by_id]
    key = identity_key(exc, closed_keys)
    row: dict[str, Any] = {
        "id": exc.exception_id,
        "key": key,
        "type": exc.exception_type.value,
        "reason": exc.reason,
        "refs": list(exc.references),
        "amounts": {k: _money(v) for k, v in exc.amounts.items()},
        "amount_at_risk": _money(exception_exposure(exc, by_id)),
        "sources": [s.value if isinstance(s, Source) else str(s) for s in exc.sources_involved],
        "records": [_record_row(rec) for rec in members],
        "explanation": hyp.explanation if hyp else None,
        "suggested_action": hyp.suggested_action if hyp else None,
        "confidence": hyp.confidence if hyp else None,
        "hypothesis_by": hyp.produced_by if hyp else None,
        "evidence": list(investigation.evidence) if investigation else [],
        "validator_passed": investigation.validator_passed if investigation else False,
        "checked_records": list(investigation.proposed_record_ids) if investigation else [],
        "first_seen": None,
        "runs_open": 1,
        "days_open": 0,
        "note": None,
        "assignee": "",
        "resolved_at": None,
    }
    return row


def build_dashboard_payload(
    report: Report,
    *,
    baseline_match_rate: float,
    match_precision: float | None,
    extra: dict[str, Any],
    result: EngineResult | None = None,
) -> dict[str, Any]:
    cash = report.cash
    latest = _latest_investigation(report.investigations)
    by_id = {r.id: r for r in (result.records if result else [])}
    closed_keys = result.closed_keys if result else set()
    exceptions = [
        _exception_row(exc, latest.get(exc.exception_id), by_id=by_id, closed_keys=closed_keys)
        for exc in report.exceptions
    ]
    store = extra.get("store") or _empty_store()
    aging = store.get("aging") or {}
    notes = store.get("notes") or {}
    for row in exceptions:
        age = aging.get(row["key"]) or {}
        row["first_seen"] = age.get("first_seen")
        row["runs_open"] = age.get("runs_open", 1)
        row["days_open"] = age.get("days_open", 0)
        note = notes.get(row["key"]) or {}
        row["note"] = note.get("note") or None
        row["assignee"] = note.get("assignee") or ""
        row["resolved_at"] = note.get("resolved_at")
    total_exposure = cash.in_flight_gross if cash else Decimal("0.00")
    payload: dict[str, Any] = {
        "seed": report.run.seed,
        "batch_source": report.run.batch_source.value,
        "source_files": dict(report.run.source_files),
        "agent_warnings": list(report.run.agent_warnings),
        "num_records": report.run.num_records,
        "match_rate": report.match_rate,
        "matched": report.matched,
        "exception_count": len(report.exceptions),
        "total_groups": report.total_groups,
        "match_precision": match_precision,
        "exception_precision": report.accuracy.precision,
        "exception_recall": report.accuracy.recall,
        "baseline_match_rate": baseline_match_rate,
        "advanced_match_rate": report.match_rate,
        "llm_used": report.run.llm_used,
        "cash": {
            "closed_bank_net": _money(cash.closed_bank_net) if cash else "0.00",
            "in_flight_amount": _money(cash.in_flight_gross) if cash else "0.00",
            "in_flight_count": cash.in_flight_count if cash else 0,
            "aged_out_count": cash.in_flight_aged_out if cash else 0,
        },
        "accuracy": {
            "false_positives": report.accuracy.false_positives,
            "false_negatives": report.accuracy.false_negatives,
            "type_accuracy": report.accuracy.type_accuracy,
            "f1": report.accuracy.f1,
        },
        "kpis": _kpis_payload(report),
        "value": (
            {
                "auto_closed_by_ai": report.value.auto_closed_by_ai,
                "auto_closed_by_rules": report.value.auto_closed_by_rules,
                "auto_closed_by_llm": report.value.auto_closed_by_llm,
                "sent_to_analyst": report.value.sent_to_analyst,
                "auto_close_rate": report.value.auto_close_rate,
                "in_flight_amount": _money(report.value.in_flight_amount),
                "est_analyst_minutes_saved": report.value.est_analyst_minutes_saved,
                "assumed_minutes_per_item": report.value.assumed_minutes_per_item,
                "assumption": report.value.assumption,
            }
            if report.value
            else None
        ),
        "exceptions": exceptions,
        "matches": [
            {
                "id": match.match_id,
                "tier": match.tier.value,
                "reason": match.reason,
                "refs": list(match.references),
            }
            for match in report.matches
        ],
        "investigations": [
            {
                "id": item.exception_id,
                "decision": item.action.value,
                "by": item.produced_by,
                "rationale": item.rationale,
            }
            for item in report.investigations
        ],
        "tax": None,
        "ingestion": None,
        "total_exposure": _money(total_exposure),
        "store": store,
    }
    merged = extra.copy()
    payload.update(merged)
    payload["store"] = store
    return payload
