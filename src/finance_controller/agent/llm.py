from __future__ import annotations

import json
import os
import time
from collections.abc import Callable
from typing import Any


class LlmUnavailable(RuntimeError):
    pass


class LlmBudgetExhausted(LlmUnavailable):
    pass


_GEMINI_OPENAI_BASE = "https://generativelanguage.googleapis.com/v1beta/openai/"

# A stalled provider must never hang the run. Every call is bounded twice:
# per-request (LLM_TIMEOUT_SEC) and per-run (LlmBudget). One retry is allowed
# for a transient blip; a second failure hands over to rules immediately.
LLM_TIMEOUT_SEC = 20.0
LLM_MAX_RETRIES = 1
LLM_BUDGET_SEC = 90.0


class LlmBudget:
    """Wall-clock budget for all LLM work in one run."""

    def __init__(self, total_seconds: float = LLM_BUDGET_SEC) -> None:
        self.total = float(total_seconds)
        self._start = time.monotonic()

    @property
    def elapsed(self) -> float:
        return time.monotonic() - self._start

    @property
    def remaining(self) -> float:
        return max(0.0, self.total - self.elapsed)

    def exhausted(self) -> bool:
        return self.remaining <= 0.0

    def check(self) -> None:
        if self.exhausted():
            raise LlmBudgetExhausted(
                f"LLM budget of {self.total:.0f}s exhausted; falling back to rules"
            )


def _client(provider: str):
    provider = (provider or "gemini").strip().lower()
    try:
        from openai import OpenAI
    except ImportError as exc:
        raise LlmUnavailable("openai package is not installed") from exc

    if provider in {"gemini", "google"}:
        api_key = os.getenv("GEMINI_API_KEY", "").strip() or os.getenv("GOOGLE_API_KEY", "").strip()
        if not api_key:
            raise LlmUnavailable("GEMINI_API_KEY is not set")
        return OpenAI(
            api_key=api_key,
            base_url=_GEMINI_OPENAI_BASE,
            timeout=LLM_TIMEOUT_SEC,
            max_retries=LLM_MAX_RETRIES,
        )

    if provider == "openai":
        api_key = os.getenv("OPENAI_API_KEY", "").strip()
        if not api_key:
            raise LlmUnavailable("OPENAI_API_KEY is not set")
        return OpenAI(api_key=api_key, timeout=LLM_TIMEOUT_SEC, max_retries=LLM_MAX_RETRIES)

    raise LlmUnavailable(f"unsupported provider: {provider}")


def _llm_error_text(exc: BaseException) -> str:
    text = str(exc)
    lowered = text.lower()
    if "503" in text or "high demand" in lowered or ("unavailable" in lowered and "model" in lowered):
        return (
            "Gemini is overloaded right now (HTTP 503). "
            "Rules finished the leftovers. Retry in a minute, or set GEMINI_MODEL=gemini-3.6-flash."
        )
    if "429" in text or "resource_exhausted" in lowered or "quota" in lowered:
        return (
            "Gemini free-tier quota was exceeded (about 20 requests). "
            "Rules finished the leftovers. Wait a minute or raise the quota."
        )
    if "401" in text or "403" in text or "api key" in lowered or ("invalid" in lowered and "key" in lowered):
        return "Gemini rejected the API key. Check GEMINI_API_KEY in .env."
    if "404" in text or "not found" in lowered:
        return "Gemini model was not found. Set GEMINI_MODEL to gemini-3.6-flash."
    snippet = text.replace("\n", " ").strip()[:180]
    return f"LLM request failed: {type(exc).__name__}: {snippet}"


def _openai_call(client, *, budget: LlmBudget | None = None, **kwargs):
    if budget is not None:
        budget.check()
        kwargs.setdefault("timeout", max(1.0, min(LLM_TIMEOUT_SEC, budget.remaining)))
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
    extra = {}
    if provider.strip().lower() == "openai":
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
    content = response.choices[0].message.content or "{}"
    content = content.strip()
    if content.startswith("```"):
        content = content.strip("`")
        if content.startswith("json"):
            content = content[4:].strip()
    data = json.loads(content)
    if not isinstance(data, dict):
        raise LlmUnavailable("LLM did not return a JSON object")
    return data


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
        response = _openai_call(
            client,
            budget=budget,
            model=model,
            temperature=0,
            tools=tools,
            tool_choice="auto",
            messages=messages,
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
