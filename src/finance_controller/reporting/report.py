from __future__ import annotations

import csv
from datetime import datetime, timezone
from decimal import Decimal
from io import StringIO
from pathlib import Path

from rich.console import Console
from rich.table import Table

from finance_controller.config import ReconConfig
from finance_controller.models import (
    AccuracyMetrics,
    AgentAction,
    BatchSource,
    CashPosition,
    ExpectedStatus,
    GroundTruth,
    Investigation,
    Report,
    RunMeta,
    Source,
    ValueMetrics,
)

ASSUMED_MINUTES_PER_ITEM = 8
VALUE_ASSUMPTION = (
    "Estimate assumes 8 analyst minutes per loop closed by rules "
    "(engine + investigator), excluding LLM; not a measured time study."
)
from finance_controller.reconciliation.engine import (
    EngineResult,
    keys_for_exception,
    predicted_exception_keys,
)
from finance_controller.reporting.exposure import exception_exposure
from finance_controller.reporting.kpis import compute_kpis


def group_match_rate(matched: int, exception_count: int) -> float:
    """Closed groups / (closed + leftover groups). Never matched/num_records.

    Seed-42/80 with edges: 56/79 = 0.7089. 66/80 = 0.825 was the dashboard bug
    (no inject_edges, and the page divided by num_records).
    """
    total = matched + exception_count
    if total <= 0:
        return 0.0
    return round(matched / total, 4)


def compute_match_precision(ground_truth: list[GroundTruth], closed_keys: set[str]) -> float | None:
    """Precision of *closes*, not of exception detection.

    Among labeled keys the engine closed, the share whose ground-truth status is
    MATCHED. Closing an EXCEPTION-labeled key drops this even if detection P/R
    stay at 1.0. None when no labeled key was closed (nothing to score).
    """
    gt_matched = {g.key for g in ground_truth if g.expected_status == ExpectedStatus.MATCHED}
    gt_exc = {g.key for g in ground_truth if g.expected_status == ExpectedStatus.EXCEPTION}
    labeled_closed = (gt_matched | gt_exc) & closed_keys
    if not labeled_closed:
        return None
    return round(len(gt_matched & closed_keys) / len(labeled_closed), 4)


def compute_accuracy(ground_truth: list[GroundTruth], result: EngineResult) -> AccuracyMetrics:
    """Score leftover exception keys against injected GT labels (EXCEPTION vs MATCHED).

    Predicted = keys still on the exception queue after matching/agent.
    Actual = ground-truth rows labeled EXCEPTION. Not scored against the agent's own labels.
    """
    actual = {g.key for g in ground_truth if g.expected_status == ExpectedStatus.EXCEPTION}
    predicted = predicted_exception_keys(result)
    tp = actual & predicted
    fp = predicted - actual
    fn = actual - predicted
    precision = len(tp) / len(predicted) if predicted else 0.0
    recall = len(tp) / len(actual) if actual else 1.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0

    actual_types = {
        g.key: g.exception_type
        for g in ground_truth
        if g.expected_status == ExpectedStatus.EXCEPTION and g.exception_type
    }
    pred_types: dict[str, object] = {}
    for exc in result.exceptions:
        for key in keys_for_exception(exc, result.closed_keys):
            pred_types[key] = exc.exception_type
    typed = [key for key in tp if key in actual_types and key in pred_types]
    type_accuracy = (
        sum(1 for key in typed if actual_types[key] == pred_types[key]) / len(typed) if typed else None
    )
    return AccuracyMetrics(
        true_positives=len(tp),
        false_positives=len(fp),
        false_negatives=len(fn),
        precision=round(precision, 4),
        recall=round(recall, 4),
        f1=round(f1, 4),
        type_accuracy=None if type_accuracy is None else round(type_accuracy, 4),
    )


def compute_cash(result: EngineResult) -> CashPosition:
    closed_banks = [
        r
        for r in result.records
        if r.id in result.closed_record_ids and r.source == Source.BANK
    ]
    closed_net = sum((b.amount for b in closed_banks), Decimal("0.00")).quantize(Decimal("0.01"))
    by_id = {r.id: r for r in result.records}
    ledger_gross = sum(
        (exception_exposure(exc, by_id) for exc in result.exceptions),
        Decimal("0.00"),
    ).quantize(Decimal("0.01"))
    aged = sum(1 for e in result.exceptions if e.exception_type.value == "late_settlement")
    return CashPosition(
        closed_bank_net=closed_net,
        in_flight_count=len(result.exceptions),
        in_flight_gross=ledger_gross,
        negative=closed_net < 0,
        in_flight_aged_out=aged,
    )


