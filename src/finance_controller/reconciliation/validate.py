from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from finance_controller.config import ReconConfig
from finance_controller.models import Record, Source
from finance_controller.reconciliation.dates import banking_days_between
from finance_controller.reconciliation.engine import _block_close, is_closed_group
from finance_controller.reconciliation.matchers import expected_net, payee_key


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

    payees = {payee_key(r) for r in records if payee_key(r)}
    if len(payees) > 1:
        return ValidationResult(False, [f"payee mismatch: {sorted(payees)}"], ids)

    banks = [r for r in records if r.source == Source.BANK]
    psps = [r for r in records if r.source == Source.PSP]
    ledgers = [r for r in records if r.source == Source.LEDGER]
    bank = banks[0]
    reasons: list[str] = []

    if bank.batch_id:
        total = sum((p.net_amount for p in psps), Decimal("0.00")).quantize(Decimal("0.01"))
        slack = config.amount_tolerance * max(len(psps), 1)
        if abs(bank.amount - total) > slack:
            return ValidationResult(
                False,
                [f"batch bank {bank.amount} != sum of psp nets {total}"],
                ids,
            )
        max_psp = max(p.txn_date for p in psps)
        days = banking_days_between(max_psp, bank.txn_date, config.holidays)
        if days < 0 or days > config.date_lag_days:
            return ValidationResult(False, ["batch settlement date outside banking-day window"], ids)
        if len(ledgers) != len(psps):
            return ValidationResult(False, ["batch ledger count != psp count"], ids)
        if _block_close(records, config):
            return ValidationResult(False, ["blocked by settlement quality gates"], ids)
        reasons.append(f"batch bank {bank.amount} equals {len(psps)} psp nets {total}")
        return ValidationResult(True, reasons, ids)

    if abs(ledgers[0].amount - psps[0].amount) > config.amount_tolerance:
        return ValidationResult(
            False,
            [f"ledger gross {ledgers[0].amount} != psp gross {psps[0].amount}"],
            ids,
        )

    counterpart = psps[0] if psps else ledgers[0]
    net = expected_net(counterpart, config.fee_rate)
    if len(banks) >= 2:
        total = sum((b.amount for b in banks), Decimal("0.00")).quantize(Decimal("0.01"))
        if abs(total - net) > config.amount_tolerance * len(banks):
            return ValidationResult(False, [f"split bank sum {total} != expected net {net}"], ids)
        max_bank = max(b.txn_date for b in banks)
        days = banking_days_between(counterpart.txn_date, max_bank, config.holidays)
        if days < 0 or days > config.date_lag_days:
            return ValidationResult(False, ["split settlement outside banking-day window"], ids)
        if any(b.txn_date < counterpart.txn_date for b in banks):
            return ValidationResult(False, ["split bank credit dated before payment"], ids)
        if _block_close(records, config):
            return ValidationResult(False, ["blocked by settlement quality gates"], ids)
        reasons.append(f"split {len(banks)} credits {total} equal expected net {net}")
        return ValidationResult(True, reasons, ids)

    if bank.amount <= 0:
        return ValidationResult(False, ["zero/negative net cannot close as a sale"], ids)
    if abs(bank.amount - net) > config.amount_tolerance:
        return ValidationResult(
            False,
            [f"bank {bank.amount} outside fee tolerance of expected net {net}"],
            ids,
        )
    days = banking_days_between(counterpart.txn_date, bank.txn_date, config.holidays)
    if days < 0:
        return ValidationResult(False, ["bank dated before payment"], ids)
    if days > config.date_lag_days:
        return ValidationResult(False, ["date lag exceeds configured banking-day window"], ids)
    if _block_close(records, config):
        return ValidationResult(False, ["blocked by settlement quality gates"], ids)
    reasons.append(f"bank {bank.amount} within {config.amount_tolerance} of expected net {net}")
    return ValidationResult(True, reasons, ids)
