from __future__ import annotations

import csv
import json
import random
from datetime import datetime, timedelta
from pathlib import Path

SEED = 42
NUM_PAYMENTS_TARGET = 60
MDR_RATE = 0.02
GST_RATE = 0.18
CUSTOMERS = [
    "Acme Retail",
    "Bluepeak Foods",
    "Cedar Logistics",
    "Dhruv Textiles",
    "Everstone Labs",
    "Ferrow Motors",
    "Ganges Traders",
    "Harlow Stores",
    "Ishaan Exports",
    "Jupiter Mart",
]
BASE_DATE = datetime(2026, 6, 1)

LAYOUT = {
    "payments": Path("books") / "2026-06" / "payments.csv",
    "settlements": Path("psp") / "india" / "settlements.csv",
    "bank": Path("bank") / "hdfc" / "june" / "neft_credits.csv",
    "tax": Path("tax") / "gst" / "invoices.csv",
    "ground_truth": Path("labels") / "ground_truth.json",
    "noise": Path("noise") / "README.md",
}


def _rupees(value: float) -> float:
    return round(value, 2)


def _fee_math(gross: float) -> tuple[float, float, float]:
    mdr = _rupees(gross * MDR_RATE)
    gst = _rupees(mdr * GST_RATE)
    net = _rupees(gross - mdr - gst)
    return mdr, gst, net


