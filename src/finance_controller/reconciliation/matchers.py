from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Iterable
from decimal import Decimal

from finance_controller.config import ReconConfig
from finance_controller.models import MatchResult, MatchTier, PaymentStatus, Record, Source
from finance_controller.reconciliation.dates import banking_days_between


def _mid(prefix: str, n: int) -> str:
    return f"{prefix}{n:04d}"


def expected_net(record: Record, fee_rate: Decimal) -> Decimal:
    if record.source == Source.PSP:
        return record.net_amount
    fee = (record.amount * fee_rate).quantize(Decimal("0.01"))
    return (record.amount - fee).quantize(Decimal("0.01"))


def payee_key(record: Record) -> str:
    return (record.payee or "").strip().upper()


def pair_unambiguous(
    left: Iterable[Record],
    right: Iterable[Record],
    key_fn: Callable[[Record], object],
) -> list[tuple[Record, Record]]:
    """Pair only when the key is unique on both sides. Never first-come-first-serve."""
    lmap: dict[object, list[Record]] = defaultdict(list)
    rmap: dict[object, list[Record]] = defaultdict(list)
    for rec in left:
        key = key_fn(rec)
        if key in ("", None, ()):
            continue
        lmap[key].append(rec)
    for rec in right:
        key = key_fn(rec)
        if key in ("", None, ()):
            continue
        rmap[key].append(rec)
    pairs: list[tuple[Record, Record]] = []
    for key, ls in lmap.items():
        rs = rmap.get(key, [])
        if len(ls) == 1 and len(rs) == 1:
            pairs.append((ls[0], rs[0]))
    return pairs


def _emit(
    matches: list[MatchResult],
    used: set[str],
    prefix: str,
    n: int,
    left: Record,
    right: Record,
    tier: MatchTier,
    reason: str,
) -> int:
    n += 1
    matches.append(
        MatchResult(
            match_id=_mid(prefix, n),
            tier=tier,
            record_ids=[left.id, right.id],
            references=sorted({left.reference, right.reference}),
            reason=reason,
        )
    )
    used.add(left.id)
    used.add(right.id)
    return n


def is_matchable(record: Record) -> bool:
    if record.extra.get("malformed_amount"):
        return False
    return record.status == PaymentStatus.SUCCESS


def exact_matches(records: list[Record], used: set[str]) -> list[MatchResult]:
    available = [r for r in records if r.id not in used and is_matchable(r)]
    matches: list[MatchResult] = []
    n = 0

    def unused(source: Source) -> list[Record]:
        return [r for r in available if r.source == source and r.id not in used]

    for left_src, right_src in (
        (Source.LEDGER, Source.PSP),
        (Source.BANK, Source.LEDGER),
        (Source.BANK, Source.PSP),
    ):
        left, right = unused(left_src), unused(right_src)
        for a, b in pair_unambiguous(
            left, right, lambda r: (r.reference, r.amount, r.currency)
        ):
            n = _emit(
                matches,
                used,
                "E",
                n,
                a,
                b,
                MatchTier.EXACT,
                "same reference, amount, and currency",
            )
        left, right = unused(left_src), unused(right_src)
        for a, b in pair_unambiguous(
            left,
            right,
            lambda r: (payee_key(r), r.amount, r.currency) if payee_key(r) else "",
        ):
            n = _emit(
                matches,
                used,
                "E",
                n,
                a,
                b,
                MatchTier.EXACT,
                f"same payee ({a.payee}), amount, and currency",
            )
    return matches


def _tolerant_hit(
    bank: Record, cand: Record, config: ReconConfig
) -> bool:
    if cand.currency != bank.currency:
        return False
    net = expected_net(cand, config.fee_rate)
    if abs(bank.amount - net) > config.amount_tolerance:
        return False
    days = banking_days_between(cand.txn_date, bank.txn_date, config.holidays)
    if days < 0 or days > config.date_lag_days:
        return False
    if bank.created_date and cand.created_date and bank.txn_date < cand.created_date:
        return False
    return True


