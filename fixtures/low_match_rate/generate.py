"""Deterministic batch whose engine match rate stays under 20%.

Most loops have no closable cash counterpart (missing bank, FX, amount
break, duplicate UTR, refund). A small clean set is included so the
rate is low, not zero. Seed 7. Run from any cwd; files land next to
this script.
"""

from __future__ import annotations

import csv
import json
import random
import zipfile
from datetime import datetime, timedelta
from pathlib import Path

random.seed(7)

OUT = Path(__file__).resolve().parent
NUM_CLEAN = 8
NUM_MISSING_BANK = 18
NUM_AMOUNT_BREAK = 10
NUM_FX = 8
NUM_REFUND = 6
NUM_DUP_PAIRS = 3
NUM_EMPTY_UTR = 4
NUM_ORPHAN_BANK = 6

CUSTOMERS = [
    "Acme Retail",
    "Bluepeak Foods",
    "Cedar Logistics",
    "Dhruv Textiles",
    "Everstone Labs",
    "Ferrow Motors",
]
BASE = datetime(2026, 6, 1)
MDR_RATE = 0.02
GST_RATE = 0.18

payments: list[dict] = []
settlements: list[dict] = []
bank_rows: list[dict] = []
ground_truth: list[dict] = []
pay_n = 1
stl_n = 1


def rupees(x: float) -> float:
    return round(float(x), 2)


def fee_math(gross: float) -> tuple[float, float, float]:
    mdr = rupees(gross * MDR_RATE)
    gst = rupees(mdr * GST_RATE)
    net = rupees(gross - mdr - gst)
    return mdr, gst, net


def utr() -> str:
    return "UTR" + "".join(random.choices("0123456789", k=10))


def add_payment(amount: float, day: int, status: str = "success") -> tuple[str, float, datetime]:
    global pay_n
    pid = f"LOW{pay_n:04d}"
    pay_n += 1
    ts = BASE + timedelta(days=day, hours=random.randint(8, 20))
    payments.append(
        {
            "payment_id": pid,
            "amount": rupees(amount),
            "customer": random.choice(CUSTOMERS),
            "timestamp": ts.strftime("%Y-%m-%d %H:%M:%S"),
            "status": status,
            "currency": "INR",
        }
    )
    return pid, amount, ts


def add_settlement(
    pid: str,
    gross: float,
    ts: datetime,
    *,
    net: float | None = None,
    mdr: float | None = None,
    gst: float | None = None,
    bank_utr: str | None = None,
    settled_utr: str | None = None,
) -> tuple[str, float, str, datetime]:
    global stl_n
    calc_mdr, calc_gst, calc_net = fee_math(gross)
    mdr = calc_mdr if mdr is None else rupees(mdr)
    gst = calc_gst if gst is None else rupees(gst)
    net = calc_net if net is None else rupees(net)
    used_utr = settled_utr if settled_utr is not None else (bank_utr or utr())
    settle = ts + timedelta(days=2)
    sid = f"LST{stl_n:04d}"
    stl_n += 1
    settlements.append(
        {
            "settlement_id": sid,
            "payment_ids": pid,
            "gross_amount": rupees(gross),
            "mdr_fee": mdr,
            "gst_on_fee": gst,
            "net_amount": net,
            "utr": used_utr,
            "settled_date": settle.strftime("%Y-%m-%d"),
            "currency": "INR",
        }
    )
    return sid, net, used_utr, settle


def add_bank(
    used_utr: str,
    amount: float,
    settle: datetime,
    *,
    currency: str = "INR",
    note: str = "NEFT CR SETTLEMENT",
) -> None:
    bank_rows.append(
        {
            "utr": used_utr,
            "credited_amount": rupees(amount),
            "credited_date": settle.strftime("%Y-%m-%d"),
            "raw_description": f"{note} {used_utr}",
            "currency": currency,
        }
    )


def clean_loop() -> None:
    day = random.randint(0, 20)
    amt = round(random.uniform(800, 20000), 2)
    pid, gross, ts = add_payment(amt, day)
    sid, net, used, settle = add_settlement(pid, gross, ts)
    add_bank(used, net, settle)
    ground_truth.append(
        {"payment_id": pid, "settlement_id": sid, "utr": used, "label": "clean_match"}
    )


def missing_bank() -> None:
    day = random.randint(0, 20)
    amt = round(random.uniform(800, 20000), 2)
    pid, gross, ts = add_payment(amt, day)
    sid, _net, used, _settle = add_settlement(pid, gross, ts)
    ground_truth.append(
        {"payment_id": pid, "settlement_id": sid, "utr": used, "label": "missing_bank_credit"}
    )


def amount_break() -> None:
    day = random.randint(0, 20)
    amt = round(random.uniform(3000, 25000), 2)
    pid, gross, ts = add_payment(amt, day)
    sid, net, used, settle = add_settlement(pid, gross, ts)
    add_bank(used, rupees(net - 500), settle, note="NEFT CR SHORT")
    ground_truth.append(
        {"payment_id": pid, "settlement_id": sid, "utr": used, "label": "undocumented_adjustment"}
    )


