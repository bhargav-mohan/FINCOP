import random
import csv
import json
from datetime import datetime, timedelta

random.seed(42)

NUM_PAYMENTS = 60
MDR_RATE = 0.02
GST_RATE = 0.18

CUSTOMERS = ["Acme Retail", "Bluepeak Foods", "Cedar Logistics", "Dhruv Textiles",
             "Everstone Labs", "Ferrow Motors", "Ganges Traders", "Harlow Stores",
             "Ishaan Exports", "Jupiter Mart"]

BASE_DATE = datetime(2026, 6, 1)

payments = []
settlements = []
bank_rows = []
ground_truth = []  # hidden — not used by matcher, only by scorer

def rupees(x):
    return round(x, 2)

pay_id_counter = 1
settle_id_counter = 1

def new_payment(amount, day_offset, status="success"):
    global pay_id_counter
    pid = f"PAY{pay_id_counter:04d}"
    pay_id_counter += 1
    ts = BASE_DATE + timedelta(days=day_offset, hours=random.randint(8, 20))
    payments.append({
        "payment_id": pid,
        "amount": rupees(amount),
        "customer": random.choice(CUSTOMERS),
        "timestamp": ts.strftime("%Y-%m-%d %H:%M:%S"),
        "status": status
    })
    return pid, amount, ts

def make_utr():
    return "UTR" + "".join(random.choices("0123456789", k=10))

def fee_math(gross):
    mdr = rupees(gross * MDR_RATE)
    gst = rupees(mdr * GST_RATE)
    net = rupees(gross - mdr - gst)
    return mdr, gst, net

records_plan = []

# ---- 1. Clean exact matches (~65%) : 1 payment -> 1 settlement -> 1 bank row, on time (T+2)
for i in range(38):
    day = random.randint(0, 20)
    amt = round(random.uniform(500, 50000), 2)
    pid, gross, ts = new_payment(amt, day)
    mdr, gst, net = fee_math(gross)
    utr = make_utr()
    settle_date = ts + timedelta(days=2)
    sid = f"STL{settle_id_counter:04d}"; settle_id_counter += 1
    settlements.append({
        "settlement_id": sid, "payment_ids": pid, "gross_amount": gross,
        "mdr_fee": mdr, "gst_on_fee": gst, "net_amount": net,
        "utr": utr, "settled_date": settle_date.strftime("%Y-%m-%d")
    })
    bank_rows.append({
        "utr": utr, "credited_amount": net,
        "credited_date": settle_date.strftime("%Y-%m-%d"),
        "raw_description": f"NEFT CR {utr} SETTLEMENT"
    })
    ground_truth.append({"payment_id": pid, "settlement_id": sid, "utr": utr, "label": "clean_match"})

# ---- 2. Late clearing (bank credit lands T+4/T+5 instead of T+2) — should still resolve
for i in range(5):
    day = random.randint(0, 20)
    amt = round(random.uniform(1000, 30000), 2)
    pid, gross, ts = new_payment(amt, day)
    mdr, gst, net = fee_math(gross)
    utr = make_utr()
    settle_date = ts + timedelta(days=2)
    credit_date = settle_date + timedelta(days=random.choice([2, 3]))
    sid = f"STL{settle_id_counter:04d}"; settle_id_counter += 1
    settlements.append({
        "settlement_id": sid, "payment_ids": pid, "gross_amount": gross,
        "mdr_fee": mdr, "gst_on_fee": gst, "net_amount": net,
        "utr": utr, "settled_date": settle_date.strftime("%Y-%m-%d")
    })
    bank_rows.append({
        "utr": utr, "credited_amount": net,
        "credited_date": credit_date.strftime("%Y-%m-%d"),
        "raw_description": f"NEFT CR {utr} SETTLEMENT DELAYED"
    })
    ground_truth.append({"payment_id": pid, "settlement_id": sid, "utr": utr, "label": "late_clearing"})

# ---- 3. Aggregated settlement (3 payments -> 1 settlement -> 1 bank row)
for i in range(3):
    day = random.randint(0, 15)
    group_pids = []
    gross_total = 0
    for j in range(3):
        amt = round(random.uniform(500, 8000), 2)
        pid, gross, ts = new_payment(amt, day)
        group_pids.append(pid)
        gross_total += gross
    mdr, gst, net = fee_math(gross_total)
    utr = make_utr()
    settle_date = BASE_DATE + timedelta(days=day + 2)
    sid = f"STL{settle_id_counter:04d}"; settle_id_counter += 1
    settlements.append({
        "settlement_id": sid, "payment_ids": "|".join(group_pids), "gross_amount": rupees(gross_total),
        "mdr_fee": mdr, "gst_on_fee": gst, "net_amount": net,
        "utr": utr, "settled_date": settle_date.strftime("%Y-%m-%d")
    })
    bank_rows.append({
        "utr": utr, "credited_amount": net,
        "credited_date": settle_date.strftime("%Y-%m-%d"),
        "raw_description": f"NEFT CR {utr} BATCH SETTLEMENT"
    })
    ground_truth.append({"payment_id": "|".join(group_pids), "settlement_id": sid, "utr": utr, "label": "aggregated"})

