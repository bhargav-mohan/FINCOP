from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from finance_controller.agent.orchestrator import orchestrate
from finance_controller.agent.tools import ReconWorkbench
from finance_controller.config import (
    DEFAULT_INJECT_EDGES,
    DEFAULT_INJECT_EXCEPTIONS,
    DEFAULT_INJECT_RESOLVABLE,
    ReconConfig,
)
from finance_controller.data.csv_batch import load_csv_batch
from finance_controller.data.synthetic import generate
from finance_controller.ingestion.pipeline import IngestResult, ingest_zip
from finance_controller.ingestion.zipfile_extract import IngestError
from finance_controller.models import BatchSource, Report
from finance_controller.reconciliation.engine import EngineResult, reconcile
from finance_controller.reporting.dashboard_payload import build_dashboard_payload, error_payload
from finance_controller.reporting.report import build_report, compute_match_precision, group_match_rate
from finance_controller.store.batch_key import dir_batch_key, file_batch_key, generated_batch_key
from finance_controller.store.persist import attach_store
from finance_controller.tax_matching.investigator import resolve_ambiguous_tax
from finance_controller.tax_matching.match import match_tax_lines


def _ingest_batch_key(zip_path: str) -> str:
    src = Path(zip_path)
    return dir_batch_key(src) if src.is_dir() else file_batch_key(src)


def generated_config(*, seed: int, num_records: int, use_llm: bool = True) -> ReconConfig:
    """Same inject mix the CLI uses for a generated batch."""
    return ReconConfig(
        seed=seed,
        num_records=num_records,
        inject_exceptions=DEFAULT_INJECT_EXCEPTIONS,
        inject_resolvable=DEFAULT_INJECT_RESOLVABLE,
        inject_edges=DEFAULT_INJECT_EDGES,
        use_llm=use_llm,
    )


@dataclass
class LoopOutcome:
    result: EngineResult
    bench: ReconWorkbench
    baseline_match_rate: float
    exceptions_before: int
    elapsed_ms: int


def execute_loop(config: ReconConfig, batch) -> LoopOutcome:
    """Reconcile then investigate. Shared by the CLI and the dashboard runner."""
    started = time.perf_counter()
    result = reconcile(batch.all_records, config)
    exceptions_before = len(result.exceptions)
    baseline_match_rate = group_match_rate(result.closed_group_count, exceptions_before)
    bench = orchestrate(result, config)
    elapsed_ms = max(0, int(round((time.perf_counter() - started) * 1000)))
    return LoopOutcome(
        result=result,
        bench=bench,
        baseline_match_rate=baseline_match_rate,
        exceptions_before=exceptions_before,
        elapsed_ms=elapsed_ms,
    )


def _config_for_ingested(config: ReconConfig, ledger_len: int) -> ReconConfig:
    return ReconConfig(
        seed=config.seed,
        num_records=max(ledger_len, 50),
        date_lag_days=max(config.date_lag_days, 5),
        model=config.model,
        provider=config.provider,
        use_llm=config.use_llm,
    )


