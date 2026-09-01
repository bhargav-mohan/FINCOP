from __future__ import annotations

from finance_controller.agent.llm import LlmUnavailable, complete_json
from finance_controller.config import ReconConfig
from finance_controller.models import Record
from finance_controller.tax_matching.match import TaxException, TaxMatch, TaxReport
from finance_controller.tax_matching.models import TaxLine
from finance_controller.tax_matching.validate import validate_tax_match

_TAX_SYSTEM = "Reply with JSON keys: ledger_id (string, empty if unsure). JSON only."


def resolve_ambiguous_tax(
    report: TaxReport,
    *,
    config: ReconConfig,
    use_llm: bool,
) -> TaxReport:
    leftover = list(report.ambiguous)
    report.ambiguous = []
    used_ledgers = {m.ledger_id for m in report.matches}
    for tax, candidates in leftover:
        open_cands = [c for c in candidates if c.id not in used_ledgers]
        chosen = _choose(tax, open_cands, config=config, use_llm=use_llm)
        if chosen is None:
            report.exceptions.append(
                TaxException(
                    tax_id=tax.id,
                    exception_type="unmatched",
                    reason="ambiguous tax-ledger relationship; not auto-cleared",
                    refs=[tax.payment_id or tax.invoice_id, *[c.reference for c in candidates]],
                )
            )
            continue
        check = validate_tax_match(tax, chosen, config)
        if not check.valid:
            report.exceptions.append(
                TaxException(
                    tax_id=tax.id,
                    exception_type="gst_mismatch",
                    reason=f"proposal failed tax validator: {check.reasons[0]}",
                    refs=[tax.payment_id or tax.invoice_id, chosen.reference],
                )
            )
            continue
        used_ledgers.add(chosen.id)
        report.matches.append(
            TaxMatch(
                tax_id=tax.id,
                ledger_id=chosen.id,
                references=[tax.payment_id or tax.invoice_id, chosen.reference],
                reason=f"ambiguous tax line closed after validator: {check.reasons[0]}",
            )
        )
    return report


def _choose(
    tax: TaxLine,
    candidates: list[Record],
    *,
    config: ReconConfig,
    use_llm: bool,
) -> Record | None:
    passing = [c for c in candidates if validate_tax_match(tax, c, config).valid]
    if len(passing) == 1:
        return passing[0]
    if not use_llm:
        return None
    try:
        data = complete_json(
            (
                "Pick at most one ledger id for this tax line.\n"
                f"tax_id={tax.id} taxable={tax.taxable_value} gst={tax.gst_amount}\n"
                f"candidates={[{'id': c.id, 'reference': c.reference, 'amount': str(c.amount)} for c in candidates]}"
            ),
            model=config.model,
            provider=config.provider,
            system=_TAX_SYSTEM,
        )
    except (LlmUnavailable, TypeError, ValueError):
        return None
    proposed = str(data.get("ledger_id") or "").strip()
    return next((c for c in candidates if c.id == proposed), None)
