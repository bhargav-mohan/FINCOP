from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
import random

from finance_controller.config import BATCH_MAX_SIZE, BATCH_MIN_SIZE, ReconConfig
from finance_controller.models import (
    CaseCategory,
    ExceptionType,
    ExpectedStatus,
    GroundTruth,
    PaymentStatus,
    Record,
    Source,
)
from finance_controller.reconciliation.gst import gst_bankers, gst_half_up

def _gt(
    *,
    key: str,
    status: ExpectedStatus,
    record_ids: list[str],
    exception_type: ExceptionType | None = None,
    category: CaseCategory = CaseCategory.CLEAN,
    defect: str = "",
) -> GroundTruth:
    return GroundTruth(
        key=key,
        expected_status=status,
        exception_type=exception_type,
        category=category,
        defect=defect,
        record_ids=record_ids,
    )


def _emit_edge(out: SyntheticBatch, txn: dict, edge: str, add_ledger, add_psp, add_bank) -> None:
    key = txn["reference"]
    split_id = f"SPLIT-{key}"
    friday = date(2026, 1, 9)
    wednesday = date(2026, 1, 7)

    if edge == "split_settlement":
        half = (txn["net"] / 2).quantize(Decimal("0.01"))
        rest = (txn["net"] - half).quantize(Decimal("0.01"))
        ledger = add_ledger(txn, None, split_id=split_id)
        psp = add_psp(txn, None, split_id=split_id)
        b1 = add_bank(txn, amount=half, split_id=split_id, utr=f"{txn['utr']}A", extra={"split": True})
        b2 = add_bank(txn, amount=rest, split_id=split_id, utr=f"{txn['utr']}B", extra={"split": True})
        out.ground_truth.append(
            _gt(key=key, status=ExpectedStatus.MATCHED, record_ids=[ledger.id, psp.id, b1.id, b2.id], defect="one payment split across two bank credits")
        )
        return

    if edge == "zero_net":
        zero = {**txn, "fee": txn["gross"], "net": Decimal("0.00")}
        ledger = add_ledger(zero, None)
        psp = add_psp(zero, None)
        bank = add_bank(zero, amount=Decimal("0.00"), extra={"refund": True})
        out.ground_truth.append(
            _gt(
                key=key,
                status=ExpectedStatus.EXCEPTION,
                exception_type=ExceptionType.ZERO_OR_NEGATIVE_NET,
                category=CaseCategory.IRRESOLVABLE,
                record_ids=[ledger.id, psp.id, bank.id],
                defect="full refund: net is zero",
            )
        )
        return

    if edge == "negative_net":
        ledger = add_ledger(txn, None)
        psp = add_psp(txn, None)
        bank = add_bank(txn, amount=Decimal("-10.00"), extra={"chargeback": True})
        out.ground_truth.append(
            _gt(
                key=key,
                status=ExpectedStatus.EXCEPTION,
                exception_type=ExceptionType.ZERO_OR_NEGATIVE_NET,
                category=CaseCategory.IRRESOLVABLE,
                record_ids=[ledger.id, psp.id, bank.id],
                defect="chargeback: negative bank net",
            )
        )
        return

    if edge == "partial_refund":
        half = (txn["net"] / 2).quantize(Decimal("0.01"))
        ledger = add_ledger(txn, None)
        psp = add_psp(txn, None)
        bank = add_bank(txn, amount=half, extra={"refund": True})
        out.ground_truth.append(
            _gt(
                key=key,
                status=ExpectedStatus.EXCEPTION,
                exception_type=ExceptionType.PARTIAL_REFUND,
                category=CaseCategory.IRRESOLVABLE,
                record_ids=[ledger.id, psp.id, bank.id],
                defect="partial refund: bank net below gross-minus-fees",
            )
        )
        return

    if edge == "status_mismatch":
        ledger = add_ledger(txn, None, status=PaymentStatus.SUCCESS)
        psp = add_psp(txn, None, status=PaymentStatus.FAILED)
        bank = add_bank(txn, status=PaymentStatus.SUCCESS)
        out.ground_truth.append(
            _gt(
                key=key,
                status=ExpectedStatus.EXCEPTION,
                exception_type=ExceptionType.STATUS_MISMATCH,
                category=CaseCategory.IRRESOLVABLE,
                record_ids=[ledger.id, psp.id, bank.id],
                defect="psp failed while ledger/bank marked success",
            )
        )
        return

    if edge == "date_inverted":
        txn_inv = {**txn, "txn_date": wednesday}
        ledger = add_ledger(txn_inv, None)
        psp = add_psp(txn_inv, None)
        bank = add_bank(txn_inv, lag=-2)
        out.ground_truth.append(
            _gt(
                key=key,
                status=ExpectedStatus.EXCEPTION,
                exception_type=ExceptionType.DATE_INVERTED,
                category=CaseCategory.IRRESOLVABLE,
                record_ids=[ledger.id, psp.id, bank.id],
                defect="bank dated before payment",
            )
        )
        return

    if edge == "late_settlement":
        txn_late = {**txn, "txn_date": wednesday}
        ledger = add_ledger(txn_late, None)
        psp = add_psp(txn_late, None)
        bank = add_bank(txn_late, lag=10)
        out.ground_truth.append(
            _gt(
                key=key,
                status=ExpectedStatus.EXCEPTION,
                exception_type=ExceptionType.LATE_SETTLEMENT,
                category=CaseCategory.IRRESOLVABLE,
                record_ids=[ledger.id, psp.id, bank.id],
                defect="cleared after more than 3 banking days (T+7+)",
            )
        )
        return

    if edge == "weekend_clear":
        txn_w = {**txn, "txn_date": friday}
        ledger = add_ledger(txn_w, None)
        psp = add_psp(txn_w, None)
        bank = add_bank(txn_w, lag=3)
        out.ground_truth.append(
            _gt(key=key, status=ExpectedStatus.MATCHED, record_ids=[ledger.id, psp.id, bank.id], defect="Friday payment, Monday bank (1 banking day)")
        )
        return

    if edge == "same_day":
        ledger = add_ledger(txn, None)
        psp = add_psp(txn, None)
        bank = add_bank(txn, lag=0)
        out.ground_truth.append(
            _gt(key=key, status=ExpectedStatus.MATCHED, record_ids=[ledger.id, psp.id, bank.id], defect="T+0 same-day settlement")
        )
        return

    if edge == "empty_utr":
        ledger = add_ledger(txn, None)
        psp = add_psp(txn, None)
        bank = add_bank(txn, utr="", extra={"empty_utr": True, "expect_utr": True})
        out.ground_truth.append(
            _gt(
                key=key,
                status=ExpectedStatus.EXCEPTION,
                exception_type=ExceptionType.EMPTY_UTR,
                category=CaseCategory.IRRESOLVABLE,
                record_ids=[ledger.id, psp.id, bank.id],
                defect="bank UTR missing",
            )
        )
        return

    if edge == "malformed_utr":
        ledger = add_ledger(txn, None)
        psp = add_psp(txn, None)
        bank = add_bank(txn, utr="UTR!!", extra={"malformed_utr": True})
        out.ground_truth.append(
            _gt(
                key=key,
                status=ExpectedStatus.EXCEPTION,
                exception_type=ExceptionType.MALFORMED_UTR,
                category=CaseCategory.IRRESOLVABLE,
                record_ids=[ledger.id, psp.id, bank.id],
                defect="bank UTR failed format check",
            )
        )
        return

    if edge == "duplicate_utr":
        ledger = add_ledger(txn, None)
        psp = add_psp(txn, None)
        bank = add_bank(txn)
        dup = add_bank(txn, extra={"duplicate_utr": True})
        out.ground_truth.append(
            _gt(key=key, status=ExpectedStatus.MATCHED, record_ids=[ledger.id, psp.id, bank.id], defect="primary bank row is valid")
        )
        out.ground_truth.append(
            _gt(
                key=f"{key}#dup",
                status=ExpectedStatus.EXCEPTION,
                exception_type=ExceptionType.DUPLICATE_UTR,
                category=CaseCategory.IRRESOLVABLE,
                record_ids=[dup.id],
                defect="second ingest of the same UTR",
            )
        )
        return

    if edge == "gst_exempt":
        extra = {"gst_exempt": True}
        ledger = add_ledger(txn, None, gst=Decimal("0.00"), extra=extra)
        psp = add_psp(txn, None, gst=Decimal("0.00"), extra=extra)
        bank = add_bank(txn)
        out.ground_truth.append(
            _gt(key=key, status=ExpectedStatus.MATCHED, record_ids=[ledger.id, psp.id, bank.id], defect="GST-exempt supply, gst=0 is valid")
        )
        return

    if edge == "gst_zero_bug":
        extra = {"taxable": True, "gst_zero_bug": True}
        ledger = add_ledger(txn, None, gst=Decimal("0.00"), extra=extra)
        psp = add_psp(txn, None, gst=Decimal("0.00"), extra=extra)
        bank = add_bank(txn)
        out.ground_truth.append(
            _gt(
                key=key,
                status=ExpectedStatus.EXCEPTION,
                exception_type=ExceptionType.GST_ZERO_BUG,
                category=CaseCategory.IRRESOLVABLE,
                record_ids=[ledger.id, psp.id, bank.id],
                defect="taxable line booked with gst=0",
            )
        )
        return

    if edge == "gst_bankers":
        gst = gst_bankers(txn["gross"])
        ledger = add_ledger(txn, None, gst=gst)
        psp = add_psp(txn, None, gst=gst)
        bank = add_bank(txn)
        out.ground_truth.append(
            _gt(key=key, status=ExpectedStatus.MATCHED, record_ids=[ledger.id, psp.id, bank.id], defect="GST bankers rounding sits inside half-up ±0.05")
        )
        return

    if edge == "bank_before_created":
        created = wednesday
        txn_c = {**txn, "txn_date": created}
        ledger = add_ledger(txn_c, None, created_date=created)
        psp = add_psp(txn_c, None, created_date=created)
        bank = add_bank(txn_c, lag=-1, created_date=created)
        out.ground_truth.append(
            _gt(
                key=key,
                status=ExpectedStatus.EXCEPTION,
                exception_type=ExceptionType.DATE_INVERTED,
                category=CaseCategory.IRRESOLVABLE,
                record_ids=[ledger.id, psp.id, bank.id],
                defect="bank credit dated before settlement created_date",
            )
        )
        return

    if edge == "malformed_amount":
        ledger = add_ledger(txn, None)
        psp = add_psp(txn, None)
        bank = add_bank(txn, amount=Decimal("0.00"), extra={"malformed_amount": True})
        out.ground_truth.append(
            _gt(
                key=key,
                status=ExpectedStatus.EXCEPTION,
                exception_type=ExceptionType.MALFORMED_AMOUNT,
                category=CaseCategory.IRRESOLVABLE,
                record_ids=[ledger.id, psp.id, bank.id],
                defect="non-finite bank amount",
            )
        )
        return

    if edge == "same_amount_diff_utr":
        ledger = add_ledger(txn, None)
        psp = add_psp(txn, None)
        bank = add_bank(txn)
        decoy = add_bank(
            txn,
            reference=f"UNK-{key}",
            utr=f"DECOY{txn['utr'][5:]}",
            extra={"orphan": True, "competing_amount": True},
        )
        out.ground_truth.append(
            _gt(key=key, status=ExpectedStatus.MATCHED, record_ids=[ledger.id, psp.id, bank.id], defect="true UTR wins; same-amount decoy is unmatched")
        )
        out.ground_truth.append(
            _gt(
                key=decoy.reference,
                status=ExpectedStatus.EXCEPTION,
                exception_type=ExceptionType.UNMATCHED,
                category=CaseCategory.IRRESOLVABLE,
                record_ids=[decoy.id],
                defect="competing same-amount bank with a different UTR",
            )
        )
        return

    ledger = add_ledger(txn, None)
    psp = add_psp(txn, None)
    bank = add_bank(txn)
    out.ground_truth.append(_gt(key=key, status=ExpectedStatus.MATCHED, record_ids=[ledger.id, psp.id, bank.id]))

