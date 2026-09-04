from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from decimal import Decimal

from finance_controller.config import ReconConfig
from finance_controller.models import (
    ExceptionType,
    MatchResult,
    PaymentStatus,
    Record,
    ReconException,
    Source,
)
from finance_controller.reconciliation.dates import banking_days_between
from finance_controller.reconciliation.gst import GST_TOLERANCE, gst_half_up, gst_on_mdr
from finance_controller.reconciliation.identity import compact_reference, payee_key
from finance_controller.reconciliation.matchers import (
    expected_net,
    exact_matches,
    is_matchable,
    many_to_one_matches,
    one_to_many_matches,
    tolerant_matches,
)
from finance_controller.reconciliation.narration import enrich_from_narration
from finance_controller.reconciliation.normalize import normalize_records
from finance_controller.reconciliation.utr import utr_status


class _UnionFind:
    def __init__(self) -> None:
        self.parent: dict[str, str] = {}

    def add(self, item: str) -> None:
        self.parent.setdefault(item, item)

    def find(self, item: str) -> str:
        self.add(item)
        while self.parent[item] != item:
            self.parent[item] = self.parent[self.parent[item]]
            item = self.parent[item]
        return item

    def union(self, left: str, right: str) -> None:
        a, b = self.find(left), self.find(right)
        if a != b:
            self.parent[b] = a


@dataclass
class EngineResult:
    matches: list[MatchResult]
    closed_matches: list[MatchResult]
    closed_record_ids: set[str]
    closed_keys: set[str]
    closed_group_count: int
    exceptions: list[ReconException]
    records: list[Record] = field(default_factory=list)


def _group_key(record: Record) -> str:
    if record.batch_id:
        return record.batch_id
    ref = compact_reference(record.reference) or record.reference
    payee = payee_key(record)
    if payee:
        return f"{ref}|{payee}"
    return ref


def is_closed_group(members: list[Record]) -> bool:
    banks = [r for r in members if r.source == Source.BANK]
    ledgers = [r for r in members if r.source == Source.LEDGER]
    psps = [r for r in members if r.source == Source.PSP]
    if not ledgers or not psps:
        return False
    if len(banks) == 1:
        bank = banks[0]
        if bank.batch_id:
            return len(ledgers) == len(psps) and len(psps) >= 2
        return len(ledgers) == 1 and len(psps) == 1
    if len(banks) >= 2 and len(ledgers) == 1 and len(psps) == 1:
        return True
    return False


def _gst_block(members: list[Record]) -> tuple[ExceptionType, str] | None:
    for rec in members:
        if rec.source not in (Source.LEDGER, Source.PSP):
            continue
        if rec.extra.get("gst_exempt"):
            continue
        if rec.extra.get("gst_on_mdr"):
            mdr = Decimal(str(rec.extra.get("mdr_fee", "0")))
            expected_fee_gst = gst_on_mdr(mdr)
            if abs(rec.gst - expected_fee_gst) > GST_TOLERANCE:
                return (
                    ExceptionType.GST_MISMATCH,
                    f"gst_on_fee {rec.gst} != 18% of mdr {mdr} ({expected_fee_gst})",
                )
            continue
        if rec.gst == 0:
            if rec.extra.get("taxable") or rec.extra.get("gst_zero_bug"):
                return ExceptionType.GST_ZERO_BUG, "gst is zero on a non-exempt taxable line"
            continue
        expected = gst_half_up(rec.amount)
        if abs(rec.gst - expected) > GST_TOLERANCE:
            return (
                ExceptionType.GST_MISMATCH,
                f"gst {rec.gst} != half_up {expected} (tol {GST_TOLERANCE})",
            )
    return None


def _amounts_ok(members: list[Record], config: ReconConfig) -> bool:
    banks = [r for r in members if r.source == Source.BANK]
    psps = [r for r in members if r.source == Source.PSP]
    ledgers = [r for r in members if r.source == Source.LEDGER]
    if not banks or not psps:
        return False
    if any(b.amount <= 0 for b in banks):
        return False
    if len(banks) == 1 and banks[0].batch_id:
        total = sum((p.net_amount for p in psps), Decimal("0.00")).quantize(Decimal("0.01"))
        slack = config.amount_tolerance * max(len(psps), 1)
        return abs(banks[0].amount - total) <= slack and len(ledgers) == len(psps) and len(psps) >= 2
    net = expected_net(psps[0], config.fee_rate)
    if len(banks) == 1:
        return abs(banks[0].amount - net) <= config.amount_tolerance
    total = sum((b.amount for b in banks), Decimal("0.00")).quantize(Decimal("0.01"))
    return abs(total - net) <= config.amount_tolerance * len(banks)


