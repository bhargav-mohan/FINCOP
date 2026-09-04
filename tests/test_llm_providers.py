import pytest

from finance_controller.agent.llm import (
    LlmUnavailable,
    OPENROUTER_GLM_MODEL,
    ZAI_GLM_MODEL,
    _client,
    _llm_error_text,
    _parse_json_object,
)
from finance_controller.config import resolve_default_model, resolve_default_provider


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