# ---- 4. Refund (net negative settlement)
for i in range(3):
    day = random.randint(0, 15)
    amt = round(random.uniform(1000, 15000), 2)
    pid, gross, ts = new_payment(amt, day, status="refunded")
    mdr, gst, _ = fee_math(gross)
    net = rupees(-gross)  # full refund, money goes back out
    utr = make_utr()
    settle_date = ts + timedelta(days=2)
    sid = f"STL{settle_id_counter:04d}"; settle_id_counter += 1
    settlements.append({
        "settlement_id": sid, "payment_ids": pid, "gross_amount": gross,
        "mdr_fee": mdr, "gst_on_fee": gst, "net_amount": net,
        "utr": utr, "settled_date": settle_date.strftime("%Y-%m-%d")
    })
    bank_rows.append({
        "utr": utr, "credited_amount": net,
        "credited_date": settle_date.strftime("%Y-%m-%d"),
        "raw_description": f"NEFT DR {utr} REFUND"
    })
    ground_truth.append({"payment_id": pid, "settlement_id": sid, "utr": utr, "label": "refund"})

# ---- 5. Duplicate UTR (data error — same UTR used twice for different settlements)
day = random.randint(0, 15)
amt1 = round(random.uniform(2000, 9000), 2)
pid1, gross1, ts1 = new_payment(amt1, day)
mdr1, gst1, net1 = fee_math(gross1)
dup_utr = make_utr()
settle_date1 = ts1 + timedelta(days=2)
sid1 = f"STL{settle_id_counter:04d}"; settle_id_counter += 1
settlements.append({
    "settlement_id": sid1, "payment_ids": pid1, "gross_amount": gross1,
    "mdr_fee": mdr1, "gst_on_fee": gst1, "net_amount": net1,
    "utr": dup_utr, "settled_date": settle_date1.strftime("%Y-%m-%d")
})

amt2 = round(random.uniform(2000, 9000), 2)
pid2, gross2, ts2 = new_payment(amt2, day + 1)
mdr2, gst2, net2 = fee_math(gross2)
settle_date2 = ts2 + timedelta(days=2)
sid2 = f"STL{settle_id_counter:04d}"; settle_id_counter += 1
settlements.append({
    "settlement_id": sid2, "payment_ids": pid2, "gross_amount": gross2,
    "mdr_fee": mdr2, "gst_on_fee": gst2, "net_amount": net2,
    "utr": dup_utr, "settled_date": settle_date2.strftime("%Y-%m-%d")  # SAME UTR
})
bank_rows.append({
    "utr": dup_utr, "credited_amount": net1,
    "credited_date": settle_date1.strftime("%Y-%m-%d"),
    "raw_description": f"NEFT CR {dup_utr} SETTLEMENT"
})
ground_truth.append({"payment_id": pid1, "settlement_id": sid1, "utr": dup_utr, "label": "duplicate_utr_conflict"})
ground_truth.append({"payment_id": pid2, "settlement_id": sid2, "utr": dup_utr, "label": "duplicate_utr_conflict"})

# ---- 6. GST mismatch (fee math doesn't add up — data/calculation error)
day = random.randint(0, 15)
amt = round(random.uniform(3000, 12000), 2)
pid, gross, ts = new_payment(amt, day)
mdr, gst, net = fee_math(gross)
wrong_gst = rupees(gst * 1.4)  # deliberately wrong GST line
wrong_net = rupees(gross - mdr - wrong_gst)
utr = make_utr()
settle_date = ts + timedelta(days=2)
sid = f"STL{settle_id_counter:04d}"; settle_id_counter += 1
settlements.append({
    "settlement_id": sid, "payment_ids": pid, "gross_amount": gross,
    "mdr_fee": mdr, "gst_on_fee": wrong_gst, "net_amount": wrong_net,
    "utr": utr, "settled_date": settle_date.strftime("%Y-%m-%d")
})
bank_rows.append({
    "utr": utr, "credited_amount": wrong_net,
    "credited_date": settle_date.strftime("%Y-%m-%d"),
    "raw_description": f"NEFT CR {utr} SETTLEMENT"
})
ground_truth.append({"payment_id": pid, "settlement_id": sid, "utr": utr, "label": "gst_mismatch"})

