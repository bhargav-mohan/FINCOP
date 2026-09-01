from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from dateutil import parser as date_parser

from finance_controller.models import Record
from finance_controller.reconciliation.utr import normalize_utr


def parse_date(value: date | datetime | str) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date_parser.parse(str(value)).date()


def parse_amount(value: Decimal | int | float | str) -> Decimal:
    try:
        amount = Decimal(str(value))
    except InvalidOperation as exc:
        raise ValueError(f"invalid amount: {value!r}") from exc
    if not amount.is_finite():
        raise ValueError(f"non-finite amount: {value!r}")
    return amount.quantize(Decimal("0.01"))


def normalize_reference(value: str) -> str:
    return str(value).strip().upper()


def normalize_currency(value: str) -> str:
    return str(value).strip().upper()


def normalize_payee(value: str) -> str:
    return " ".join(str(value).strip().upper().split())


def normalize_record(record: Record) -> Record:
    extra = dict(record.extra)
    try:
        amount = parse_amount(record.amount)
        fee = parse_amount(record.fee)
        gst = parse_amount(record.gst)
    except ValueError:
        extra["malformed_amount"] = True
        amount = Decimal("0.00")
        fee = Decimal("0.00")
        gst = Decimal("0.00")
    created = parse_date(record.created_date) if record.created_date else parse_date(record.txn_date)
    return record.model_copy(
        update={
            "reference": normalize_reference(record.reference),
            "currency": normalize_currency(record.currency),
            "payee": normalize_payee(record.payee),
            "amount": amount,
            "fee": fee,
            "gst": gst,
            "utr": normalize_utr(record.utr),
            "txn_date": parse_date(record.txn_date),
            "created_date": created,
            "batch_id": normalize_reference(record.batch_id) if record.batch_id else None,
            "split_id": normalize_reference(record.split_id) if record.split_id else None,
            "extra": extra,
        }
    )


def normalize_records(records: list[Record]) -> list[Record]:
    return [normalize_record(r) for r in records]
