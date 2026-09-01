from __future__ import annotations

import csv
import json
import random
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
import zipfile

from finance_controller.reconciliation.gst import gst_on_mdr
from finance_controller.razorpay.schema import RECON_COLUMNS

SEED = 42
OUT_DIR = Path(__file__).resolve().parent / "razorpay_sample"


def _paise(amount: Decimal) -> int:
    return int((amount * 100).quantize(Decimal("1")))


def _row(
    *,
    entity_id: str,
    kind: str,
    payment_id: str,
    order_id: str,
    gross: Decimal,
    mdr: Decimal,
    gst: Decimal,
    settlement_id: str,
    utr: str,
    created: datetime,
    settled: datetime,
    method: str = "card",
    notes: str = "ACME",
    debit: Decimal | None = None,
    credit: Decimal | None = None,
    settled_flag: str = "true",
) -> dict[str, str]:
    fee = mdr + gst
    if credit is None and kind == "payment":
        credit = (gross - fee).quantize(Decimal("0.01"))
    if debit is None:
        debit = Decimal("0.00") if kind == "payment" else gross
    return {
        "entity_id": entity_id,
        "type": kind,
        "payment_id": payment_id,
        "order_id": order_id,
        "amount": str(_paise(gross)),
        "fee": str(_paise(fee)),
        "tax": str(_paise(gst)),
        "debit": str(_paise(debit)),
        "credit": str(_paise(credit or Decimal("0.00"))),
        "currency": "INR",
        "settlement_id": settlement_id,
        "settlement_utr": utr,
        "created_at": str(int(created.timestamp())),
        "settled_at": str(int(settled.timestamp())),
        "method": method,
        "settled": settled_flag,
        "notes": notes,
    }


def generate_sample(seed: int = SEED) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    rng = random.Random(seed)
    start = datetime(2026, 1, 5, 10, 0, tzinfo=timezone.utc)
    rows: list[dict[str, str]] = []
    truth: list[dict[str, str]] = []
    n = 0

    def money() -> Decimal:
        return (Decimal(rng.randint(8000, 250000)) / Decimal(100)).quantize(Decimal("0.01"))

    def add_payment(
        *,
        sid: str,
        utr: str,
        day: int,
        gst: Decimal | None = None,
        settled_flag: str = "true",
        notes: str = "ACME",
        credit_gross: bool = False,
    ) -> str:
        nonlocal n
        n += 1
        pid = f"pay_Fc{n:012d}"
        oid = f"order_Fc{n:010d}"
        eid = pid
        gross = money()
        mdr = (gross * Decimal("0.02")).quantize(Decimal("0.01"))
        tax = gst if gst is not None else gst_on_mdr(mdr)
        created = start + timedelta(days=day)
        settled = created + timedelta(days=2)
        credit = gross if credit_gross else None
        rows.append(
            _row(
                entity_id=eid,
                kind="payment",
                payment_id=pid,
                order_id=oid,
                gross=gross,
                mdr=mdr,
                gst=tax,
                settlement_id=sid,
                utr=utr,
                created=created,
                settled=settled,
                notes=notes,
                settled_flag=settled_flag,
                credit=credit,
            )
        )
        return pid

    # 44 single-payment settlements (clean)
    for i in range(44):
        pid = add_payment(sid=f"setl_CLEAN{i:04d}", utr=f"UTRCLN{i:013d}", day=i % 20, notes="GLOBEX" if i >= 12 else "ACME")
        truth.append({"payment_id": pid, "label": "clean_match"})

    # Settled payouts whose settlement_utr has not been published in the export.
    # The statement line carries the sponsor bank's reference and the payment id
    # only in free text, so no deterministic tier can claim these -- the agent has
    # to recover them from narration and clear the validator. Labelled
    # clean_match because they are genuinely matchable.
    for i in range(6):
        pid = add_payment(sid=f"setl_MEMO{i:04d}", utr="", day=10 + i, notes="ACME")
        truth.append({"payment_id": pid, "label": "clean_match"})

    # GST mismatch: tax = 0 while MDR > 0
    for i in range(2):
        pid = add_payment(
            sid=f"setl_GST{i:04d}",
            utr=f"UTRGST{i:013d}",
            day=20 + i,
            gst=Decimal("0.00"),
        )
        truth.append({"payment_id": pid, "label": "gst_mismatch"})

    # Missing bank credit: settled=false
    for i in range(2):
        pid = add_payment(
            sid=f"setl_MISS{i:04d}",
            utr=f"UTRMSS{i:013d}",
            day=22 + i,
            settled_flag="false",
        )
        truth.append({"payment_id": pid, "label": "missing_bank_credit"})

    # Amount mismatch: bank credit ignores MDR (gross credited)
    for i in range(2):
        pid = add_payment(
            sid=f"setl_AMT{i:04d}",
            utr=f"UTRAMT{i:013d}",
            day=24 + i,
            credit_gross=True,
        )
        truth.append({"payment_id": pid, "label": "undocumented_adjustment"})

    # Full refund settlement (net <= 0)
    n += 1
    pid = f"pay_Fc{n:012d}"
    created = start + timedelta(days=26)
    settled = created + timedelta(days=2)
    gross = Decimal("150.00")
    mdr = Decimal("3.00")
    gst = gst_on_mdr(mdr)
    rows.append(
        _row(
            entity_id=f"rfnd_Fc{n:012d}",
            kind="refund",
            payment_id=pid,
            order_id=f"order_Fc{n:010d}",
            gross=gross,
            mdr=Decimal("0.00"),
            gst=Decimal("0.00"),
            settlement_id="setl_RFND0001",
            utr="UTRRFD0000000000001",
            created=created,
            settled=settled,
            debit=gross,
            credit=Decimal("0.00"),
        )
    )
    truth.append({"payment_id": pid, "label": "refund"})

    # Honest skips
    for i, kind in enumerate(("adjustment", "transfer", "adjustment")):
        n += 1
        created = start + timedelta(days=27)
        rows.append(
            _row(
                entity_id=f"adj_Fc{n:012d}" if kind == "adjustment" else f"trf_Fc{n:012d}",
                kind=kind,
                payment_id=f"pay_SKIP{n:08d}",
                order_id=f"order_SKIP{n:06d}",
                gross=Decimal("10.00"),
                mdr=Decimal("0.00"),
                gst=Decimal("0.00"),
                settlement_id="setl_SKIP0001",
                utr="UTRSKP0000000000001",
                created=created,
                settled=created,
            )
        )

    assert sum(1 for r in rows if r["type"] == "payment") >= 50
    return rows, truth


def write_sample(out_dir: Path = OUT_DIR) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    rows, truth = generate_sample()
    csv_path = out_dir / "settlement_recon.csv"
    gt_path = out_dir / "ground_truth.json"
    zip_path = out_dir / "batch.zip"
    with csv_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(RECON_COLUMNS))
        writer.writeheader()
        writer.writerows(rows)
    gt_path.write_text(json.dumps(truth, indent=2), encoding="utf-8")
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.write(csv_path, "settlement_recon.csv")
        zf.write(gt_path, "ground_truth.json")
    return zip_path


if __name__ == "__main__":
    path = write_sample()
    print(f"wrote {path}")