INJECT_CYCLE = (
    ExceptionType.MISSING_IN_BANK,
    ExceptionType.MISSING_IN_LEDGER,
    ExceptionType.AMOUNT_MISMATCH,
    ExceptionType.DUPLICATE,
    ExceptionType.FX_MISMATCH,
    ExceptionType.UNMATCHED,
)
EDGE_CYCLE = (
    "split_settlement",
    "zero_net",
    "negative_net",
    "partial_refund",
    "status_mismatch",
    "date_inverted",
    "late_settlement",
    "weekend_clear",
    "same_day",
    "empty_utr",
    "malformed_utr",
    "duplicate_utr",
    "gst_exempt",
    "gst_zero_bug",
    "gst_bankers",
    "bank_before_created",
    "malformed_amount",
    "same_amount_diff_utr",
)

MERCHANTS = ("ACME", "GLOBEX", "INITECH", "UMBRELLA", "SOYLENT")


@dataclass
class SyntheticBatch:
    ledger: list[Record] = field(default_factory=list)
    bank: list[Record] = field(default_factory=list)
    psp: list[Record] = field(default_factory=list)
    ground_truth: list[GroundTruth] = field(default_factory=list)

    @property
    def all_records(self) -> list[Record]:
        return [*self.ledger, *self.bank, *self.psp]


