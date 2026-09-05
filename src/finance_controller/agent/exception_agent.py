from __future__ import annotations

import json

from finance_controller.agent.llm import LlmBudget, LlmUnavailable, complete_json
from finance_controller.models import (
    ExceptionHypothesis,
    ExceptionType,
    Record,
    ReconException,
)
from finance_controller.reporting.citations import cites_instance

_RULES: dict[ExceptionType, tuple[str, str, float]] = {
    ExceptionType.MISSING_IN_BANK: (
        "Books show the transaction but no bank cash movement was found.",
        "Trace settlement timing and request the missing bank line from ops.",
        0.78,
    ),
    ExceptionType.MISSING_IN_LEDGER: (
        "Cash or PSP settlement exists without a ledger booking.",
        "Post the missing journal entry or confirm it is a non-book item.",
        0.78,
    ),
    ExceptionType.AMOUNT_MISMATCH: (
        "Linked rows disagree on amount beyond fee/rounding tolerance.",
        "Inspect fees, chargebacks, and partial captures before adjusting.",
        0.8,
    ),
    ExceptionType.DUPLICATE: (
        "An extra bank row shares a reference already closed by another match.",
        "Mark the extra statement line as a duplicate or split booking.",
        0.86,
    ),
    ExceptionType.FX_MISMATCH: (
        "Same economic event is booked in different currencies.",
        "Rebook at the contracted currency or attach the FX conversion ticket.",
        0.84,
    ),
    ExceptionType.UNMATCHED: (
        "No counterpart could be linked with exact, fee-tolerant, or batch rules.",
        "Leave on the exception queue; do not auto-clear.",
        0.7,
    ),
    ExceptionType.PARTIAL_REFUND: (
        "Bank cash is below expected net; a partial refund or capture is likely.",
        "Confirm the refund in the PSP and post the residual, do not force-match.",
        0.82,
    ),
    ExceptionType.ZERO_OR_NEGATIVE_NET: (
        "Settlement net is zero or negative (full refund or chargeback).",
        "Book the refund/chargeback separately; do not close as a sale.",
        0.88,
    ),
    ExceptionType.STATUS_MISMATCH: (
        "Sources disagree on success vs failed/pending.",
        "Hold until the PSP terminal status matches the books.",
        0.84,
    ),
    ExceptionType.DATE_INVERTED: (
        "Bank credit is dated before the payment or before the settlement was created.",
        "Reject the pairing; investigate back-valued entries.",
        0.86,
    ),
    ExceptionType.LATE_SETTLEMENT: (
        "Clearing lagged beyond the allowed banking-day window.",
        "Age the item in-flight and chase the acquirer.",
        0.8,
    ),
    ExceptionType.EMPTY_UTR: (
        "Bank UTR is missing.",
        "Request the UTR from ops before closing.",
        0.83,
    ),
    ExceptionType.MALFORMED_UTR: (
        "Bank UTR failed the format check.",
        "Correct the UTR; do not match on a garbage identifier.",
        0.85,
    ),
    ExceptionType.GST_ZERO_BUG: (
        "Taxable line was booked with GST of zero.",
        "Recompute 18% GST; this is not an exempt supply.",
        0.87,
    ),
    ExceptionType.GST_MISMATCH: (
        "GST is not half-up 18% of gross (beyond 0.05 tolerance).",
        "Recalculate tax before releasing the match.",
        0.8,
    ),
    ExceptionType.MALFORMED_AMOUNT: (
        "Amount is non-finite or unparsable.",
        "Repair the source file; do not reconcile NaN/Inf.",
        0.95,
    ),
    ExceptionType.DUPLICATE_UTR: (
        "The same UTR was ingested more than once.",
        "Drop the duplicate statement line.",
        0.86,
    ),
}


def instance_facts(exception: ReconException) -> str:
    refs = ", ".join(exception.references) or "no reference"
    amount_bits = ", ".join(f"{rid}={amount}" for rid, amount in list(exception.amounts.items())[:6])
    reason = (exception.reason or "").rstrip(".")
    parts = [reason] if reason else []
    parts.append(f"refs {refs}")
    if amount_bits:
        parts.append(f"amounts {amount_bits}")
    sources = ", ".join(s.value for s in exception.sources_involved)
    if sources:
        parts.append(f"sources {sources}")
    return "; ".join(parts)


def ensure_instance_explanation(hypothesis: ExceptionHypothesis, exception: ReconException) -> ExceptionHypothesis:
    """Keep LLM wording when it already cites this row; otherwise prefix engine facts."""
    if cites_instance(hypothesis.explanation, exception):
        return hypothesis
    facts = instance_facts(exception)
    explanation = f"{facts}. {hypothesis.explanation}".strip()
    return hypothesis.model_copy(update={"explanation": explanation})


def rule_hypothesis(exception: ReconException) -> ExceptionHypothesis:
    generic, action, confidence = _RULES.get(
        exception.exception_type,
        (
            "Exception remains on the queue after deterministic matching.",
            "Investigate manually; do not auto-clear.",
            0.65,
        ),
    )
    facts = instance_facts(exception)
    return ExceptionHypothesis(
        hypothesis_type=exception.exception_type,
        explanation=f"{facts}. {generic}",
        suggested_action=action,
        confidence=confidence,
        produced_by="rules",
    )