def _block_close(members: list[Record], config: ReconConfig) -> bool:
    if any(not is_matchable(r) for r in members):
        return True
    gst_hit = _gst_block(members)
    if gst_hit:
        return True
    if any(
        r.extra.get("empty_utr")
        or r.extra.get("malformed_utr")
        or r.extra.get("malformed_amount")
        or r.extra.get("refund")
        or r.extra.get("chargeback")
        # A UTR reused across settlements, or a payment settled twice, is a
        # conflict even when this group looks clean on its own. _classify calls
        # these DUPLICATE_UTR/DUPLICATE, so the close gate must agree -- otherwise
        # the agent can close what the engine would have refused.
        or r.extra.get("duplicate_utr")
        or r.extra.get("duplicate_settlement")
        or r.extra.get("duplicate_of")
        for r in members
    ):
        return True
    banks = [r for r in members if r.source == Source.BANK]
    if any(
        r.extra.get("expect_utr") and utr_status(r.utr) == "empty" for r in banks
    ):
        return True
    if any(utr_status(r.utr) == "malformed" for r in banks if r.utr):
        return True
    bank_utrs = [r.utr for r in banks if r.utr]
    split = any(r.split_id for r in members)
    if not split and len(bank_utrs) != len(set(bank_utrs)):
        return True
    statuses = {r.status for r in members}
    if PaymentStatus.FAILED in statuses or PaymentStatus.PENDING in statuses:
        return True
    if not _amounts_ok(members, config):
        return True
    ledgers = [r for r in members if r.source == Source.LEDGER]
    psps = [r for r in members if r.source == Source.PSP]
    counterpart_rows = psps or ledgers
    start = max(r.txn_date for r in counterpart_rows)
    min_counterpart = min(r.txn_date for r in counterpart_rows)
    max_bank = max(b.txn_date for b in banks)
    days = banking_days_between(start, max_bank, config.holidays)
    if days < 0 or days > config.date_lag_days:
        return True
    if any(b.txn_date < min_counterpart for b in banks):
        return True
    created = [r.created_date for r in counterpart_rows if r.created_date]
    if created and any(b.txn_date < min(created) for b in banks):
        return True
    return False