def _money(rng: random.Random) -> Decimal:
    return (Decimal(rng.randint(500, 250_000)) / Decimal(100)).quantize(Decimal("0.01"))


def generate(config: ReconConfig) -> SyntheticBatch:
    rng = random.Random(config.seed)
    n = config.num_records
    n_exc = min(config.inject_exceptions, max(0, n // 2))
    n_res = min(config.inject_resolvable, max(0, n // 3))
    start = date(2026, 1, 1)

    intended: list[dict] = []
    for i in range(n):
        gross = _money(rng)
        fee = (gross * config.fee_rate).quantize(Decimal("0.01"))
        intended.append(
            {
                "reference": f"TXN-{i + 1:04d}",
                "gross": gross,
                "fee": fee,
                "net": (gross - fee).quantize(Decimal("0.01")),
                "txn_date": start + timedelta(days=rng.randint(0, 40)),
                "currency": "INR",
                "merchant": rng.choice(MERCHANTS),
                "utr": f"UTR{i + 1:013d}",
                "gst": gst_half_up(gross),
            }
        )

    indices = list(range(n))
    rng.shuffle(indices)
    exception_ix = set(indices[:n_exc])
    leftover = [i for i in indices if i not in exception_ix]
    resolvable_ix = set(leftover[:n_res])
    clean_ix = [i for i in leftover if i not in resolvable_ix]

    batches: list[tuple[str, list[int]]] = []
    pool = list(clean_ix)
    for b in range(2):
        if len(pool) < BATCH_MIN_SIZE:
            break
        size = min(rng.randint(BATCH_MIN_SIZE, BATCH_MAX_SIZE), len(pool))
        members = [pool.pop() for _ in range(size)]
        batches.append((f"BATCH-{b + 1:02d}", members))
    batched = {i: bid for bid, members in batches for i in members}
    edge_pool = [i for i in clean_ix if i not in batched]
    n_edge = min(config.inject_edges, len(edge_pool))
    edge_ix = set(edge_pool[:n_edge])
    edge_for: dict[int, str] = {}
    for k, i in enumerate(sorted(edge_ix)):
        edge_for[i] = EDGE_CYCLE[k % len(EDGE_CYCLE)]

    exception_type_for: dict[int, ExceptionType] = {}
    for k, i in enumerate(sorted(exception_ix)):
        exception_type_for[i] = INJECT_CYCLE[k % len(INJECT_CYCLE)]

    used_nets: set[Decimal] = set()
    for i in sorted(resolvable_ix):
        net = intended[i]["net"]
        while net in used_nets:
            intended[i]["gross"] = (intended[i]["gross"] + Decimal("1.00")).quantize(Decimal("0.01"))
            intended[i]["fee"] = (intended[i]["gross"] * config.fee_rate).quantize(Decimal("0.01"))
            intended[i]["net"] = (intended[i]["gross"] - intended[i]["fee"]).quantize(Decimal("0.01"))
            net = intended[i]["net"]
        used_nets.add(net)

    seq = 0

    def nid(prefix: str) -> str:
        nonlocal seq
        seq += 1
        return f"{prefix}{seq:05d}"

    out = SyntheticBatch()

    def add_ledger(txn: dict, batch_id: str | None, **overrides) -> Record:
        rec = Record(
            id=nid("L"),
            source=Source.LEDGER,
            reference=txn["reference"],
            amount=txn["gross"],
            currency=txn["currency"],
            txn_date=txn["txn_date"],
            fee=Decimal("0.00"),
            payee=txn["merchant"],
            description=f"{txn['merchant']} sale",
            batch_id=batch_id,
            split_id=overrides.get("split_id"),
            utr=txn.get("utr", ""),
            status=overrides.get("status", PaymentStatus.SUCCESS),
            gst=overrides.get("gst", txn.get("gst", Decimal("0.00"))),
            created_date=overrides.get("created_date", txn["txn_date"]),
            extra=overrides.get("extra") or {},
        )
        out.ledger.append(rec)
        return rec

    def add_psp(txn: dict, batch_id: str | None, **overrides) -> Record:
        rec = Record(
            id=nid("P"),
            source=Source.PSP,
            reference=txn["reference"],
            amount=txn["gross"],
            currency=txn["currency"],
            txn_date=txn["txn_date"],
            fee=txn["fee"],
            payee=txn["merchant"],
            description=f"psp {txn['merchant']}",
            batch_id=batch_id,
            split_id=overrides.get("split_id"),
            utr=txn.get("utr", ""),
            status=overrides.get("status", PaymentStatus.SUCCESS),
            gst=overrides.get("gst", txn.get("gst", Decimal("0.00"))),
            created_date=overrides.get("created_date", txn["txn_date"]),
            extra=overrides.get("extra") or {},
        )
        out.psp.append(rec)
        return rec

    def add_bank(
        txn: dict,
        *,
        amount: Decimal | None = None,
        currency: str | None = None,
        reference: str | None = None,
        batch_id: str | None = None,
        extra: dict | None = None,
        lag: int = 1,
        payee: str | None = None,
        description: str | None = None,
        utr: str | None = None,
        split_id: str | None = None,
        status: PaymentStatus = PaymentStatus.SUCCESS,
        created_date: date | None = None,
    ) -> Record:
        rec = Record(
            id=nid("B"),
            source=Source.BANK,
            reference=reference or txn["reference"],
            amount=(amount if amount is not None else txn["net"]),
            currency=currency or txn["currency"],
            txn_date=txn["txn_date"] + timedelta(days=lag),
            fee=Decimal("0.00"),
            payee=txn["merchant"] if payee is None else payee,
            description=description if description is not None else f"bank {txn['merchant']}",
            batch_id=batch_id,
            split_id=split_id,
            utr=txn["utr"] if utr is None else utr,
            status=status,
            created_date=created_date or (txn["txn_date"] + timedelta(days=lag)),
            extra=extra or {},
        )
        out.bank.append(rec)
        return rec

    for i, txn in enumerate(intended):
        bid = batched.get(i)
        et = exception_type_for.get(i)
        ids: list[str] = []

        if et is ExceptionType.UNMATCHED:
            bank = add_bank(txn, reference=f"UNK-{txn['reference']}", extra={"orphan": True})
            out.ground_truth.append(
                GroundTruth(
                    key=bank.reference,
                    expected_status=ExpectedStatus.EXCEPTION,
                    exception_type=ExceptionType.UNMATCHED,
                    category=CaseCategory.IRRESOLVABLE,
                    defect="orphan bank row with no ledger/psp counterpart",
                    record_ids=[bank.id],
                )
            )
            continue

        edge = edge_for.get(i)
        if edge is not None:
            _emit_edge(out, txn, edge, add_ledger, add_psp, add_bank)
            continue

        if et is not ExceptionType.MISSING_IN_LEDGER:
            ids.append(add_ledger(txn, bid).id)
        ids.append(add_psp(txn, bid).id)

        if bid is not None:
            continue

        if i in resolvable_ix:
            variant = "stripped_ref_memo" if i % 2 == 0 else "wire_memo_only"
            dummy_ref = f"NEFT-{i + 1:04d}" if variant == "stripped_ref_memo" else f"WIRE-{i + 1:04d}"
            memo = f"{dummy_ref} payout {txn['merchant']} {txn['reference']}"
            bank = add_bank(
                txn,
                reference=dummy_ref,
                payee="",
                description=memo,
                extra={
                    "resolvable": True,
                    "true_reference": txn["reference"],
                    "variant": variant,
                },
            )
            ids.append(bank.id)
            out.ground_truth.append(
                GroundTruth(
                    key=txn["reference"],
                    expected_status=ExpectedStatus.MATCHED,
                    category=CaseCategory.RESOLVABLE_AMBIGUOUS,
                    defect=(
                        f"{variant}: bank reference is {dummy_ref} and payee is blank; "
                        f"unique identity is in description ({memo})"
                    ),
                    record_ids=ids,
                )
            )
            continue

        if et is ExceptionType.MISSING_IN_BANK:
            out.ground_truth.append(
                GroundTruth(
                    key=txn["reference"],
                    expected_status=ExpectedStatus.EXCEPTION,
                    exception_type=ExceptionType.MISSING_IN_BANK,
                    category=CaseCategory.IRRESOLVABLE,
                    defect="bank row dropped",
                    record_ids=ids,
                )
            )
            continue

        if et is ExceptionType.AMOUNT_MISMATCH:
            bank = add_bank(txn, amount=(txn["net"] + Decimal("15.00")).quantize(Decimal("0.01")))
            ids.append(bank.id)
            out.ground_truth.append(
                GroundTruth(
                    key=txn["reference"],
                    expected_status=ExpectedStatus.EXCEPTION,
                    exception_type=ExceptionType.AMOUNT_MISMATCH,
                    category=CaseCategory.IRRESOLVABLE,
                    defect="bank amount off by 15.00 beyond fee tolerance",
                    record_ids=ids,
                )
            )
            continue

        if et is ExceptionType.FX_MISMATCH:
            bank = add_bank(txn, currency="USD")
            ids.append(bank.id)
            out.ground_truth.append(
                GroundTruth(
                    key=txn["reference"],
                    expected_status=ExpectedStatus.EXCEPTION,
                    exception_type=ExceptionType.FX_MISMATCH,
                    category=CaseCategory.IRRESOLVABLE,
                    defect="bank currency USD vs ledger/psp INR",
                    record_ids=ids,
                )
            )
            continue

        if et is ExceptionType.MISSING_IN_LEDGER:
            bank = add_bank(txn)
            ids.append(bank.id)
            out.ground_truth.append(
                GroundTruth(
                    key=txn["reference"],
                    expected_status=ExpectedStatus.EXCEPTION,
                    exception_type=ExceptionType.MISSING_IN_LEDGER,
                    category=CaseCategory.IRRESOLVABLE,
                    defect="ledger row dropped",
                    record_ids=ids,
                )
            )
            continue

        if et is ExceptionType.DUPLICATE:
            bank = add_bank(txn)
            dup = add_bank(txn, extra={"duplicate_of": bank.id})
            out.ground_truth.append(
                GroundTruth(
                    key=txn["reference"],
                    expected_status=ExpectedStatus.MATCHED,
                    defect="primary bank row is valid; duplicate is a separate exception",
                    record_ids=[*ids, bank.id],
                )
            )
            out.ground_truth.append(
                GroundTruth(
                    key=f"{txn['reference']}#dup",
                    expected_status=ExpectedStatus.EXCEPTION,
                    exception_type=ExceptionType.DUPLICATE,
                    category=CaseCategory.IRRESOLVABLE,
                    defect="duplicate bank row",
                    record_ids=[dup.id],
                )
            )
            continue

        bank = add_bank(txn, lag=rng.randint(0, 2))
        ids.append(bank.id)
        out.ground_truth.append(
            GroundTruth(
                key=txn["reference"],
                expected_status=ExpectedStatus.MATCHED,
                record_ids=ids,
            )
        )

    for bid, members in batches:
        txns = [intended[i] for i in members]
        total = sum((t["net"] for t in txns), Decimal("0.00")).quantize(Decimal("0.01"))
        max_date = max(t["txn_date"] for t in txns)
        proto = {
            **txns[0],
            "txn_date": max_date,
            "merchant": "SETTLEMENT",
            "net": total,
        }
        bank = add_bank(proto, amount=total, reference=bid, batch_id=bid, lag=1)
        rec_ids = [bank.id]
        for i in members:
            rec_ids.extend(
                r.id
                for r in (*out.ledger, *out.psp)
                if r.reference == intended[i]["reference"]
            )
        out.ground_truth.append(
            GroundTruth(
                key=bid,
                expected_status=ExpectedStatus.MATCHED,
                defect=f"batched settlement of {len(members)} psp nets",
                record_ids=sorted(set(rec_ids)),
            )
        )

    return out
