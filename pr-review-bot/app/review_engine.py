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
from pathlib import Path

import tiktoken

from app.config import Settings, get_active_api_key
from app.models import ReviewResult

logger = logging.getLogger(__name__)

# Path to the system prompt file (kept separate for fast iteration)
PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "code_review.txt"


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


# ────────────────────────────────────────────────────────────────
# LLM call + structured output — per-provider implementations
# ────────────────────────────────────────────────────────────────

async def call_llm_anthropic(
    system_prompt: str,
    user_message: str,
    settings: Settings,
    api_key: str,
) -> tuple[dict, object]:
    """Call Claude via the Anthropic SDK and return the parsed JSON dict."""
    import anthropic

    client = anthropic.AsyncAnthropic(api_key=api_key)

    response = await client.messages.create(
        model=settings.llm_model,
        max_tokens=4096,
        system=system_prompt,
        messages=[{"role": "user", "content": user_message}],
    )

    # Log token usage for cost tracking
    usage = response.usage
    logger.info(
        "LLM usage [anthropic] — input_tokens=%d, output_tokens=%d",
        usage.input_tokens, usage.output_tokens,
    )

    # Extract text content and parse as JSON
    text = response.content[0].text
    return json.loads(text), usage


async def call_llm_openai(
    system_prompt: str,
    user_message: str,
    settings: Settings,
    api_key: str,
) -> tuple[dict, object]:
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

    usage = response.usage
    logger.info(
        "LLM usage [openai] — input_tokens=%d, output_tokens=%d",
        usage.prompt_tokens, usage.completion_tokens,
    )

    text = response.choices[0].message.content
    return json.loads(text), usage


async def call_llm_groq(
    system_prompt: str,
    user_message: str,
    settings: Settings,
    api_key: str,
) -> tuple[dict, object]:
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

    usage = response.usage
    logger.info(
        "LLM usage [groq] — input_tokens=%d, output_tokens=%d",
        usage.prompt_tokens, usage.completion_tokens,
    )

    text = response.choices[0].message.content
    return json.loads(text), usage


async def call_llm_gemini(
    system_prompt: str,
    user_message: str,
    settings: Settings,
    api_key: str,
) -> tuple[dict, object]:
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

    # Gemini usage metadata
    usage = response.usage_metadata
    input_tokens = usage.prompt_token_count if usage else 0
    output_tokens = usage.candidates_token_count if usage else 0
    logger.info(
        "LLM usage [gemini] — input_tokens=%d, output_tokens=%d",
        input_tokens, output_tokens,
    )

    text = response.text
    return json.loads(text), usage


async def call_llm_nvidia_nim(
    system_prompt: str,
    user_message: str,
    settings: Settings,
    api_key: str,
) -> tuple[dict, object]:
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

    usage = response.usage
    logger.info(
        "LLM usage [nvidia_nim] — input_tokens=%d, output_tokens=%d",
        usage.prompt_tokens if usage else 0,
        usage.completion_tokens if usage else 0,
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


async def call_llm(
    system_prompt: str,
    user_message: str,
    settings: Settings,
) -> tuple[dict, object]:
    """
    Dispatch to the configured LLM provider with key roulette support.

    The active API key is selected via get_active_api_key(), which either
    returns the single configured key or rotates through multiple keys
    round-robin when key_roulette_enabled=True.
    """
    provider_fn = _PROVIDER_MAP.get(settings.llm_provider)
    if provider_fn is None:
        raise ValueError(
            f"Unknown LLM provider: '{settings.llm_provider}'. "
            f"Supported: {', '.join(_PROVIDER_MAP.keys())}"
        )

    api_key = get_active_api_key(settings)
    return await provider_fn(system_prompt, user_message, settings, api_key)


# ────────────────────────────────────────────────────────────────
# Full review pipeline
# ────────────────────────────────────────────────────────────────

async def review_diff(
    annotated_diff: str,
    settings: Settings,
    pr_title: str = "",
    pr_body: str = "",
) -> ReviewResult:
    """
    Run the full review pipeline: prompt → LLM → parse → validate.

    On parse failure, retries once with a stricter prompt.
    On second failure, returns a minimal fallback result.
    """
    system_prompt = load_system_prompt()
    user_message = build_user_message(annotated_diff, pr_title, pr_body)

    for attempt in range(2):
        try:
            raw_json, _usage = await call_llm(system_prompt, user_message, settings)
            result = ReviewResult.model_validate(raw_json)
            logger.info(
                "Review parsed successfully (attempt %d) — verdict=%s, %d comments",
                attempt + 1, result.verdict, len(result.comments),
            )
            return result

        except (json.JSONDecodeError, Exception) as exc:
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
                # Give up — return a minimal fallback
                logger.error("Review generation failed after 2 attempts")
                return ReviewResult(
                    verdict="needs-work",
                    summary=(
                        "⚠️ Automated review generation failed. "
                        "Please request a manual review."
                    ),
                    comments=[],
                )

    # Unreachable, but satisfies the type checker
    raise RuntimeError("review_diff loop exited unexpectedly")
