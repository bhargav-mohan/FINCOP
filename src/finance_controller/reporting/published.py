from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from finance_controller.config import ReconConfig
from finance_controller.run_finance_controller import close_finance_loop

ROOT = Path(__file__).resolve().parents[3]
PUBLISHED_PATH = ROOT / "fixtures" / "published_metrics.json"


def _snapshot(report) -> dict[str, Any]:
    cash = report.cash
    acc = report.accuracy
    return {
        "matched": report.matched,
        "exceptions": len(report.exceptions),
        "total_groups": report.total_groups,
        "match_rate": report.match_rate,
        "precision": acc.precision,
        "recall": acc.recall,
        "f1": acc.f1,
        "false_positives": acc.false_positives,
        "false_negatives": acc.false_negatives,
        "cash": {
            "settled_bank": str(cash.closed_bank_net) if cash else "0.00",
            "blocked_ledger": str(cash.in_flight_gross) if cash else "0.00",
            "blocked_count": cash.in_flight_count if cash else 0,
            "expected_not_credited": str(cash.expected_not_credited) if cash else "0.00",
            "unmatched_bank": str(cash.unmatched_bank_net) if cash else "0.00",
            "bank_credited": str(cash.bank_credited_total) if cash else "0.00",
            "expected_ledger": str(cash.expected_ledger_gross) if cash else "0.00",
            "variance": str(cash.variance) if cash else "0.00",
        },
        "forward": (
            {
                "as_of": report.forward.as_of.isoformat(),
                "due_within_window": str(report.forward.due_within_window),
                "stuck_past_window": str(report.forward.stuck_past_window),
            }
            if report.forward
            else None
        ),
    }


def measure() -> dict[str, Any]:
    razorpay, _, _ = close_finance_loop(
        config=ReconConfig(use_llm=False),
        zip_path=str(ROOT / "fixtures" / "razorpay_sample" / "batch.zip"),
    )
    csv_report, _, _ = close_finance_loop(
        config=ReconConfig(use_llm=False),
        data_dir=str(ROOT / "fixtures" / "finance_synthetic_data"),
    )
    seeded, _, _ = close_finance_loop(
        config=ReconConfig(
            seed=42,
            num_records=80,
            inject_exceptions=12,
            inject_resolvable=6,
            inject_edges=16,
            use_llm=False,
        )
    )
    return {
        "razorpay_zip": _snapshot(razorpay),
        "csv_dir": _snapshot(csv_report),
        "seed_42_80_edges": _snapshot(seeded),
    }


def expected() -> dict[str, Any]:
    return json.loads(PUBLISHED_PATH.read_text(encoding="utf-8"))


def drift(measured: dict[str, Any], want: dict[str, Any]) -> list[str]:
    failures: list[str] = []

    def walk(prefix: str, left: Any, right: Any) -> None:
        if isinstance(left, dict) and isinstance(right, dict):
            for key in sorted(set(left) | set(right)):
                if key not in left:
                    failures.append(f"{prefix}.{key}: missing in measured")
                elif key not in right:
                    failures.append(f"{prefix}.{key}: missing in published")
                else:
                    walk(f"{prefix}.{key}", left[key], right[key])
            return
        if left != right:
            failures.append(f"{prefix}: measured={left!r} published={right!r}")

    walk("published", measured, want)
    return failures
