from __future__ import annotations

import re
from collections import defaultdict

from finance_controller.models import Record, Source
from finance_controller.reconciliation.identity import compact_reference, identity_keys, payee_key
from finance_controller.reconciliation.utr import normalize_utr, utr_status

_WORD = re.compile(r"[A-Z0-9]+(?:[-_][A-Z0-9]+)*")
_ALNUM = re.compile(r"[A-Z0-9]+")
_SKIP_ENRICH = frozenset({"orphan", "duplicate_utr", "duplicate_settlement", "duplicate_of"})


def memo_compacts(text: str) -> set[str]:
    """Exact compact tokens from unstructured bank text, including joined runs.

    Substring checks are not used: PAY1 must not hit PAY12.
    """
    raw = str(text or "").upper()
    if not raw:
        return set()
    words = _WORD.findall(raw)
    alnum = _ALNUM.findall(raw)
    out: set[str] = set()
    for token in (*words, *alnum):
        compacted = compact_reference(token)
        if compacted:
            out.add(compacted)
    for tokens in (alnum, words):
        for i, _ in enumerate(tokens):
            acc = ""
            for piece in tokens[i : i + 4]:
                acc += compact_reference(piece)
                if acc:
                    out.add(acc)
    return out


def _counterparts(records: list[Record]) -> list[Record]:
    return [r for r in records if r.source != Source.BANK]


def _index_by_compact(records: list[Record]) -> dict[str, list[Record]]:
    by_key: dict[str, list[Record]] = defaultdict(list)
    seen: dict[str, set[str]] = defaultdict(set)
    for rec in records:
        for key in identity_keys(rec):
            if rec.id in seen[key]:
                continue
            seen[key].add(rec.id)
            by_key[key].append(rec)
    return by_key


def _unique_ref_hit(bank: Record, by_key: dict[str, list[Record]]) -> Record | None:
    hits = {key for key in memo_compacts(bank.description) if key in by_key}
    if not hits:
        return None

    def _pick(key: str) -> Record | None:
        recs = by_key[key]
        ledgers = [r for r in recs if r.source == Source.LEDGER]
        if len(ledgers) > 1:
            return None
        if len({compact_reference(r.reference) for r in recs}) > 1:
            return None
        return ledgers[0] if ledgers else recs[0]

    # A token that equals a ledger payment id wins over a shared settlement id.
    payment_hits: list[Record] = []
    seen: set[str] = set()
    for key in hits:
        recs = by_key[key]
        ledgers = [r for r in recs if r.source == Source.LEDGER and compact_reference(r.reference) == key]
        if len(ledgers) == 1 and ledgers[0].id not in seen:
            seen.add(ledgers[0].id)
            payment_hits.append(ledgers[0])
    if len(payment_hits) == 1:
        return payment_hits[0]
    if len(payment_hits) > 1:
        return None
    if len(hits) != 1:
        return None
    return _pick(next(iter(hits)))


def _unique_utr_hit(bank: Record, utr_index: dict[str, list[Record]]) -> str | None:
    if bank.utr or bank.extra.get("empty_utr") or bank.extra.get("malformed_utr") or bank.extra.get("expect_utr"):
        return None
    found: set[str] = set()
    for token in _ALNUM.findall((bank.description or "").upper()):
        utr = normalize_utr(token)
        if utr_status(utr) != "ok":
            continue
        if utr in utr_index:
            found.add(utr)
    if len(found) != 1:
        return None
    utr = next(iter(found))
    if len(utr_index[utr]) < 1:
        return None
    return utr


def _unique_payee_hit(bank: Record, unique_payees: dict[str, Record]) -> str | None:
    """Fill payee only when that name is globally unique among counterparts.

    Shared names like RAZORPAY on many settlement memos must not attach.
    """
    if payee_key(bank) or not unique_payees:
        return None
    hay = " " + " ".join(_ALNUM.findall((bank.description or "").upper())) + " "
    hits = [p for p in unique_payees if len(p) >= 3 and f" {p} " in hay]
    if len(hits) != 1:
        return None
    return unique_payees[hits[0]].payee


def enrich_from_narration(records: list[Record]) -> list[Record]:
    """Fill blank bank identity from unstructured memos when the hit is unique."""
    counterparts = _counterparts(records)
    by_key = _index_by_compact(counterparts)
    utr_index: dict[str, list[Record]] = defaultdict(list)
    payee_index: dict[str, list[Record]] = defaultdict(list)
    for rec in counterparts:
        if rec.utr:
            utr_index[normalize_utr(rec.utr)].append(rec)
        key = payee_key(rec)
        if key:
            payee_index[key].append(rec)
    unique_payees = {key: recs[0] for key, recs in payee_index.items() if len(recs) == 1}

    out: list[Record] = []
    for rec in records:
        if rec.source != Source.BANK or any(rec.extra.get(flag) for flag in _SKIP_ENRICH):
            out.append(rec)
            continue
        extra = dict(rec.extra)
        updates: dict = {}
        counterpart = _unique_ref_hit(rec, by_key)
        if counterpart is not None:
            if compact_reference(rec.reference) != compact_reference(counterpart.reference):
                extra.setdefault("raw_reference", rec.reference)
                extra["ref_from_narration"] = True
                updates["reference"] = counterpart.reference
            if counterpart.batch_id and not rec.batch_id:
                updates["batch_id"] = counterpart.batch_id
        utr = _unique_utr_hit(rec, utr_index)
        if utr:
            extra.setdefault("raw_utr", rec.utr)
            extra["utr_from_narration"] = True
            updates["utr"] = utr
        if not payee_key(rec):
            payee = _unique_payee_hit(rec, unique_payees)
            if payee:
                extra.setdefault("raw_payee", rec.payee)
                extra["payee_from_narration"] = True
                updates["payee"] = payee
        if updates:
            updates["extra"] = extra
            out.append(rec.model_copy(update=updates))
        else:
            out.append(rec)
    return out
