from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from base64 import b64encode

FIXTURE_DIR = Path(__file__).resolve().parents[3] / "fixtures" / "razorpay_sample"
RECON_URL = "https://api.razorpay.com/v1/settlements/recon/combined"
TIMEOUT_SEC = 10


@dataclass
class LiveFetchResult:
    rows: list[dict[str, str]]
    warnings: list[str] = field(default_factory=list)
    source: str = "fixture"
    zip_path: Path | None = None


def fixture_zip_path() -> Path:
    return FIXTURE_DIR / "batch.zip"


def _load_fixture_rows() -> tuple[list[dict[str, str]], list[str]]:
    import csv

    csv_path = FIXTURE_DIR / "settlement_recon.csv"
    warnings = ["live Razorpay fetch skipped; using offline fixture"]
    if not csv_path.exists():
        gen = Path(__file__).resolve().parents[3] / "fixtures" / "generate_razorpay_sample.py"
        if gen.exists():
            import importlib.util

            spec = importlib.util.spec_from_file_location("generate_razorpay_sample", gen)
            if spec and spec.loader:
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
                mod.write_sample(FIXTURE_DIR)
                warnings.append("generated missing Razorpay fixture")
    if not csv_path.exists():
        return [], warnings + [f"fixture CSV missing: {csv_path}"]
    with csv_path.open(newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    return rows, warnings


def _test_keys() -> tuple[str | None, str | None, list[str]]:
    warnings: list[str] = []
    key_id = (os.getenv("RAZORPAY_KEY_ID") or "").strip()
    secret = (os.getenv("RAZORPAY_KEY_SECRET") or "").strip()
    if not key_id or not secret:
        warnings.append("RAZORPAY_KEY_ID/RAZORPAY_KEY_SECRET not set")
        return None, None, warnings
    if not key_id.startswith("rzp_test_"):
        warnings.append("refusing live fetch: key is not a Razorpay test key (rzp_test_)")
        return None, None, warnings
    return key_id, secret, warnings


def _item_to_row(item: dict[str, Any]) -> dict[str, str]:
    def cell(name: str) -> str:
        value = item.get(name)
        if value is None:
            return ""
        if isinstance(value, bool):
            return "true" if value else "false"
        return str(value)

    return {
        "entity_id": cell("entity_id"),
        "type": cell("type") or "payment",
        "payment_id": cell("payment_id") or cell("entity_id"),
        "order_id": cell("order_id"),
        "amount": cell("amount"),
        "fee": cell("fee"),
        "tax": cell("tax"),
        "debit": cell("debit"),
        "credit": cell("credit"),
        "currency": cell("currency"),
        "settlement_id": cell("settlement_id"),
        "settlement_utr": cell("settlement_utr"),
        "created_at": cell("created_at"),
        "settled_at": cell("settled_at"),
        "method": cell("method"),
        "settled": cell("settled") or "true",
        "notes": cell("notes") if not isinstance(item.get("notes"), dict) else json.dumps(item.get("notes")),
    }


def fetch_recon(*, year: int = 2026, month: int = 1) -> LiveFetchResult:
    """Read-only test-mode GET. Falls back to the in-repo fixture — never required for demo/tests."""
    key_id, secret, warnings = _test_keys()
    if key_id is None or secret is None:
        rows, extra = _load_fixture_rows()
        return LiveFetchResult(
            rows=rows,
            warnings=warnings + extra,
            source="fixture",
            zip_path=fixture_zip_path(),
        )

    token = b64encode(f"{key_id}:{secret}".encode()).decode()
    url = f"{RECON_URL}?year={year}&month={month}"
    request = Request(url, headers={"Authorization": f"Basic {token}", "Accept": "application/json"})
    try:
        with urlopen(request, timeout=TIMEOUT_SEC) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError, ValueError) as exc:
        rows, extra = _load_fixture_rows()
        return LiveFetchResult(
            rows=rows,
            warnings=warnings + extra + [f"live recon GET failed ({exc}); using offline fixture"],
            source="fixture",
            zip_path=fixture_zip_path(),
        )

    items = payload.get("items") if isinstance(payload, dict) else None
    if not items:
        rows, extra = _load_fixture_rows()
        return LiveFetchResult(
            rows=rows,
            warnings=warnings + extra + ["live recon returned no items; using offline fixture"],
            source="fixture",
            zip_path=fixture_zip_path(),
        )
    rows = [_item_to_row(item) for item in items if isinstance(item, dict)]
    return LiveFetchResult(rows=rows, warnings=warnings, source="live")
