from finance_controller.agent.orchestrator import orchestrate
from finance_controller.config import ReconConfig
from finance_controller.data.synthetic import generate
from finance_controller.models import AgentAction
from finance_controller.reconciliation.engine import reconcile
from finance_controller.reporting.report import (
    ASSUMED_MINUTES_PER_ITEM,
    VALUE_ASSUMPTION,
    build_report,
    compute_value,
)


def test_value_metrics_split_equals_investigations_and_states_assumption():
    config = ReconConfig(
        seed=42,
        num_records=60,
        inject_exceptions=12,
        inject_resolvable=6,
        inject_edges=0,
        use_llm=False,
    )
    batch = generate(config)
    result = reconcile(batch.all_records, config)
    bench = orchestrate(result, config)
    report = build_report(
        config=config,
        source_counts={"ledger": len(batch.ledger), "bank": len(batch.bank), "psp": len(batch.psp)},
        result=result,
        ground_truth=batch.ground_truth,
        llm_used=False,
        investigations=bench.investigations,
    )
    value = report.value
    assert value is not None
    assert value.auto_closed_by_ai + value.sent_to_analyst == len(report.investigations)
    assert value.assumed_minutes_per_item == ASSUMED_MINUTES_PER_ITEM
    assert value.est_analyst_minutes_saved == (
        result.closed_group_count - value.auto_closed_by_llm
    ) * ASSUMED_MINUTES_PER_ITEM
    assert result.closed_group_count >= 1
    assert "8 analyst minutes" in value.assumption
    assert value.assumption == VALUE_ASSUMPTION
    recomputed = compute_value(
        bench.investigations, report.cash, closed_count=result.closed_group_count
    )
    assert recomputed.auto_closed_by_ai == sum(
        1 for item in bench.investigations if item.action == AgentAction.RECONCILE
    )
    assert recomputed.auto_closed_by_llm == sum(
        1
        for item in bench.investigations
        if item.action == AgentAction.RECONCILE and item.produced_by == "llm"
    )
    assert recomputed.auto_closed_by_rules == recomputed.auto_closed_by_ai - recomputed.auto_closed_by_llm
    assert recomputed.auto_closed_by_llm == 0
    assert recomputed.sent_to_analyst == sum(
        1 for item in bench.investigations if item.action == AgentAction.ESCALATE
    )


def test_minutes_saved_counts_rules_closed_loops_not_llm():
    from finance_controller.models import Investigation

    investigations = [
        Investigation(
            exception_id="X1",
            decision=AgentAction.RECONCILE,
            action=AgentAction.RECONCILE,
            produced_by="rules",
        ),
        Investigation(
            exception_id="X2",
            decision=AgentAction.RECONCILE,
            action=AgentAction.RECONCILE,
            produced_by="llm",
        ),
        Investigation(
            exception_id="X3",
            decision=AgentAction.ESCALATE,
            action=AgentAction.ESCALATE,
            produced_by="rules",
        ),
    ]
    value = compute_value(investigations, None, closed_count=12)
    assert value.auto_closed_by_rules == 1
    assert value.auto_closed_by_llm == 1
    assert value.sent_to_analyst == 1
    assert value.est_analyst_minutes_saved == 11 * ASSUMED_MINUTES_PER_ITEM
    assert value.est_analyst_minutes_saved != 12 * ASSUMED_MINUTES_PER_ITEM
    assert "excluding LLM" in value.assumption