def _classify(
    members: list[Record],
    all_by_ref: dict[str, list[Record]],
    closed_ids: set[str],
    config: ReconConfig,
) -> tuple[ExceptionType, str]:
    sources = {r.source for r in members}
    banks = [r for r in members if r.source == Source.BANK]
    refs = {r.reference for r in members}
    currencies = {r.currency for r in members}
    statuses = {r.status for r in members}

    if any(r.extra.get("malformed_amount") for r in members):
        return ExceptionType.MALFORMED_AMOUNT, "non-finite or unparsable amount"

    if PaymentStatus.REFUNDED in statuses or any(b.amount <= 0 for b in banks):
        return ExceptionType.ZERO_OR_NEGATIVE_NET, "settlement net is zero or negative (refund/chargeback)"

    if PaymentStatus.FAILED in statuses or PaymentStatus.PENDING in statuses:
        if len(statuses) > 1 or PaymentStatus.SUCCESS not in statuses:
            return ExceptionType.STATUS_MISMATCH, f"status set {sorted(s.value for s in statuses)}"

    extra_banks = []
    for ref in refs:
        extra_banks.extend(r for r in all_by_ref.get(ref, []) if r.source == Source.BANK)
    unique_bank_ids = {r.id for r in extra_banks}
    closed_banks = {r.id for r in extra_banks if r.id in closed_ids}

    utrs = [r.utr for r in members if r.source == Source.BANK]
    if any(r.extra.get("empty_utr") or (utr_status(r.utr) == "empty" and r.extra.get("expect_utr")) for r in members if r.source == Source.BANK):
        return ExceptionType.EMPTY_UTR, "bank UTR is empty"
    if any(r.extra.get("malformed_utr") or utr_status(r.utr) == "malformed" for r in members if r.source == Source.BANK and r.utr):
        return ExceptionType.MALFORMED_UTR, "bank UTR failed format check"

    bank_utrs = [r.utr for r in members if r.source == Source.BANK and r.utr]
    if len(bank_utrs) != len(set(bank_utrs)) or any(r.extra.get("duplicate_utr") for r in members):
        return ExceptionType.DUPLICATE_UTR, "same UTR ingested more than once"

    if any(r.extra.get("orphan") or r.reference.startswith("UNK-") for r in members):
        return ExceptionType.UNMATCHED, "orphan bank row with no counterpart"

    if any(r.extra.get("refund") for r in members):
        psps = [r for r in members if r.source == Source.PSP]
        if psps and banks and 0 < banks[0].amount < psps[0].net_amount - config.amount_tolerance:
            return ExceptionType.PARTIAL_REFUND, "bank net below gross-minus-fees (partial refund)"
        if banks and 0 < banks[0].amount:
            return ExceptionType.PARTIAL_REFUND, "partial refund indicated on settlement"

    ledgers = [r for r in members if r.source == Source.LEDGER]
    psps = [r for r in members if r.source == Source.PSP]
    if banks and (ledgers or psps):
        counterpart_rows = psps or ledgers
        start = max(r.txn_date for r in counterpart_rows)
        end = max(b.txn_date for b in banks)
        days = banking_days_between(start, end, config.holidays)
        if days < 0 or min(b.txn_date for b in banks) < min(r.txn_date for r in counterpart_rows):
            return ExceptionType.DATE_INVERTED, "settlement/bank dated before payment"
        if days > config.date_lag_days:
            return ExceptionType.LATE_SETTLEMENT, f"cleared after {days} banking days"
        created = [r.created_date for r in counterpart_rows if r.created_date]
        if created and any(b.txn_date < min(created) for b in banks):
            return ExceptionType.DATE_INVERTED, "bank credit dated before settlement record created"

    if closed_banks and banks and not (sources & {Source.LEDGER, Source.PSP}):
        return ExceptionType.DUPLICATE, "extra bank row with same reference"

    if Source.LEDGER not in sources and Source.PSP in sources and Source.BANK in sources:
        return ExceptionType.MISSING_IN_LEDGER, "psp/bank present, ledger missing"

    if Source.LEDGER not in sources and Source.BANK in sources and Source.PSP not in sources:
        counterparts = [r for ref in refs for r in all_by_ref.get(ref, [])]
        if not any(r.source in (Source.LEDGER, Source.PSP) for r in counterparts):
            return ExceptionType.UNMATCHED, "no ledger or psp counterpart"
        return ExceptionType.MISSING_IN_LEDGER, "bank present, ledger missing"

    if Source.BANK not in sources and (Source.LEDGER in sources or Source.PSP in sources):
        return ExceptionType.MISSING_IN_BANK, "ledger/psp present, bank missing"

    gst_hit = _gst_block(members)
    if gst_hit:
        return gst_hit

    if len(unique_bank_ids) > 1 and Source.BANK in sources and len(banks) == 1:
        return ExceptionType.DUPLICATE, "extra bank row with same reference"

    if len(banks) > 1:
        if any(b.split_id for b in banks) or any(r.split_id for r in members):
            return ExceptionType.AMOUNT_MISMATCH, "split bank credits do not sum to psp net"
        return ExceptionType.DUPLICATE, "multiple bank rows for the same reference"

    if len(currencies) > 1:
        return ExceptionType.FX_MISMATCH, f"currency mismatch: {sorted(currencies)}"

    if Source.BANK in sources and (Source.LEDGER in sources or Source.PSP in sources):
        bank = banks[0]
        counterpart = psps[0] if psps else ledgers[0]
        expected = expected_net(counterpart, config.fee_rate)
        return ExceptionType.AMOUNT_MISMATCH, (
            f"bank {bank.amount} does not match expected net {expected} "
            f"(gross {counterpart.amount}, fee {counterpart.fee})"
        )

    return ExceptionType.UNMATCHED, "could not reconcile this group"


