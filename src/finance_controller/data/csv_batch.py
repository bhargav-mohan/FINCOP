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
        label = row.get("label") or ""
        pid = (row.get("payment_id") or "").strip().upper()
        utr = (row.get("utr") or "").strip().upper()
        if label in _MATCH_LABELS:
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

        if not batched:
            pid = pids[0] if pids else stl["settlement_id"]
            pay = pay_by_id.get(pid, {})
            status = _status(pay.get("status", "success"))
            out.psp.append(
                Record(
                    id=stl["settlement_id"],
                    source=Source.PSP,
                    reference=pid,
                    amount=gross,
                    currency=_ccy(stl) if stl.get("currency") else _ccy(pay),
                    txn_date=settled,
                    fee=(mdr + gst).quantize(Decimal("0.01")),
                    payee=pay.get("customer") or "",
                    description=f"settlement {stl['settlement_id']}",
                    batch_id=None,
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
                    payee=pay.get("customer") or "",
                    description=f"settlement {stl['settlement_id']} part {pid}",
                    batch_id=batch_id,
                    utr=utr,
                    status=_status(pay.get("status", "success")),
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
        matching = [s for s in settlements if (s.get("utr") or "").strip() == utr and utr]
        pids = []
        batch_id = None
        if len(matching) == 1:
            pids = [p.strip() for p in matching[0].get("payment_ids", "").split("|") if p.strip()]
            if len(pids) > 1:
                batch_id = matching[0]["settlement_id"]
        elif len(matching) > 1:
            extra["duplicate_utr"] = True
        if batch_id:
            reference = utr or batch_id
        elif len(pids) == 1:
            reference = pids[0]
        else:
            reference = utr or f"BANK-{n}"
        payee = ""
        if len(pids) == 1:
            payee = pay_by_id.get(pids[0], {}).get("customer") or ""
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
                utr=utr,
                status=PaymentStatus.SUCCESS,
                created_date=parse_date(row["credited_date"]),
                extra=extra,
            )
        )

    apply_ground_truth(out, truth_rows)
    return out
