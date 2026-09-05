from __future__ import annotations

import json
import os
import time
from collections.abc import Callable
from typing import Any

from finance_controller.config import env_secret


class LlmUnavailable(RuntimeError):
    pass


class LlmBudgetExhausted(LlmUnavailable):
    pass


_GEMINI_OPENAI_BASE = "https://generativelanguage.googleapis.com/v1beta/openai/"
_OPENROUTER_BASE = "https://openrouter.ai/api/v1"
_ZAI_BASE = "https://api.z.ai/api/paas/v4/"
_ANTHROPIC_BASE = "https://api.anthropic.com/v1/"

# Per-call wall-clock cap. A timeout or failed call hands over to rules after
# LLM_MAX_RETRIES. The engine and validator never wait on this path.
LLM_TIMEOUT_SEC: float | None = 12.0
GLM_TIMEOUT_SEC: float | None = 12.0
LLM_MAX_RETRIES = 1
LLM_BUDGET_SEC: float | None = None


class LlmBudget:
    """Optional wall-clock budget for all LLM work in one run. None = unlimited."""

    def __init__(self, total_seconds: float | None = LLM_BUDGET_SEC) -> None:
        self.total = None if total_seconds is None else float(total_seconds)
        self._start = time.monotonic()

    @property
    def elapsed(self) -> float:
        return time.monotonic() - self._start

    @property
    def remaining(self) -> float:
        if self.total is None:
            return float("inf")
        return max(0.0, self.total - self.elapsed)

    def exhausted(self) -> bool:
        if self.total is None:
            return False
        return self.remaining <= 0.0

    def check(self) -> None:
        if self.exhausted():
            raise LlmBudgetExhausted(
                f"LLM budget of {self.total:.0f}s exhausted; falling back to rules"
            )


def _openai_sdk():
    try:
        from openai import OpenAI
    except ImportError as exc:
        raise LlmUnavailable("openai package is not installed") from exc
    return OpenAI


def _client(provider: str):
    provider = (provider or "gemini").strip().lower()
    if provider == "anthropic":
        provider = "claude"
    if provider == "google":
        provider = "gemini"
    OpenAI = _openai_sdk()

    if provider == "gemini":
        api_key = env_secret("GEMINI_API_KEY") or env_secret("GOOGLE_API_KEY")
        if not api_key:
            raise LlmUnavailable("GEMINI_API_KEY is not set")
        return OpenAI(
            api_key=api_key,
            base_url=_GEMINI_OPENAI_BASE,
            timeout=LLM_TIMEOUT_SEC,
            max_retries=LLM_MAX_RETRIES,
        )

    if provider == "openai":
        api_key = env_secret("OPENAI_API_KEY")
        if not api_key:
            raise LlmUnavailable("OPENAI_API_KEY is not set")
        if api_key.startswith("sk-or-"):
            raise LlmUnavailable(
                "OPENAI_API_KEY looks like an OpenRouter key. "
                "Set LLM_PROVIDER=glm and OPENROUTER_API_KEY, or use a real OpenAI key."
            )
        return OpenAI(api_key=api_key, timeout=LLM_TIMEOUT_SEC, max_retries=LLM_MAX_RETRIES)

    if provider == "claude":
        api_key = env_secret("ANTHROPIC_API_KEY") or env_secret("CLAUDE_API_KEY")
        if not api_key:
            raise LlmUnavailable("ANTHROPIC_API_KEY is not set")
        kwargs: dict[str, Any] = {
            "api_key": api_key,
            "base_url": os.getenv("ANTHROPIC_BASE_URL", "").strip() or _ANTHROPIC_BASE,
            "timeout": LLM_TIMEOUT_SEC,
            "max_retries": LLM_MAX_RETRIES,
        }
        workspace = os.getenv("ANTHROPIC_WORKSPACE_ID", "").strip()
        if workspace:
            kwargs["default_headers"] = {"anthropic-workspace-id": workspace}
        return OpenAI(**kwargs)

    if provider in {"openrouter", "glm", "zai", "zhipu"}:
        or_key = env_secret("OPENROUTER_API_KEY")
        zai_key = env_secret("ZAI_API_KEY") or env_secret("GLM_API_KEY")
        openai_key = env_secret("OPENAI_API_KEY")
        use_openrouter = (
            provider == "openrouter"
            or bool(or_key)
            or openai_key.startswith("sk-or-")
        )
        if use_openrouter:
            api_key = or_key or (openai_key if openai_key.startswith("sk-or-") else "")
            if not api_key:
                raise LlmUnavailable("OPENROUTER_API_KEY is not set")
            return OpenAI(
                api_key=api_key,
                base_url=os.getenv("OPENROUTER_BASE_URL", "").strip() or _OPENROUTER_BASE,
                timeout=GLM_TIMEOUT_SEC,
                max_retries=LLM_MAX_RETRIES,
                default_headers={
                    "HTTP-Referer": "http://localhost:3000",
                    "X-Title": "AI Finance Controller",
                },
            )
        api_key = zai_key or openai_key
        if not api_key:
            raise LlmUnavailable("OPENROUTER_API_KEY or ZAI_API_KEY is not set")
        return OpenAI(
            api_key=api_key,
            base_url=os.getenv("ZAI_BASE_URL", "").strip() or _ZAI_BASE,
            timeout=GLM_TIMEOUT_SEC,
            max_retries=LLM_MAX_RETRIES,
        )

    raise LlmUnavailable(f"unsupported provider: {provider}")


