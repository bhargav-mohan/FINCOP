from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from finance_controller.store.audit import append_event
from finance_controller.store.db import connect


def add_note(
    *,
    batch_key: str,
    exception_key: str,
    author: str,
    note: str,
    assignee: str = "",
    path: Path | None = None,
) -> int:
    conn = connect(path)
    try:
        cur = conn.execute(
            """
            INSERT INTO exception_notes (
                batch_key, exception_key, author, note, assignee, resolved_at, created_at
            ) VALUES (?, ?, ?, ?, ?, NULL, ?)
            """,
            (
                batch_key,
                exception_key,
                author,
                note,
                assignee,
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        conn.commit()
        note_id = int(cur.lastrowid)
    finally:
        conn.close()
    append_event(
        actor="analyst",
        event="note",
        exception_id=exception_key,
        rationale=note,
        payload={"batch_key": batch_key, "author": author, "assignee": assignee},
        path=path,
    )
    return note_id


def resolve_exception(
    *,
    batch_key: str,
    exception_key: str,
    author: str,
    note: str = "",
    assignee: str = "",
    path: Path | None = None,
) -> None:
    """Stamp an exception resolved, carrying any note the analyst typed alongside it.

    A blank note or assignee leaves the stored value alone, so resolving never
    erases context that was saved earlier.
    """
    conn = connect(path)
    now = datetime.now(timezone.utc).isoformat()
    try:
        conn.execute(
            """
            UPDATE exception_notes
            SET resolved_at = ?,
                note = COALESCE(NULLIF(?, ''), note),
                assignee = COALESCE(NULLIF(?, ''), assignee)
            WHERE id = (
                SELECT id FROM exception_notes
                WHERE batch_key = ? AND exception_key = ?
                ORDER BY id DESC LIMIT 1
            )
            """,
            (now, note, assignee, batch_key, exception_key),
        )
        if conn.execute("SELECT changes()").fetchone()[0] == 0:
            conn.execute(
                """
                INSERT INTO exception_notes (
                    batch_key, exception_key, author, note, assignee, resolved_at, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (batch_key, exception_key, author, note, assignee, now, now),
            )
        conn.commit()
    finally:
        conn.close()
    rationale = f"resolved by {author}"
    if note:
        rationale = f"{rationale}: {note}"
    append_event(
        actor="analyst",
        event="resolve",
        exception_id=exception_key,
        rationale=rationale,
        payload={"batch_key": batch_key, "author": author, "assignee": assignee},
        path=path,
    )


def notes_for_batch(batch_key: str, path: Path | None = None) -> dict[str, dict]:
    conn = connect(path)
    try:
        rows = conn.execute(
            """
            SELECT exception_key, author, note, assignee, resolved_at, created_at
            FROM exception_notes
            WHERE batch_key = ?
            ORDER BY id
            """,
            (batch_key,),
        ).fetchall()
    finally:
        conn.close()
    latest: dict[str, dict] = {}
    for row in rows:
        current = latest.setdefault(
            row["exception_key"],
            {"author": "", "note": "", "assignee": "", "resolved_at": None, "created_at": row["created_at"]},
        )
        # Merge per field so a later blank write cannot erase context saved earlier.
        for field in ("author", "note", "assignee"):
            if row[field]:
                current[field] = row[field]
        if row["resolved_at"]:
            current["resolved_at"] = row["resolved_at"]
    return latest
