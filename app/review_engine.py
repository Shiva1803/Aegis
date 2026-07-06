"""
AI review engine — builds the prompt, calls the LLM, and validates the response.

Supports Anthropic (Claude), OpenAI (GPT-4), Groq (Llama/Mixtral),
Google Gemini, and NVIDIA NIM backends. Forces structured JSON output
and handles parse failures with a retry.

Optionally uses key roulette to rotate through multiple API keys.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import tiktoken
from pydantic import ValidationError

from app.config import (
    Settings,
    get_api_key_candidates,
    mark_api_key_failure,
    mark_api_key_success,
)
from app.models import ReviewResult


@dataclass
class TokenUsage:
    """Normalized token usage across all LLM providers."""

    input_tokens: int = 0
    output_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


RoutingTier = Literal["lightweight", "standard", "reasoning"]


@dataclass
class RoutingDecision:
    """Resolved model selection for a single review request."""

    provider: str
    model: str
    tier: RoutingTier
    reason: str

logger = logging.getLogger(__name__)

# Path to the system prompt file (kept separate for fast iteration)
PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "code_review.txt"

_LIGHTWEIGHT_MODEL_DEFAULTS: dict[str, str] = {
    "anthropic": "claude-3-haiku-20240307",
    "openai": "gpt-4o-mini",
    "groq": "llama-3.1-8b-instant",
    "gemini": "gemini-2.0-flash",
    "nvidia_nim": "deepseek-ai/deepseek-r1",
}

_REASONING_MODEL_DEFAULTS: dict[str, str] = {
    "anthropic": "claude-sonnet-4-20250514",
    "openai": "gpt-4o",
    "groq": "llama-3.3-70b-versatile",
    "gemini": "gemini-2.5-pro",
    "nvidia_nim": "deepseek-ai/deepseek-r1",
}

_SIMPLE_PATH_HINTS = (
    ".md",
    ".mdx",
    ".txt",
    ".rst",
    ".adoc",
    ".json",
    ".yml",
    ".yaml",
    ".toml",
    ".ini",
    ".editorconfig",
    ".gitignore",
    ".prettierrc",
    ".eslintrc",
)

_COMPLEX_HINTS = (
    "auth",
    "oauth",
    "jwt",
    "token",
    "permission",
    "secret",
    "security",
    "encrypt",
    "decrypt",
    "migration",
    "schema",
    "database",
    "sql",
    "billing",
    "payment",
    "terraform",
    "kubernetes",
    "helm",
    "docker",
    "gateway",
    "firewall",
    "iam",
    "policy",
)


# ────────────────────────────────────────────────────────────────
# Token counting & diff size guard
# ────────────────────────────────────────────────────────────────

def count_tokens(text: str, model: str = "cl100k_base") -> int:
    """
    Count tokens using tiktoken. Falls back to a rough heuristic
    if the encoding isn't available for the given model.
    """
    try:
        enc = tiktoken.get_encoding(model)
    except KeyError:
        # Rough estimate: ~4 chars per token for English/code
        return len(text) // 4
    return len(enc.encode(text))


def truncate_diff(annotated_diff: str, token_limit: int) -> tuple[str, bool]:
    """
    Truncate the diff if it exceeds the token limit.

    Returns (possibly truncated diff, was_truncated).
    Truncation happens at hunk boundaries to avoid cutting mid-context.
    """
    token_count = count_tokens(annotated_diff)
    if token_count <= token_limit:
        return annotated_diff, False

    # Split by hunks (@@) and keep as many complete hunks as fit
    hunks = annotated_diff.split("\n@@")
    result_lines: list[str] = []
    current_tokens = 0

    for i, hunk in enumerate(hunks):
        hunk_text = ("@@" + hunk) if i > 0 else hunk
        hunk_tokens = count_tokens(hunk_text)

        if current_tokens + hunk_tokens > token_limit:
            break

        result_lines.append(hunk_text)
        current_tokens += hunk_tokens

    truncated = "\n".join(result_lines)
    truncated += "\n\n[... diff truncated — PR is too large for full review ...]"

    logger.warning(
        "Diff truncated from %d to %d tokens (%d hunks kept of %d)",
        token_count, current_tokens, len(result_lines), len(hunks),
    )
    return truncated, True


# ────────────────────────────────────────────────────────────────
# Prompt construction
# ────────────────────────────────────────────────────────────────

def load_system_prompt() -> str:
    """Load the code review system prompt from the external text file."""
    return PROMPT_PATH.read_text(encoding="utf-8").strip()


def build_user_message(annotated_diff: str, pr_title: str = "", pr_body: str = "") -> str:
    """Construct the user message containing the PR context and diff."""
    parts = ["## Pull Request\n"]

    if pr_title:
        parts.append(f"**Title:** {pr_title}\n")
    if pr_body:
        parts.append(f"**Description:**\n{pr_body}\n")

    parts.append("## Diff\n")
    parts.append(f"```diff\n{annotated_diff}\n```")

    return "\n".join(parts)


def _extract_touched_paths(annotated_diff: str) -> list[str]:
    paths: list[str] = []
    for line in annotated_diff.splitlines():
        if line.startswith("+++ b/") or line.startswith("--- a/"):
            path = line[6:].strip()
            if path != "/dev/null":
                paths.append(path)
    return list(dict.fromkeys(paths))


def _count_changed_lines(annotated_diff: str) -> int:
    return sum(
        1
        for line in annotated_diff.splitlines()
        if (line.startswith("+") or line.startswith("-"))
        and not line.startswith("+++")
        and not line.startswith("---")
    )


def decide_routing(
    annotated_diff: str,
    settings: Settings,
    pr_title: str = "",
    pr_body: str = "",
) -> RoutingDecision:
    """
    Classify the diff and choose the best-fit model within the active provider.
    """
    default_model = settings.llm_model
    provider = settings.llm_provider

    if not settings.model_auto_routing_enabled:
        return RoutingDecision(
            provider=provider,
            model=default_model,
            tier="standard",
            reason="Smart routing disabled; using the configured default model.",
        )

    lowered_context = f"{pr_title}\n{pr_body}\n{annotated_diff}".lower()
    touched_paths = _extract_touched_paths(annotated_diff)
    changed_lines = _count_changed_lines(annotated_diff)
    file_count = len(touched_paths)

    simple_paths_only = bool(touched_paths) and all(
        any(path.lower().endswith(suffix) for suffix in _SIMPLE_PATH_HINTS)
        for path in touched_paths
    )
    simple_keywords = ("typo", "docs", "documentation", "readme", "format", "whitespace", "copy change")
    is_simple = simple_paths_only and changed_lines <= 120 and file_count <= 4
    if not is_simple:
        is_simple = (
            changed_lines <= 40
            and file_count <= 2
            and any(keyword in lowered_context for keyword in simple_keywords)
        )

    complex_hits = [hint for hint in _COMPLEX_HINTS if hint in lowered_context]
    is_complex = bool(complex_hits) or changed_lines >= 320 or file_count >= 8

    if is_simple and not is_complex:
        routed_model = settings.auto_route_simple_model.strip() or _LIGHTWEIGHT_MODEL_DEFAULTS.get(provider, default_model)
        return RoutingDecision(
            provider=provider,
            model=routed_model or default_model,
            tier="lightweight",
            reason=(
                f"Detected a low-risk diff across {file_count or 1} file(s) with about "
                f"{changed_lines} changed lines; routed to a lower-cost model."
            ),
        )

    if is_complex:
        routed_model = settings.auto_route_complex_model.strip() or _REASONING_MODEL_DEFAULTS.get(provider, default_model)
        reason = (
            f"Detected higher-risk changes ({', '.join(complex_hits[:3])}) across "
            f"{file_count or 1} file(s); routed to a reasoning-capable model."
            if complex_hits
            else f"Detected a broad diff spanning {file_count or 1} file(s) and {changed_lines} changed lines; routed to a reasoning-capable model."
        )
        return RoutingDecision(
            provider=provider,
            model=routed_model or default_model,
            tier="reasoning",
            reason=reason,
        )

    return RoutingDecision(
        provider=provider,
        model=default_model,
        tier="standard",
        reason=(
            f"Detected a medium-complexity diff across {file_count or 1} file(s) "
            f"with {changed_lines} changed lines; using the standard model."
        ),
    )


# ────────────────────────────────────────────────────────────────
# LLM call + structured output — per-provider implementations
# ────────────────────────────────────────────────────────────────

async def call_llm_anthropic(
    system_prompt: str,
    user_message: str,
    settings: Settings,
    api_key: str,
) -> tuple[dict, TokenUsage]:
    """Call Claude via the Anthropic SDK and return the parsed JSON dict."""
    import anthropic

    client = anthropic.AsyncAnthropic(api_key=api_key)

    response = await client.messages.create(
        model=settings.llm_model,
        max_tokens=4096,
        system=system_prompt,
        messages=[{"role": "user", "content": user_message}],
    )

    # Extract and normalize token usage
    raw = response.usage
    usage = TokenUsage(
        input_tokens=raw.input_tokens,
        output_tokens=raw.output_tokens,
    )
    logger.info(
        "LLM usage [anthropic] — input_tokens=%d, output_tokens=%d",
        usage.input_tokens, usage.output_tokens,
    )

    text = response.content[0].text
    return json.loads(text), usage


async def call_llm_openai(
    system_prompt: str,
    user_message: str,
    settings: Settings,
    api_key: str,
) -> tuple[dict, TokenUsage]:
    """Call GPT-4 via the OpenAI SDK and return the parsed JSON dict."""
    import openai

    client = openai.AsyncOpenAI(api_key=api_key)

    response = await client.chat.completions.create(
        model=settings.llm_model,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ],
        max_tokens=4096,
    )

    raw = response.usage
    usage = TokenUsage(
        input_tokens=raw.prompt_tokens if raw else 0,
        output_tokens=raw.completion_tokens if raw else 0,
    )
    logger.info(
        "LLM usage [openai] — input_tokens=%d, output_tokens=%d",
        usage.input_tokens, usage.output_tokens,
    )

    text = response.choices[0].message.content
    return json.loads(text), usage


async def call_llm_groq(
    system_prompt: str,
    user_message: str,
    settings: Settings,
    api_key: str,
) -> tuple[dict, TokenUsage]:
    """
    Call Groq (Llama, Mixtral, etc.) via the Groq SDK.

    Groq uses the OpenAI-compatible API format with JSON mode support.
    Great for fast inference at low cost.
    """
    from groq import AsyncGroq

    client = AsyncGroq(api_key=api_key)

    response = await client.chat.completions.create(
        model=settings.llm_model,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ],
        max_tokens=4096,
    )

    raw = response.usage
    usage = TokenUsage(
        input_tokens=raw.prompt_tokens if raw else 0,
        output_tokens=raw.completion_tokens if raw else 0,
    )
    logger.info(
        "LLM usage [groq] — input_tokens=%d, output_tokens=%d",
        usage.input_tokens, usage.output_tokens,
    )

    text = response.choices[0].message.content
    return json.loads(text), usage


async def call_llm_gemini(
    system_prompt: str,
    user_message: str,
    settings: Settings,
    api_key: str,
) -> tuple[dict, TokenUsage]:
    """
    Call Google Gemini via the google-genai SDK.

    Uses the new unified google.genai client with JSON response mime type.
    """
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=api_key)

    response = await client.aio.models.generate_content(
        model=settings.llm_model,
        contents=f"{system_prompt}\n\n{user_message}",
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            max_output_tokens=4096,
        ),
    )

    # Gemini usage metadata uses different field names
    raw = response.usage_metadata
    usage = TokenUsage(
        input_tokens=raw.prompt_token_count if raw else 0,
        output_tokens=raw.candidates_token_count if raw else 0,
    )
    logger.info(
        "LLM usage [gemini] — input_tokens=%d, output_tokens=%d",
        usage.input_tokens, usage.output_tokens,
    )

    text = response.text
    return json.loads(text), usage


async def call_llm_nvidia_nim(
    system_prompt: str,
    user_message: str,
    settings: Settings,
    api_key: str,
) -> tuple[dict, TokenUsage]:
    """
    Call NVIDIA NIM using the OpenAI-compatible chat completions API.
    """
    import openai

    client = openai.AsyncOpenAI(
        api_key=api_key,
        base_url=settings.nvidia_nim_base_url,
    )

    extra_body: dict[str, object] = {}
    if settings.nvidia_nim_disable_thinking:
        extra_body = {"chat_template_kwargs": {"thinking": False}}

    response = await client.chat.completions.create(
        model=settings.llm_model,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ],
        temperature=0.2,
        top_p=0.95,
        max_tokens=4096,
        extra_body=extra_body if extra_body else None,
    )

    raw = response.usage
    usage = TokenUsage(
        input_tokens=raw.prompt_tokens if raw else 0,
        output_tokens=raw.completion_tokens if raw else 0,
    )
    logger.info(
        "LLM usage [nvidia_nim] — input_tokens=%d, output_tokens=%d",
        usage.input_tokens, usage.output_tokens,
    )

    text = response.choices[0].message.content
    return json.loads(text), usage


# ────────────────────────────────────────────────────────────────
# Provider dispatch
# ────────────────────────────────────────────────────────────────

_PROVIDER_MAP = {
    "anthropic": call_llm_anthropic,
    "openai": call_llm_openai,
    "groq": call_llm_groq,
    "gemini": call_llm_gemini,
    "nvidia_nim": call_llm_nvidia_nim,
}


def _extract_error_status(exc: Exception) -> int | None:
    """Best-effort extraction of an HTTP status code from SDK exceptions."""
    for attr in ("status_code", "status", "http_status"):
        value = getattr(exc, attr, None)
        if isinstance(value, int):
            return value

    response = getattr(exc, "response", None)
    status_code = getattr(response, "status_code", None)
    if isinstance(status_code, int):
        return status_code
    return None


async def call_llm(
    system_prompt: str,
    user_message: str,
    settings: Settings,
    routing: RoutingDecision,
) -> tuple[dict, TokenUsage]:
    """
    Dispatch to the configured LLM provider with key roulette support.

    The active API key is selected via get_active_api_key(), which either
    returns the single configured key or rotates through multiple keys
    round-robin when key_roulette_enabled=True.
    """
    provider_fn = _PROVIDER_MAP.get(routing.provider)
    if provider_fn is None:
        raise ValueError(
            f"Unknown LLM provider: '{routing.provider}'. "
            f"Supported: {', '.join(_PROVIDER_MAP.keys())}"
        )

    effective_settings = settings.model_copy(update={"llm_model": routing.model})
    candidates = get_api_key_candidates(settings)
    last_exc: Exception | None = None

    for api_key in candidates:
        try:
            payload, usage = await provider_fn(system_prompt, user_message, effective_settings, api_key)
            mark_api_key_success(api_key)
            return payload, usage
        except Exception as exc:
            status_code = _extract_error_status(exc)
            if status_code in {401, 429}:
                mark_api_key_failure(settings, api_key, status_code, str(exc))
                last_exc = exc
                logger.warning(
                    "Provider call failed for key ...%s with status %s; attempting failover",
                    api_key[-4:],
                    status_code,
                )
                continue
            raise

    if last_exc is not None:
        raise last_exc
    raise RuntimeError("No API keys available for LLM call")


# ────────────────────────────────────────────────────────────────
# Full review pipeline
# ────────────────────────────────────────────────────────────────

async def review_diff(
    annotated_diff: str,
    settings: Settings,
    pr_title: str = "",
    pr_body: str = "",
) -> tuple[ReviewResult, TokenUsage, RoutingDecision]:
    """
    Run the full review pipeline: prompt → LLM → parse → validate.

    Returns (ReviewResult, TokenUsage, RoutingDecision) so callers can track
    real API costs and the selected routed model.
    On parse failure, retries once with a stricter prompt.
    On second failure, returns a minimal fallback result with zero usage.
    """
    custom_prompt = settings.custom_system_prompt.strip() if hasattr(settings, "custom_system_prompt") else ""
    system_prompt = custom_prompt if custom_prompt else load_system_prompt()
    user_message = build_user_message(annotated_diff, pr_title, pr_body)
    routing = decide_routing(annotated_diff, settings, pr_title=pr_title, pr_body=pr_body)

    for attempt in range(2):
        try:
            raw_json, usage = await call_llm(system_prompt, user_message, settings, routing)
            result = ReviewResult.model_validate(raw_json)
            logger.info(
                "Review parsed successfully (attempt %d) — verdict=%s, %d comments, route=%s/%s",
                attempt + 1, result.verdict, len(result.comments), routing.provider, routing.model,
            )
            return result, usage, routing

        except (json.JSONDecodeError, ValidationError) as exc:
            logger.warning(
                "Review parse failed (attempt %d): %s", attempt + 1, exc,
            )
            if attempt == 0:
                # Retry with a stricter addendum
                system_prompt += (
                    "\n\nIMPORTANT: Your previous response was not valid JSON. "
                    "You MUST respond with ONLY a JSON object matching the schema. "
                    "No markdown fences, no extra text."
                )
            else:
                # Give up — return a minimal fallback with zero usage
                logger.error("Review generation failed after 2 attempts")
                return ReviewResult(
                    verdict="needs-work",
                    summary=(
                        "⚠️ Automated review generation failed. "
                        "Please request a manual review."
                    ),
                    comments=[],
                ), TokenUsage(), routing

    # Unreachable, but satisfies the type checker
    raise RuntimeError("review_diff loop exited unexpectedly")