# ---- 7. Missing bank credit (settlement confirmed, bank never shows it)
day = random.randint(0, 15)
amt = round(random.uniform(2000, 10000), 2)
pid, gross, ts = new_payment(amt, day)
mdr, gst, net = fee_math(gross)
utr = make_utr()
settle_date = ts + timedelta(days=2)
sid = f"STL{settle_id_counter:04d}"; settle_id_counter += 1
settlements.append({
    "settlement_id": sid, "payment_ids": pid, "gross_amount": gross,
    "mdr_fee": mdr, "gst_on_fee": gst, "net_amount": net,
    "utr": utr, "settled_date": settle_date.strftime("%Y-%m-%d")
})
# NOTE: no bank row added — money never showed up
ground_truth.append({"payment_id": pid, "settlement_id": sid, "utr": utr, "label": "missing_bank_credit"})

# ---- 8. Orphan bank credit (money arrived, no settlement/payment record at all)
orphan_utr = make_utr()
orphan_day = random.randint(0, 20)
bank_rows.append({
    "utr": orphan_utr, "credited_amount": round(random.uniform(500, 5000), 2),
    "credited_date": (BASE_DATE + timedelta(days=orphan_day)).strftime("%Y-%m-%d"),
    "raw_description": f"NEFT CR {orphan_utr} UNKNOWN CREDIT"
})
ground_truth.append({"payment_id": None, "settlement_id": None, "utr": orphan_utr, "label": "orphan_bank_credit"})

# ---- 9. Undocumented adjustment (bank amount off by flat Rs 400, no reason in any source)
day = random.randint(0, 15)
amt = round(random.uniform(3000, 9000), 2)
pid, gross, ts = new_payment(amt, day)
mdr, gst, net = fee_math(gross)
utr = make_utr()
settle_date = ts + timedelta(days=2)
sid = f"STL{settle_id_counter:04d}"; settle_id_counter += 1
settlements.append({
    "settlement_id": sid, "payment_ids": pid, "gross_amount": gross,
    "mdr_fee": mdr, "gst_on_fee": gst, "net_amount": net,
    "utr": utr, "settled_date": settle_date.strftime("%Y-%m-%d")
})
adjusted_credit = rupees(net - 400)  # unexplained Rs 400 short
bank_rows.append({
    "utr": utr, "credited_amount": adjusted_credit,
    "credited_date": settle_date.strftime("%Y-%m-%d"),
    "raw_description": f"NEFT CR {utr} SETTLEMENT ADJ"
})
ground_truth.append({"payment_id": pid, "settlement_id": sid, "utr": utr, "label": "undocumented_adjustment"})

# ---- 10. Amount rounding drift (paisa-level rounding mismatch)
day = random.randint(0, 15)
amt = round(random.uniform(2000, 9000), 2)
pid, gross, ts = new_payment(amt, day)
mdr, gst, net = fee_math(gross)
drifted_net = rupees(net + 0.03)  # 3 paisa rounding drift
utr = make_utr()
settle_date = ts + timedelta(days=2)
sid = f"STL{settle_id_counter:04d}"; settle_id_counter += 1
settlements.append({
    "settlement_id": sid, "payment_ids": pid, "gross_amount": gross,
    "mdr_fee": mdr, "gst_on_fee": gst, "net_amount": net,
    "utr": utr, "settled_date": settle_date.strftime("%Y-%m-%d")
})
bank_rows.append({
    "utr": utr, "credited_amount": drifted_net,
    "credited_date": settle_date.strftime("%Y-%m-%d"),
    "raw_description": f"NEFT CR {utr} SETTLEMENT"
})
ground_truth.append({"payment_id": pid, "settlement_id": sid, "utr": utr, "label": "rounding_drift"})

# shuffle everything so it's not neatly grouped by type
random.shuffle(payments)
random.shuffle(settlements)
random.shuffle(bank_rows)

print(f"payments: {len(payments)}, settlements: {len(settlements)}, bank_rows: {len(bank_rows)}")

with open("payments.csv", "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=["payment_id", "amount", "customer", "timestamp", "status"])
    w.writeheader(); w.writerows(payments)

with open("settlements.csv", "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=["settlement_id", "payment_ids", "gross_amount", "mdr_fee", "gst_on_fee", "net_amount", "utr", "settled_date"])
    w.writeheader(); w.writerows(settlements)

with open("bank.csv", "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=["utr", "credited_amount", "credited_date", "raw_description"])
    w.writeheader(); w.writerows(bank_rows)

with open("ground_truth.json", "w") as f:
    json.dump(ground_truth, f, indent=2)

print("done")
