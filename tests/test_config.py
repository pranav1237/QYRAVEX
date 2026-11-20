"""Runtime optional API credential refresh tests."""
from workbridge.config import refresh_optional_api_keys, settings


def test_refresh_optional_api_keys_accepts_alpha_vantage_aliases(monkeypatch):
    monkeypatch.delenv("ALPHAVANTAGE_API_KEY", raising=False)
    monkeypatch.setenv("ALPHA_VANTAGE_API_KEY", "alpha-alias-test")
    monkeypatch.setenv("OPENAI_API_KEY", "openai-test")
    monkeypatch.setenv("GEMINI_API_KEY", "gemini-test")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "anthropic-test")

    refresh_optional_api_keys()

    assert settings.alpha_vantage_api_key == "alpha-alias-test"
    assert settings.openai_api_key == "openai-test"
    assert settings.gemini_api_key == "gemini-test"
    assert settings.anthropic_api_key == "anthropic-test"


def test_refresh_optional_api_keys_clears_missing_credentials(monkeypatch):
    for name in (
        "ALPHAVANTAGE_API_KEY", "ALPHA_VANTAGE_API_KEY", "OPENAI_API_KEY",
        "GEMINI_API_KEY", "ANTHROPIC_API_KEY",
    ):
        monkeypatch.delenv(name, raising=False)

    refresh_optional_api_keys()

    assert settings.alpha_vantage_api_key is None
    assert settings.openai_api_key is None
    assert settings.gemini_api_key is None
    assert settings.anthropic_api_key is None
