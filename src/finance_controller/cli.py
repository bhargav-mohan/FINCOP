from __future__ import annotations

import argparse
import sys

from rich.console import Console

from finance_controller.config import (
    DEFAULT_INJECT_EDGES,
    DEFAULT_INJECT_EXCEPTIONS,
    DEFAULT_INJECT_RESOLVABLE,
    DEFAULT_NUM_RECORDS,
    DEFAULT_SEED,
    ReconConfig,
)
from finance_controller.reporting.accuracy_gate import failing_metric
from finance_controller.reporting.report import render_text, write_report
from finance_controller.run_finance_controller import close_finance_loop
from finance_controller.store.persist import attach_store


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Reconcile a 50+ record synthetic finance batch and report match rate plus exceptions."
    )
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--num-records", type=int, default=DEFAULT_NUM_RECORDS)
    parser.add_argument("--inject-exceptions", type=int, default=DEFAULT_INJECT_EXCEPTIONS)
    parser.add_argument("--inject-resolvable", type=int, default=DEFAULT_INJECT_RESOLVABLE)
    parser.add_argument("--inject-edges", type=int, default=DEFAULT_INJECT_EDGES)
    parser.add_argument("--model", default=None)
    parser.add_argument("--provider", default=None)
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
        help="LLM on leftovers after rules (the default). Kept for older scripts.",
    )
    parser.add_argument(
        "--no-llm",
        action="store_true",
        help="Rules only. Skip the LLM on leftovers.",
    )
    parser.add_argument(
        "--fail-under",
        type=float,
        default=None,
        help="Exit 2 if precision, recall, or F1 falls below this threshold",
    )
    return parser.parse_args(argv)


def _finish(console: Console, report, result, extra: dict, out: str, fail_under: float | None) -> int:
    attach_store(
        report,
        result,
        batch_key=extra["batch_key"],
        baseline_match_rate=extra["baseline_match_rate"],
    )
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


def run(
    config: ReconConfig,
    out: str,
    data_dir: str | None = None,
    zip_path: str | None = None,
    razorpay_live: bool = False,
    fail_under: float | None = None,
) -> int:
    console = Console()
    ingested = None
    live_key: str | None = None
    if razorpay_live:
        from finance_controller.ingestion.pipeline import ingest_razorpay_rows
        from finance_controller.razorpay.live_fetch import fetch_recon, fixture_zip_path

        fetched = fetch_recon()
        for warning in fetched.warnings:
            console.print(f"[yellow]{warning}[/yellow]")
        if fetched.source == "live":
            ingested = ingest_razorpay_rows(fetched.rows)
            live_key = "razorpay-live"
        else:
            zip_path = str(fetched.zip_path or fixture_zip_path())

    try:
        report, result, extra = close_finance_loop(
            config=config,
            zip_path=str(zip_path) if zip_path else None,
            data_dir=data_dir,
            ingested=ingested,
            match_tax=False,
            batch_key=live_key,
        )
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        return 2
    return _finish(console, report, result, extra, out, fail_under)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    config = ReconConfig(
        seed=args.seed,
        num_records=args.num_records,
        inject_exceptions=args.inject_exceptions,
        inject_resolvable=args.inject_resolvable,
        inject_edges=args.inject_edges,
        model=args.model or "",
        provider=args.provider or "",
        use_llm=not args.no_llm,
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
