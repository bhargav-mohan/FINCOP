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
_OPENROUTER_BASE = "https://openrouter.ai/api/v1"
_ZAI_BASE = "https://api.z.ai/api/paas/v4/"
OPENROUTER_GLM_MODEL = "z-ai/glm-5.2"
ZAI_GLM_MODEL = "glm-5.2"

# None = no wall-clock cap. A failed call still hands over to rules after
# LLM_MAX_RETRIES; a stalled provider can hang a run until it returns.
LLM_TIMEOUT_SEC: float | None = None
GLM_TIMEOUT_SEC: float | None = None
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
    OpenAI = _openai_sdk()

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

    if provider in {"openrouter", "glm", "zai", "zhipu"}:
        or_key = os.getenv("OPENROUTER_API_KEY", "").strip()
        zai_key = os.getenv("ZAI_API_KEY", "").strip() or os.getenv("GLM_API_KEY", "").strip()
        openai_key = os.getenv("OPENAI_API_KEY", "").strip()
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
            "GLM 5.2 timed out on a leftover. "
            "Rules finished the rest. Retry, or set GLM_MODEL=z-ai/glm-5.3-flash for a faster pass."
        )
    if "exhausted" in lowered and "budget" in lowered:
        return (
            "GLM hit the time cap for this review. "
            "Rules finished the remaining leftovers."
        )
    if "401" in text or "403" in text or "api key" in lowered or ("invalid" in lowered and "key" in lowered):
        if "openrouter" in lowered:
            return "OpenRouter rejected the API key. Check OPENROUTER_API_KEY in .env."
        if "gemini" in lowered or "google" in lowered:
            return "Gemini rejected the API key. Check GEMINI_API_KEY in .env."
        return "The LLM API key was rejected. Check OPENROUTER_API_KEY or GEMINI_API_KEY in .env."
    if "404" in text or "not found" in lowered:
        return "The model name in .env was not found. For GLM 5.2 set GLM_MODEL=z-ai/glm-5.2 with LLM_PROVIDER=glm."
    snippet = text.replace("\n", " ").strip()[:180]
    return f"LLM request failed: {type(exc).__name__}: {snippet}"


def _is_glm_provider(provider: str) -> bool:
    return (provider or "").strip().lower() in {"openrouter", "glm", "zai", "zhipu"}


def _glm_call_kwargs() -> dict[str, Any]:
    """GLM 5.2 thinks by default; disable that so JSON/tool calls stay structured."""
    return {
        "max_tokens": 1024,
        "extra_body": {"thinking": {"type": "disabled"}},
    }


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
    extra: dict[str, Any] = {}
    if provider.strip().lower() == "openai":
        extra["response_format"] = {"type": "json_object"}
    if _is_glm_provider(provider):
        extra.update(_glm_call_kwargs())
        if GLM_TIMEOUT_SEC is not None:
            extra["timeout_cap"] = GLM_TIMEOUT_SEC
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
        extra = _glm_call_kwargs() if _is_glm_provider(provider) else {}
        if extra and GLM_TIMEOUT_SEC is not None:
            extra["timeout_cap"] = GLM_TIMEOUT_SEC
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