def close_finance_loop(
    *,
    config: ReconConfig,
    zip_path: str | None = None,
    data_dir: str | None = None,
    ingested: IngestResult | None = None,
    match_tax: bool = True,
    batch_key: str | None = None,
) -> tuple[Report, EngineResult, dict]:
    """One load → execute_loop → report path. CLI and dashboard both call this."""
    ingest_meta = None
    tax_lines: list = []
    if ingested is not None:
        batch = ingested.batch
        tax_lines = ingested.tax_lines
        ingest_meta = {"files": ingested.files, "warnings": ingested.warnings}
        source_files = dict(ingested.files)
        batch_source = (
            BatchSource.RAZORPAY_RECON if "razorpay_recon" in ingested.files else BatchSource.ZIP
        )
        config = _config_for_ingested(config, len(batch.ledger))
        batch_key = batch_key or "razorpay-live"
    elif zip_path:
        ingested = ingest_zip(zip_path)
        batch = ingested.batch
        tax_lines = ingested.tax_lines
        ingest_meta = {"files": ingested.files, "warnings": ingested.warnings}
        source_files = dict(ingested.files)
        batch_source = (
            BatchSource.RAZORPAY_RECON if "razorpay_recon" in ingested.files else BatchSource.ZIP
        )
        config = _config_for_ingested(config, len(batch.ledger))
        batch_key = _ingest_batch_key(str(zip_path))
    elif data_dir:
        batch = load_csv_batch(data_dir)
        source_files = {"data_dir": str(data_dir)}
        batch_source = BatchSource.CSV_DIR
        config = ReconConfig(
            seed=config.seed,
            num_records=max(len(batch.ledger), config.num_records),
            inject_exceptions=config.inject_exceptions,
            inject_resolvable=config.inject_resolvable,
            inject_edges=config.inject_edges,
            amount_tolerance=config.amount_tolerance,
            fee_rate=config.fee_rate,
            date_lag_days=max(config.date_lag_days, 5),
            holidays=config.holidays,
            model=config.model,
            provider=config.provider,
            use_llm=config.use_llm,
        )
        batch_key = dir_batch_key(data_dir)
    else:
        if config.num_records < 50:
            raise ValueError("num_records must be >= 50")
        batch = generate(config)
        source_files = {}
        batch_source = BatchSource.GENERATED
        batch_key = generated_batch_key(config)

    outcome = execute_loop(config, batch)
    result, bench = outcome.result, outcome.bench
    baseline_match_rate = outcome.baseline_match_rate
    llm_used = config.use_llm and (
        any(item.produced_by == "llm" for item in bench.investigations)
        or any(exc.hypothesis and exc.hypothesis.produced_by == "llm" for exc in result.exceptions)
    )
    report = build_report(
        config=config,
        source_counts={
            "ledger": len(batch.ledger),
            "bank": len(batch.bank),
            "psp": len(batch.psp),
        },
        result=result,
        ground_truth=batch.ground_truth,
        llm_used=llm_used,
        investigations=bench.investigations,
        agent_warnings=bench.warnings,
        batch_source=batch_source,
        source_files=source_files,
        exceptions_before=outcome.exceptions_before,
        elapsed_ms=outcome.elapsed_ms,
    )
    extra: dict = {
        "ingestion": ingest_meta,
        "tax": None,
        "baseline_match_rate": baseline_match_rate,
        "match_precision": compute_match_precision(batch.ground_truth, result.closed_keys),
        "exceptions_before": outcome.exceptions_before,
        "elapsed_ms": outcome.elapsed_ms,
        "batch_key": batch_key,
        "tax_lines": tax_lines,
        "ledger": batch.ledger,
        "zip_path": zip_path,
        "data_dir": data_dir,
    }
    if match_tax and tax_lines:
        tax_report = match_tax_lines(tax_lines, batch.ledger, config)
        tax_report = resolve_ambiguous_tax(tax_report, config=config, use_llm=config.use_llm)
        extra["tax"] = {
            "matched": len(tax_report.matches),
            "exception_count": len(tax_report.exceptions),
            "match_rate": tax_report.match_rate,
            "exceptions": [
                {
                    "id": item.tax_id,
                    "type": item.exception_type,
                    "reason": item.reason,
                    "refs": item.refs,
                }
                for item in tax_report.exceptions
            ],
            "matches": [
                {
                    "id": item.tax_id,
                    "type": "matched",
                    "reason": item.reason,
                    "refs": item.references,
                }
                for item in tax_report.matches
            ],
        }
    elif match_tax and zip_path:
        extra["tax"] = {
            "skipped": True,
            "reason": "no tax lines in zip",
            "matched": 0,
            "exception_count": 0,
            "match_rate": None,
            "exceptions": [],
            "matches": [],
        }
    return report, result, extra


def run_finance_controller(
    *,
    seed: int = 42,
    num_records: int = 80,
    zip_path: str | None = None,
    data_dir: str | None = None,
    use_llm: bool = True,
    match_tax: bool = True,
    config: ReconConfig | None = None,
) -> dict:
    """Dashboard JSON wrapper around close_finance_loop. CLI uses the same loop."""
    try:
        if config is not None:
            cfg = config
        elif zip_path or data_dir:
            cfg = ReconConfig(
                seed=seed,
                num_records=num_records,
                date_lag_days=5,
                use_llm=use_llm,
            )
        else:
            cfg = generated_config(seed=seed, num_records=num_records, use_llm=use_llm)
        report, result, extra = close_finance_loop(
            config=cfg,
            zip_path=zip_path,
            data_dir=data_dir,
            match_tax=match_tax,
        )
        baseline_match_rate = extra.pop("baseline_match_rate")
        match_precision = extra.pop("match_precision")
        extra.pop("exceptions_before", None)
        extra.pop("elapsed_ms", None)
        batch_key = extra.pop("batch_key")
        extra.pop("tax_lines", None)
        extra.pop("ledger", None)
        extra.pop("zip_path", None)
        extra.pop("data_dir", None)
        extra["store"] = attach_store(
            report,
            result,
            batch_key=batch_key,
            baseline_match_rate=baseline_match_rate,
        )
        return build_dashboard_payload(
            report,
            baseline_match_rate=baseline_match_rate,
            match_precision=match_precision,
            extra=extra,
            result=result,
        )
    except (IngestError, UnicodeDecodeError, ValueError) as exc:
        return error_payload(seed=seed, num_records=num_records, error=str(exc))


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--num-records", type=int, default=80)
    parser.add_argument("--zip", dest="zip_path", default=None)
    parser.add_argument("--data-dir", dest="data_dir", default=None)
    parser.add_argument("--use-llm", action="store_true")
    parser.add_argument("--no-llm", action="store_true")
    parser.add_argument("--no-tax", action="store_true")
    args = parser.parse_args(argv)
    payload = run_finance_controller(
        seed=args.seed,
        num_records=args.num_records,
        zip_path=args.zip_path,
        data_dir=args.data_dir,
        use_llm=not args.no_llm,
        match_tax=not args.no_tax,
    )
    json.dump(payload, sys.stdout)
    if payload.get("error"):
        sys.exit(1)


if __name__ == "__main__":
    main()
