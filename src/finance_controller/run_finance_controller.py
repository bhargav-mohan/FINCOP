from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from finance_controller.agent.orchestrator import orchestrate
from finance_controller.agent.tools import ReconWorkbench
from finance_controller.config import (
    DEFAULT_INJECT_EDGES,
    DEFAULT_INJECT_EXCEPTIONS,
    DEFAULT_INJECT_RESOLVABLE,
    ReconConfig,
)
from finance_controller.data.synthetic import generate
from finance_controller.ingestion.pipeline import ingest_zip
from finance_controller.ingestion.zipfile_extract import IngestError
from finance_controller.models import BatchSource
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


def generated_config(*, seed: int, num_records: int, use_llm: bool) -> ReconConfig:
    """Same inject mix the CLI uses for a generated batch."""
    return ReconConfig(
        seed=seed,
        num_records=num_records,
        inject_exceptions=DEFAULT_INJECT_EXCEPTIONS,
        inject_resolvable=DEFAULT_INJECT_RESOLVABLE,
        inject_edges=DEFAULT_INJECT_EDGES,
        use_llm=use_llm,
    )


def execute_loop(config: ReconConfig, batch) -> tuple[EngineResult, ReconWorkbench, float]:
    """Reconcile then investigate. Shared by the CLI and the dashboard runner."""
    result = reconcile(batch.all_records, config)
    baseline_match_rate = group_match_rate(result.closed_group_count, len(result.exceptions))
    bench = orchestrate(result, config)
    return result, bench, baseline_match_rate


def run_finance_controller(
    *,
    seed: int = 42,
    num_records: int = 80,
    zip_path: str | None = None,
    use_llm: bool = False,
    match_tax: bool = True,
) -> dict:
    """Run the existing controller. ZIP/tax/LLM wrap it; matchers are unchanged."""
    ingest_meta = None
    tax_lines = []
    batch_source = BatchSource.GENERATED
    source_files: dict[str, str] = {}
    try:
        if zip_path:
            ingested = ingest_zip(zip_path)
            batch = ingested.batch
            tax_lines = ingested.tax_lines
            ingest_meta = {"files": ingested.files, "warnings": ingested.warnings}
            source_files = dict(ingested.files)
            batch_source = (
                BatchSource.RAZORPAY_RECON
                if "razorpay_recon" in ingested.files
                else BatchSource.ZIP
            )
            config = ReconConfig(
                seed=seed,
                num_records=max(len(batch.ledger), 50),
                date_lag_days=5,
                use_llm=use_llm,
            )
        else:
            if num_records < 50:
                raise ValueError("num_records must be >= 50")
            config = generated_config(seed=seed, num_records=num_records, use_llm=use_llm)
            batch = generate(config)

        result, bench, baseline_match_rate = execute_loop(config, batch)
        llm_used = use_llm and (
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
        )

        match_precision = compute_match_precision(batch.ground_truth, result.closed_keys)

        extra: dict = {"ingestion": ingest_meta, "tax": None}
        if match_tax and tax_lines:
            tax_report = match_tax_lines(tax_lines, batch.ledger, config)
            tax_report = resolve_ambiguous_tax(tax_report, config=config, use_llm=use_llm)
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

        extra["store"] = attach_store(
            report,
            result,
            batch_key=_ingest_batch_key(zip_path) if zip_path else generated_batch_key(config),
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
    parser.add_argument("--use-llm", action="store_true")
    parser.add_argument("--no-tax", action="store_true")
    args = parser.parse_args(argv)
    payload = run_finance_controller(
        seed=args.seed,
        num_records=args.num_records,
        zip_path=args.zip_path,
        use_llm=args.use_llm,
        match_tax=not args.no_tax,
    )
    json.dump(payload, sys.stdout)
    if payload.get("error"):
        sys.exit(1)


if __name__ == "__main__":
    main()
