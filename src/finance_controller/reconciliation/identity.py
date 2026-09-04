from __future__ import annotations

import re
from collections.abc import Iterable
from difflib import SequenceMatcher

from finance_controller.models import Record

_NON_ALNUM = re.compile(r"[^A-Z0-9]")
_PUNCT = re.compile(r"[.,'`\"()/\\&+-]+")
_ALT_FIELDS = ("order_id", "entity_id", "payment_id", "invoice_id", "settlement_id")

# Longest first so "PRIVATE LIMITED" wins over "LIMITED".
_LEGAL_SUFFIXES = (
    "PRIVATE LIMITED",
    "PUBLIC LIMITED",
    "PVT LIMITED",
    "PVT LTD",
    "LIMITED",
    "INCORPORATED",
    "CORPORATION",
    "COMPANY",
    "LTD",
    "LLC",
    "LLP",
    "PLC",
    "OPC",
    "INC",
    "CORP",
    "GMBH",
    "PVT",
    "CO",
)


def compact_reference(value: str) -> str:
    """PAY-0001, PAY 0001, and pay_0001 are the same identity key."""
    return _NON_ALNUM.sub("", str(value or "").upper())


def canonical_payee(value: str) -> str:
    """Acme Pvt Ltd, ACME PRIVATE LIMITED, and The ACME Co. collapse to ACME."""
    text = str(value or "").upper().replace("&", " AND ")
    text = _PUNCT.sub(" ", text)
    text = " ".join(text.split())
    if text.startswith("THE "):
        text = text[4:]
    changed = True
    while changed and text:
        changed = False
        for suffix in _LEGAL_SUFFIXES:
            if text == suffix:
                return text
            if text.endswith(" " + suffix):
                text = text[: -(len(suffix) + 1)].rstrip()
                changed = True
                break
    return text


def payee_key(record: Record | str) -> str:
    if isinstance(record, str):
        return canonical_payee(record)
    return canonical_payee(record.payee)


def names_compatible(left: str, right: str, *, threshold: float = 0.82) -> bool:
    a, b = canonical_payee(left), canonical_payee(right)
    if not a or not b or a == b:
        return True
    ta, tb = set(a.split()), set(b.split())
    if ta and tb and (ta <= tb or tb <= ta):
        return True
    return SequenceMatcher(None, a, b).ratio() >= threshold


def identity_keys(record: Record) -> set[str]:
    """Compact identifiers this row can be joined on. Empty keys are dropped."""
    keys: set[str] = set()
    for raw in (record.reference, record.batch_id, record.split_id, record.utr):
        compacted = compact_reference(raw or "")
        if compacted:
            keys.add(compacted)
    for field in _ALT_FIELDS:
        extra = record.extra.get(field)
        if extra:
            compacted = compact_reference(str(extra))
            if compacted:
                keys.add(compacted)
    keys.discard("")
    return keys


def pair_unambiguous_by_keys(
    left: Iterable[Record],
    right: Iterable[Record],
    keys_fn,
) -> list[tuple[Record, Record]]:
    """Pair when keys uniquely identify one counterpart. Never first-come-first-serve.

    A record that uniquely keys to two different counterparts is dropped, not guessed.
    """
    lmap: dict[object, list[Record]] = {}
    rmap: dict[object, list[Record]] = {}

    def _add(bucket: dict[object, list[Record]], rec: Record) -> None:
        seen: set[object] = set()
        for key in keys_fn(rec):
            if key in ("", None, ()) or key in seen:
                continue
            seen.add(key)
            bucket.setdefault(key, []).append(rec)

    for rec in left:
        _add(lmap, rec)
    for rec in right:
        _add(rmap, rec)

    left_by_id = {r.id: r for r in left}
    right_by_id = {r.id: r for r in right}
    left_to: dict[str, set[str]] = {}
    right_to: dict[str, set[str]] = {}
    for key, ls in lmap.items():
        rs = rmap.get(key, [])
        if len(ls) != 1 or len(rs) != 1:
            continue
        left_to.setdefault(ls[0].id, set()).add(rs[0].id)
        right_to.setdefault(rs[0].id, set()).add(ls[0].id)

    pairs: list[tuple[Record, Record]] = []
    used_l: set[str] = set()
    used_r: set[str] = set()
    for lid, rids in left_to.items():
        if len(rids) != 1:
            continue
        rid = next(iter(rids))
        if len(right_to.get(rid, ())) != 1:
            continue
        if lid in used_l or rid in used_r:
            continue
        used_l.add(lid)
        used_r.add(rid)
        pairs.append((left_by_id[lid], right_by_id[rid]))
    return pairs
