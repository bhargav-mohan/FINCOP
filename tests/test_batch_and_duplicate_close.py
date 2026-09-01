"""Regression cover for the two shapes that produced every false positive.

A batched settlement must close as one loop, and a duplicated bank row must
cost only itself rather than blocking the primary loop it duplicates.
"""

from finance_controller.config import ReconConfig
from finance_controller.data.synthetic import generate
from finance_controller.models import ExceptionType, ExpectedStatus, MatchTier, Source
from finance_controller.reconciliation.engine import predicted_exception_keys, reconcile

CONFIG = dict(seed=42, num_records=80, inject_exceptions=12, inject_resolvable=6, inject_edges=16)


def _seeded():
    config = ReconConfig(**CONFIG, use_llm=False)
    batch = generate(config)
    return batch, reconcile(batch.all_records, config)


def test_batched_settlement_closes_as_one_loop():
    """The pairwise tiers used to consume the batch psp rows first, starving
    many_to_one and turning every batched settlement into a false exception."""
    _, result = _seeded()
    batched = [m for m in result.closed_matches if m.tier == MatchTier.MANY_TO_ONE]
    assert batched, "batched settlements must close, not land on the exception queue"

    for match in batched:
        members = [r for r in result.records if r.id in set(match.record_ids)]
        assert {r.source for r in members} == {Source.BANK, Source.PSP, Source.LEDGER}
        psps = [r for r in members if r.source == Source.PSP]
        ledgers = [r for r in members if r.source == Source.LEDGER]
        banks = [r for r in members if r.source == Source.BANK]
        assert len(banks) == 1
        assert len(psps) == len(ledgers) >= 2, "one ledger booking per psp row"
        assert set(match.record_ids) <= result.closed_record_ids

    closed_refs = {
        r.reference
        for m in batched
        for r in result.records
        if r.id in set(m.record_ids)
    }
    flagged = {ref for e in result.exceptions for ref in e.references}
    assert closed_refs & flagged == set(), "a closed batch ref must not also be an exception"


def test_batch_refs_are_labelled_matched_and_are_not_predicted():
    batch, result = _seeded()
    batched = [m for m in result.closed_matches if m.tier == MatchTier.MANY_TO_ONE]
    refs = {
        r.reference
        for m in batched
        for r in result.records
        if r.id in set(m.record_ids) and r.source != Source.BANK
    }
    gt_exceptions = {g.key for g in batch.ground_truth if g.expected_status == ExpectedStatus.EXCEPTION}
    predicted = predicted_exception_keys(result)
    assert refs, "seeded batch injects batched settlements"
    assert refs & gt_exceptions == set(), "batched refs are labelled matched"
    assert refs & predicted == set(), "so they must not be predicted as exceptions"


def test_duplicate_bank_row_closes_primary_and_flags_only_the_extra():
    batch, result = _seeded()
    dups = [
        e
        for e in result.exceptions
        if e.exception_type in {ExceptionType.DUPLICATE, ExceptionType.DUPLICATE_UTR}
    ]
    assert dups, "seeded batch injects duplicate bank rows"

    keys = predicted_exception_keys(result)
    gt = {}
    for label in batch.ground_truth:
        gt.setdefault(label.key, []).append(label)

    for exc in dups:
        members = [r for r in result.records if r.id in set(exc.record_ids)]
        assert {r.source for r in members} == {Source.BANK}, "only the extra bank row is unresolved"
        assert len(members) == 1
        assert members[0].extra.get("duplicate_of") or members[0].extra.get("duplicate_utr")

        for ref in exc.references:
            assert ref in result.closed_keys, f"primary loop for {ref} must still close"
            # The duplicate is reported under the "#dup" key, and the primary
            # reference is not reported at all.
            assert f"{ref}#dup" in keys
            assert ref not in keys
            assert any(g.expected_status == ExpectedStatus.MATCHED for g in gt.get(ref, []))
            assert any(
                g.expected_status == ExpectedStatus.EXCEPTION for g in gt.get(f"{ref}#dup", [])
            )


def test_duplicate_primary_loop_records_all_close():
    _, result = _seeded()
    dup_banks = [
        r
        for r in result.records
        if r.source == Source.BANK
        and (r.extra.get("duplicate_of") or r.extra.get("duplicate_utr"))
    ]
    assert dup_banks
    for dup in dup_banks:
        assert dup.id not in result.closed_record_ids, "the extra row never closes"
        siblings = [
            r for r in result.records if r.reference == dup.reference and r.id != dup.id
        ]
        assert siblings
        assert all(r.id in result.closed_record_ids for r in siblings), (
            "every other record on that reference closes"
        )
