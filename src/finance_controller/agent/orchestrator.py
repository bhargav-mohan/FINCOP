from __future__ import annotations

import sys

from finance_controller.agent.exception_agent import attach_explanations
from finance_controller.agent.llm import LlmBudget, LlmUnavailable, run_tool_loop
from finance_controller.agent.tools import ReconWorkbench
from finance_controller.config import ReconConfig
from finance_controller.models import AgentAction, ExceptionType, ReconException
from finance_controller.reconciliation.engine import EngineResult

SYSTEM = """You are the finance reconciliation investigator for unresolved groups.
The deterministic matching engine already closed unambiguous matches. You do not replace it.

You investigate one exception at a time using tools on the actual batch:
- list_open_exceptions
- get_records
- find_candidates
- validate_proposed_match
- reconcile
- escalate

Rules:
- Financial truth comes only from validate_proposed_match. If valid is false, you must not treat the group as matched.
- Call reconcile only after validate_proposed_match returns valid=true for those record_ids.
- Reconcile only a complete cash loop (ledger + psp + bank, or a valid batched settlement).
- Escalate FX breaks, missing cash, amount breaks that fail validation, duplicates, orphans, and any ambiguous same-amount/payee collision.
- Never invent records or IDs. Never first-come-first-serve among equal candidates.
- You must finish with either reconcile (ok) or escalate.
"""

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "list_open_exceptions",
            "description": "List exceptions the engine could not close.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_records",
            "description": "Fetch ledger/bank/psp rows by id.",
            "parameters": {
                "type": "object",
                "properties": {
                    "record_ids": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["record_ids"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "find_candidates",
            "description": "Find unused counterpart rows that could complete this exception.",
            "parameters": {
                "type": "object",
                "properties": {"exception_id": {"type": "string"}},
                "required": ["exception_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "validate_proposed_match",
            "description": "Run deterministic amount/date/currency/payee/cash-loop validation.",
            "parameters": {
                "type": "object",
                "properties": {
                    "record_ids": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["record_ids"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "reconcile",
            "description": "Close the group only if validation passes.",
            "parameters": {
                "type": "object",
                "properties": {
                    "exception_id": {"type": "string"},
                    "record_ids": {"type": "array", "items": {"type": "string"}},
                    "evidence": {"type": "array", "items": {"type": "string"}},
                    "rationale": {"type": "string"},
                },
                "required": ["exception_id", "record_ids", "rationale"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "escalate",
            "description": "Leave the group unresolved with a classification and evidence.",
            "parameters": {
                "type": "object",
                "properties": {
                    "exception_id": {"type": "string"},
                    "classification": {
                        "type": "string",
                            "enum": [
                            "missing_in_bank",
                            "missing_in_ledger",
                            "amount_mismatch",
                            "duplicate",
                            "fx_mismatch",
                            "unmatched",
                            "partial_refund",
                            "zero_or_negative_net",
                            "status_mismatch",
                            "date_inverted",
                            "late_settlement",
                            "empty_utr",
                            "malformed_utr",
                            "gst_zero_bug",
                            "gst_mismatch",
                            "malformed_amount",
                            "duplicate_utr",
                        ],
                    },
                    "evidence": {"type": "array", "items": {"type": "string"}},
                    "rationale": {"type": "string"},
                },
                "required": ["exception_id", "classification", "rationale"],
            },
        },
    },
]


def _investigated_ids(bench: ReconWorkbench) -> set[str]:
    return {item.exception_id for item in bench.investigations}


def investigate_with_rules(bench: ReconWorkbench, exception_id: str) -> None:
    produced = "rules"
    exc = bench._exc_map().get(exception_id)
    if exc is None:
        return
    member_ids = list(exc.record_ids)
    members_check = bench.validate(member_ids, exception_id=exception_id)
    if members_check.get("valid") and not bench.competing_alternatives(member_ids):
        bench.reconcile(
            exception_id,
            member_ids,
            evidence=["engine leftover already forms a valid cash loop", *members_check.get("reasons", [])],
            rationale="deterministic validator accepted the leftover group as-is",
            produced_by=produced,
        )
        return
    found = bench.find_candidates(exception_id)
    candidate_ids = [c["id"] for c in found.get("candidates", [])]
    missing = found.get("missing_sources") or []
    by_source: dict[str, list[str]] = {}
    for cand in found.get("candidates", []):
        by_source.setdefault(str(cand["source"]), []).append(str(cand["id"]))
    if missing and all(len(by_source.get(src, [])) == 1 for src in missing):
        trial = list(dict.fromkeys([*member_ids, *[by_source[src][0] for src in missing]]))
        trial_check = bench.validate(trial, exception_id=exception_id)
        if trial_check.get("valid") and not bench.competing_alternatives(trial):
            bench.reconcile(
                exception_id,
                trial,
                evidence=[
                    f"unique candidate per missing source {missing}",
                    *trial_check.get("reasons", []),
                ],
                rationale="deterministic validator accepted a unique completing cash loop",
                produced_by=produced,
            )
            return
    passing: list[tuple[str, list[str], dict]] = []
    financially_valid = 0
    for cid in candidate_ids:
        trial = list(dict.fromkeys([*member_ids, cid]))
        trial_check = bench.validate(trial, exception_id=exception_id)
        if trial_check.get("valid"):
            financially_valid += 1
            if not bench.competing_alternatives(trial):
                passing.append((cid, trial, trial_check))
    if len(passing) == 1:
        cid, trial, trial_check = passing[0]
        bench.reconcile(
            exception_id,
            trial,
            evidence=[f"exactly one completing candidate {cid}", *trial_check.get("reasons", [])],
            rationale="deterministic validator accepted members plus one unique candidate",
            produced_by=produced,
        )
        return
    evidence = [exc.reason, f"validator rejected leftover group: {members_check.get('reasons')}"]
    if financially_valid > 1 or len(passing) > 1 or any(len(v) > 1 for v in by_source.values()):
        evidence.append(
            "ambiguous: multiple candidates would validate; refusing first-come-first-serve"
        )
    bench.escalate(
        exception_id,
        exc.exception_type.value,
        evidence=evidence,
        rationale=exc.reason,
        produced_by=produced,
    )


def investigate_with_llm(
    bench: ReconWorkbench,
    exception_id: str,
    config: ReconConfig,
    budget: LlmBudget | None = None,
) -> None:
    exc = bench._exc_map()[exception_id]

    def dispatch(name: str, args: dict) -> dict:
        return bench.dispatch(name, args, exception_id=exception_id, produced_by="llm")

    user = (
        f"Investigate exception {exception_id}.\n"
        f"engine_type={exc.exception_type.value}\n"
        f"reason={exc.reason}\n"
        f"record_ids={exc.record_ids}\n"
        f"references={exc.references}\n"
        "Use tools, then reconcile or escalate."
    )
    run_tool_loop(
        system=SYSTEM,
        user=user,
        tools=TOOLS,
        dispatch=dispatch,
        model=config.model,
        provider=config.provider,
        max_rounds=4,
        budget=budget,
    )


def _investigate_order(exc: ReconException) -> tuple:
    """Completable counterpart groups first so singleton leftovers can be absorbed before we log escalate."""
    if exc.exception_type == ExceptionType.MISSING_IN_BANK:
        return (0, exc.exception_id)
    if len(exc.sources_involved) >= 2:
        return (1, exc.exception_id)
    return (2, exc.exception_id)


def drop_stale_escalations(bench: ReconWorkbench) -> None:
    """Drop escalate rows whose exception was later closed by another reconcile."""
    open_ids = {e.exception_id for e in bench.result.exceptions}
    bench.investigations = [
        item
        for item in bench.investigations
        if item.action == AgentAction.RECONCILE or item.exception_id in open_ids
    ]


def _progress(message: str) -> None:
    """Progress goes to stderr; stdout stays reserved for the JSON payload."""
    sys.stderr.write(f"{message}\n")
    sys.stderr.flush()


def orchestrate(result: EngineResult, config: ReconConfig) -> ReconWorkbench:
    bench = ReconWorkbench(result, config)
    pending = sorted(result.exceptions, key=_investigate_order)
    use_llm = bool(config.use_llm)
    budget = LlmBudget() if use_llm else None
    total = len(pending)
    for i, exc in enumerate(pending, start=1):
        exception_id = exc.exception_id
        if exception_id not in bench._exc_map():
            continue
        if set(bench._exc_map()[exception_id].record_ids) <= result.closed_record_ids:
            continue
        if exception_id in _investigated_ids(bench):
            continue
        _progress(f"[agent] investigating {exception_id} ({i}/{total}) with rules")
        investigate_with_rules(bench, exception_id)
        current = bench._exc_map().get(exception_id)
        still_open = (
            current is not None
            and not set(current.record_ids) <= result.closed_record_ids
        )
        if still_open and use_llm:
            _progress(f"[agent] leftovers {exception_id} ({i}/{total}) with llm")
            try:
                investigate_with_llm(bench, exception_id, config, budget)
            except LlmUnavailable as exc_err:
                use_llm = False
                bench.warnings.append(str(exc_err))
                _progress(f"[agent] {exc_err} — remaining leftovers stay on rules")
        if exception_id not in _investigated_ids(bench) and exception_id in bench._exc_map():
            investigate_with_rules(bench, exception_id)

    remaining = [
        e
        for e in result.exceptions
        if not set(e.record_ids) <= result.closed_record_ids
    ]
    # Rule hypotheses already cite refs/amounts. A second GLM pass per leftover
    # was slow and surfaced as "AI assistant was unavailable".
    if config.use_llm and not use_llm:
        if not any("quota" in w.lower() for w in bench.warnings):
            if not any("time cap" in w.lower() or "timed out" in w.lower() or "budget" in w.lower() for w in bench.warnings):
                bench.warnings.append("Exception hypotheses came from rules, not the LLM.")
    result.exceptions = remaining
    drop_stale_escalations(bench)
    for exc in result.exceptions:
        if exc.exception_id not in _investigated_ids(bench):
            investigate_with_rules(bench, exc.exception_id)
    drop_stale_escalations(bench)
    result.exceptions = attach_explanations(
        [e for e in result.exceptions if not set(e.record_ids) <= result.closed_record_ids]
    )
    return bench
