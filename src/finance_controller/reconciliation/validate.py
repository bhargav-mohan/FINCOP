from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from finance_controller.config import ReconConfig
from finance_controller.models import Record, Source
from finance_controller.reconciliation.dates import banking_days_between
from finance_controller.reconciliation.engine import _amounts_ok, _block_close, _gst_block, is_closed_group
from finance_controller.reconciliation.identity import names_compatible, payee_key
from finance_controller.reconciliation.matchers import expected_net


@dataclass
class ValidationResult:
    valid: bool
    reasons: list[str] = field(default_factory=list)
    record_ids: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "valid": self.valid,
            "reasons": self.reasons,
            "record_ids": self.record_ids,
        }


def _engine_block_reasons(records: list[Record], config: ReconConfig) -> list[str]:
    """Explain a _block_close hit using the same predicates the engine close path uses."""
    gst_hit = _gst_block(records)
    if gst_hit:
        return [gst_hit[1]]
    if not _amounts_ok(records, config):
        banks = [r for r in records if r.source == Source.BANK]
        psps = [r for r in records if r.source == Source.PSP]
        ledgers = [r for r in records if r.source == Source.LEDGER]
        bank = banks[0]
        if bank.amount <= 0:
            return ["zero/negative net cannot close as a sale"]
        if bank.batch_id:
            total = sum((p.net_amount for p in psps), Decimal("0.00")).quantize(Decimal("0.01"))
            return [f"batch bank {bank.amount} != sum of psp nets {total}"]
        counterpart = psps[0] if psps else ledgers[0]
        net = expected_net(counterpart, config.fee_rate)
        if len(banks) >= 2:
            total = sum((b.amount for b in banks), Decimal("0.00")).quantize(Decimal("0.01"))
            return [f"split bank sum {total} != expected net {net}"]
        return [f"bank {bank.amount} outside fee tolerance of expected net {net}"]
    banks = [r for r in records if r.source == Source.BANK]
    psps = [r for r in records if r.source == Source.PSP]
    ledgers = [r for r in records if r.source == Source.LEDGER]
    counterpart_rows = psps or ledgers
    start = max(r.txn_date for r in counterpart_rows)
    max_bank = max(b.txn_date for b in banks)
    days = banking_days_between(start, max_bank, config.holidays)
    if days < 0:
        return ["bank dated before payment"]
    if days > config.date_lag_days:
        return ["date lag exceeds configured banking-day window"]
    return ["blocked by settlement quality gates"]


def validate_proposed_match(
    records: list[Record],
    config: ReconConfig,
    closed_ids: set[str],
) -> ValidationResult:
    ids = [r.id for r in records]
    if not records:
        return ValidationResult(False, ["no records proposed"], [])
    dup = [i for i in ids if ids.count(i) > 1]
    if dup:
        return ValidationResult(False, [f"duplicate ids in proposal: {sorted(set(dup))}"], ids)
    already = [r.id for r in records if r.id in closed_ids]
    if already:
        return ValidationResult(False, [f"records already closed: {already}"], ids)
    if not is_closed_group(records):
        return ValidationResult(
            False,
            ["group is not a closable cash loop (need 1 bank + matching ledger/psp counts)"],
            ids,
        )

    currencies = {r.currency for r in records}
    if len(currencies) > 1:
        return ValidationResult(False, [f"currency mismatch: {sorted(currencies)}"], ids)

    named = [r.payee for r in records if payee_key(r)]
    if len(named) >= 2:
        mismatched = False
        for i, left in enumerate(named):
            for right in named[i + 1 :]:
                if not names_compatible(left, right):
                    mismatched = True
                    break
            if mismatched:
                break
        if mismatched:
            return ValidationResult(
                False,
                [f"payee mismatch: {sorted({payee_key(r) for r in records if payee_key(r)})}"],
                ids,
            )

    banks = [r for r in records if r.source == Source.BANK]
    psps = [r for r in records if r.source == Source.PSP]
    ledgers = [r for r in records if r.source == Source.LEDGER]
    bank = banks[0]

    # Ledger vs PSP gross is not in _block_close (matchers already require it).
    if not bank.batch_id and ledgers and psps:
        if abs(ledgers[0].amount - psps[0].amount) > config.amount_tolerance:
            return ValidationResult(
                False,
                [f"ledger gross {ledgers[0].amount} != psp gross {psps[0].amount}"],
                ids,
            )

    if _block_close(records, config):
        return ValidationResult(False, _engine_block_reasons(records, config), ids)

    reasons: list[str] = []
    if bank.batch_id:
        total = sum((p.net_amount for p in psps), Decimal("0.00")).quantize(Decimal("0.01"))
        reasons.append(f"batch bank {bank.amount} equals {len(psps)} psp nets {total}")
    elif len(banks) >= 2:
        counterpart = psps[0] if psps else ledgers[0]
        net = expected_net(counterpart, config.fee_rate)
        total = sum((b.amount for b in banks), Decimal("0.00")).quantize(Decimal("0.01"))
        reasons.append(f"split {len(banks)} credits {total} equal expected net {net}")
    else:
        counterpart = psps[0] if psps else ledgers[0]
        net = expected_net(counterpart, config.fee_rate)
        reasons.append(f"bank {bank.amount} within {config.amount_tolerance} of expected net {net}")
    return ValidationResult(True, reasons, ids)
