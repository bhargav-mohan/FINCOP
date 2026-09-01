from __future__ import annotations

import re

_UTR_RE = re.compile(r"^[A-Z0-9]{10,22}$")


def normalize_utr(value: str) -> str:
    return str(value or "").strip().upper().replace(" ", "")


def utr_status(value: str) -> str:
    """empty | malformed | ok"""
    utr = normalize_utr(value)
    if not utr:
        return "empty"
    if not _UTR_RE.match(utr):
        return "malformed"
    return "ok"
