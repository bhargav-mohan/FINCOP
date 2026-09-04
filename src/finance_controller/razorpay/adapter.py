from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from finance_controller.data.synthetic import SyntheticBatch
from finance_controller.ingestion.detect import FileRole
from finance_controller.ingestion.normalize import write_canonical
from finance_controller.models import PaymentStatus, Record, Source
from finance_controller.razorpay.schema import (
    PAYMENT_TYPE,
    REFUND_TYPE,
    SKIP_TYPES,
    parse_razorpay_amount,
)
from finance_controller.reconciliation.normalize import parse_date


@dataclass
class AdapterResult:
    payments: list[dict[str, str]]
    settlements: list[dict[str, str]]
    bank: list[dict[str, str]]
    batch: SyntheticBatch = field(default_factory=SyntheticBatch)
    warnings: list[str] = field(default_factory=list)


def _cell(row: dict[str, str], *names: str) -> str:
    by_norm = {k.strip().lower().replace(" ", "_"): (v if v is not None else "") for k, v in row.items()}
    for name in names:
        value = by_norm.get(name, "")
        if str(value).strip():
            return str(value).strip()
    return ""


def _parse_when(value: str) -> str:
    if not value:
        return ""
    if value.isdigit():
        ts = datetime.fromtimestamp(int(value), tz=timezone.utc)
        return ts.date().isoformat()
    return value[:10]


def _truthy(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "settled"}


def _statement_token(settlement_id: str) -> str:
    """Sponsor-bank reference derived from the settlement id.

    Kept to 12-22 alnum chars so it passes the UTR format check, and derived from
    the whole id rather than a digit fingerprint so distinct settlements stay
    distinct.
    """
    token = "".join(ch for ch in settlement_id.upper() if ch.isalnum())
    return token.ljust(12, "X")[:22]


def _statement_utr(settlement_id: str) -> str:
    return _statement_token(settlement_id)


def _statement_ref(settlement_id: str) -> str:
    return f"NEFT-{_statement_token(settlement_id)}"


def _mdr_and_gst(fee: Decimal, tax: Decimal) -> tuple[Decimal, Decimal]:
    """Razorpay `fee` usually includes `tax`. Split so gst_on_mdr(mdr) can be checked."""
    if tax > 0 and tax <= fee:
        return (fee - tax).quantize(Decimal("0.01")), tax
    return fee.quantize(Decimal("0.01")), tax.quantize(Decimal("0.01"))


def _status(value: str) -> PaymentStatus:
    raw = (value or "success").strip().lower()
    try:
        return PaymentStatus(raw)
    except ValueError:
        return PaymentStatus.SUCCESS


