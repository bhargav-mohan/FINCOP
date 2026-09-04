from __future__ import annotations

import csv
import json
from collections import Counter, defaultdict
from decimal import Decimal
from pathlib import Path

from finance_controller.data.synthetic import SyntheticBatch
from finance_controller.models import (
    CaseCategory,
    ExceptionType,
    ExpectedStatus,
    GroundTruth,
    PaymentStatus,
    Record,
    Source,
)
from finance_controller.reconciliation.normalize import parse_amount, parse_date

_MATCH_LABELS = frozenset(
    {
        "clean_match",
        "late_clearing",
        "aggregated",
        "rounding_drift",
        "aggregated_settlement",
        "resolve",
        "resolve_or_tolerate",
    }
)
_LABEL_TYPE = {
    "refund": ExceptionType.ZERO_OR_NEGATIVE_NET,
    "refund_net_negative": ExceptionType.ZERO_OR_NEGATIVE_NET,
    "duplicate_utr_conflict": ExceptionType.DUPLICATE_UTR,
    "gst_mismatch": ExceptionType.GST_MISMATCH,
    "gst_fee_mismatch": ExceptionType.GST_MISMATCH,
    "missing_bank_credit": ExceptionType.MISSING_IN_BANK,
    "orphan_bank_credit": ExceptionType.UNMATCHED,
    "undocumented_adjustment": ExceptionType.AMOUNT_MISMATCH,
    "late_clearing_t+4": ExceptionType.LATE_SETTLEMENT,
    "late_clearing_t+5": ExceptionType.LATE_SETTLEMENT,
    "currency_mismatch": ExceptionType.FX_MISMATCH,
    "date_inverted": ExceptionType.DATE_INVERTED,
    "empty_utr": ExceptionType.EMPTY_UTR,
    "malformed_utr": ExceptionType.MALFORMED_UTR,
}
_MATCHED_HANDLING = frozenset({"resolve", "resolve_or_tolerate", "match", "matched", "tolerate"})


def _norm_label(value: str) -> str:
    return (value or "").strip().lower().replace(" ", "_")


def normalize_truth_rows(rows: list[dict] | dict) -> list[dict]:
    """Accept JSON lists or Excel GT sheets (exception_type + expected_handling)."""
    if isinstance(rows, dict):
        rows = rows.get("rows") or rows.get("ground_truth") or []
    out: list[dict] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        if row.get("key") and row.get("expected_status"):
            out.append(row)
            continue
        if row.get("label"):
            out.append(row)
            continue
        handling = _norm_label(str(row.get("expected_handling") or ""))
        etype = _norm_label(str(row.get("exception_type") or row.get("type") or ""))
        if handling in _MATCHED_HANDLING or etype in _MATCH_LABELS:
            label = "clean_match" if etype not in _MATCH_LABELS else etype.replace("-", "_")
            if etype in {"aggregated_settlement", "rounding_drift"}:
                label = etype
            out.append({**row, "label": label})
            continue
        label = etype if etype in _LABEL_TYPE else (etype or "unmatched")
        out.append({**row, "label": label})
    return out


