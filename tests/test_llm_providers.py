import pytest

from finance_controller.agent.llm import (
    LlmUnavailable,
    _client,
    _llm_error_text,
    _parse_json_object,
    _provider_call_kwargs,
    is_free_lane,
)
from finance_controller.config import (
    CLAUDE_DEFAULT_MODEL,
    GEMINI_DEFAULT_MODEL,
    OPENAI_DEFAULT_MODEL,
    OPENROUTER_FREE_MODELS,
    OPENROUTER_GLM_MODEL,
    ReconConfig,
    ZAI_GLM_MODEL,
    resolve_default_model,
    resolve_default_provider,
    resolve_model_candidates,
)


def test_glm_with_openrouter_key_uses_openrouter_base(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-v1-test")
    client = _client("glm")
    assert "openrouter.ai" in str(client.base_url)
    assert client.api_key == "sk-or-v1-test"


def test_glm_with_zai_key_uses_z_ai_base(monkeypatch):
    monkeypatch.setenv("ZAI_API_KEY", "zai-test")
    client = _client("glm")
    assert "api.z.ai" in str(client.base_url)
    assert client.api_key == "zai-test"


def test_glm_without_key_raises(monkeypatch):
    with pytest.raises(LlmUnavailable, match="OPENROUTER_API_KEY or ZAI_API_KEY"):
        _client("glm")


def test_openrouter_without_key_raises(monkeypatch):
    with pytest.raises(LlmUnavailable, match="OPENROUTER_API_KEY is not set"):
        _client("openrouter")


def test_resolve_glm_model_prefers_openrouter_id(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "glm")
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-v1-test")
    monkeypatch.delenv("GLM_MODEL", raising=False)
    assert resolve_default_provider() == "glm"
    assert resolve_default_model() == OPENROUTER_GLM_MODEL


def test_resolve_glm_model_direct_z_ai(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "glm")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("GLM_MODEL", raising=False)
    assert resolve_default_model() == ZAI_GLM_MODEL


def test_parse_json_object_strips_fences_and_prose():
    assert _parse_json_object('{"ok": true}') == {"ok": True}
    assert _parse_json_object("```json\n{\"ok\": true}\n```") == {"ok": True}
    assert _parse_json_object("here you go\n{\"ok\": true}\n") == {"ok": True}
    assert _parse_json_object('[{"id": "X0001"}]') == {"items": [{"id": "X0001"}]}


def test_quota_error_is_named_not_swallowed():
    text = _llm_error_text(
        RuntimeError("Error code: 429 - quota exceeded for metric generate_content_free_tier_requests")
    )
    assert "quota" in text.lower()


def test_openrouter_402_names_missing_credits():
    text = _llm_error_text(
        RuntimeError(
            "Error code: 402 - You requested up to 1024 tokens, but can only afford 165"
        )
    )
    assert "credits" in text.lower()
    assert "unavailable" not in text.lower()


def test_budget_error_names_the_time_cap():
    text = _llm_error_text(RuntimeError("LLM budget of 90s exhausted; falling back to rules"))
    assert "time cap" in text.lower() or "budget" in text.lower()


def test_infers_openai_from_key(monkeypatch):
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    assert resolve_default_provider() == "openai"
    assert resolve_default_model() == OPENAI_DEFAULT_MODEL


def test_infers_claude_from_key(monkeypatch):
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    assert resolve_default_provider() == "claude"
    assert resolve_default_model() == CLAUDE_DEFAULT_MODEL


def test_infers_gemini_from_key(monkeypatch):
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    monkeypatch.setenv("GEMINI_API_KEY", "g-test")
    assert resolve_default_provider() == "gemini"
    assert resolve_default_model() == GEMINI_DEFAULT_MODEL


def test_explicit_provider_beats_other_keys(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("GEMINI_API_KEY", "g-test")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    assert resolve_default_provider() == "openai"


def test_placeholder_glm_falls_through_to_gemini(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "glm")
    monkeypatch.setenv("OPENROUTER_API_KEY", "PASTE_HERE")
    monkeypatch.setenv("GEMINI_API_KEY", "g-test")
    assert resolve_default_provider() == "gemini"
    assert ReconConfig().provider == "gemini"


def test_placeholder_key_does_not_open_a_client(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "PASTE_HERE")
    with pytest.raises(LlmUnavailable, match="OPENROUTER_API_KEY or ZAI_API_KEY"):
        _client("glm")


def test_embedded_paste_here_is_rejected(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "sk-PASTE_HERE")
    with pytest.raises(LlmUnavailable, match="GEMINI_API_KEY"):
        _client("gemini")


def test_claude_client_uses_anthropic_base(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    client = _client("claude")
    assert "anthropic.com" in str(client.base_url)
    assert client.api_key == "sk-ant-test"


def test_anthropic_alias_uses_claude_path(monkeypatch):
    monkeypatch.setenv("CLAUDE_API_KEY", "sk-ant-alias")
    client = _client("anthropic")
    assert "anthropic.com" in str(client.base_url)
    assert client.api_key == "sk-ant-alias"


def test_openai_client_uses_openai_key(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    client = _client("openai")
    assert client.api_key == "sk-test"
    assert "generativelanguage" not in str(client.base_url)
    assert "anthropic.com" not in str(client.base_url)


def test_claude_without_key_raises():
    with pytest.raises(LlmUnavailable, match="ANTHROPIC_API_KEY"):
        _client("claude")


def test_openai_without_key_raises():
    with pytest.raises(LlmUnavailable, match="OPENAI_API_KEY"):
        _client("openai")


def test_gemini_without_key_raises():
    with pytest.raises(LlmUnavailable, match="GEMINI_API_KEY"):
        _client("gemini")


def test_free_lane_uses_a_small_token_cap():
    assert is_free_lane("z-ai/glm-5.2:free")
    assert not is_free_lane("z-ai/glm-5.2")
    assert _provider_call_kwargs("glm", "z-ai/glm-5.2:free")["max_tokens"] == 512
    assert _provider_call_kwargs("glm", "z-ai/glm-5.2")["max_tokens"] == 1024
    assert "extra_body" not in _provider_call_kwargs("glm", "google/gemma-4-31b-it:free")
    assert "extra_body" in _provider_call_kwargs("glm", "z-ai/glm-5.2:free")


def test_free_lane_tries_more_than_one_openrouter_model():
    names = resolve_model_candidates("z-ai/glm-5.2:free", "glm")
    assert names[0] == "z-ai/glm-5.2:free"
    assert "google/gemma-4-31b-it:free" in names
    assert "minimax/minimax-m2.7:free" in names
    assert names == list(dict.fromkeys(names))
    assert set(OPENROUTER_FREE_MODELS) <= set(names)


def test_complete_json_falls_through_to_the_next_model(monkeypatch):
    from finance_controller.agent import llm as llm_mod

    calls: list[str] = []

    class _Msg:
        content = '{"ok": true}'

    class _Choice:
        message = _Msg()

    class _Resp:
        choices = [_Choice()]

    def fake_call(client, **kwargs):
        calls.append(kwargs["model"])
        if kwargs["model"].endswith("glm-5.2:free"):
            raise LlmUnavailable("Model quota was exceeded.")
        return _Resp()

    monkeypatch.setattr(llm_mod, "_client", lambda provider: object())
    monkeypatch.setattr(llm_mod, "_openai_call", fake_call)
    data = llm_mod.complete_json("{}", model="z-ai/glm-5.2:free", provider="glm")
    assert data == {"ok": True}
    assert calls[0] == "z-ai/glm-5.2:free"
    assert calls[1] != "z-ai/glm-5.2:free"


def test_complete_json_falls_through_when_first_model_returns_prose(monkeypatch):
    from finance_controller.agent import llm as llm_mod

    class _Msg:
        def __init__(self, content):
            self.content = content

    class _Choice:
        def __init__(self, content):
            self.message = _Msg(content)

    class _Resp:
        def __init__(self, content):
            self.choices = [_Choice(content)]

    def fake_call(client, **kwargs):
        if "gemma" in kwargs["model"]:
            return _Resp("sure, here are some thoughts")
        return _Resp('{"items":[{"id":"X0001","explanation":"ok"}]}')

    monkeypatch.setattr(llm_mod, "_client", lambda provider: object())
    monkeypatch.setattr(llm_mod, "_openai_call", fake_call)
    data = llm_mod.complete_json("{}", model="google/gemma-4-31b-it:free", provider="glm")
    assert data["items"][0]["id"] == "X0001"