def razorpay_recon_to_canonical(rows: list[dict[str, str]]) -> AdapterResult:
    warnings: list[str] = []
    grouped: dict[str, list[dict[str, str]]] = defaultdict(list)
    orphan_index = 0

    for i, row in enumerate(rows, start=2):
        kind = (_cell(row, "type") or PAYMENT_TYPE).lower()
        if kind in SKIP_TYPES:
            eid = _cell(row, "entity_id") or f"row {i}"
            warnings.append(f"skipped Razorpay {kind} {eid}: not mapped to ledger/psp/bank")
            continue
        if kind not in {PAYMENT_TYPE, REFUND_TYPE}:
            eid = _cell(row, "entity_id") or f"row {i}"
            warnings.append(f"skipped unknown Razorpay type {kind!r} on {eid}")
            continue
        sid = _cell(row, "settlement_id")
        if not sid:
            orphan_index += 1
            sid = f"UNSETTLED-{orphan_index:04d}"
            warnings.append(f"row {i} has no settlement_id; grouped as {sid}")
        grouped[sid].append(row)

    payments: dict[str, dict[str, str]] = {}
    settlements: list[dict[str, str]] = []
    bank_rows: list[dict[str, str]] = []
    batch = SyntheticBatch()
    utr_uses: Counter[str] = Counter()

    parsed_groups: list[tuple[str, list[dict], dict]] = []

    for sid, members in grouped.items():
        pay_ids: list[str] = []
        lines: list[dict] = []
        gross = Decimal("0.00")
        mdr_total = Decimal("0.00")
        gst_total = Decimal("0.00")
        net = Decimal("0.00")
        utr = ""
        settled_date = ""
        any_settled = False

        for row in members:
            kind = (_cell(row, "type") or PAYMENT_TYPE).lower()
            amount = parse_razorpay_amount(_cell(row, "amount"))
            fee = parse_razorpay_amount(_cell(row, "fee"))
            tax = parse_razorpay_amount(_cell(row, "tax"))
            credit = parse_razorpay_amount(_cell(row, "credit"))
            debit = parse_razorpay_amount(_cell(row, "debit"))
            mdr, gst = _mdr_and_gst(fee, tax)
            pid = _cell(row, "payment_id", "entity_id")
            created = _parse_when(_cell(row, "created_at"))
            settled_at = _parse_when(_cell(row, "settled_at"))
            customer = _cell(row, "notes") or _cell(row, "method") or "RAZORPAY"
            currency = _cell(row, "currency") or "INR"
            if currency.upper() != "INR":
                warnings.append(f"{pid or sid}: currency {currency} passed through as-is")
            settled_flag = _cell(row, "settled")
            if settled_flag == "" or _truthy(settled_flag):
                any_settled = True
            if not utr:
                utr = _cell(row, "settlement_utr")
            if not settled_date and settled_at:
                settled_date = settled_at
            if not settled_date and created:
                settled_date = created

            line_net = credit if kind == PAYMENT_TYPE else (Decimal("0.00") - (debit if debit else amount))
            if kind == PAYMENT_TYPE:
                if not credit:
                    line_net = amount - fee if fee else amount - mdr - gst
                if not pid:
                    warnings.append(f"settlement {sid}: payment row missing payment_id/entity_id")
                    continue
                pay_ids.append(pid)
                gross += amount
                mdr_total += mdr
                gst_total += gst
                net += line_net
                if pid not in payments:
                    payments[pid] = {
                        "payment_id": pid,
                        "amount": str(amount),
                        "customer": customer,
                        "timestamp": created or settled_date,
                        "status": "success",
                    }
            else:
                net += line_net
                mdr_total += mdr
                gst_total += gst
                if pid:
                    if pid in payments:
                        payments[pid]["status"] = "refunded"
                    else:
                        payments[pid] = {
                            "payment_id": pid,
                            "amount": str(amount),
                            "customer": customer,
                            "timestamp": created or settled_date,
                            "status": "refunded",
                        }
                        pay_ids.append(pid)
            lines.append(
                {
                    "kind": kind,
                    "pid": pid,
                    "amount": amount,
                    "mdr": mdr,
                    "gst": gst,
                    "fee_incl": (mdr + gst).quantize(Decimal("0.01")),
                    "net": line_net.quantize(Decimal("0.01")),
                    "customer": customer,
                    "currency": currency,
                    "created": created or settled_date,
                    "order_id": _cell(row, "order_id"),
                    "entity_id": _cell(row, "entity_id"),
                    "status": "refunded" if kind == REFUND_TYPE else "success",
                }
            )

        unique_pids = list(dict.fromkeys(pay_ids))
        if not unique_pids:
            warnings.append(f"settlement {sid}: no payment/refund ids after mapping")
            continue

        net = net.quantize(Decimal("0.01"))
        gross = gross.quantize(Decimal("0.01"))
        mdr_total = mdr_total.quantize(Decimal("0.01"))
        gst_total = gst_total.quantize(Decimal("0.01"))
        if gross == 0:
            gross = sum((line["amount"] for line in lines), Decimal("0.00")).quantize(Decimal("0.01"))

        settlements.append(
            {
                "settlement_id": sid,
                "payment_ids": "|".join(unique_pids),
                "gross_amount": str(gross),
                "mdr_fee": str(mdr_total),
                "gst_on_fee": str(gst_total),
                "net_amount": str(net),
                "utr": utr,
                "settled_date": settled_date,
            }
        )
        if utr:
            utr_uses[utr] += 1
        meta = {
            "utr": utr,
            "settled_date": settled_date,
            "any_settled": any_settled,
            "net": net,
            "unique_pids": unique_pids,
        }
        parsed_groups.append((sid, lines, meta))
        if any_settled:
            batched = len(unique_pids) > 1
            bank_rows.append(
                {
                    "payment_reference": unique_pids[0] if len(unique_pids) == 1 else sid,
                    "batch_id": sid if batched else "",
                    "utr": utr,
                    "credited_amount": str(net),
                    "credited_date": settled_date,
                    "raw_description": f"NEFT CR RAZORPAY SETTLEMENT {sid}",
                }
            )
        else:
            warnings.append(f"settlement {sid}: not settled; no bank credit emitted")

    for sid, lines, meta in parsed_groups:
        unique_pids = meta["unique_pids"]
        batched = len(unique_pids) > 1
        batch_id = sid if batched else None
        utr = meta["utr"]
        settled_date = meta["settled_date"] or "2026-01-01"
        dup = bool(utr and utr_uses[utr] > 1)
        pay_status = {p: payments[p]["status"] for p in unique_pids if p in payments}

        for line in lines:
            pid = line["pid"]
            if not pid:
                continue
            extra = {"gst_on_mdr": True, "mdr_fee": str(line["mdr"]), "settlement_id": sid}
            if line.get("order_id"):
                extra["order_id"] = line["order_id"]
            if line.get("entity_id") and line["entity_id"] != pid:
                extra["entity_id"] = line["entity_id"]
            if dup:
                extra["duplicate_utr"] = True
            if line["status"] == "refunded" or line["net"] <= 0:
                extra["refund"] = True
            status = _status(pay_status.get(pid, line["status"]))
            created = parse_date(line["created"] or settled_date)
            settled = parse_date(settled_date)
            if line["kind"] == PAYMENT_TYPE or pid not in {r.reference for r in batch.ledger}:
                batch.ledger.append(
                    Record(
                        id=pid,
                        source=Source.LEDGER,
                        reference=pid,
                        amount=line["amount"],
                        currency=line["currency"],
                        txn_date=created,
                        payee=line["customer"],
                        description=f"payment {pid}",
                        batch_id=batch_id,
                        utr=utr,
                        status=status,
                        gst=line["gst"],
                        created_date=created,
                        extra=dict(extra),
                    )
                )
            batch.psp.append(
                Record(
                    id=f"{sid}-{pid}" if batched else sid,
                    source=Source.PSP,
                    reference=pid,
                    amount=line["amount"],
                    currency=line["currency"],
                    txn_date=settled,
                    fee=line["fee_incl"],
                    payee=line["customer"],
                    description=f"settlement {sid}",
                    batch_id=batch_id,
                    utr=utr,
                    status=status,
                    gst=line["gst"],
                    created_date=settled,
                    extra=dict(extra),
                )
            )

        if meta["any_settled"]:
            bank_extra: dict = {}
            if dup:
                bank_extra["duplicate_utr"] = True
            if meta["net"] <= 0:
                bank_extra["refund"] = True
            bank_utr = utr
            narration = f"NEFT CR RAZORPAY SETTLEMENT {sid}"
            if batched:
                reference = sid
            elif unique_pids:
                reference = unique_pids[0]
            else:
                reference = sid
            payee = ""
            if len(unique_pids) == 1 and unique_pids[0] in payments:
                payee = payments[unique_pids[0]].get("customer") or ""
            if not utr:
                if len(unique_pids) == 1:
                    # Money landed but the export has not published the UTR yet.
                    # The statement line still exists, carrying the sponsor bank's
                    # own reference with the payment id only in free text. Nothing
                    # links it by reference, UTR or payee, so the deterministic
                    # tiers cannot claim it and it goes to the agent, which must
                    # still pass the validator to close it.
                    bank_utr = _statement_utr(sid)
                    reference = _statement_ref(sid)
                    payee = ""
                    narration = (
                        f"NEFT CR: HDFC {bank_utr} RAZORPAY SETTLEMENT {unique_pids[0]}"
                    )
                    bank_extra["narration_only"] = True
                    bank_extra["true_reference"] = unique_pids[0]
                else:
                    # A batched payout with no UTR cannot be pinned to one payment.
                    bank_extra["empty_utr"] = True
            batch.bank.append(
                Record(
                    id=f"B-{sid}",
                    source=Source.BANK,
                    reference=reference,
                    amount=meta["net"],
                    currency="INR",
                    txn_date=parse_date(settled_date),
                    payee=payee,
                    description=narration,
                    batch_id=batch_id,
                    utr=bank_utr,
                    status=PaymentStatus.SUCCESS,
                    created_date=parse_date(settled_date),
                    extra=bank_extra,
                )
            )

    return AdapterResult(
        payments=list(payments.values()),
        settlements=settlements,
        bank=bank_rows,
        batch=batch,
        warnings=warnings,
    )


def write_adapted_canonical(dest: Path, adapted: AdapterResult) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    write_canonical(dest / "payments.csv", FileRole.LEDGER, adapted.payments)
    write_canonical(dest / "settlements.csv", FileRole.PSP, adapted.settlements)
    write_canonical(dest / "bank.csv", FileRole.BANK, adapted.bank)