def build_seed_tables(seed: int = SEED) -> dict[str, list]:
    rng = random.Random(seed)
    payments: list[dict] = []
    settlements: list[dict] = []
    bank_rows: list[dict] = []
    ground_truth: list[dict] = []
    pay_n = 1
    stl_n = 1

    def new_payment(amount: float, day_offset: int, status: str = "success") -> tuple[str, float, datetime]:
        nonlocal pay_n
        pid = f"PAY{pay_n:04d}"
        pay_n += 1
        ts = BASE_DATE + timedelta(days=day_offset, hours=rng.randint(8, 20))
        payments.append(
            {
                "payment_id": pid,
                "amount": _rupees(amount),
                "customer": rng.choice(CUSTOMERS),
                "timestamp": ts.strftime("%Y-%m-%d %H:%M:%S"),
                "status": status,
            }
        )
        return pid, amount, ts

    def make_utr() -> str:
        return "UTR" + "".join(rng.choices("0123456789", k=10))

    def add_settlement(
        pid: str,
        gross: float,
        ts: datetime,
        *,
        net: float | None = None,
        gst_override: float | None = None,
        delay_days: int = 0,
        desc: str = "SETTLEMENT",
    ) -> tuple[str, str, float, datetime, str]:
        nonlocal stl_n
        mdr, gst, computed_net = _fee_math(gross)
        if gst_override is not None:
            gst = gst_override
            computed_net = _rupees(gross - mdr - gst)
        if net is not None:
            computed_net = net
        utr = make_utr()
        settle_date = ts + timedelta(days=2)
        credit_date = settle_date + timedelta(days=delay_days)
        sid = f"STL{stl_n:04d}"
        stl_n += 1
        settlements.append(
            {
                "settlement_id": sid,
                "payment_ids": pid,
                "gross_amount": _rupees(gross),
                "mdr_fee": mdr,
                "gst_on_fee": gst,
                "net_amount": computed_net,
                "utr": utr,
                "settled_date": settle_date.strftime("%Y-%m-%d"),
            }
        )
        return sid, utr, computed_net, credit_date, desc

    for _ in range(38):
        pid, gross, ts = new_payment(rng.uniform(500, 50000), rng.randint(0, 20))
        sid, utr, net, credit_date, desc = add_settlement(pid, gross, ts)
        bank_rows.append(
            {
                "utr": utr,
                "credited_amount": net,
                "credited_date": credit_date.strftime("%Y-%m-%d"),
                "raw_description": f"NEFT CR {utr} {desc}",
            }
        )
        ground_truth.append({"payment_id": pid, "settlement_id": sid, "utr": utr, "label": "clean_match"})

    for _ in range(5):
        pid, gross, ts = new_payment(rng.uniform(1000, 30000), rng.randint(0, 20))
        sid, utr, net, credit_date, desc = add_settlement(pid, gross, ts, delay_days=rng.choice([2, 3]), desc="SETTLEMENT DELAYED")
        bank_rows.append(
            {
                "utr": utr,
                "credited_amount": net,
                "credited_date": credit_date.strftime("%Y-%m-%d"),
                "raw_description": f"NEFT CR {utr} {desc}",
            }
        )
        ground_truth.append({"payment_id": pid, "settlement_id": sid, "utr": utr, "label": "late_clearing"})

    for _ in range(3):
        day = rng.randint(0, 15)
        group: list[str] = []
        gross_total = 0.0
        for _j in range(3):
            pid, gross, _ts = new_payment(rng.uniform(500, 8000), day)
            group.append(pid)
            gross_total += gross
        mdr, gst, net = _fee_math(gross_total)
        utr = make_utr()
        settle_date = BASE_DATE + timedelta(days=day + 2)
        sid = f"STL{stl_n:04d}"
        stl_n += 1
        settlements.append(
            {
                "settlement_id": sid,
                "payment_ids": "|".join(group),
                "gross_amount": _rupees(gross_total),
                "mdr_fee": mdr,
                "gst_on_fee": gst,
                "net_amount": net,
                "utr": utr,
                "settled_date": settle_date.strftime("%Y-%m-%d"),
            }
        )
        bank_rows.append(
            {
                "utr": utr,
                "credited_amount": net,
                "credited_date": settle_date.strftime("%Y-%m-%d"),
                "raw_description": f"NEFT CR {utr} BATCH SETTLEMENT",
            }
        )
        ground_truth.append({"payment_id": "|".join(group), "settlement_id": sid, "utr": utr, "label": "aggregated"})

    for _ in range(3):
        pid, gross, ts = new_payment(rng.uniform(1000, 15000), rng.randint(0, 15), status="refunded")
        sid, utr, net, credit_date, desc = add_settlement(pid, gross, ts, net=_rupees(-gross), desc="REFUND")
        bank_rows.append(
            {
                "utr": utr,
                "credited_amount": net,
                "credited_date": credit_date.strftime("%Y-%m-%d"),
                "raw_description": f"NEFT DR {utr} {desc}",
            }
        )
        ground_truth.append({"payment_id": pid, "settlement_id": sid, "utr": utr, "label": "refund"})

    day = rng.randint(0, 15)
    pid1, gross1, ts1 = new_payment(rng.uniform(2000, 9000), day)
    sid1, dup_utr, net1, credit_date1, _ = add_settlement(pid1, gross1, ts1)
    settlements[-1]["utr"] = dup_utr
    pid2, gross2, ts2 = new_payment(rng.uniform(2000, 9000), day + 1)
    sid2, _other, net2, _cd2, _ = add_settlement(pid2, gross2, ts2)
    settlements[-1]["utr"] = dup_utr
    bank_rows.append(
        {
            "utr": dup_utr,
            "credited_amount": net1,
            "credited_date": credit_date1.strftime("%Y-%m-%d"),
            "raw_description": f"NEFT CR {dup_utr} SETTLEMENT",
        }
    )
    ground_truth.append({"payment_id": pid1, "settlement_id": sid1, "utr": dup_utr, "label": "duplicate_utr_conflict"})
    ground_truth.append({"payment_id": pid2, "settlement_id": sid2, "utr": dup_utr, "label": "duplicate_utr_conflict"})

    pid, gross, ts = new_payment(rng.uniform(3000, 12000), rng.randint(0, 15))
    mdr, gst, _ = _fee_math(gross)
    wrong_gst = _rupees(gst * 1.4)
    sid, utr, net, credit_date, desc = add_settlement(pid, gross, ts, gst_override=wrong_gst)
    bank_rows.append(
        {
            "utr": utr,
            "credited_amount": net,
            "credited_date": credit_date.strftime("%Y-%m-%d"),
            "raw_description": f"NEFT CR {utr} {desc}",
        }
    )
    ground_truth.append({"payment_id": pid, "settlement_id": sid, "utr": utr, "label": "gst_mismatch"})

    pid, gross, ts = new_payment(rng.uniform(2000, 10000), rng.randint(0, 15))
    sid, utr, net, _cd, _ = add_settlement(pid, gross, ts)
    ground_truth.append({"payment_id": pid, "settlement_id": sid, "utr": utr, "label": "missing_bank_credit"})

    orphan_utr = make_utr()
    bank_rows.append(
        {
            "utr": orphan_utr,
            "credited_amount": _rupees(rng.uniform(500, 5000)),
            "credited_date": (BASE_DATE + timedelta(days=rng.randint(0, 20))).strftime("%Y-%m-%d"),
            "raw_description": f"NEFT CR {orphan_utr} UNKNOWN CREDIT",
        }
    )
    ground_truth.append({"payment_id": None, "settlement_id": None, "utr": orphan_utr, "label": "orphan_bank_credit"})

    pid, gross, ts = new_payment(rng.uniform(3000, 9000), rng.randint(0, 15))
    sid, utr, net, credit_date, _ = add_settlement(pid, gross, ts)
    bank_rows.append(
        {
            "utr": utr,
            "credited_amount": _rupees(net - 400),
            "credited_date": credit_date.strftime("%Y-%m-%d"),
            "raw_description": f"NEFT CR {utr} SETTLEMENT ADJ",
        }
    )
    ground_truth.append({"payment_id": pid, "settlement_id": sid, "utr": utr, "label": "undocumented_adjustment"})

    pid, gross, ts = new_payment(rng.uniform(2000, 9000), rng.randint(0, 15))
    sid, utr, net, credit_date, _ = add_settlement(pid, gross, ts)
    bank_rows.append(
        {
            "utr": utr,
            "credited_amount": _rupees(net + 0.03),
            "credited_date": credit_date.strftime("%Y-%m-%d"),
            "raw_description": f"NEFT CR {utr} SETTLEMENT",
        }
    )
    ground_truth.append({"payment_id": pid, "settlement_id": sid, "utr": utr, "label": "rounding_drift"})

    assert len(payments) >= NUM_PAYMENTS_TARGET
    rng.shuffle(payments)
    rng.shuffle(settlements)
    rng.shuffle(bank_rows)

    tax_rows = []
    for i, pay in enumerate(payments, start=1):
        if pay["status"] != "success":
            continue
        if i > 55:
            break
        taxable = float(pay["amount"])
        gst_amt = _rupees(taxable * GST_RATE)
        tax_rows.append(
            {
                "invoice_id": f"INV-{i:04d}",
                "payment_id": pay["payment_id"],
                "taxable_value": taxable,
                "gst_rate": GST_RATE,
                "gst_amount": gst_amt,
                "hsn": "9983",
            }
        )

    return {
        "payments": payments,
        "settlements": settlements,
        "bank": bank_rows,
        "tax": tax_rows,
        "ground_truth": ground_truth,
    }