def _pick_unique(
    bank: Record,
    candidates: list[Record],
    config: ReconConfig,
    claimed_counterparts: set[str],
) -> Record | None:
    hits = [
        c
        for c in candidates
        if c.id not in claimed_counterparts and _tolerant_hit(bank, c, config)
    ]
    if payee_key(bank):
        payee_hits = [c for c in hits if payee_key(c) == payee_key(bank)]
        if payee_hits:
            hits = payee_hits
        elif any(payee_key(c) for c in hits):
            return None
    psp_hits = [c for c in hits if c.source == Source.PSP]
    if len(psp_hits) == 1:
        return psp_hits[0]
    if len(hits) == 1:
        return hits[0]
    return None


def tolerant_matches(
    records: list[Record], used: set[str], config: ReconConfig
) -> list[MatchResult]:
    banks = sorted(
        [r for r in records if r.source == Source.BANK and r.id not in used and is_matchable(r)],
        key=lambda r: r.id,
    )
    counterparts = [r for r in records if r.source in (Source.LEDGER, Source.PSP) and is_matchable(r)]
    by_ref: dict[str, list[Record]] = defaultdict(list)
    by_payee: dict[str, list[Record]] = defaultdict(list)
    by_utr: dict[str, list[Record]] = defaultdict(list)
    for rec in counterparts:
        by_ref[rec.reference].append(rec)
        if payee_key(rec):
            by_payee[payee_key(rec)].append(rec)
        if rec.utr:
            by_utr[rec.utr].append(rec)

    matches: list[MatchResult] = []
    n = 0
    claimed_counterparts: set[str] = set()
    claimed_payee_amt: set[tuple[str, Decimal, str]] = set()
    for bank in banks:
        if bank.id in used or bank.batch_id:
            continue
        if bank.amount <= 0:
            continue
        cand = _pick_unique(
            bank, by_ref.get(bank.reference, []), config, claimed_counterparts
        )
        if cand is None and bank.utr and len(by_utr.get(bank.utr, [])) == 1:
            cand = _pick_unique(
                bank, by_utr.get(bank.utr, []), config, claimed_counterparts
            )
        if cand is None and payee_key(bank):
            key = (payee_key(bank), bank.amount, bank.currency)
            if key not in claimed_payee_amt:
                cand = _pick_unique(
                    bank, by_payee.get(payee_key(bank), []), config, claimed_counterparts
                )
        if cand is None:
            continue
        n += 1
        matches.append(
            MatchResult(
                match_id=_mid("T", n),
                tier=MatchTier.TOLERANT,
                record_ids=[bank.id, cand.id],
                references=sorted({bank.reference, cand.reference}),
                reason=(
                    f"bank net {bank.amount} within {config.amount_tolerance} "
                    f"of expected {expected_net(cand, config.fee_rate)}; "
                    f"date lag <= {config.date_lag_days}d"
                    + (
                        f"; payee {bank.payee}"
                        if payee_key(bank) and payee_key(bank) == payee_key(cand)
                        else ""
                    )
                ),
            )
        )
        used.add(bank.id)
        used.add(cand.id)
        claimed_counterparts.add(cand.id)
        for rec in counterparts:
            same_ref = rec.reference == cand.reference
            same_payee = bool(payee_key(cand)) and payee_key(rec) == payee_key(cand)
            if rec.id == cand.id or (same_ref and (same_payee or not payee_key(cand))):
                claimed_counterparts.add(rec.id)
        if payee_key(bank):
            claimed_payee_amt.add((payee_key(bank), bank.amount, bank.currency))
    return matches