def reconcile(records: list[Record], config: ReconConfig) -> EngineResult:
    if not records:
        return EngineResult(
            matches=[],
            closed_matches=[],
            closed_record_ids=set(),
            closed_keys=set(),
            closed_group_count=0,
            exceptions=[],
            records=[],
        )
    normalized = enrich_from_narration(normalize_records(records))
    used: set[str] = set()

    matches: list[MatchResult] = []
    # Deterministic, tier-prioritized — not input-order greedy.
    # Tiers run in fixed order (M → E → T → S). An earlier tier that emits a
    # pair marks those ids used, so a later tier cannot form a competing pair
    # on the same id. That is priority, not a race: the order is part of the
    # contract (batch_id is the strongest signal; pairwise first would steal
    # batch PSP rows).
    # Within a tier, a pair is emitted only when the join key uniquely
    # identifies one counterpart on both sides. Ambiguous keys are dropped,
    # never first-come-first-serve. Competing banks for one batch or
    # counterpart are resolved by sorting on record id, not list order.
    # Same records → same closed groups and exception groups. Match ids
    # (E0001, …) follow emission order and may change if the input list is
    # shuffled; the groupings must not.
    matches.extend(many_to_one_matches(normalized, used, config))
    matches.extend(exact_matches(normalized, used))
    matches.extend(tolerant_matches(normalized, used, config))
    matches.extend(one_to_many_matches(normalized, used, config))

    uf = _UnionFind()
    for rec in normalized:
        uf.add(rec.id)
    for match in matches:
        for a, b in zip(match.record_ids, match.record_ids[1:]):
            uf.union(a, b)

    components: dict[str, list[Record]] = defaultdict(list)
    for rec in normalized:
        components[uf.find(rec.id)].append(rec)

    closed_ids: set[str] = set()
    closed_keys: set[str] = set()
    closed_group_count = 0
    for members in components.values():
        if not is_closed_group(members):
            continue
        if _block_close(members, config):
            continue
        closed_group_count += 1
        closed_ids.update(r.id for r in members)
        for rec in members:
            closed_keys.add(_group_key(rec))
            closed_keys.add(rec.reference)

    closed_matches = [m for m in matches if set(m.record_ids) <= closed_ids]

    leftover = [r for r in normalized if r.id not in closed_ids]
    all_by_ref: dict[str, list[Record]] = defaultdict(list)
    for rec in normalized:
        all_by_ref[rec.reference].append(rec)

    clusters: dict[str, list[Record]] = defaultdict(list)
    for rec in leftover:
        clusters[_group_key(rec)].append(rec)

    exceptions: list[ReconException] = []
    for i, (key, members) in enumerate(sorted(clusters.items()), start=1):
        etype, reason = _classify(members, all_by_ref, closed_ids, config)
        amounts = {r.id: r.amount for r in members}
        exceptions.append(
            ReconException(
                exception_id=f"X{i:04d}",
                exception_type=etype,
                record_ids=[r.id for r in sorted(members, key=lambda x: x.id)],
                references=sorted({r.reference for r in members}),
                sources_involved=sorted({r.source for r in members}, key=lambda s: s.value),
                amounts=amounts,
                reason=reason,
            )
        )

    return EngineResult(
        matches=matches,
        closed_matches=closed_matches,
        closed_record_ids=closed_ids,
        closed_keys=closed_keys,
        closed_group_count=closed_group_count,
        exceptions=exceptions,
        records=normalized,
    )


def keys_for_exception(exc: ReconException, closed_keys: set[str]) -> set[str]:
    if exc.exception_type in {ExceptionType.DUPLICATE, ExceptionType.DUPLICATE_UTR}:
        # "#dup" means "the primary closed and this is the extra copy", so only
        # use it when a primary actually closed. When nothing closed, the plain
        # reference is the unresolved item -- inventing a "#dup" key that no
        # label set uses would score as a false positive.
        return {
            f"{ref}#dup" if ref in closed_keys else ref
            for ref in exc.references
        }
    return set(exc.references)


def predicted_exception_keys(result: EngineResult) -> set[str]:
    keys: set[str] = set()
    for exc in result.exceptions:
        keys |= keys_for_exception(exc, result.closed_keys)
    return keys