def _llm_error_text(exc: BaseException) -> str:
    text = str(exc)
    lowered = text.lower()
    if "503" in text or "high demand" in lowered or ("unavailable" in lowered and "model" in lowered):
        return (
            "The model provider is overloaded right now (HTTP 503). "
            "Rules finished the leftovers. Retry in a minute."
        )
    if "429" in text or "resource_exhausted" in lowered or "quota" in lowered:
        return (
            "Model quota was exceeded. "
            "Rules finished the leftovers. Wait a minute or raise the quota."
        )
    if "timed out" in lowered or "timeout" in lowered:
        return (
            "The model timed out on a leftover. "
            "Rules finished the rest. Retry, or pass --no-llm."
        )
    if "exhausted" in lowered and "budget" in lowered:
        return (
            "The model hit the time cap for this review. "
            "Rules finished the remaining leftovers."
        )
    if "401" in text or "403" in text or "api key" in lowered or ("invalid" in lowered and "key" in lowered):
        if "openrouter" in lowered:
            return "OpenRouter rejected the API key. Check OPENROUTER_API_KEY in .env."
        if "gemini" in lowered or "google" in lowered:
            return "Gemini rejected the API key. Check GEMINI_API_KEY in .env."
        if "anthropic" in lowered or "claude" in lowered:
            return "Claude rejected the API key. Check ANTHROPIC_API_KEY in .env."
        if "openai" in lowered:
            return "OpenAI rejected the API key. Check OPENAI_API_KEY in .env."
        return (
            "The LLM API key was rejected. "
            "Check GEMINI_API_KEY, OPENAI_API_KEY, ANTHROPIC_API_KEY, or OPENROUTER_API_KEY in .env."
        )
    if "404" in text or "not found" in lowered:
        return (
            "The model name in .env was not found. "
            "Set GEMINI_MODEL, OPENAI_MODEL, CLAUDE_MODEL, or GLM_MODEL to match LLM_PROVIDER."
        )
    snippet = text.replace("\n", " ").strip()[:180]
    return f"LLM request failed: {type(exc).__name__}: {snippet}"


def _normalize_provider(provider: str) -> str:
    name = (provider or "gemini").strip().lower()
    if name == "anthropic":
        return "claude"
    if name == "google":
        return "gemini"
    return name


def _is_glm_provider(provider: str) -> bool:
    return _normalize_provider(provider) in {"openrouter", "glm", "zai", "zhipu"}


def _is_claude_provider(provider: str) -> bool:
    return _normalize_provider(provider) == "claude"


def _glm_call_kwargs() -> dict[str, Any]:
    """GLM 5.2 thinks by default; disable that so JSON/tool calls stay structured."""
    return {
        "max_tokens": 1024,
        "extra_body": {"thinking": {"type": "disabled"}},
    }


def _claude_call_kwargs() -> dict[str, Any]:
    return {"max_tokens": 1024}