def apply_ground_truth(batch: SyntheticBatch, truth_rows: list[dict] | dict) -> None:
    """Attach GT labels. Keys are uppercased to match normalized references."""
    seen_dup_utr: set[str] = set()
    for row in normalize_truth_rows(truth_rows):
        if row.get("key") and row.get("expected_status") and not row.get("label"):
            data = dict(row)
            data["key"] = str(data["key"]).strip()
            batch.ground_truth.append(GroundTruth.model_validate(data))
            continue
        label = row.get("label") or ""
        pid = (row.get("payment_id") or "").strip().upper()
        utr = (row.get("utr") or "").strip().upper()
        if label in _MATCH_LABELS:
            sid = (row.get("settlement_id") or "").strip().upper()
            if label in {"aggregated", "aggregated_settlement"} or "|" in pid:
                key = sid or pid or utr
            else:
                key = pid or utr
            batch.ground_truth.append(
                GroundTruth(
                    key=key,
                    expected_status=ExpectedStatus.MATCHED,
                    category=CaseCategory.CLEAN,
                    defect=label,
                    record_ids=[],
                )
            )
            continue
        etype = _LABEL_TYPE.get(label, ExceptionType.UNMATCHED)
        keys = [pid] if pid else []
        if not pid and utr:
            keys = [utr]
        if label == "duplicate_utr_conflict" and utr not in seen_dup_utr:
            seen_dup_utr.add(utr)
            keys.append(utr)
        for key in keys:
            if not key:
                continue
            batch.ground_truth.append(
                GroundTruth(
                    key=key,
                    expected_status=ExpectedStatus.EXCEPTION,
                    exception_type=etype,
                    category=CaseCategory.IRRESOLVABLE,
                    defect=label,
                    record_ids=[],
                )
            )


def _ccy(row: dict, default: str = "INR") -> str:
    value = (row.get("currency") or default).strip()
    return value or default


def _money(value: object) -> Decimal:
    if value is None or str(value).strip() == "":
        return Decimal("0.00")
    return parse_amount(value)


def _status(value: str) -> PaymentStatus:
    raw = (value or "success").strip().lower()
    if raw in {"paid", "settled", "captured", "cleared", "success"}:
        return PaymentStatus.SUCCESS
    if raw in {"refund", "refunded", "reversed"}:
        return PaymentStatus.REFUNDED
    try:
        return PaymentStatus(raw)
    except ValueError:
        return PaymentStatus.SUCCESS


def _cell(row: dict, *names: str) -> str:
    for name in names:
        value = (row.get(name) or "").strip()
        if value:
            return value
    return ""


def _money_str(value: Decimal) -> str:
    return str(value.quantize(Decimal("0.01")))


def _dump_extra(extra: dict | None) -> str:
    if not extra:
        return ""
    return json.dumps(extra, separators=(",", ":"), default=str)


def _parse_extra(row: dict) -> dict:
    raw = (row.get("extra") or "").strip()
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _psp_fee_gst_net(rec: Record) -> tuple[Decimal, Decimal, Decimal]:
    mdr = rec.fee
    gst = rec.gst if rec.extra.get("gst_on_mdr") else Decimal("0.00")
    net = (rec.amount - mdr - gst).quantize(Decimal("0.01"))
    return mdr, gst, net


def _bank_loop_identity(
    row: dict,
    *,
    utr: str,
    settlements: list[dict],
    pay_by_id: dict[str, dict],
    n: int,
) -> tuple[str, str | None, str]:
    """Loop key is payment reference / batch_id. UTR is not a grouping key."""
    explicit_ref = _cell(row, "payment_reference", "payment_id")
    explicit_batch = _cell(row, "batch_id") or None
    if explicit_ref or explicit_batch:
        reference = explicit_ref or explicit_batch
        payee = _cell(row, "customer", "payee")
        if not payee and explicit_batch is None:
            payee = pay_by_id.get(reference, {}).get("customer") or ""
        return reference, explicit_batch, payee

    matching = [s for s in settlements if (s.get("utr") or "").strip() == utr and utr]
    pids: list[str] = []
    batch_id = None
    if len(matching) == 1:
        pids = [p.strip() for p in matching[0].get("payment_ids", "").split("|") if p.strip()]
        if len(pids) > 1:
            batch_id = matching[0]["settlement_id"]
    if batch_id:
        reference = batch_id
    elif len(pids) == 1:
        reference = pids[0]
    else:
        reference = utr or f"BANK-{n}"
    payee = ""
    if len(pids) == 1:
        payee = pay_by_id.get(pids[0], {}).get("customer") or ""
    return reference, batch_id, payee


