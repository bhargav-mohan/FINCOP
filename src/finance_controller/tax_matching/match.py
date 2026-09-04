from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from finance_controller.config import ReconConfig
from finance_controller.models import Record, Source
from finance_controller.tax_matching.models import TaxLine
from finance_controller.tax_matching.validate import validate_tax_match
from finance_controller.reconciliation.identity import compact_reference


@dataclass
class TaxMatch:
    tax_id: str
    ledger_id: str
    references: list[str]
    reason: str


@dataclass
class TaxException:
    tax_id: str
    exception_type: str
    reason: str
    refs: list[str]


@dataclass
class TaxReport:
    matches: list[TaxMatch] = field(default_factory=list)
    exceptions: list[TaxException] = field(default_factory=list)
    ambiguous: list[tuple[TaxLine, list[Record]]] = field(default_factory=list)

    @property
    def match_rate(self) -> float | None:
        total = len(self.matches) + len(self.exceptions)
        return round(len(self.matches) / total, 4) if total else None


def match_tax_lines(
    tax_lines: list[TaxLine],
    ledgers: list[Record],
    config: ReconConfig,
) -> TaxReport:
    ledgers = [r for r in ledgers if r.source == Source.LEDGER]
    by_ref: dict[str, list[Record]] = defaultdict(list)
    for rec in ledgers:
        for key in {compact_reference(rec.reference), rec.reference}:
            if key:
                by_ref[str(key)].append(rec)
    used: set[str] = set()
    report = TaxReport()

    for tax in tax_lines:
        keys = []
        for raw in (tax.payment_id, tax.invoice_id):
            if not raw:
                continue
            keys.append(raw)
            compacted = compact_reference(raw)
            if compacted and compacted != raw:
                keys.append(compacted)
        hits: list[Record] = []
        seen: set[str] = set()
        for key in keys:
            for rec in by_ref.get(key, []):
                if rec.id in used or rec.id in seen:
                    continue
                seen.add(rec.id)
                hits.append(rec)
        if len(hits) > 1:
            valid = [rec for rec in hits if validate_tax_match(tax, rec, config).valid]
            if len(valid) == 1:
                hits = valid
            else:
                report.ambiguous.append((tax, hits))
                continue
        if len(hits) == 1:
            ledger = hits[0]
            check = validate_tax_match(tax, ledger, config)
            if check.valid:
                used.add(ledger.id)
                report.matches.append(
                    TaxMatch(
                        tax_id=tax.id,
                        ledger_id=ledger.id,
                        references=[tax.payment_id or tax.invoice_id, ledger.reference],
                        reason=check.reasons[0],
                    )
                )
            else:
                report.exceptions.append(
                    TaxException(
                        tax_id=tax.id,
                        exception_type="gst_mismatch",
                        reason=check.reasons[0],
                        refs=[tax.payment_id or tax.invoice_id, ledger.reference],
                    )
                )
            continue
        report.exceptions.append(
            TaxException(
                tax_id=tax.id,
                exception_type="unmatched",
                reason="no unique ledger counterpart for tax line",
                refs=[tax.payment_id or tax.invoice_id or tax.id],
            )
        )
    return report
