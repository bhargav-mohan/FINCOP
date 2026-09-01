from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[2] / ".env", override=True)


DEFAULT_SEED = 42
DEFAULT_NUM_RECORDS = 80
DEFAULT_INJECT_EXCEPTIONS = 12
DEFAULT_INJECT_RESOLVABLE = 6
DEFAULT_INJECT_EDGES = 16
DEFAULT_MODEL = os.getenv("GEMINI_MODEL") or os.getenv("OPENAI_MODEL") or "gemini-3.6-flash"
DEFAULT_PROVIDER = os.getenv("LLM_PROVIDER", "gemini")

AMOUNT_TOLERANCE = Decimal("0.05")
FEE_RATE = Decimal("0.02")
DATE_LAG_DAYS = 3
BATCH_MIN_SIZE = 3
BATCH_MAX_SIZE = 5
HOLIDAYS = frozenset(
    {
        date(2026, 1, 26),
        date(2026, 8, 15),
        date(2026, 10, 2),
    }
)


@dataclass(frozen=True)
class ReconConfig:
    seed: int = DEFAULT_SEED
    num_records: int = DEFAULT_NUM_RECORDS
    inject_exceptions: int = DEFAULT_INJECT_EXCEPTIONS
    inject_resolvable: int = DEFAULT_INJECT_RESOLVABLE
    inject_edges: int = DEFAULT_INJECT_EDGES
    amount_tolerance: Decimal = AMOUNT_TOLERANCE
    fee_rate: Decimal = FEE_RATE
    date_lag_days: int = DATE_LAG_DAYS
    holidays: frozenset[date] = HOLIDAYS
    model: str = DEFAULT_MODEL
    provider: str = DEFAULT_PROVIDER
    use_llm: bool = False