def many_to_one_matches(
    records: list[Record], used: set[str], config: ReconConfig
) -> list[MatchResult]:
    banks = sorted(
        [
            r
            for r in records
            if r.source == Source.BANK and r.id not in used and r.batch_id and is_matchable(r)
        ],
        key=lambda r: r.id,
    )
    psp_by_batch: dict[str, list[Record]] = defaultdict(list)
    ledger_by_batch_ref: dict[tuple[str, str], list[Record]] = defaultdict(list)
    for rec in records:
        if not rec.batch_id or not is_matchable(rec):
            continue
        if rec.source == Source.PSP:
            psp_by_batch[rec.batch_id].append(rec)
        elif rec.source == Source.LEDGER:
            ledger_by_batch_ref[(rec.batch_id, rec.reference)].append(rec)

    matches: list[MatchResult] = []
    n = 0
    claimed_batches: set[str] = set()
    for bank in banks:
        batch_id = bank.batch_id or ""
        if not batch_id or batch_id in claimed_batches:
            continue
        psp_rows = sorted(
            [p for p in psp_by_batch.get(batch_id, []) if p.id not in used],
            key=lambda r: r.id,
        )
        if len(psp_rows) < 2:
            continue
        if any(p.currency != bank.currency for p in psp_rows):
            continue
        total = sum((p.net_amount for p in psp_rows), Decimal("0.00")).quantize(Decimal("0.01"))
        slack = config.amount_tolerance * len(psp_rows)
        if abs(bank.amount - total) > slack:
            continue
        max_psp = max(p.txn_date for p in psp_rows)
        days = banking_days_between(max_psp, bank.txn_date, config.holidays)
        if days < 0 or days > config.date_lag_days:
            continue
        # Claim the ledger side too. A batched settlement only closes when the
        # component holds one ledger row per psp row, so the bank credit and its
        # ledger bookings have to land in the same match.
        ledger_rows: list[Record] = []
        for psp in psp_rows:
            candidates = [
                led
                for led in ledger_by_batch_ref.get((batch_id, psp.reference), [])
                if led.id not in used
            ]
            if len(candidates) == 1:
                ledger_rows.append(candidates[0])
        n += 1
        claimed = [bank, *psp_rows, *ledger_rows]
        matches.append(
            MatchResult(
                match_id=_mid("M", n),
                tier=MatchTier.MANY_TO_ONE,
                record_ids=[r.id for r in claimed],
                references=sorted({r.reference for r in claimed}),
                reason=(
                    f"bank {bank.amount} equals sum of {len(psp_rows)} psp nets ({total})"
                    + (f" with {len(ledger_rows)} ledger bookings" if ledger_rows else "")
                ),
            )
        )
        claimed_batches.add(batch_id)
        for rec in claimed:
            used.add(rec.id)
    return matches


def one_to_many_matches(
    records: list[Record], used: set[str], config: ReconConfig
) -> list[MatchResult]:
    """One PSP/ledger payment split across two or more bank credits."""
    banks = sorted(
        [
            r
            for r in records
            if r.source == Source.BANK and r.id not in used and not r.batch_id and is_matchable(r) and r.amount > 0
        ],
        key=lambda r: r.id,
    )
    by_key: dict[str, list[Record]] = defaultdict(list)
    for bank in banks:
        key = bank.split_id or bank.reference
        by_key[key].append(bank)
    psps = [r for r in records if r.source == Source.PSP and is_matchable(r)]
    psp_by_key: dict[str, list[Record]] = defaultdict(list)
    for psp in psps:
        psp_by_key[psp.split_id or psp.reference].append(psp)

    matches: list[MatchResult] = []
    n = 0
    for key in sorted(by_key):
        group = by_key[key]
        if len(group) < 2:
            continue
        group = sorted(group, key=lambda r: r.id)
        psp_rows = list(psp_by_key.get(key, []))
        if len(psp_rows) != 1:
            continue
        psp = psp_rows[0]
        total = sum((b.amount for b in group), Decimal("0.00")).quantize(Decimal("0.01"))
        slack = config.amount_tolerance * len(group)
        if abs(total - psp.net_amount) > slack:
            continue
        max_bank = max(b.txn_date for b in group)
        days = banking_days_between(psp.txn_date, max_bank, config.holidays)
        if days < 0 or days > config.date_lag_days:
            continue
        n += 1
        ids = [psp.id, *[b.id for b in group]]
        matches.append(
            MatchResult(
                match_id=_mid("S", n),
                tier=MatchTier.ONE_TO_MANY,
                record_ids=ids,
                references=sorted({psp.reference, *[b.reference for b in group]}),
                reason=f"split: {len(group)} bank credits {total} equal psp net {psp.net_amount}",
            )
        )
        used.add(psp.id)
        for bank in group:
            used.add(bank.id)
    return matches
