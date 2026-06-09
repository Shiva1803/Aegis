"""Tests for the GitHub client — signature verification, diff annotation, review posting."""

from __future__ import annotations

import hashlib
import hmac

from app.github_client import _format_comment, annotate_diff
from app.main import verify_signature
from app.models import CommentThread

# ────────────────────────────────────────────────────────────────
# Webhook signature verification
# ────────────────────────────────────────────────────────────────


class TestVerifySignature:
    """Test HMAC-SHA256 webhook signature verification."""

    SECRET = "test-secret-123"
    PAYLOAD = b'{"action":"opened"}'

    def _make_signature(self, payload: bytes, secret: str) -> str:
        mac = hmac.new(secret.encode(), payload, hashlib.sha256)
        return f"sha256={mac.hexdigest()}"

    def test_valid_signature_passes(self):
        sig = self._make_signature(self.PAYLOAD, self.SECRET)
        assert verify_signature(self.PAYLOAD, sig, self.SECRET) is True

    def test_invalid_signature_fails(self):
        sig = "sha256=deadbeef" * 4
        assert verify_signature(self.PAYLOAD, sig, self.SECRET) is False

    def test_wrong_secret_fails(self):
        sig = self._make_signature(self.PAYLOAD, "wrong-secret")
        assert verify_signature(self.PAYLOAD, sig, self.SECRET) is False

    def test_missing_prefix_fails(self):
        mac = hmac.new(self.SECRET.encode(), self.PAYLOAD, hashlib.sha256)
        assert verify_signature(self.PAYLOAD, mac.hexdigest(), self.SECRET) is False

    def test_empty_signature_fails(self):
        assert verify_signature(self.PAYLOAD, "", self.SECRET) is False


# ────────────────────────────────────────────────────────────────
# Diff annotation
# ────────────────────────────────────────────────────────────────


class TestAnnotateDiff:
    """Test that diff lines get correct [L{n}] labels."""

    SAMPLE_DIFF = (
        "@@ -10,6 +10,10 @@ context before\n"
        " unchanged line\n"
        "+added line 1\n"
        "+added line 2\n"
        "-removed line\n"
        " another context\n"
    )

    def test_context_lines_get_labels(self):
        result = annotate_diff(self.SAMPLE_DIFF)
        assert "[L10]" in result  # first context line at +10

    def test_added_lines_get_labels(self):
        result = annotate_diff(self.SAMPLE_DIFF)
        assert "[L11]" in result  # first added line
        assert "[L12]" in result  # second added line

    def test_removed_lines_have_no_labels(self):
        result = annotate_diff(self.SAMPLE_DIFF)
        for line in result.splitlines():
            if line.startswith("-") and not line.startswith("---"):
                assert "[L" not in line

    def test_line_numbers_are_sequential(self):
        result = annotate_diff(self.SAMPLE_DIFF)
        nums = []
        for line in result.splitlines():
            if "[L" in line:
                start = line.index("[L") + 2
                end = line.index("]", start)
                nums.append(int(line[start:end]))
        # Should be monotonically increasing
        assert nums == sorted(nums)
        assert len(set(nums)) == len(nums)  # no duplicates

    def test_multiple_hunks(self):
        diff = (
            "@@ -1,3 +1,4 @@\n"
            " line1\n"
            "+new_line\n"
            " line2\n"
            "@@ -20,3 +21,4 @@\n"
            " line20\n"
            "+new_line20\n"
            " line21\n"
        )
        result = annotate_diff(diff)
        assert "[L1]" in result
        assert "[L2]" in result
        assert "[L21]" in result
        assert "[L22]" in result


# ────────────────────────────────────────────────────────────────
# Comment formatting
# ────────────────────────────────────────────────────────────────


class TestFormatComment:
    """Test inline comment formatting with emoji and category labels."""

    def test_critical_security(self):
        c = CommentThread(
            file="test.py", line=1, severity="critical",
            category="security", body="SQL injection risk",
        )
        result = _format_comment(c)
        assert "🚨" in result
        assert "**Security**" in result
        assert "SQL injection risk" in result

    def test_suggestion_logic(self):
        c = CommentThread(
            file="test.py", line=1, severity="suggestion",
            category="logic", body="Off by one error",
        )
        result = _format_comment(c)
        assert "💡" in result
        assert "**Logic**" in result

    def test_nit_style(self):
        c = CommentThread(
            file="test.py", line=1, severity="nit",
            category="style", body="Consider renaming",
        )
        result = _format_comment(c)
        assert "🔹" in result
        assert "**Style**" in result