def fx_break() -> None:
    day = random.randint(0, 20)
    amt = round(random.uniform(2000, 18000), 2)
    pid, gross, ts = add_payment(amt, day)
    sid, net, used, settle = add_settlement(pid, gross, ts)
    add_bank(used, net, settle, currency="USD", note="WIRE CR FX")
    ground_truth.append(
        {"payment_id": pid, "settlement_id": sid, "utr": used, "label": "currency_mismatch"}
    )


def refund() -> None:
    day = random.randint(0, 20)
    amt = round(random.uniform(1000, 12000), 2)
    pid, gross, ts = add_payment(amt, day, status="refunded")
    mdr, gst, _ = fee_math(gross)
    sid, net, used, settle = add_settlement(
        pid, gross, ts, net=rupees(-gross), mdr=mdr, gst=gst
    )
    add_bank(used, net, settle, note="NEFT DR REFUND")
    ground_truth.append(
        {"payment_id": pid, "settlement_id": sid, "utr": used, "label": "refund"}
    )


def empty_utr() -> None:
    day = random.randint(0, 20)
    amt = round(random.uniform(1500, 15000), 2)
    pid, gross, ts = add_payment(amt, day)
    sid, net, _used, settle = add_settlement(pid, gross, ts, settled_utr="")
    add_bank(utr(), net, settle, note="NEFT CR NOREF")
    ground_truth.append(
        {"payment_id": pid, "settlement_id": sid, "utr": "", "label": "empty_utr"}
    )


def dup_pair() -> None:
    shared = utr()
    for offset in (0, 1):
        day = random.randint(0, 18)
        amt = round(random.uniform(2000, 9000), 2)
        pid, gross, ts = add_payment(amt, day + offset)
        sid, net, used, settle = add_settlement(pid, gross, ts, settled_utr=shared)
        if offset == 0:
            add_bank(used, net, settle)
        ground_truth.append(
            {
                "payment_id": pid,
                "settlement_id": sid,
                "utr": shared,
                "label": "duplicate_utr_conflict",
            }
        )


def orphan_bank() -> None:
    used = utr()
    day = random.randint(0, 20)
    bank_rows.append(
        {
            "utr": used,
            "credited_amount": rupees(random.uniform(400, 4000)),
            "credited_date": (BASE + timedelta(days=day)).strftime("%Y-%m-%d"),
            "raw_description": f"NEFT CR UNKNOWN {used}",
            "currency": "INR",
        }
    )
    ground_truth.append(
        {"payment_id": None, "settlement_id": None, "utr": used, "label": "orphan_bank_credit"}
    )


for _ in range(NUM_CLEAN):
    clean_loop()
for _ in range(NUM_MISSING_BANK):
    missing_bank()
for _ in range(NUM_AMOUNT_BREAK):
    amount_break()
for _ in range(NUM_FX):
    fx_break()
for _ in range(NUM_REFUND):
    refund()
for _ in range(NUM_EMPTY_UTR):
    empty_utr()
for _ in range(NUM_DUP_PAIRS):
    dup_pair()
for _ in range(NUM_ORPHAN_BANK):
    orphan_bank()

random.shuffle(payments)
random.shuffle(settlements)
random.shuffle(bank_rows)

pay_fields = ["payment_id", "amount", "customer", "timestamp", "status", "currency"]
stl_fields = [
    "settlement_id",
    "payment_ids",
    "gross_amount",
    "mdr_fee",
    "gst_on_fee",
    "net_amount",
    "utr",
    "settled_date",
    "currency",
]
bank_fields = ["utr", "credited_amount", "credited_date", "raw_description", "currency"]

with (OUT / "payments.csv").open("w", newline="", encoding="utf-8") as fh:
    w = csv.DictWriter(fh, fieldnames=pay_fields)
    w.writeheader()
    w.writerows(payments)
with (OUT / "settlements.csv").open("w", newline="", encoding="utf-8") as fh:
    w = csv.DictWriter(fh, fieldnames=stl_fields)
    w.writeheader()
    w.writerows(settlements)
with (OUT / "bank.csv").open("w", newline="", encoding="utf-8") as fh:
    w = csv.DictWriter(fh, fieldnames=bank_fields)
    w.writeheader()
    w.writerows(bank_rows)
(OUT / "ground_truth.json").write_text(json.dumps(ground_truth, indent=2), encoding="utf-8")

zip_path = OUT.parent / "low_match_rate.zip"
with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
    for name in ("payments.csv", "settlements.csv", "bank.csv", "ground_truth.json"):
        zf.write(OUT / name, name)

print(
    f"payments={len(payments)} settlements={len(settlements)} bank={len(bank_rows)} "
    f"wrote {OUT / 'payments.csv'} and {zip_path}"
)
