"""Typed runtime configuration with safe defaults."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Settings:
    sec_user_agent: str = os.getenv("SEC_USER_AGENT", "WorkBridge research contact@example.com")
    sec_base_url: str = os.getenv("SEC_BASE_URL", "https://data.sec.gov")
    finnhub_api_key: str | None = os.getenv("FINNHUB_API_KEY") or None
    fred_api_key: str | None = os.getenv("FRED_API_KEY") or None
    newsapi_api_key: str | None = os.getenv("NEWSAPI_API_KEY") or None
    alpha_vantage_api_key: str | None = os.getenv("ALPHAVANTAGE_API_KEY") or None
    openai_api_key: str | None = os.getenv("OPENAI_API_KEY") or None
    gemini_api_key: str | None = os.getenv("GEMINI_API_KEY") or None
    anthropic_api_key: str | None = os.getenv("ANTHROPIC_API_KEY") or None
    db_path: Path = Path(os.getenv("WORKBRIDGE_DB", "./data/workbridge.sqlite"))
    max_steps: int = int(os.getenv("WORKBRIDGE_MAX_STEPS", "12"))
    timeout_seconds: float = float(os.getenv("WORKBRIDGE_TIMEOUT_SECONDS", "20"))
    log_level: str = os.getenv("WORKBRIDGE_LOG_LEVEL", "INFO")


settings = Settings()


def refresh_optional_api_keys() -> None:
    """Refresh optional provider credentials after Codespaces injects secrets.

    Codespaces secrets added after a codespace was created may only appear in
    the environment after it is restarted. Refreshing here also avoids keeping
    stale empty values in the module-level Settings instance.
    """
    from os import getenv

    object.__setattr__(settings, "newsapi_api_key", getenv("NEWSAPI_API_KEY") or None)
    object.__setattr__(settings, "finnhub_api_key", getenv("FINNHUB_API_KEY") or None)
    object.__setattr__(settings, "openai_api_key", getenv("OPENAI_API_KEY") or None)
    object.__setattr__(settings, "gemini_api_key", getenv("GEMINI_API_KEY") or None)
    object.__setattr__(settings, "anthropic_api_key", getenv("ANTHROPIC_API_KEY") or None)
