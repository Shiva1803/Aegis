"""Tests for the review engine — prompt construction, token counting, diff truncation, parsing."""

from __future__ import annotations

import json

from app.models import ReviewResult
from app.review_engine import (
    build_user_message,
    count_tokens,
    load_system_prompt,
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