def compute_value(
    investigations: list[Investigation],
    cash: CashPosition | None,
    *,
    closed_count: int,
) -> ValueMetrics:
    auto_closed = sum(1 for item in investigations if item.action == AgentAction.RECONCILE)
    by_llm = sum(
        1
        for item in investigations
        if item.action == AgentAction.RECONCILE and item.produced_by == "llm"
    )
    by_rules = auto_closed - by_llm
    sent = sum(1 for item in investigations if item.action == AgentAction.ESCALATE)
    total = auto_closed + sent
    rate = (auto_closed / total) if total else 0.0
    in_flight = cash.in_flight_gross if cash else Decimal("0.00")
    engine_closed = max(closed_count - auto_closed, 0)
    rules_closed = engine_closed + by_rules
    return ValueMetrics(
        auto_closed_by_ai=auto_closed,
        auto_closed_by_rules=by_rules,
        auto_closed_by_llm=by_llm,
        sent_to_analyst=sent,
        auto_close_rate=round(rate, 4),
        in_flight_amount=in_flight,
        est_analyst_minutes_saved=rules_closed * ASSUMED_MINUTES_PER_ITEM,
        assumed_minutes_per_item=ASSUMED_MINUTES_PER_ITEM,
        assumption=VALUE_ASSUMPTION,
    )


def build_report(
    *,
    config: ReconConfig,
    source_counts: dict[str, int],
    result: EngineResult,
    ground_truth: list[GroundTruth],
    llm_used: bool,
    investigations: list[Investigation] | None = None,
    agent_warnings: list[str] | None = None,
    batch_source: BatchSource = BatchSource.GENERATED,
    source_files: dict[str, str] | None = None,
    exceptions_before: int | None = None,
    elapsed_ms: int = 0,
) -> Report:
    matched = result.closed_group_count
    exceptions = result.exceptions
    total = matched + len(exceptions)
    rate = group_match_rate(matched, len(exceptions))
    investigations = investigations or []
    cash = compute_cash(result)
    match_precision = compute_match_precision(ground_truth, result.closed_keys)
    kpis = compute_kpis(
        result=result,
        ground_truth=ground_truth,
        exceptions_before=len(exceptions) if exceptions_before is None else exceptions_before,
        elapsed_ms=elapsed_ms,
        match_precision=match_precision,
    )
    return Report(
        run=RunMeta(
            seed=config.seed,
            batch_source=batch_source,
            source_files=dict(source_files or {}),
            num_records=config.num_records,
            inject_exceptions=config.inject_exceptions,
            inject_resolvable=config.inject_resolvable,
            inject_edges=config.inject_edges,
            timestamp=datetime.now(timezone.utc),
            source_counts=source_counts,
            model=config.model,
            llm_used=llm_used,
            agent_reconciled=sum(1 for i in investigations if i.action.value == "reconcile"),
            agent_escalated=sum(1 for i in investigations if i.action.value == "escalate"),
            agent_warnings=list(agent_warnings or []),
        ),
        total_groups=total,
        matched=matched,
        match_rate=round(rate, 4),
        matches=result.closed_matches,
        exceptions=exceptions,
        investigations=investigations,
        accuracy=compute_accuracy(ground_truth, result),
        kpis=kpis,
        cash=cash,
        value=compute_value(investigations, cash, closed_count=matched),
        ground_truth=ground_truth,
    )


