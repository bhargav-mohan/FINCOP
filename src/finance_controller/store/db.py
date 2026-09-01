from __future__ import annotations

import os
import sqlite3
from pathlib import Path

SCHEMA_VERSION = 1
BUSY_TIMEOUT_MS = 5000

_REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_DB_PATH = _REPO_ROOT / "data" / "finance_controller.db"
_SCHEMA_PATH = Path(__file__).with_name("schema.sql")


def db_path() -> Path:
    env = os.getenv("FC_DB_PATH", "").strip()
    if env:
        return Path(env).expanduser()
    return DEFAULT_DB_PATH


def available(path: Path | None = None) -> tuple[bool, str]:
    try:
        conn = connect(path)
        conn.execute("SELECT 1")
        conn.close()
        return True, ""
    except (sqlite3.Error, OSError) as exc:
        return False, str(exc)


def connect(path: Path | None = None) -> sqlite3.Connection:
    target = path or db_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(target), timeout=BUSY_TIMEOUT_MS / 1000)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute(f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS}")
    conn.execute("PRAGMA foreign_keys=ON")
    apply_schema(conn)
    return conn


def apply_schema(conn: sqlite3.Connection) -> None:
    current = conn.execute("PRAGMA user_version").fetchone()[0]
    if current >= SCHEMA_VERSION:
        return
    sql = _SCHEMA_PATH.read_text(encoding="utf-8")
    conn.executescript(sql)
    conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
    conn.commit()
