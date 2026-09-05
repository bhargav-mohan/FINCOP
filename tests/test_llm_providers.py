import pytest

from finance_controller.agent.llm import (
    LlmUnavailable,
    _client,
    _llm_error_text,
    _parse_json_object,
)
from finance_controller.config import (
    CLAUDE_DEFAULT_MODEL,
    GEMINI_DEFAULT_MODEL,
    OPENAI_DEFAULT_MODEL,
    OPENROUTER_GLM_MODEL,
    ReconConfig,
    ZAI_GLM_MODEL,
    resolve_default_model,
    resolve_default_provider,
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


def test_quota_error_is_named_not_swallowed():
    text = _llm_error_text(
        RuntimeError("Error code: 429 - quota exceeded for metric generate_content_free_tier_requests")
    )
    assert "quota" in text.lower()


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