def render_text(report: Report) -> str:
    console = Console(file=StringIO(), record=True, width=100)
    console.print("[bold]AI Finance Controller — reconciliation report[/bold]")
    if report.run.batch_source == BatchSource.GENERATED:
        console.print(
            f"source=generated  seed={report.run.seed}  records={report.run.num_records}  "
            f"injected={report.run.inject_exceptions}  resolvable={report.run.inject_resolvable}  "
            f"edges={report.run.inject_edges}  llm={report.run.llm_used}"
        )
        gt_label = "injected GT labels"
    else:
        rows = sum(report.run.source_counts.values())
        console.print(
            f"source={report.run.batch_source.value}  ingested_rows={rows}  "
            f"records={report.run.num_records}  llm={report.run.llm_used}"
        )
        if report.run.source_files:
            files = "  ".join(f"{role}={name}" for role, name in sorted(report.run.source_files.items()))
            console.print(f"files: {files}")
        gt_label = "supplied GT labels"
    console.print(
        f"matched={report.matched}/{report.total_groups}  "
        f"match_rate={report.match_rate:.2%}  "
        f"exceptions={len(report.exceptions)}"
    )
    acc = report.accuracy
    console.print(
        f"exception detection vs {gt_label}  "
        f"P={acc.precision:.2%} R={acc.recall:.2%} F1={acc.f1:.2%}  "
        f"type_accuracy={acc.type_accuracy}"
    )
    console.print(
        "policy: unresolved items are over-flagged on purpose "
        "(a false exception costs review time; a false close corrupts the ledger)  "
        f"false_positives={acc.false_positives}  false_negatives={acc.false_negatives}"
    )
    kpis = report.kpis
    if kpis:
        mp = "n/a" if kpis.match_precision is None else f"{kpis.match_precision:.2%}"
        ep = "n/a" if kpis.explanation_precision is None else f"{kpis.explanation_precision:.2%}"
        mp_gate = (
            "pass"
            if kpis.match_precision_pass
            else ("n/a" if kpis.match_precision_pass is None else "fail")
        )
        ep_gate = (
            "pass"
            if kpis.explanation_precision_pass
            else ("n/a" if kpis.explanation_precision_pass is None else "fail")
        )
        console.print(
            f"kpis  match_precision={mp} (≥{kpis.match_precision_threshold:.0%} {mp_gate})  "
            f"exceptions {kpis.exceptions_before}→{kpis.exceptions_after} "
            f"reduced={kpis.exceptions_reduced}  "
            f"elapsed_ms={kpis.elapsed_ms}  "
            f"explanation_precision={ep} (≥{kpis.explanation_precision_threshold:.0%} {ep_gate})"
        )
    console.print(f"sources: {report.run.source_counts}")
    if report.cash:
        cash = report.cash
        console.print(
            f"cash  closed_bank_net={cash.closed_bank_net}  "
            f"in_flight_exceptions={cash.in_flight_count} ledger_gross={cash.in_flight_gross}  "
            f"negative={cash.negative}  aged_out={cash.in_flight_aged_out}"
        )
    if report.value:
        value = report.value
        console.print(
            f"value  auto_closed_by_ai={value.auto_closed_by_ai}  "
            f"sent_to_analyst={value.sent_to_analyst}  "
            f"auto_close_rate={value.auto_close_rate:.2%}  "
            f"est_minutes_saved={value.est_analyst_minutes_saved}  "
            f"({value.assumption})"
        )

    console.print(
        f"agent  reconciled={report.run.agent_reconciled}  "
        f"escalated={report.run.agent_escalated}  investigations={len(report.investigations)}"
    )
    for warning in report.run.agent_warnings:
        console.print(f"[yellow]warning: {warning}[/yellow]")

    inv = Table(title="Agent investigations (decision / evidence / action)")
    inv.add_column("exc")
    inv.add_column("decision")
    inv.add_column("by")
    inv.add_column("valid")
    inv.add_column("evidence")
    inv.add_column("rationale")
    if not report.investigations:
        inv.add_row("—", "—", "—", "—", "none", "—")
    for item in report.investigations:
        inv.add_row(
            item.exception_id,
            item.action.value,
            item.produced_by,
            "yes" if item.validator_passed else "no",
            "; ".join(item.evidence[:2]),
            item.rationale,
        )
    console.print(inv)

    table = Table(title="Exceptions (unresolved)")
    table.add_column("id")
    table.add_column("type")
    table.add_column("refs")
    table.add_column("reason")
    table.add_column("hypothesis")
    table.add_column("conf")
    if not report.exceptions:
        table.add_row("—", "—", "—", "none", "—", "—")
    for exc in report.exceptions:
        hyp = exc.hypothesis
        table.add_row(
            exc.exception_id,
            exc.exception_type.value,
            ", ".join(exc.references),
            exc.reason,
            (hyp.explanation if hyp else ""),
            f"{hyp.confidence:.2f}" if hyp else "",
        )
    console.print(table)
    return console.export_text()


def write_report(report: Report, out_prefix: str) -> tuple[Path, Path, Path, Path]:
    prefix = Path(out_prefix)
    prefix.parent.mkdir(parents=True, exist_ok=True)
    json_path = prefix.with_suffix(".json") if prefix.suffix != ".json" else prefix
    text_path = json_path.with_suffix(".txt")
    stem = json_path.with_suffix("")
    exceptions_csv = Path(f"{stem}_exceptions.csv")
    matches_csv = Path(f"{stem}_matches.csv")
    json_path.write_text(report.model_dump_json(indent=2), encoding="utf-8")
    text_path.write_text(render_text(report), encoding="utf-8")
    with exceptions_csv.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["id", "type", "references", "reason", "hypothesis", "confidence"])
        for exc in report.exceptions:
            hyp = exc.hypothesis
            writer.writerow(
                [
                    exc.exception_id,
                    exc.exception_type.value,
                    "; ".join(exc.references),
                    exc.reason,
                    hyp.explanation if hyp else "",
                    f"{hyp.confidence:.2f}" if hyp else "",
                ]
            )
    with matches_csv.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["match_id", "tier", "record_ids", "references"])
        for match in report.matches:
            writer.writerow(
                [
                    match.match_id,
                    match.tier.value,
                    "; ".join(match.record_ids),
                    "; ".join(match.references),
                ]
            )
    return json_path, text_path, exceptions_csv, matches_csv
