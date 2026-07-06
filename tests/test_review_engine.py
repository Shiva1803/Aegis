"""Tests for the review engine — prompt construction, token counting, diff truncation, parsing."""

from __future__ import annotations

import asyncio
import json
from unittest.mock import patch

from app.config import Settings, get_api_key_health_snapshot
from app.models import ReviewResult
from app.review_engine import (
    build_user_message,
    call_llm,
    count_tokens,
    decide_routing,
    load_system_prompt,
    TokenUsage,
    truncate_diff,
)

# ────────────────────────────────────────────────────────────────
# Prompt loading
# ────────────────────────────────────────────────────────────────


class TestLoadPrompt:
    """Test that the system prompt loads correctly from file."""

    def test_prompt_file_exists(self):
        prompt = load_system_prompt()
        assert len(prompt) > 100  # should be substantial
        assert "JSON" in prompt  # should mention JSON output

    def test_prompt_mentions_severity_levels(self):
        prompt = load_system_prompt()
        assert "critical" in prompt
        assert "suggestion" in prompt
        assert "nit" in prompt

    def test_prompt_mentions_line_numbers(self):
        prompt = load_system_prompt()
        assert "[L{n}]" in prompt or "[L" in prompt


# ────────────────────────────────────────────────────────────────
# User message construction
# ────────────────────────────────────────────────────────────────


class TestBuildUserMessage:
    """Test user message formatting."""

    def test_includes_diff(self):
        msg = build_user_message("+ some code", pr_title="Test PR")
        assert "+ some code" in msg
        assert "```diff" in msg

    def test_includes_title_when_provided(self):
        msg = build_user_message("diff", pr_title="Fix login bug")
        assert "Fix login bug" in msg

    def test_includes_description_when_provided(self):
        msg = build_user_message("diff", pr_body="This fixes the auth issue")
        assert "This fixes the auth issue" in msg

    def test_works_without_optional_fields(self):
        msg = build_user_message("+ code")
        assert "```diff" in msg


# ────────────────────────────────────────────────────────────────
# Token counting
# ────────────────────────────────────────────────────────────────


class TestCountTokens:
    """Test token counting with tiktoken."""

    def test_empty_string(self):
        assert count_tokens("") == 0

    def test_short_string(self):
        count = count_tokens("Hello, world!")
        assert 1 <= count <= 10

    def test_code_snippet(self):
        code = "def hello():\n    print('world')\n"
        count = count_tokens(code)
        assert count > 0


# ────────────────────────────────────────────────────────────────
# Diff truncation
# ────────────────────────────────────────────────────────────────


class TestTruncateDiff:
    """Test diff size guard / truncation."""

    def test_small_diff_not_truncated(self):
        diff = "+ small change"
        result, was_truncated = truncate_diff(diff, token_limit=1000)
        assert not was_truncated
        assert result == diff

    def test_large_diff_gets_truncated(self):
        # Build a diff that's definitely over the token limit
        large_diff = "\n".join([f"+ line {i} with some padding text here" for i in range(2000)])
        result, was_truncated = truncate_diff(large_diff, token_limit=100)
        assert was_truncated
        assert "[... diff truncated" in result

    def test_truncation_adds_notice(self):
        large_diff = "\n".join([f"@@ -1,1 +1,1 @@\n+ big line {i} " * 20 for i in range(100)])
        _, was_truncated = truncate_diff(large_diff, token_limit=50)
        assert was_truncated


# ────────────────────────────────────────────────────────────────
# ReviewResult parsing
# ────────────────────────────────────────────────────────────────


class TestReviewResultParsing:
    """Test Pydantic model validation of LLM responses."""

    def test_valid_response_parses(self):
        raw = {
            "verdict": "needs-work",
            "summary": "Found a SQL injection vulnerability.",
            "comments": [
                {
                    "file": "src/auth/login.py",
                    "line": 14,
                    "severity": "critical",
                    "category": "security",
                    "body": "Use parameterized queries instead of f-strings.",
                }
            ],
        }
        result = ReviewResult.model_validate(raw)
        assert result.verdict == "needs-work"
        assert len(result.comments) == 1
        assert result.comments[0].severity == "critical"

    def test_empty_comments_parses(self):
        raw = {
            "verdict": "looks-good",
            "summary": "Clean code, no issues found.",
            "comments": [],
        }
        result = ReviewResult.model_validate(raw)
        assert result.verdict == "looks-good"
        assert len(result.comments) == 0

    def test_invalid_verdict_raises(self):
        raw = {
            "verdict": "maybe",
            "summary": "Not sure",
            "comments": [],
        }
        try:
            ReviewResult.model_validate(raw)
            assert False, "Should have raised a validation error"
        except Exception:
            pass

    def test_missing_required_field_raises(self):
        raw = {"verdict": "looks-good"}  # missing summary
        try:
            ReviewResult.model_validate(raw)
            assert False, "Should have raised a validation error"
        except Exception:
            pass

    def test_from_json_string(self):
        json_str = json.dumps({
            "verdict": "looks-good",
            "summary": "All good.",
            "comments": [],
        })
        parsed = json.loads(json_str)
        result = ReviewResult.model_validate(parsed)
        assert result.verdict == "looks-good"


