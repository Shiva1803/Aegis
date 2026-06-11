"""
Application configuration loaded from environment variables.

Uses pydantic-settings so every value can be overridden via env vars,
a .env file, or secrets injected by the deployment platform.

Supports key roulette: provide multiple API keys (comma-separated) and
the bot will rotate through them round-robin to distribute rate limits.
"""

from __future__ import annotations

import itertools
import logging
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)


class Settings(BaseSettings):
    """All configuration for the PR Review Bot, grouped by concern."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ── GitHub App credentials ──────────────────────────────────
    github_webhook_secret: str = ""
    github_app_id: int = 0
    github_private_key_path: Path = Path("./private-key.pem")
    github_private_key: str = ""  # Alternative: paste PEM contents directly
    github_installation_id: int = 0
    github_oauth_client_id: str = ""
    github_oauth_client_secret: str = ""
    github_oauth_redirect_uri: str = "http://127.0.0.1:8000/auth/github/callback"
    dashboard_session_secret: str = "change-me-local-dev-secret"
    dashboard_admin_users: str = ""
    frontend_url: str = "http://127.0.0.1:5173"

    # ── LLM configuration ───────────────────────────────────────
    llm_provider: Literal["anthropic", "openai", "groq", "gemini", "nvidia_nim"] = "anthropic"
    llm_api_key: str = "local-dev-placeholder"  # single key OR comma-separated for roulette
    llm_model: str = "claude-sonnet-4-20250514"
    nvidia_nim_base_url: str = "https://integrate.api.nvidia.com/v1"
    nvidia_nim_disable_thinking: bool = True

    # ── Key roulette (optional) ─────────────────────────────────
    # Set to true to enable round-robin rotation across multiple keys.
    # When enabled, llm_api_key should be comma-separated keys:
    #   LLM_API_KEY=sk-key1,sk-key2,sk-key3
    key_roulette_enabled: bool = False

    # ── Guardrails ──────────────────────────────────────────────
    diff_token_limit: int = 8000
    rate_limit_window_seconds: int = 60
    rate_limit_max_reviews: int = 3

    @field_validator("llm_api_key")
    @classmethod
    def validate_api_key(cls, v: str) -> str:
        """Strip whitespace from each key (handles sloppy comma-separated input)."""
        keys = [k.strip() for k in v.split(",") if k.strip()]
        if not keys:
            raise ValueError("At least one API key is required in LLM_API_KEY")
        return ",".join(keys)

    @property
    def api_keys(self) -> list[str]:
        """Parse comma-separated keys into a list."""
        return [k.strip() for k in self.llm_api_key.split(",") if k.strip()]

    @property
    def admin_users(self) -> set[str]:
        return {user.strip().lower() for user in self.dashboard_admin_users.split(",") if user.strip()}

    @property
    def resolved_private_key(self) -> str:
        """Return PEM key contents from env var or file, preferring the env var."""
        if self.github_private_key.strip():
            return self.github_private_key
        return self.github_private_key_path.read_text()


# ── Key roulette ────────────────────────────────────────────────
# Round-robin iterator that cycles through available keys forever.
# Thread-safe for async (single-threaded event loop).

_key_cycle: itertools.cycle | None = None


def _get_key_cycle(settings: Settings) -> itertools.cycle:
    """Lazily initialize the key roulette cycle."""
    global _key_cycle
    if _key_cycle is None:
        keys = settings.api_keys
        if len(keys) > 1:
            logger.info("Key roulette initialized with %d keys", len(keys))
        _key_cycle = itertools.cycle(keys)
    return _key_cycle


def get_active_api_key(settings: Settings) -> str:
    """
    Get the next API key to use.

    - If roulette is disabled (default), always returns the first key.
    - If roulette is enabled, cycles through keys round-robin.
    """
    if not settings.key_roulette_enabled:
        return settings.api_keys[0]

    cycle = _get_key_cycle(settings)
    key = next(cycle)
    # Log only the last 4 chars for debugging without exposing the full key
    logger.debug("Key roulette selected key ending in ...%s", key[-4:])
    return key


@lru_cache
def get_settings() -> Settings:
    """Cached singleton — call this everywhere instead of constructing Settings() directly."""
    return Settings()
