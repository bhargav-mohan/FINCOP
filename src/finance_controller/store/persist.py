from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from finance_controller.models import Report
from finance_controller.reconciliation.engine import EngineResult
from finance_controller.store.db import available
from finance_controller.store.runs import history_block, identity_key, persist_run


def attach_store(
    report: Report,
    result: EngineResult,
    *,
    batch_key: str,
    baseline_match_rate: float | None = None,
    path: Path | None = None,
) -> dict[str, Any]:
    ok, reason = available(path)
    empty = {
        "available": False,
        "reason": reason or "store unavailable",
        "batch_key": batch_key,
        "recent_runs": [],
        "repeat_offenders": [],
        "aging": {},
        "notes": {},
    }
    if not ok:
        return empty
    try:
        persist_run(
            report,
            result,
            batch_key=batch_key,
            baseline_match_rate=baseline_match_rate,
            path=path,
        )
        keys = [identity_key(exc, result.closed_keys) for exc in report.exceptions]
        block = history_block(batch_key, keys, path=path)
        block["available"] = True
        block["reason"] = ""
        return block
    except (sqlite3.Error, OSError) as exc:
        empty["reason"] = str(exc)
        return empty