def _provider_call_kwargs(provider: str) -> dict[str, Any]:
    if _is_glm_provider(provider):
        extra = _glm_call_kwargs()
        if GLM_TIMEOUT_SEC is not None:
            extra["timeout_cap"] = GLM_TIMEOUT_SEC
        return extra
    if _is_claude_provider(provider):
        extra = _claude_call_kwargs()
        extra["timeout_cap"] = LLM_TIMEOUT_SEC
        return extra
    return {}


def _message_text(message: Any) -> str:
    content = (getattr(message, "content", None) or "").strip()
    if content:
        return content
    return str(getattr(message, "reasoning", None) or "").strip()


def _parse_json_object(raw: str) -> dict:
    content = (raw or "").strip() or "{}"
    if content.startswith("```"):
        content = content.strip("`")
        if content.startswith("json"):
            content = content[4:].strip()
    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        start, end = content.find("{"), content.rfind("}")
        if start < 0 or end <= start:
            raise LlmUnavailable("LLM did not return a JSON object") from None
        data = json.loads(content[start : end + 1])
    if not isinstance(data, dict):
        raise LlmUnavailable("LLM did not return a JSON object")
    return data


def _openai_call(client, *, budget: LlmBudget | None = None, timeout_cap: float | None = None, **kwargs):
    if budget is not None:
        budget.check()
    if "timeout" not in kwargs:
        cap = timeout_cap if timeout_cap is not None else LLM_TIMEOUT_SEC
        if cap is not None:
            remaining = budget.remaining if budget is not None else float("inf")
            kwargs["timeout"] = cap if remaining == float("inf") else max(1.0, min(cap, remaining))
    try:
        return client.chat.completions.create(**kwargs)
    except LlmUnavailable:
        raise
    except Exception as exc:
        raise LlmUnavailable(_llm_error_text(exc)) from None


def complete_json(
    prompt: str,
    *,
    model: str,
    provider: str = "gemini",
    system: str | None = None,
    budget: LlmBudget | None = None,
) -> dict:
    if budget is not None:
        budget.check()
    client = _client(provider)
    extra: dict[str, Any] = _provider_call_kwargs(provider)
    if _normalize_provider(provider) == "openai":
        extra["response_format"] = {"type": "json_object"}
    system_content = system or (
        "You classify finance reconciliation exceptions. "
        "Reply with JSON keys: hypothesis_type, explanation, "
        "suggested_action, confidence. hypothesis_type must be an exception type. "
        "confidence is a number 0-1. "
        "Never mark an unresolved item as matched. JSON only."
    )
    response = _openai_call(
        client,
        budget=budget,
        model=model,
        temperature=0,
        messages=[
            {
                "role": "system",
                "content": system_content,
            },
            {"role": "user", "content": prompt},
        ],
        **extra,
    )
    return _parse_json_object(_message_text(response.choices[0].message))


def run_tool_loop(
    *,
    system: str,
    user: str,
    tools: list[dict[str, Any]],
    dispatch: Callable[[str, dict], dict],
    model: str,
    provider: str,
    max_rounds: int = 8,
    budget: LlmBudget | None = None,
) -> None:
    if budget is not None:
        budget.check()
    client = _client(provider)
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
    for _ in range(max_rounds):
        if budget is not None:
            budget.check()
        extra = _provider_call_kwargs(provider)
        response = _openai_call(
            client,
            budget=budget,
            model=model,
            temperature=0,
            tools=tools,
            tool_choice="auto",
            messages=messages,
            **extra,
        )
        message = response.choices[0].message
        tool_calls = message.tool_calls or []
        if not tool_calls:
            return
        messages.append(
            {
                "role": "assistant",
                "content": message.content or "",
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments or "{}",
                        },
                    }
                    for tc in tool_calls
                ],
            }
        )
        for call in tool_calls:
            try:
                args = json.loads(call.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {}
            if not isinstance(args, dict):
                args = {}
            result = dispatch(call.function.name, args)
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call.id,
                    "content": json.dumps(result, default=str),
                }
            )
            if call.function.name in {"reconcile", "escalate"} and result.get("ok"):
                return
