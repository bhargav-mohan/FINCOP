from __future__ import annotations

from decimal import Decimal
from typing import Any

from finance_controller.config import ReconConfig
from finance_controller.models import (
    AgentAction,
    ExceptionType,
    Investigation,
    MatchResult,
    MatchTier,
    Record,
    ReconException,
    Source,
    ToolCallLog,
)
from finance_controller.reconciliation.engine import EngineResult, _group_key
from finance_controller.reconciliation.matchers import expected_net, payee_key
from finance_controller.reconciliation.validate import validate_proposed_match


def serialize_record(record: Record) -> dict[str, Any]:
    return {
        "id": record.id,
        "source": record.source.value,
        "reference": record.reference,
        "amount": str(record.amount),
        "net_amount": str(record.net_amount),
        "currency": record.currency,
        "txn_date": record.txn_date.isoformat(),
        "fee": str(record.fee),
        "payee": record.payee,
        "description": record.description,
        "batch_id": record.batch_id,
        "closed": False,
    }


class ReconWorkbench:
    """Tool surface over the deterministic engine. The LLM cannot close cash without validation."""

    def __init__(self, result: EngineResult, config: ReconConfig) -> None:
        self.result = result
        self.config = config
        self.by_id: dict[str, Record] = {r.id: r for r in result.records}
        self.investigations: list[Investigation] = []
        self.warnings: list[str] = []
        self._logs: dict[str, list[ToolCallLog]] = {}
        self._agent_match_n = 0

    def _exc_map(self) -> dict[str, ReconException]:
        return {e.exception_id: e for e in self.result.exceptions}

    def _log(self, exception_id: str, tool: str, arguments: dict, summary: str) -> None:
        self._logs.setdefault(exception_id, []).append(
            ToolCallLog(tool=tool, arguments=arguments, result_summary=summary)
        )

    def _open_records(self) -> list[Record]:
        return [r for r in self.result.records if r.id not in self.result.closed_record_ids]

    def list_open_exceptions(self, exception_id: str = "") -> dict:
        open_excs = [
            e
            for e in self.result.exceptions
            if not set(e.record_ids) <= self.result.closed_record_ids
        ]
        payload = [
            {
                "exception_id": e.exception_id,
                "type": e.exception_type.value,
                "reason": e.reason,
                "record_ids": e.record_ids,
                "references": e.references,
                "sources": [s.value for s in e.sources_involved],
                "amounts": {k: str(v) for k, v in e.amounts.items()},
            }
            for e in open_excs
        ]
        self._log(exception_id or "_", "list_open_exceptions", {}, f"{len(payload)} open")
        return {"exceptions": payload}

    def get_records(self, record_ids: list[str], exception_id: str = "") -> dict:
        rows = []
        missing = []
        for rid in record_ids:
            rec = self.by_id.get(rid)
            if rec is None:
                missing.append(rid)
                continue
            data = serialize_record(rec)
            data["closed"] = rec.id in self.result.closed_record_ids
            rows.append(data)
        self._log(exception_id or "_", "get_records", {"record_ids": record_ids}, f"{len(rows)} records")
        return {"records": rows, "missing": missing}

    def find_candidates(self, exception_id: str) -> dict:
        exc = self._exc_map().get(exception_id)
        if exc is None:
            return {"error": f"unknown exception {exception_id}", "candidates": []}
        members = [self.by_id[i] for i in exc.record_ids if i in self.by_id]
        member_ids = {r.id for r in members}
        sources_have = {r.source for r in members}
        need = {Source.LEDGER, Source.BANK, Source.PSP} - sources_have
        locked = set()
        for other in self.result.exceptions:
            if other.exception_id == exception_id:
                continue
            if len(other.record_ids) >= 2 or len(other.sources_involved) >= 2:
                locked.update(other.record_ids)
        open_rows = [
            r
            for r in self._open_records()
            if r.id not in member_ids and r.id not in locked
        ]
        scored: list[tuple[int, Record]] = []
        for rec in open_rows:
            if rec.source not in need and need:
                continue
            score = 0
            for mem in members:
                if rec.currency == mem.currency:
                    score += 2
                if payee_key(rec) and payee_key(rec) == payee_key(mem):
                    score += 5
                desc = (rec.description or "").upper()
                if mem.reference and mem.reference in desc:
                    score += 6
                if payee_key(mem) and payee_key(mem) in desc:
                    score += 3
                if abs((rec.txn_date - mem.txn_date).days) <= self.config.date_lag_days:
                    score += 2
                target = expected_net(mem, self.config.fee_rate) if mem.source != Source.BANK else mem.amount
                other = rec.amount if rec.source == Source.BANK else expected_net(rec, self.config.fee_rate)
                if abs(target - other) <= self.config.amount_tolerance:
                    score += 4
                elif abs(rec.amount - mem.amount) <= Decimal("15.00"):
                    score += 1
            if score >= 4:
                scored.append((score, rec))
        scored.sort(key=lambda item: (-item[0], item[1].id))
        candidates = []
        for score, rec in scored[:15]:
            data = serialize_record(rec)
            data["score"] = score
            data["closed"] = False
            candidates.append(data)
        self._log(
            exception_id,
            "find_candidates",
            {"exception_id": exception_id},
            f"{len(candidates)} candidates",
        )
        return {
            "exception_id": exception_id,
            "member_ids": exc.record_ids,
            "missing_sources": [s.value for s in sorted(need, key=lambda s: s.value)],
            "candidates": candidates,
        }

    def validate(self, record_ids: list[str], exception_id: str = "") -> dict:
        recs = [self.by_id[i] for i in record_ids if i in self.by_id]
        missing = [i for i in record_ids if i not in self.by_id]
        result = validate_proposed_match(recs, self.config, self.result.closed_record_ids)
        payload = result.as_dict()
        payload["missing"] = missing
        self._log(
            exception_id or "_",
            "validate_proposed_match",
            {"record_ids": record_ids},
            f"valid={result.valid}",
        )
        return payload

    def competing_alternatives(self, record_ids: list[str]) -> list[list[str]]:
        chosen = set(record_ids)
        alts: list[list[str]] = []
        for rec_id in record_ids:
            rec = self.by_id.get(rec_id)
            if rec is None:
                continue
            for rival in self._open_records():
                if rival.id in chosen or rival.source != rec.source:
                    continue
                alt = [rival.id if i == rec_id else i for i in record_ids]
                check = validate_proposed_match(
                    [self.by_id[i] for i in alt if i in self.by_id],
                    self.config,
                    self.result.closed_record_ids,
                )
                if check.valid:
                    alts.append(alt)
        return alts

    def reconcile(
        self,
        exception_id: str,
        record_ids: list[str],
        evidence: list[str],
        rationale: str,
        produced_by: str,
    ) -> dict:
        check = self.validate(record_ids, exception_id=exception_id)
        alternatives = self.competing_alternatives(record_ids) if check.get("valid") else []
        if not check.get("valid") or alternatives:
            reasons = list(check.get("reasons") or [])
            if alternatives:
                reasons.append(
                    f"ambiguous: {len(alternatives)} competing completions; refusing first-come-first-serve"
                )
            investigation = Investigation(
                exception_id=exception_id,
                decision=AgentAction.ESCALATE,
                action=AgentAction.ESCALATE,
                proposed_record_ids=record_ids,
                validator_passed=False,
                evidence=list(evidence) + reasons,
                rationale=f"reconcile rejected by validator: {reasons}",
                produced_by=produced_by,
                tool_calls=list(self._logs.get(exception_id, [])),
                classification=self._exc_map().get(exception_id).exception_type
                if exception_id in self._exc_map()
                else ExceptionType.UNMATCHED,
            )
            return {
                "ok": False,
                "rejected": True,
                "validation": check,
                "alternatives": alternatives,
                "investigation": investigation.model_dump(mode="json"),
            }
        recs = [self.by_id[i] for i in record_ids]
        self._agent_match_n += 1
        match = MatchResult(
            match_id=f"A{self._agent_match_n:04d}",
            tier=MatchTier.AGENT_VALIDATED,
            record_ids=record_ids,
            references=sorted({r.reference for r in recs}),
            reason=f"agent-validated: {rationale}",
        )
        self.result.matches.append(match)
        self.result.closed_matches.append(match)
        self.result.closed_record_ids.update(record_ids)
        self.result.closed_group_count += 1
        for rec in recs:
            self.result.closed_keys.add(_group_key(rec))
            self.result.closed_keys.add(rec.reference)
        self._prune_exceptions()
        investigation = Investigation(
            exception_id=exception_id,
            decision=AgentAction.RECONCILE,
            action=AgentAction.RECONCILE,
            proposed_record_ids=record_ids,
            validator_passed=True,
            evidence=list(evidence) + check.get("reasons", []),
            rationale=rationale,
            produced_by=produced_by,
            tool_calls=list(self._logs.get(exception_id, [])),
        )
        self.investigations.append(investigation)
        return {"ok": True, "match_id": match.match_id, "validation": check}

    def escalate(
        self,
        exception_id: str,
        classification: str,
        evidence: list[str],
        rationale: str,
        produced_by: str,
    ) -> dict:
        exc = self._exc_map().get(exception_id)
        try:
            etype = ExceptionType(classification)
        except ValueError:
            etype = exc.exception_type if exc else ExceptionType.UNMATCHED
        if exc is not None:
            exc.exception_type = etype
            exc.reason = rationale or exc.reason
        investigation = Investigation(
            exception_id=exception_id,
            decision=AgentAction.ESCALATE,
            action=AgentAction.ESCALATE,
            classification=etype,
            proposed_record_ids=exc.record_ids if exc else [],
            validator_passed=False,
            evidence=evidence,
            rationale=rationale,
            produced_by=produced_by,
            tool_calls=list(self._logs.get(exception_id, [])),
        )
        self.investigations.append(investigation)
        return {"ok": True, "action": "escalate", "classification": etype.value}

    def _prune_exceptions(self) -> None:
        self.result.exceptions = [
            e
            for e in self.result.exceptions
            if not set(e.record_ids) <= self.result.closed_record_ids
        ]

    def dispatch(self, name: str, arguments: dict, *, exception_id: str, produced_by: str) -> dict:
        if name == "list_open_exceptions":
            return self.list_open_exceptions(exception_id)
        if name == "get_records":
            return self.get_records(list(arguments.get("record_ids") or []), exception_id)
        if name == "find_candidates":
            return self.find_candidates(arguments.get("exception_id") or exception_id)
        if name == "validate_proposed_match":
            return self.validate(list(arguments.get("record_ids") or []), exception_id)
        if name == "reconcile":
            return self.reconcile(
                arguments.get("exception_id") or exception_id,
                list(arguments.get("record_ids") or []),
                list(arguments.get("evidence") or []),
                str(arguments.get("rationale") or ""),
                produced_by,
            )
        if name == "escalate":
            return self.escalate(
                arguments.get("exception_id") or exception_id,
                str(arguments.get("classification") or "unmatched"),
                list(arguments.get("evidence") or []),
                str(arguments.get("rationale") or ""),
                produced_by,
            )
        return {"error": f"unknown tool {name}"}
