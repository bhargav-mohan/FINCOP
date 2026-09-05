#!/usr/bin/env python3
"""Run the shipped Razorpay ZIP through the CLI. Works on Windows and Unix."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from finance_controller.cli import main  # noqa: E402


if __name__ == "__main__":
    zip_path = ROOT / "fixtures" / "razorpay_sample" / "batch.zip"
    argv = [
        "--razorpay-zip",
        str(zip_path),
        "--out",
        "report",
        *sys.argv[1:],
    ]
    main(argv)
