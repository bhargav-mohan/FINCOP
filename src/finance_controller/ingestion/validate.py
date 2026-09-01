from __future__ import annotations

from finance_controller.ingestion.detect import FileRole
from finance_controller.ingestion.normalize import CANONICAL_FIELDS
from finance_controller.ingestion.zipfile_extract import IngestError


REQUIRED_ROLES = (FileRole.BANK, FileRole.LEDGER, FileRole.PSP)


def validate_detected(roles: dict[FileRole, str]) -> list[str]:
    warnings: list[str] = []
    if FileRole.RAZORPAY_RECON in roles:
        extras = [r.value for r in REQUIRED_ROLES if r in roles]
        if extras:
            warnings.append(
                "Razorpay recon present; ignored separate "
                + ", ".join(extras)
                + " files (adapter emits canonical bank/ledger/psp)"
            )
    else:
        missing = [r.value for r in REQUIRED_ROLES if r not in roles]
        if missing:
            raise IngestError(f"zip missing required files: {missing}")
    return warnings


def validate_rows(role: FileRole, rows: list[dict[str, str]]) -> None:
    if not rows:
        raise IngestError(f"{role.value} file has no data rows")
    required = CANONICAL_FIELDS[role]
    if role == FileRole.TAX:
        key_cols = ("taxable_value", "gst_amount", "gst_rate")
    elif role == FileRole.BANK:
        key_cols = ("credited_amount",)
    else:
        key_cols = tuple(required[:2])
    for i, row in enumerate(rows, start=2):
        if any(not str(row.get(c, "")).strip() for c in key_cols):
            raise IngestError(f"{role.value} row {i} missing {key_cols}")