def attach_explanations(exceptions: list[ReconException]) -> list[ReconException]:
    """Every leftover gets an instance-specific hypothesis. LLM text is kept if it already cites the row."""
    attached: list[ReconException] = []
    for exc in exceptions:
        hyp = exc.hypothesis or rule_hypothesis(exc)
        hyp = ensure_instance_explanation(hyp, exc)
        attached.append(exc.model_copy(update={"hypothesis": hyp}))
    return attached


def explain_leftovers_batch(
    exceptions: list[ReconException],
    *,
    model: str,
    provider: str,
    budget: LlmBudget | None = None,
) -> list[ReconException]:
    """One JSON call for every leftover. Free OpenRouter dies if we tool-loop each row."""
    if not exceptions:
        return exceptions
    payload = [
        {
            "id": exc.exception_id,
            "type": exc.exception_type.value,
            "reason": exc.reason,
            "refs": list(exc.references)[:6],
        }
        for exc in exceptions[:12]
    ]
    ids = [row["id"] for row in payload]
    data = complete_json(
        (
            "Explain every open item. Return one object per id. "
            f"Required ids: {', '.join(ids)}. "
            "Do not mark any as matched. JSON only.\n"
            + json.dumps(payload)
        ),
        model=model,
        provider=provider,
        budget=budget,
        system=(
            "You explain finance leftovers. Reply with JSON only: "
            '{"items":[{"id":"X0001","explanation":"...","suggested_action":"...","confidence":0.7}]}. '
            "Include every required id. Never say an item is matched or closed."
        ),
    )
    rows = data.get("items") if isinstance(data.get("items"), list) else []
    by_id = {
        str(row.get("id")): row
        for row in rows
        if isinstance(row, dict) and row.get("id")
    }
    updated: list[ReconException] = []
    for exc in exceptions:
        row = by_id.get(exc.exception_id)
        if not row:
            updated.append(exc)
            continue
        base = rule_hypothesis(exc)
        try:
            confidence = max(0.0, min(1.0, float(row.get("confidence", 0.6))))
        except (TypeError, ValueError):
            confidence = base.confidence
        updated.append(
            exc.model_copy(
                update={
                    "hypothesis": ExceptionHypothesis(
                        hypothesis_type=exc.exception_type,
                        explanation=str(row.get("explanation") or "").strip() or base.explanation,
                        suggested_action=str(row.get("suggested_action") or "").strip()
                        or base.suggested_action,
                        confidence=confidence,
                        produced_by="llm",
                    )
                }
            )
        )
    if not any(exc.hypothesis and exc.hypothesis.produced_by == "llm" for exc in updated):
        raise LlmUnavailable("LLM did not return a JSON object")
    return updated


def _prompt(exception: ReconException, nearby: list[Record]) -> str:
    sample = [
        {
            "id": r.id,
            "source": r.source.value,
            "reference": r.reference,
            "amount": str(r.amount),
            "currency": r.currency,
            "date": r.txn_date.isoformat(),
            "fee": str(r.fee),
            "batch_id": r.batch_id,
        }
        for r in nearby[:12]
    ]
    return (
        f"Exception {exception.exception_id} type_hint={exception.exception_type.value}\n"
        f"reason={exception.reason}\n"
        f"references={exception.references}\n"
        f"sources={[s.value for s in exception.sources_involved]}\n"
        f"amounts={ {k: str(v) for k, v in exception.amounts.items()} }\n"
        f"nearby_records={sample}\n"
    )


def hypothesize_exception(
    exception: ReconException,
    records: list[Record],
    *,
    model: str,
    provider: str,
    budget: LlmBudget | None = None,
) -> ExceptionHypothesis:
    nearby = [r for r in records if r.reference in set(exception.references) or r.id in set(exception.record_ids)]
    try:
        data = complete_json(
            _prompt(exception, nearby), model=model, provider=provider, budget=budget
        )
        htype = ExceptionType(data["hypothesis_type"])
        return ExceptionHypothesis(
            hypothesis_type=htype,
            explanation=str(data.get("explanation") or "").strip() or rule_hypothesis(exception).explanation,
            suggested_action=str(data.get("suggested_action") or "").strip()
            or rule_hypothesis(exception).suggested_action,
            confidence=max(0.0, min(1.0, float(data.get("confidence", 0.5)))),
            produced_by="llm",
        )
    except (LlmUnavailable, KeyError, ValueError, TypeError):
        return rule_hypothesis(exception)


def annotate_exceptions(
    exceptions: list[ReconException],
    records: list[Record],
    *,
    model: str,
    provider: str,
    budget: LlmBudget | None = None,
) -> list[ReconException]:
    annotated: list[ReconException] = []
    for exc in exceptions:
        annotated.append(
            exc.model_copy(
                update={
                    "hypothesis": hypothesize_exception(
                        exc, records, model=model, provider=provider, budget=budget
                    )
                }
            )
        )
    return annotated
