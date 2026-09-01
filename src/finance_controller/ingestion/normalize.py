from __future__ import annotations

import csv
from decimal import Decimal
from pathlib import Path

from finance_controller.ingestion.detect import FileRole

_ALIASES: dict[FileRole, dict[str, tuple[str, ...]]] = {
    FileRole.LEDGER: {
        "payment_id": ("payment_id", "id", "txn_id", "reference"),
        "amount": ("amount", "gross", "gross_amount"),
        "customer": ("customer", "payee", "merchant"),
        "timestamp": ("timestamp", "txn_date", "date", "created_at", "payment_date"),
        "status": ("status", "payment_status"),
        "currency": ("currency", "ccy"),
    },
    FileRole.BANK: {
        "utr": ("utr", "utr_no", "bank_ref"),
        "credited_amount": ("credited_amount", "amount", "credit", "net_amount", "settlement_amount"),
        "credited_date": ("credited_date", "date", "txn_date", "value_date", "settlement_date"),
        "raw_description": ("raw_description", "narration", "description", "remarks", "bank_credit_id"),
        "currency": ("currency", "ccy"),
    },
    FileRole.PSP: {
        "settlement_id": ("settlement_id", "id"),
        "payment_ids": ("payment_ids", "payment_id", "payments"),
        "gross_amount": ("gross_amount", "gross", "amount", "settlement_amount"),
        "mdr_fee": ("mdr_fee", "fee", "fees"),
        "gst_on_fee": ("gst_on_fee", "gst", "gst_amount"),
        "net_amount": ("net_amount", "net", "settlement_amount", "expected_net"),
        "utr": ("utr",),
        "settled_date": ("settled_date", "date", "settlement_date"),
        "currency": ("currency", "ccy"),
    },
    FileRole.TAX: {
        "invoice_id": ("invoice_id", "invoice", "inv_no"),
        "payment_id": ("payment_id", "txn_id", "reference"),
        "taxable_value": ("taxable_value", "taxable", "assessable_value", "amount"),
        "gst_rate": ("gst_rate", "rate", "tax_rate"),
        "gst_amount": ("gst_amount", "gst", "tax_amount"),
        "hsn": ("hsn", "hsn_code"),
    },
}

CANONICAL_FIELDS = {
    FileRole.LEDGER: ["payment_id", "amount", "customer", "timestamp", "status", "currency"],
    FileRole.BANK: ["utr", "credited_amount", "credited_date", "raw_description", "currency"],
    FileRole.PSP: [
        "settlement_id",
        "payment_ids",
        "gross_amount",
        "mdr_fee",
        "gst_on_fee",
        "net_amount",
        "utr",
        "settled_date",
        "currency",
    ],
    FileRole.TAX: ["invoice_id", "payment_id", "taxable_value", "gst_rate", "gst_amount", "hsn"],
}


def _key(name: str) -> str:
    return name.strip().lower().replace(" ", "_")


def remap_row(role: FileRole, row: dict[str, str]) -> dict[str, str]:
    by_norm = {_key(k): (v if v is not None else "") for k, v in row.items()}
    out: dict[str, str] = {}
    for canon, aliases in _ALIASES.get(role, {}).items():
        for alias in aliases:
            if alias in by_norm and by_norm[alias] != "":
                out[canon] = by_norm[alias]
                break
        else:
            out[canon] = ""
    return out


def fill_psp_from_payments(psp_rows: list[dict[str, str]], payment_rows: list[dict[str, str]]) -> None:
    """When settlement is net-only, recover gross from the payment and fee as gross − net.

    Workbooks in this shape store GST on the payment, not 18% of MDR. Copying that GST onto
    gst_on_fee makes the engine treat net as gross − (fee+GST) and nothing closes.
    """
    pays: dict[str, dict[str, str]] = {}
    for row in payment_rows:
        keyed = {_key(k): (v if v is not None else "") for k, v in row.items()}
        pid = keyed.get("payment_id") or keyed.get("id") or ""
        if pid:
            pays[pid] = keyed
    for stl in psp_rows:
        keyed = {_key(k): (v if v is not None else "") for k, v in stl.items()}
        pid = (keyed.get("payment_id") or keyed.get("payment_ids") or "").split("|")[0].strip()
        pay = pays.get(pid, {})
        gross = pay.get("gross_amount") or pay.get("amount") or keyed.get("gross_amount") or ""
        net = keyed.get("net_amount") or keyed.get("settlement_amount") or pay.get("expected_net") or ""
        if gross:
            stl["gross_amount"] = gross
        if net:
            stl["net_amount"] = net
        if gross and net and not (keyed.get("mdr_fee") or keyed.get("fee")):
            try:
                delta = Decimal(str(gross)) - Decimal(str(net))
                stl["mdr_fee"] = str(delta.quantize(Decimal("0.01")))
            except Exception:
                pass
        elif pay.get("fee") and not keyed.get("mdr_fee"):
            stl["mdr_fee"] = pay["fee"]


def write_canonical(path: Path, role: FileRole, rows: list[dict[str, str]]) -> Path:
    fields = CANONICAL_FIELDS[role]
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, "") for k in fields})
    return path
