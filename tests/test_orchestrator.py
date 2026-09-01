from datetime import date
from decimal import Decimal

from finance_controller.agent.orchestrator import investigate_with_rules, orchestrate
from finance_controller.agent.tools import ReconWorkbench
from finance_controller.config import ReconConfig
from finance_controller.models import AgentAction, Record, Source
from finance_controller.reconciliation.engine import reconcile


def _rec(**kwargs) -> Record:
    base = dict(
        fee=Decimal("0.00"),
        description="",
        payee="",
        batch_id=None,
        txn_date=date(2026, 1, 10),
        currency="INR",
    )
    base.update(kwargs)
    return Record(**base)


def test_agent_reconciles_unique_bank_the_engine_missed():
    records = [
        _rec(id="L1", source=Source.LEDGER, reference="TXN-A", amount=Decimal("100.00"), payee="ALICE"),
        _rec(
            id="P1",
            source=Source.PSP,
            reference="TXN-A",
            amount=Decimal("100.00"),
            fee=Decimal("2.00"),
            payee="ALICE",
        ),
        _rec(
            id="B1",
            source=Source.BANK,
            reference="OTHER",
            amount=Decimal("98.00"),
            txn_date=date(2026, 1, 11),
            payee="",
        ),
    ]
    config = ReconConfig()
    result = reconcile(records, config)
    assert result.closed_group_count == 0
    bench = ReconWorkbench(result, config)
    for exc in list(result.exceptions):
        investigate_with_rules(bench, exc.exception_id)
    assert any(item.action == AgentAction.RECONCILE for item in bench.investigations)
    assert result.closed_group_count == 1
    assert any(m.tier.value == "agent_validated" for m in result.closed_matches)


def test_agent_escalates_amount_mismatch():
    records = [
        _rec(id="L1", source=Source.LEDGER, reference="TXN-A", amount=Decimal("100.00"), payee="ALICE"),
        _rec(
            id="P1",
            source=Source.PSP,
            reference="TXN-A",
            amount=Decimal("100.00"),
            fee=Decimal("2.00"),
            payee="ALICE",
        ),
        _rec(
            id="B1",
            source=Source.BANK,
            reference="TXN-A",
            amount=Decimal("113.00"),
            txn_date=date(2026, 1, 11),
            payee="ALICE",
        ),
    ]
    config = ReconConfig()
    result = reconcile(records, config)
    bench = ReconWorkbench(result, config)
    for exc in list(result.exceptions):
        investigate_with_rules(bench, exc.exception_id)
    assert all(item.action == AgentAction.ESCALATE for item in bench.investigations)
    assert result.closed_group_count == 0
    assert result.exceptions


def test_agent_refuses_fcfs_when_two_banks_would_validate():
    records = [
        _rec(id="L1", source=Source.LEDGER, reference="TXN-A", amount=Decimal("100.00"), payee="ALICE"),
        _rec(
            id="P1",
            source=Source.PSP,
            reference="TXN-A",
            amount=Decimal("100.00"),
            fee=Decimal("2.00"),
            payee="ALICE",
        ),
        _rec(id="B1", source=Source.BANK, reference="X1", amount=Decimal("98.00"), txn_date=date(2026, 1, 11)),
        _rec(id="B2", source=Source.BANK, reference="X2", amount=Decimal("98.00"), txn_date=date(2026, 1, 11)),
    ]
    config = ReconConfig()
    result = reconcile(records, config)
    bench = ReconWorkbench(result, config)
    missing = next(e for e in result.exceptions if "L1" in e.record_ids)
    investigate_with_rules(bench, missing.exception_id)
    inv = next(i for i in bench.investigations if i.exception_id == missing.exception_id)
    assert inv.action == AgentAction.ESCALATE
    assert any("ambiguous" in e for e in inv.evidence)


def test_orchestrate_fallback_without_api_key_completes_seeded_batch():
    from finance_controller.data.synthetic import generate

    config = ReconConfig(seed=42, num_records=60, inject_exceptions=12, inject_edges=0, use_llm=False)
    batch = generate(config)
    result = reconcile(batch.all_records, config)
    bench = orchestrate(result, config)
    assert bench.investigations
    assert all(i.action in {AgentAction.RECONCILE, AgentAction.ESCALATE} for i in bench.investigations)
    assert any(i.action == AgentAction.ESCALATE for i in bench.investigations)
    escalated = [i for i in bench.investigations if i.action == AgentAction.ESCALATE]
    assert len(escalated) == len(result.exceptions)
    assert {i.exception_id for i in escalated} == {e.exception_id for e in result.exceptions}


def test_agent_resolves_ambiguous_memo_cases():
    from finance_controller.data.synthetic import generate
    from finance_controller.models import CaseCategory

    config = ReconConfig(seed=42, num_records=60, inject_exceptions=12, inject_resolvable=6, inject_edges=0, use_llm=False)
    batch = generate(config)
    result = reconcile(batch.all_records, config)
    keys = {g.key for g in batch.ground_truth if g.category == CaseCategory.RESOLVABLE_AMBIGUOUS}
    engine_closed = result.closed_group_count
    bench = orchestrate(result, config)
    assert result.closed_group_count > engine_closed
    assert keys <= result.closed_keys
    assert any(i.action == AgentAction.RECONCILE for i in bench.investigations)
    open_ids = {e.exception_id for e in result.exceptions}
    escalated = [i for i in bench.investigations if i.action == AgentAction.ESCALATE]
    assert {i.exception_id for i in escalated} == open_ids
    assert len(escalated) == len(result.exceptions)


def test_escalated_count_equals_open_exceptions_on_full_seed():
    from finance_controller.data.synthetic import generate

    config = ReconConfig(
        seed=42,
        num_records=80,
        inject_exceptions=12,
        inject_resolvable=6,
        inject_edges=16,
        use_llm=False,
    )
    batch = generate(config)
    result = reconcile(batch.all_records, config)
    bench = orchestrate(result, config)
    escalated = [i for i in bench.investigations if i.action == AgentAction.ESCALATE]
    assert len(escalated) == len(result.exceptions)
    assert {i.exception_id for i in escalated} == {e.exception_id for e in result.exceptions}
    from finance_controller.reporting.report import compute_cash

    cash = compute_cash(result)
    assert cash.in_flight_count == len(result.exceptions)
    by_id = {r.id: r for r in result.records}
    expected_gross = sum(
        (
            by_id[rid].amount
            for e in result.exceptions
            for rid in e.record_ids
            if rid in by_id and by_id[rid].source == Source.LEDGER
        ),
        Decimal("0.00"),
    ).quantize(Decimal("0.01"))
    assert cash.in_flight_gross == expected_gross
