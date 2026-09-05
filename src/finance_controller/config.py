from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path

from dotenv import load_dotenv

OPENROUTER_GLM_MODEL = "google/gemma-4-31b-it:free"
ZAI_GLM_MODEL = "glm-5.2"
OPENROUTER_FREE_MODELS = (
    "google/gemma-4-31b-it:free",
    "minimax/minimax-m2.7:free",
    "z-ai/glm-5.2:free",
)
OPENAI_DEFAULT_MODEL = "gpt-4o-mini"
CLAUDE_DEFAULT_MODEL = "claude-sonnet-4-6"
GEMINI_DEFAULT_MODEL = "gemini-3.6-flash"

load_dotenv(Path(__file__).resolve().parents[2] / ".env", override=True)


DEFAULT_SEED = 42
DEFAULT_NUM_RECORDS = 80
DEFAULT_INJECT_EXCEPTIONS = 12
DEFAULT_INJECT_RESOLVABLE = 6
DEFAULT_INJECT_EDGES = 16

_PROVIDER_ALIASES = {
    "anthropic": "claude",
    "google": "gemini",
}

_PLACEHOLDER_SECRETS = frozenset(
    {
        "",
        "paste_here",
        "your-key-here",
        "changeme",
        "xxx",
        "sk-...",
        "<paste_here>",
    }
)


def _env(name: str) -> str:
    return os.getenv(name, "").strip()


def usable_secret(value: str | None) -> str:
    raw = (value or "").strip()
    lowered = raw.lower()
    if not raw or lowered in _PLACEHOLDER_SECRETS or "paste_here" in lowered:
        return ""
    return raw


def env_secret(name: str) -> str:
    return usable_secret(os.getenv(name))


def _provider_has_key(provider: str) -> bool:
    if provider == "claude":
        return bool(env_secret("ANTHROPIC_API_KEY") or env_secret("CLAUDE_API_KEY"))
    if provider == "openai":
        key = env_secret("OPENAI_API_KEY")
        return bool(key) and not key.startswith("sk-or-")
    if provider == "gemini":
        return bool(env_secret("GEMINI_API_KEY") or env_secret("GOOGLE_API_KEY"))
    if provider in {"glm", "openrouter", "zai", "zhipu"}:
        openai_key = env_secret("OPENAI_API_KEY")
        return bool(
            env_secret("OPENROUTER_API_KEY")
            or env_secret("ZAI_API_KEY")
            or env_secret("GLM_API_KEY")
            or openai_key.startswith("sk-or-")
        )
    return False


def resolve_default_provider() -> str:
    explicit = _PROVIDER_ALIASES.get(_env("LLM_PROVIDER").lower(), _env("LLM_PROVIDER").lower())
    if explicit and _provider_has_key(explicit):
        return explicit
    if _provider_has_key("claude"):
        return "claude"
    if _provider_has_key("openai"):
        return "openai"
    if _provider_has_key("gemini"):
        return "gemini"
    if _provider_has_key("glm"):
        return "glm"
    return explicit or "gemini"


def resolve_default_model(provider: str | None = None) -> str:
    provider = (provider or resolve_default_provider()).strip().lower()
    provider = _PROVIDER_ALIASES.get(provider, provider)
    if provider == "claude":
        return _env("CLAUDE_MODEL") or _env("ANTHROPIC_MODEL") or CLAUDE_DEFAULT_MODEL
    if provider == "openai":
        return _env("OPENAI_MODEL") or OPENAI_DEFAULT_MODEL
    if provider == "gemini":
        return _env("GEMINI_MODEL") or GEMINI_DEFAULT_MODEL
    glm = _env("GLM_MODEL") or _env("OPENROUTER_MODEL")
    if provider == "openrouter":
        return glm or OPENROUTER_GLM_MODEL
    if provider in {"glm", "zai", "zhipu"}:
        if env_secret("OPENROUTER_API_KEY"):
            return glm or OPENROUTER_GLM_MODEL
        return glm or ZAI_GLM_MODEL
    return _env("GEMINI_MODEL") or _env("OPENAI_MODEL") or GEMINI_DEFAULT_MODEL


def resolve_model_candidates(model: str, provider: str = "") -> list[str]:
    extra = [item.strip() for item in _env("GLM_MODELS").split(",") if item.strip()]
    provider = _PROVIDER_ALIASES.get((provider or "").strip().lower(), (provider or "").strip().lower())
    names = [model, *extra]
    if provider in {"glm", "openrouter", "zai", "zhipu"} and (
        extra or ":free" in (model or "").lower()
    ):
        names.extend(OPENROUTER_FREE_MODELS)
    seen: list[str] = []
    for name in names:
        name = (name or "").strip()
        if name and name not in seen:
            seen.append(name)
    return seen or [(model or "").strip() or OPENROUTER_GLM_MODEL]


DEFAULT_MODEL = resolve_default_model()
DEFAULT_PROVIDER = resolve_default_provider()

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
    model: str = ""
    provider: str = ""
    use_llm: bool = True

    def __post_init__(self) -> None:
        provider = (self.provider or "").strip().lower()
        provider = _PROVIDER_ALIASES.get(provider, provider) or resolve_default_provider()
        model = (self.model or "").strip() or resolve_default_model(provider)
        object.__setattr__(self, "provider", provider)
        object.__setattr__(self, "model", model)
