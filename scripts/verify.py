#!/usr/bin/env python3
"""Reproduce every figure published in README / fixtures/published_metrics.json."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from finance_controller.reporting.published import drift, expected, measure  # noqa: E402


def main() -> int:
    want = expected()
    got = measure()
    failures = drift(got, want)
    n = 0
    for batch, snapshot in want.items():
        n += 1
        measured = got.get(batch)
        if measured == snapshot:
            print(f"ok  {n:02d}  {batch}")
        else:
            print(f"FAIL  {n:02d}  {batch}")
    if failures:
        print()
        for line in failures:
            print(f"  {line}")
        print(f"\n{len(failures)} published figure(s) drifted.")
        return 1
    print(f"\n{n} published batches reproduced.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