class TestRoutingDecisions:
    def test_simple_diff_routes_to_lightweight_model(self):
        settings = Settings(
            llm_provider="openai",
            llm_api_key="key-1111",
            llm_model="gpt-4o",
            model_auto_routing_enabled=True,
        )
        diff = """--- a/README.md
+++ b/README.md
@@ -1,2 +1,2 @@
-Typpo
+Typo
"""

        routing = decide_routing(diff, settings, pr_title="docs: fix typo")

        assert routing.tier == "lightweight"
        assert routing.model == "gpt-4o-mini"

    def test_complex_diff_routes_to_reasoning_model(self):
        settings = Settings(
            llm_provider="gemini",
            llm_api_key="key-1111",
            llm_model="gemini-2.0-flash",
            model_auto_routing_enabled=True,
        )
        diff = """--- a/db/migrations/001_users.sql
+++ b/db/migrations/001_users.sql
@@ -1,2 +1,8 @@
+ALTER TABLE users ADD COLUMN encrypted_token TEXT;
"""

        routing = decide_routing(diff, settings, pr_title="add auth migration")

        assert routing.tier == "reasoning"
        assert routing.model == "gemini-2.5-pro"


class TestKeyFailover:
    def test_fails_over_to_next_key_after_rate_limit(self):
        settings = Settings(
            llm_provider="openai",
            llm_api_key="primary-1111,backup-2222",
            llm_model="gpt-4o",
            key_roulette_enabled=False,
            key_failure_cooldown_seconds=300,
        )
        routing = decide_routing("+ quick change", settings)
        attempted_keys: list[str] = []

        class RateLimitError(Exception):
            def __init__(self, status_code: int):
                super().__init__(f"provider failed with {status_code}")
                self.status_code = status_code

        async def fake_provider(system_prompt: str, user_message: str, active_settings: Settings, api_key: str):
            attempted_keys.append(api_key)
            if api_key == "primary-1111":
                raise RateLimitError(429)
            assert active_settings.llm_model == "gpt-4o"
            return {"verdict": "looks-good", "summary": "ok", "comments": []}, TokenUsage(input_tokens=1, output_tokens=1)

        with patch.dict("app.review_engine._PROVIDER_MAP", {"openai": fake_provider}):
            payload, usage = asyncio.run(call_llm("system", "user", settings, routing))

        health = get_api_key_health_snapshot(settings)
        primary = next(item for item in health if item["key_suffix"] == "1111")
        backup = next(item for item in health if item["key_suffix"] == "2222")

        assert attempted_keys == ["primary-1111", "backup-2222"]
        assert payload["verdict"] == "looks-good"
        assert usage.input_tokens == 1
        assert primary["status"] == "cooldown"
        assert primary["last_error_status"] == 429
        assert backup["status"] == "healthy"


class TestCustomSystemPrompt:
    """Test that custom system prompts from settings override the default code_review.txt prompt."""

    @patch("app.review_engine.call_llm")
    def test_custom_prompt_loaded(self, mock_call_llm):
        from app.review_engine import review_diff
        mock_call_llm.return_value = ({"verdict": "looks-good", "summary": "ok", "comments": []}, TokenUsage(1, 1))

        settings = Settings(
            llm_provider="openai",
            llm_api_key="test-key",
            custom_system_prompt="My custom guidelines focusing on TS strictness.",
        )

        asyncio.run(review_diff(
            annotated_diff="diff",
            pr_title="PR Title",
            pr_body="PR Body",
            settings=settings
        ))

        # Check call_llm system_prompt argument
        system_prompt_arg = mock_call_llm.call_args[0][0]
        assert system_prompt_arg == "My custom guidelines focusing on TS strictness."

    @patch("app.review_engine.call_llm")
    def test_default_prompt_loaded_when_custom_empty(self, mock_call_llm):
        from app.review_engine import review_diff
        mock_call_llm.return_value = ({"verdict": "looks-good", "summary": "ok", "comments": []}, TokenUsage(1, 1))

        settings = Settings(
            llm_provider="openai",
            llm_api_key="test-key",
            custom_system_prompt="",
        )

        asyncio.run(review_diff(
            annotated_diff="diff",
            pr_title="PR Title",
            pr_body="PR Body",
            settings=settings
        ))

        system_prompt_arg = mock_call_llm.call_args[0][0]
        assert "critical" in system_prompt_arg
        assert len(system_prompt_arg) > 100