def write_csv_batch(batch: SyntheticBatch, dest: str | Path) -> Path:
    """Dump a generated batch with the same loop key generate() uses internally."""
    from finance_controller.ingestion.detect import FileRole
    from finance_controller.ingestion.normalize import write_canonical

    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    write_canonical(
        dest / "payments.csv",
        FileRole.LEDGER,
        [
            {
                "payment_id": rec.reference,
                "amount": _money_str(rec.amount),
                "customer": rec.payee,
                "timestamp": rec.txn_date.isoformat(),
                "status": rec.status.value,
                "currency": rec.currency,
                "split_id": rec.split_id or "",
                "extra": _dump_extra(rec.extra),
            }
            for rec in batch.ledger
        ],
    )

    stl_rows: list[dict[str, str]] = []
    grouped: dict[str, list[Record]] = defaultdict(list)
    singles: list[Record] = []
    for rec in batch.psp:
        if rec.batch_id:
            grouped[rec.batch_id].append(rec)
        else:
            singles.append(rec)
    bank_by_batch = {b.batch_id: b for b in batch.bank if b.batch_id}

    def emit_settlement(sid: str, recs: list[Record], utr: str) -> None:
        gross = sum((r.amount for r in recs), Decimal("0.00"))
        mdr = gst = net = Decimal("0.00")
        for rec in recs:
            dm, dg, dn = _psp_fee_gst_net(rec)
            mdr += dm
            gst += dg
            net += dn
        stl_rows.append(
            {
                "settlement_id": sid,
                "payment_ids": "|".join(r.reference for r in recs),
                "gross_amount": _money_str(gross),
                "mdr_fee": _money_str(mdr),
                "gst_on_fee": _money_str(gst),
                "net_amount": _money_str(net),
                "utr": utr,
                "settled_date": max(r.txn_date for r in recs).isoformat(),
                "currency": recs[0].currency,
                "customer": recs[0].payee if len(recs) == 1 else "",
                "status": recs[0].status.value if len(recs) == 1 else "",
                "split_id": recs[0].split_id or "" if len(recs) == 1 else "",
                "extra": _dump_extra(recs[0].extra if len(recs) == 1 else {}),
            }
        )

    for bid, recs in grouped.items():
        bank = bank_by_batch.get(bid)
        emit_settlement(bid, recs, (bank.utr if bank else recs[0].utr) or "")
    for rec in singles:
        sid = str(rec.extra.get("settlement_id") or rec.id)
        emit_settlement(sid, [rec], rec.utr or "")
    write_canonical(dest / "settlements.csv", FileRole.PSP, stl_rows)

    bank_rows: list[dict[str, str]] = []
    for rec in batch.bank:
        desc = rec.description or ""
        if rec.extra.get("orphan") and "UNKNOWN" not in desc.upper():
            desc = f"UNKNOWN {desc}"
        bank_rows.append(
            {
                "payment_reference": rec.reference,
                "batch_id": rec.batch_id or "",
                "split_id": rec.split_id or "",
                "utr": rec.utr,
                "credited_amount": _money_str(rec.amount),
                "credited_date": rec.txn_date.isoformat(),
                "raw_description": desc,
                "currency": rec.currency,
                "customer": rec.payee,
                "status": rec.status.value,
                "extra": _dump_extra(rec.extra),
            }
        )
    write_canonical(dest / "bank.csv", FileRole.BANK, bank_rows)
    if batch.ground_truth:
        (dest / "ground_truth.json").write_text(
            json.dumps([g.model_dump(mode="json") for g in batch.ground_truth], indent=2),
            encoding="utf-8",
        )
    return dest


