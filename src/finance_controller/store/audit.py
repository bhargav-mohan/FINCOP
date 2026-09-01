from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from finance_controller.store.db import connect


def append_event(
    *,
    actor: str,
    event: str,
    run_id: int | None = None,
    exception_id: str | None = None,
    validator_passed: bool | None = None,
    proposed_record_ids: list[str] | None = None,
    evidence: list[str] | None = None,
    rationale: str = "",
    payload: dict[str, Any] | None = None,
    path: Path | None = None,
) -> int:
    conn = connect(path)
    try:
        cur = conn.execute(
            """
            INSERT INTO audit_events (
                run_id, at, exception_id, actor, event, validator_passed,
                proposed_record_ids, evidence, rationale, payload
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                datetime.now(timezone.utc).isoformat(),
                exception_id,
                actor,
                event,
                None if validator_passed is None else int(validator_passed),
                json.dumps(proposed_record_ids or []),
                json.dumps(evidence or []),
                rationale,
                json.dumps(payload or {}),
            ),
        )
        conn.commit()
        return int(cur.lastrowid)
    finally:
        conn.close()
