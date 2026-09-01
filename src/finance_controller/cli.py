from __future__ import annotations

import argparse
import sys

from rich.console import Console

from finance_controller.config import (
    DEFAULT_INJECT_EDGES,
    DEFAULT_INJECT_EXCEPTIONS,
    DEFAULT_INJECT_RESOLVABLE,
    DEFAULT_MODEL,
    DEFAULT_NUM_RECORDS,
    DEFAULT_PROVIDER,
    DEFAULT_SEED,
    ReconConfig,
)
from finance_controller.data.csv_batch import load_csv_batch
from finance_controller.data.synthetic import generate
from finance_controller.models import BatchSource
from finance_controller.reporting.accuracy_gate import failing_metric
from finance_controller.reporting.report import build_report, render_text, write_report
from finance_controller.run_finance_controller import execute_loop
from finance_controller.store.batch_key import dir_batch_key, file_batch_key, generated_batch_key
from finance_controller.store.persist import attach_store


def _ingested_source(files: dict[str, str]) -> BatchSource:
    return BatchSource.RAZORPAY_RECON if "razorpay_recon" in files else BatchSource.ZIP


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Reconcile a 50+ record synthetic finance batch and report match rate plus exceptions."
    )
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--num-records", type=int, default=DEFAULT_NUM_RECORDS)
    parser.add_argument("--inject-exceptions", type=int, default=DEFAULT_INJECT_EXCEPTIONS)
    parser.add_argument("--inject-resolvable", type=int, default=DEFAULT_INJECT_RESOLVABLE)
    parser.add_argument("--inject-edges", type=int, default=DEFAULT_INJECT_EDGES)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--provider", default=DEFAULT_PROVIDER)
    parser.add_argument("--out", default="report")
    parser.add_argument("--data-dir", default=None, help="Load payments.csv, settlements.csv, bank.csv instead of generating")
    parser.add_argument(
        "--zip",
        dest="zip_path",
        default=None,
        help="Ingest a ZIP, Excel workbook, or folder of Bank/Ledger/PSP/Tax files",
    )
    parser.add_argument(
        "--razorpay-zip",
        dest="razorpay_zip",
        default=None,
        help="ZIP containing a Razorpay Settlement Recon CSV (and optional ground_truth.json)",
    )
    parser.add_argument(
        "--razorpay-live",
        action="store_true",
        help="Optional. Read-only Razorpay test-mode GET. No keys needed: uses the offline fixture.",
    )
    parser.add_argument(
        "--use-llm",
        action="store_true",
        help="Let Gemini investigate leftovers after rules. Default is rules only.",
    )
    parser.add_argument(
        "--no-llm",
        action="store_true",
        help="Rules only (default). Kept so older scripts that pass --no-llm still work.",
    )
    parser.add_argument(
        "--fail-under",
        type=float,
        default=None,
        help="Exit 2 if precision, recall, or F1 falls below this threshold",
    )
    return parser.parse_args(argv)


def run(
    config: ReconConfig,
    out: str,
    data_dir: str | None = None,
    zip_path: str | None = None,
    razorpay_live: bool = False,
    fail_under: float | None = None,
) -> int:
    console = Console()
    batch_source = BatchSource.GENERATED
    source_files: dict[str, str] = {}
    if razorpay_live:
        from finance_controller.ingestion.pipeline import ingest_razorpay_rows, ingest_zip
        from finance_controller.razorpay.live_fetch import fetch_recon, fixture_zip_path

        fetched = fetch_recon()
        for warning in fetched.warnings:
            console.print(f"[yellow]{warning}[/yellow]")
        if fetched.source == "live":
            ingested = ingest_razorpay_rows(fetched.rows)
        else:
            ingested = ingest_zip(fetched.zip_path or fixture_zip_path())
        batch = ingested.batch
        batch_source = BatchSource.RAZORPAY_RECON
        source_files = dict(ingested.files)
        config = ReconConfig(
            seed=config.seed,
            num_records=max(len(batch.ledger), 50),
            date_lag_days=max(config.date_lag_days, 5),
            model=config.model,
            provider=config.provider,
            use_llm=config.use_llm,
        )
    elif zip_path:
        from finance_controller.ingestion.pipeline import ingest_zip

        ingested = ingest_zip(zip_path)
        batch = ingested.batch
        batch_source = _ingested_source(ingested.files)
        source_files = dict(ingested.files)
        config = ReconConfig(
            seed=config.seed,
            num_records=max(len(batch.ledger), 50),
            date_lag_days=max(config.date_lag_days, 5),
            model=config.model,
            provider=config.provider,
            use_llm=config.use_llm,
        )
    elif data_dir:
        batch = load_csv_batch(data_dir)
        batch_source = BatchSource.CSV_DIR
        source_files = {"data_dir": str(data_dir)}
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
    else:
        if config.num_records < 50:
            console.print("[red]--num-records must be >= 50[/red]")
            return 2
        batch = generate(config)
    result, bench, baseline_match_rate = execute_loop(config, batch)
    llm_used = any(item.produced_by == "llm" for item in bench.investigations) or any(
        exc.hypothesis and exc.hypothesis.produced_by == "llm" for exc in result.exceptions
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
    if zip_path:
        batch_key = file_batch_key(zip_path)
    elif razorpay_live:
        from finance_controller.razorpay.live_fetch import fixture_zip_path

        batch_key = file_batch_key(fixture_zip_path())
    elif data_dir:
        batch_key = dir_batch_key(data_dir)
    else:
        batch_key = generated_batch_key(config)
    attach_store(report, result, batch_key=batch_key, baseline_match_rate=baseline_match_rate)
    json_path, text_path, exceptions_csv, matches_csv = write_report(report, out)
    console.print(render_text(report))
    console.print(f"wrote {json_path}, {text_path}, {exceptions_csv}, and {matches_csv}")
    if fail_under is not None:
        metric = failing_metric(report.accuracy, fail_under)
        if metric:
            console.print(
                f"[red]{metric}={getattr(report.accuracy, metric)} below --fail-under {fail_under}[/red]"
            )
            return 2
    return 0


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    config = ReconConfig(
        seed=args.seed,
        num_records=args.num_records,
        inject_exceptions=args.inject_exceptions,
        inject_resolvable=args.inject_resolvable,
        inject_edges=args.inject_edges,
        model=args.model,
        provider=args.provider,
        use_llm=bool(args.use_llm) and not args.no_llm,
    )
    sys.exit(
        run(
            config,
            args.out,
            data_dir=args.data_dir,
            zip_path=args.razorpay_zip or args.zip_path,
            razorpay_live=args.razorpay_live,
            fail_under=args.fail_under,
        )
    )


if __name__ == "__main__":
    main()