def load_csv_batch(data_dir: str | Path) -> SyntheticBatch:
    root = Path(data_dir)
    payments_path = root / "payments.csv"
    settlements_path = root / "settlements.csv"
    bank_path = root / "bank.csv"
    truth_path = root / "ground_truth.json"
    if not payments_path.exists() or not settlements_path.exists() or not bank_path.exists():
        raise FileNotFoundError(f"expected payments.csv, settlements.csv, bank.csv in {root}")

    with payments_path.open(newline="", encoding="utf-8") as fh:
        payments = list(csv.DictReader(fh))
    with settlements_path.open(newline="", encoding="utf-8") as fh:
        settlements = list(csv.DictReader(fh))
    with bank_path.open(newline="", encoding="utf-8") as fh:
        bank_rows = list(csv.DictReader(fh))
    truth_rows: list[dict] = []
    if truth_path.exists():
        truth_rows = json.loads(truth_path.read_text(encoding="utf-8"))

    utr_uses = Counter(
        u for row in settlements if (u := (row.get("utr") or "").strip())
    )
    pay_by_id = {row["payment_id"]: row for row in payments}

    out = SyntheticBatch()
    seq = 0

    def nid(prefix: str) -> str:
        nonlocal seq
        seq += 1
        return f"{prefix}{seq:05d}"

    settlement_by_pay: dict[str, dict] = {}
    duplicate_settlement_pids: set[str] = set()
    for stl in settlements:
        for pid in (stl.get("payment_ids") or "").split("|"):
            pid = pid.strip()
            if not pid:
                continue
            if pid in settlement_by_pay:
                duplicate_settlement_pids.add(pid)
                continue
            settlement_by_pay[pid] = stl

    for pay in payments:
        pid = pay["payment_id"]
        stl = settlement_by_pay.get(pid, {})
        pids = [p.strip() for p in (stl.get("payment_ids") or "").split("|") if p.strip()]
        batched = len(pids) > 1
        batch_id = stl.get("settlement_id") if batched else None
        extra = {"mdr_fee": str(stl.get("mdr_fee") or "0")} if stl else {}
        if stl and stl.get("gst_on_fee") not in (None, "", "0", "0.00", "0.0"):
            extra["gst_on_mdr"] = True
        if pid in duplicate_settlement_pids:
            extra["duplicate_settlement"] = True
        utr = (stl.get("utr") or "").strip()
        if utr and utr_uses.get(utr, 0) > 1:
            extra["duplicate_utr"] = True
        status = _status(pay.get("status", "success"))
        if status == PaymentStatus.REFUNDED:
            extra["refund"] = True
        extra = {**extra, **_parse_extra(pay)}
        out.ledger.append(
            Record(
                id=pid,
                source=Source.LEDGER,
                reference=pid,
                amount=_money(pay["amount"]),
                currency=_ccy(pay),
                txn_date=parse_date(pay["timestamp"]),
                payee=pay.get("customer") or "",
                description=f"payment {pid}",
                batch_id=batch_id,
                split_id=_cell(pay, "split_id") or None,
                utr=(stl.get("utr") or "").strip(),
                status=status,
                gst=_money(stl["gst_on_fee"]) if stl.get("gst_on_fee") not in (None, "") else Decimal("0.00"),
                created_date=parse_date(pay["timestamp"]),
                extra=extra,
            )
        )

    for stl in settlements:
        pids = [p.strip() for p in (stl.get("payment_ids") or "").split("|") if p.strip()]
        batched = len(pids) > 1
        batch_id = stl["settlement_id"] if batched else None
        gross = _money(stl["gross_amount"])
        mdr = _money(stl["mdr_fee"])
        gst = _money(stl["gst_on_fee"])
        net = _money(stl["net_amount"])
        utr = (stl.get("utr") or "").strip()
        settled = parse_date(stl["settled_date"])
        extra_base = {"mdr_fee": str(mdr), "settlement_id": stl["settlement_id"]}
        if stl.get("gst_on_fee") not in (None, "", "0", "0.00", "0.0"):
            extra_base["gst_on_mdr"] = True
        if utr and utr_uses[utr] > 1:
            extra_base["duplicate_utr"] = True
        if net <= 0:
            extra_base["refund"] = True
        extra_base = {
            **extra_base,
            **_parse_extra(stl),
            **_parse_extra(pay_by_id.get(pids[0], {}) if pids else {}),
        }

        if not batched:
            pid = pids[0] if pids else stl["settlement_id"]
            pay = pay_by_id.get(pid, {})
            status = _status(stl.get("status") or pay.get("status") or "success")
            out.psp.append(
                Record(
                    id=stl["settlement_id"],
                    source=Source.PSP,
                    reference=pid,
                    amount=gross,
                    currency=_ccy(stl) if stl.get("currency") else _ccy(pay),
                    txn_date=settled,
                    fee=(mdr + gst).quantize(Decimal("0.01")),
                    payee=pay.get("customer") or stl.get("customer") or "",
                    description=f"settlement {stl['settlement_id']}",
                    batch_id=None,
                    split_id=_cell(stl, "split_id") or _cell(pay, "split_id") or None,
                    utr=utr,
                    status=status,
                    gst=gst,
                    created_date=settled,
                    extra=extra_base,
                )
            )
            continue

        remaining_net = net
        remaining_mdr = mdr
        remaining_gst = gst
        for i, pid in enumerate(pids):
            pay = pay_by_id.get(pid, {})
            pay_gross = _money(pay["amount"]) if pay else Decimal("0.00")
            last = i == len(pids) - 1
            if last or gross == 0:
                share_net, share_mdr, share_gst = remaining_net, remaining_mdr, remaining_gst
            else:
                ratio = (pay_gross / gross) if gross else Decimal("0")
                share_net = (net * ratio).quantize(Decimal("0.01"))
                share_mdr = (mdr * ratio).quantize(Decimal("0.01"))
                share_gst = (gst * ratio).quantize(Decimal("0.01"))
                remaining_net -= share_net
                remaining_mdr -= share_mdr
                remaining_gst -= share_gst
            fee = (pay_gross - share_net).quantize(Decimal("0.01"))
            extra = {
                **extra_base,
                "mdr_fee": str(share_mdr),
                **_parse_extra(pay),
            }
            out.psp.append(
                Record(
                    id=f"{stl['settlement_id']}-{pid}",
                    source=Source.PSP,
                    reference=pid,
                    amount=pay_gross,
                    currency=_ccy(stl) if stl.get("currency") else _ccy(pay),
                    txn_date=settled,
                    fee=fee,
                    payee=pay.get("customer") or stl.get("customer") or "",
                    description=f"settlement {stl['settlement_id']} part {pid}",
                    batch_id=batch_id,
                    split_id=_cell(pay, "split_id") or None,
                    utr=utr,
                    status=_status(stl.get("status") or pay.get("status") or "success"),
                    gst=share_gst,
                    created_date=settled,
                    extra=extra,
                )
            )

    seen_bank: dict[str, int] = defaultdict(int)
    for row in bank_rows:
        utr = (row.get("utr") or "").strip()
        seen_bank[utr] += 1
        n = seen_bank[utr]
        amount = _money(row["credited_amount"])
        extra: dict = {}
        if utr and utr_uses[utr] > 1:
            extra["duplicate_utr"] = True
        if amount <= 0:
            extra["refund"] = True
        if "UNKNOWN" in (row.get("raw_description") or "").upper():
            extra["orphan"] = True
        extra = {**extra, **_parse_extra(row)}
        reference, batch_id, payee = _bank_loop_identity(
            row,
            utr=utr,
            settlements=settlements,
            pay_by_id=pay_by_id,
            n=n,
        )
        out.bank.append(
            Record(
                id=f"B-{utr}-{n}",
                source=Source.BANK,
                reference=reference,
                amount=amount,
                currency=_ccy(row),
                txn_date=parse_date(row["credited_date"]),
                payee=payee,
                description=row.get("raw_description") or "",
                batch_id=batch_id,
                split_id=_cell(row, "split_id") or None,
                utr=utr,
                status=_status(row.get("status") or "success"),
                created_date=parse_date(row["credited_date"]),
                extra=extra,
            )
        )

    apply_ground_truth(out, truth_rows)
    return out