def write_multidir_seed(root: str | Path, *, seed: int = SEED) -> dict[str, str]:
    """Write bank / payments / settlements into separate nested folders."""
    dest = Path(root)
    dest.mkdir(parents=True, exist_ok=True)
    tables = build_seed_tables(seed)
    written: dict[str, str] = {}

    def dump_csv(rel: Path, rows: list[dict], fields: list[str]) -> None:
        path = dest / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)
        written[rel.as_posix()] = str(path)

    dump_csv(
        LAYOUT["payments"],
        tables["payments"],
        ["payment_id", "amount", "customer", "timestamp", "status"],
    )
    dump_csv(
        LAYOUT["settlements"],
        tables["settlements"],
        [
            "settlement_id",
            "payment_ids",
            "gross_amount",
            "mdr_fee",
            "gst_on_fee",
            "net_amount",
            "utr",
            "settled_date",
        ],
    )
    dump_csv(
        LAYOUT["bank"],
        tables["bank"],
        ["utr", "credited_amount", "credited_date", "raw_description"],
    )
    dump_csv(
        LAYOUT["tax"],
        tables["tax"],
        ["invoice_id", "payment_id", "taxable_value", "gst_rate", "gst_amount", "hsn"],
    )
    gt_path = dest / LAYOUT["ground_truth"]
    gt_path.parent.mkdir(parents=True, exist_ok=True)
    gt_path.write_text(json.dumps(tables["ground_truth"], indent=2), encoding="utf-8")
    written[LAYOUT["ground_truth"].as_posix()] = str(gt_path)
    noise = dest / LAYOUT["noise"]
    noise.parent.mkdir(parents=True, exist_ok=True)
    noise.write_text("Ignored by ingest. Seed folders live next to this file.\n", encoding="utf-8")
    written[LAYOUT["noise"].as_posix()] = str(noise)
    return written
