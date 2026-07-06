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
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
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
    model_auto_routing_enabled: bool = False
    auto_route_simple_model: str = ""
    auto_route_complex_model: str = ""
    key_failure_cooldown_seconds: int = 900

    # ── Guardrails ──────────────────────────────────────────────
    diff_token_limit: int = 8000
    rate_limit_window_seconds: int = 60
    rate_limit_max_reviews: int = 3
    monthly_budget_cap: float = 0.0

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
            return self._normalize_pem(self.github_private_key)
        return self.github_private_key_path.read_text()

    @staticmethod
    def _normalize_pem(raw: str) -> str:
        """Normalize a PEM key that may be mangled by env var storage."""
        key = raw.strip()
        # Remove surrounding quotes if present
        if (key.startswith('"') and key.endswith('"')) or \
           (key.startswith("'") and key.endswith("'")):
            key = key[1:-1]
        # Replace literal \n (two chars) with actual newlines
        key = key.replace("\\n", "\n")
        # If the key is still a single line, try to reconstruct proper PEM format
        if "\n" not in key.strip():
            # Extract header, body, footer and rebuild with proper line breaks
            key = key.replace("-----BEGIN RSA PRIVATE KEY-----", "-----BEGIN RSA PRIVATE KEY-----\n")
            key = key.replace("-----END RSA PRIVATE KEY-----", "\n-----END RSA PRIVATE KEY-----")
            key = key.replace("-----BEGIN PRIVATE KEY-----", "-----BEGIN PRIVATE KEY-----\n")
            key = key.replace("-----END PRIVATE KEY-----", "\n-----END PRIVATE KEY-----")
        # Ensure final newline
        if not key.endswith("\n"):
            key += "\n"
        logger.debug("PEM key loaded: starts with '%s', length=%d", key[:30], len(key))
        return key


# ── Key roulette ────────────────────────────────────────────────
# Round-robin iterator that cycles through available keys forever.
# Thread-safe for async (single-threaded event loop).

_key_cycle: itertools.cycle | None = None
_key_cycle_keys: tuple[str, ...] | None = None


@dataclass
class KeyHealthRecord:
    """Runtime health state for an individual API key."""

    failure_count: int = 0
    last_error_status: int | None = None
    last_error_reason: str | None = None
    last_error_at: datetime | None = None
    disabled_until: datetime | None = None


_key_health: dict[str, KeyHealthRecord] = {}


def _key_suffix(key: str) -> str:
    trimmed = key.strip()
    if len(trimmed) <= 4:
        return trimmed
    return trimmed[-4:]


def _get_key_record(api_key: str) -> KeyHealthRecord:
    return _key_health.setdefault(api_key, KeyHealthRecord())


def _is_key_healthy(api_key: str, *, now: datetime | None = None) -> bool:
    record = _get_key_record(api_key)
    reference_time = now or datetime.now(UTC)
    if record.disabled_until and record.disabled_until > reference_time:
        return False
    return True


def _get_key_cycle(settings: Settings) -> itertools.cycle:
    """Lazily initialize the key roulette cycle."""
    global _key_cycle, _key_cycle_keys
    keys_tuple = tuple(settings.api_keys)
    if _key_cycle is None or _key_cycle_keys != keys_tuple:
        keys = settings.api_keys
        if len(keys) > 1:
            logger.info("Key roulette initialized with %d keys", len(keys))
        _key_cycle = itertools.cycle(keys)
        _key_cycle_keys = keys_tuple
    return _key_cycle


def get_api_key_candidates(settings: Settings) -> list[str]:
    """
    Return API keys in preferred order, filtering out cooldown keys when possible.

    If key roulette is enabled, the current round-robin selection becomes the first
    candidate and the remaining keys follow in sequence. If roulette is disabled,
    the configured order is preserved. When all keys are cooling down, the original
    order is returned so the system can still attempt recovery.
    """
    keys = settings.api_keys
    if len(keys) <= 1:
        return keys

    ordered_keys = keys[:]
    if settings.key_roulette_enabled:
        cycle = _get_key_cycle(settings)
        start_key = next(cycle)
        start_index = ordered_keys.index(start_key)
        ordered_keys = ordered_keys[start_index:] + ordered_keys[:start_index]

    healthy_keys = [key for key in ordered_keys if _is_key_healthy(key)]
    if healthy_keys:
        unhealthy_keys = [key for key in ordered_keys if key not in healthy_keys]
        return healthy_keys + unhealthy_keys
    return ordered_keys


def get_healthy_api_keys(settings: Settings) -> list[str]:
    return [key for key in settings.api_keys if _is_key_healthy(key)]


def get_active_api_key(settings: Settings) -> str:
    """
    Get the next API key to use.

    - If roulette is disabled (default), always returns the first key.
    - If roulette is enabled, cycles through keys round-robin.
    """
    candidates = get_api_key_candidates(settings)
    key = candidates[0]
    # Log only the last 4 chars for debugging without exposing the full key
    logger.debug("Key roulette selected key ending in ...%s", key[-4:])
    return key


def mark_api_key_failure(
    settings: Settings,
    api_key: str,
    status_code: int,
    reason: str,
) -> None:
    """
    Mark an API key as temporarily unhealthy after auth/rate-limit failures.
    """
    record = _get_key_record(api_key)
    now = datetime.now(UTC)
    record.failure_count += 1
    record.last_error_status = status_code
    record.last_error_reason = reason[:240]
    record.last_error_at = now
    record.disabled_until = now + timedelta(seconds=max(settings.key_failure_cooldown_seconds, 0))
    logger.warning(
        "Flagged API key ...%s unhealthy for %ds after %s",
        _key_suffix(api_key),
        settings.key_failure_cooldown_seconds,
        status_code,
    )


def mark_api_key_success(api_key: str) -> None:
    """Clear any active cooldown when a key succeeds."""
    record = _get_key_record(api_key)
    record.disabled_until = None


def get_api_key_health_snapshot(settings: Settings) -> list[dict[str, object]]:
    """Return dashboard-safe health metadata for each configured API key."""
    now = datetime.now(UTC)
    snapshot: list[dict[str, object]] = []
    for api_key in settings.api_keys:
        record = _get_key_record(api_key)
        snapshot.append(
            {
                "key_suffix": _key_suffix(api_key),
                "status": "healthy" if _is_key_healthy(api_key, now=now) else "cooldown",
                "failure_count": record.failure_count,
                "last_error_status": record.last_error_status,
                "last_error_reason": record.last_error_reason,
                "last_error_at": record.last_error_at,
                "disabled_until": record.disabled_until,
            }
        )
    return snapshot


@lru_cache
def get_settings() -> Settings:
    """Cached singleton — call this everywhere instead of constructing Settings() directly."""
    return Settings()
