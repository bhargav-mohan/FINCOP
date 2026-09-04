from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from finance_controller.models import Report

_MUTATE = re.compile(
    r"\b(change|update|set|mark|re-?run|delete|overwrite|force-?match|auto-?match|close it)\b",
    re.I,
)
_MUTATE_TARGET = re.compile(r"\b(match|status|amount|reconcil|close|ledger)", re.I)
_MONEY_INTENT = re.compile(
    r"\b(stuck|in[-\s]?flight|cash|rupee|blocked|waiting|variance|credited|settled|exposure)\b",
    re.I,
)
_RATE_INTENT = re.compile(r"\b(match rate|how many matched|how many closed)\b", re.I)
_EXC_INTENT = re.compile(r"\b(exception|unresolved|leftover|open item|needs you)\b", re.I)
_ID = re.compile(r"\b(X\d{4}|E\d{4}|A\d{4}|TXN[-_][A-Z0-9_]+|[A-Z]{2,}\d{3,})\b", re.I)


@dataclass(frozen=True)
class Answer:
    tool: str
    data: dict[str, Any]
    prose: str


def _cash_data(report: Report) -> dict[str, Any]:
    cash = report.cash
    if cash is None:
        return {}
    payload: dict[str, Any] = {
        "settled_bank": str(cash.closed_bank_net),
        "blocked_ledger": str(cash.in_flight_gross),
        "blocked_count": cash.in_flight_count,
        "expected_not_credited": str(cash.expected_not_credited),
        "unmatched_bank": str(cash.unmatched_bank_net),
        "bank_credited": str(cash.bank_credited_total),
        "expected_ledger": str(cash.expected_ledger_gross),
        "variance": str(cash.variance),
        "aged_out": cash.in_flight_aged_out,
    }
    if report.forward:
        payload["due_within_window"] = str(report.forward.due_within_window)
        payload["stuck_past_window"] = str(report.forward.stuck_past_window)
        payload["as_of"] = report.forward.as_of.isoformat()
    return payload


def _match_data(report: Report) -> dict[str, Any]:
    return {
        "matched": report.matched,
        "exceptions": len(report.exceptions),
        "total_groups": report.total_groups,
        "match_rate": report.match_rate,
        "precision": report.accuracy.precision,
        "recall": report.accuracy.recall,
        "f1": report.accuracy.f1,
        "false_positives": report.accuracy.false_positives,
        "false_negatives": report.accuracy.false_negatives,
    }


def _exceptions_data(report: Report) -> dict[str, Any]:
    return {
        "count": len(report.exceptions),
        "items": [
            {
                "id": exc.exception_id,
                "type": exc.exception_type.value,
                "reason": exc.reason,
                "references": list(exc.references),
            }
            for exc in report.exceptions
        ],
    }


def _evidence_data(report: Report, token: str) -> dict[str, Any] | None:
    upper = token.upper()
    for exc in report.exceptions:
        refs = [r.upper() for r in exc.references]
        if exc.exception_id.upper() == upper or upper in refs or any(upper in r for r in refs):
            amounts = {k: str(v) for k, v in exc.amounts.items()}
            return {
                "id": exc.exception_id,
                "type": exc.exception_type.value,
                "reason": exc.reason,
                "references": list(exc.references),
                "record_ids": list(exc.record_ids),
                "amounts": amounts,
            }
    return None


def _refuse(reason: str) -> Answer:
    return Answer(tool="refuse", data={"ok": False, "reason": reason}, prose=reason)


def route(question: str) -> str:
    text = (question or "").strip()
    if not text:
        return "refuse"
    if _MUTATE.search(text) and _MUTATE_TARGET.search(text):
        return "refuse"
    if _ID.search(text) and re.search(r"\b(why|evidence|unresolved|open|detail)\b", text, re.I):
        return "evidence"
    if _MONEY_INTENT.search(text):
        return "cash"
    if _RATE_INTENT.search(text):
        return "match_rate"
    if _EXC_INTENT.search(text):
        return "exceptions"
    if _ID.search(text):
        return "evidence"
    return "unknown"


def ask(question: str, report: Report) -> Answer:
    """Answer from a frozen report. Never closes, scores, or rewrites a figure."""
    intent = route(question)
    if intent == "refuse":
        return _refuse(
            "This interface cannot change a match, amount, or status. "
            "Ask about the match rate, the cash position, or a specific exception."
        )
    if intent == "cash":
        data = _cash_data(report)
        prose = (
            f"{data.get('blocked_count', 0)} exceptions block {data.get('blocked_ledger', '0.00')} ledger gross. "
            f"Settled bank {data.get('settled_bank', '0.00')}; "
            f"expected not credited {data.get('expected_not_credited', '0.00')}; "
            f"variance {data.get('variance', '0.00')}."
        )
        return Answer(tool="get_cash_position", data=data, prose=prose)
    if intent == "match_rate":
        data = _match_data(report)
        prose = (
            f"{data['matched']} of {data['total_groups']} closed "
            f"({data['match_rate']:.2%}). Detection F1={data['f1']:.2%} "
            f"with {data['false_positives']} false positives and {data['false_negatives']} misses."
        )
        return Answer(tool="get_match_rate", data=data, prose=prose)
    if intent == "exceptions":
        data = _exceptions_data(report)
        prose = f"{data['count']} unresolved items. None were auto-passed."
        return Answer(tool="get_exceptions", data=data, prose=prose)
    if intent == "evidence":
        token_match = _ID.search(question or "")
        if token_match is None:
            return _refuse("Name an exception id or reference to fetch evidence.")
        found = _evidence_data(report, token_match.group(1))
        if found is None:
            return Answer(
                tool="get_evidence",
                data={"id": token_match.group(1), "found": False},
                prose=f"No open exception matches {token_match.group(1)}.",
            )
        prose = f"{found['id']} is {found['type']}: {found['reason']}"
        return Answer(tool="get_evidence", data=found, prose=prose)
    return _refuse(
        "Ask about match rate, exceptions, cash position, or a specific exception id. "
        "This interface does not recompute or close anything."
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only Q&A over a frozen reconciliation report.")
    parser.add_argument("question")
    parser.add_argument("--report", default="report.json")
    args = parser.parse_args(argv)
    path = Path(args.report)
    if not path.exists():
        raise SystemExit(f"report not found: {path}")
    report = Report.model_validate_json(path.read_text(encoding="utf-8"))
    answer = ask(args.question, report)
    print(answer.prose)
    print(json.dumps({"tool": answer.tool, "data": answer.data}, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
