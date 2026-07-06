"""
GitHub API client — handles authentication, diff fetching, review posting, and labels.

All GitHub API interactions are isolated here so they can be mocked cleanly in tests.
"""

from __future__ import annotations

import logging
import re
import time
from typing import Any

import httpx
import jwt

from app.models import CommentThread, ReviewResult

logger = logging.getLogger(__name__)

GITHUB_API = "https://api.github.com"
GITHUB_API_VERSION = "2022-11-28"


# ────────────────────────────────────────────────────────────────
# Authentication — GitHub App installation tokens
# ────────────────────────────────────────────────────────────────

_token_cache: dict[str, Any] = {"token": None, "expires_at": 0}


def get_installation_token(
    app_id: int,
    private_key_pem: str,
    installation_id: int,
) -> str:
    """
    Exchange a GitHub App JWT for a short-lived installation access token.

    Tokens are valid for 1 hour. We cache and refresh ~5 min before expiry.
    """
    now = int(time.time())

    # Return cached token if still fresh (5 min buffer)
    if _token_cache["token"] and _token_cache["expires_at"] > now + 300:
        return _token_cache["token"]

    # 1. Sign a JWT with the app's private key
    jwt_payload = {"iat": now - 60, "exp": now + 600, "iss": str(app_id)}
    jwt_token = jwt.encode(jwt_payload, private_key_pem, algorithm="RS256")

    # 2. Exchange JWT for an installation access token
    resp = httpx.post(
        f"{GITHUB_API}/app/installations/{installation_id}/access_tokens",
        headers={
            "Authorization": f"Bearer {jwt_token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": GITHUB_API_VERSION,
        },
    )
    resp.raise_for_status()
    data = resp.json()

    _token_cache["token"] = data["token"]
    # GitHub returns expires_at as ISO string; we store as epoch for easy comparison
    _token_cache["expires_at"] = now + 3300  # ~55 min, conservative
    logger.info("Refreshed GitHub installation token (valid for ~55 min)")

    return data["token"]


def _auth_headers(token: str) -> dict[str, str]:
    """Standard headers for authenticated GitHub API calls."""
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": GITHUB_API_VERSION,
    }


# ────────────────────────────────────────────────────────────────
# Diff fetching
# ────────────────────────────────────────────────────────────────


async def fetch_pr_diff(
    owner: str,
    repo: str,
    pull_number: int,
    token: str,
) -> str:
    """
    Fetch the raw unified diff for a PR.

    Uses the 'application/vnd.github.v3.diff' accept header
    so GitHub returns the diff as plain text instead of JSON.
    """
    headers = _auth_headers(token)
    headers["Accept"] = "application/vnd.github.v3.diff"

    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{GITHUB_API}/repos/{owner}/{repo}/pulls/{pull_number}",
            headers=headers,
            follow_redirects=True,
        )
        resp.raise_for_status()

    return resp.text


def annotate_diff(raw_diff: str) -> str:
    """
    Prepend each diff line with its line number in the new file.

    This is critical — the LLM needs these [L{n}] labels to produce
    accurate inline comments, and GitHub's review API only accepts
    line numbers that exist in the diff.

    Only '+' lines and context lines (right side) get labels.
    Removed '-' lines don't increment the new-file counter.
    """
    lines: list[str] = []
    new_line_num = 0

    for line in raw_diff.splitlines():
        if line.startswith("@@"):
            # Parse hunk header: @@ -old_start,old_count +new_start,new_count @@
            match = re.search(r"\+(\d+)", line)
            if match:
                new_line_num = int(match.group(1)) - 1
            lines.append(line)
        elif line.startswith("+"):
            new_line_num += 1
            lines.append(f"[L{new_line_num}] {line}")
        elif line.startswith("-"):
            # Removed lines don't increment new_line_num
            lines.append(line)
        else:
            new_line_num += 1  # context line
            lines.append(f"[L{new_line_num}] {line}")

    return "\n".join(lines)


# ────────────────────────────────────────────────────────────────
# Posting reviews
# ────────────────────────────────────────────────────────────────

_SEVERITY_EMOJI = {"critical": "🚨", "suggestion": "💡", "nit": "🔹"}


def _format_comment(c: CommentThread) -> str:
    """Format a single inline comment with severity emoji and category label."""
    emoji = _SEVERITY_EMOJI.get(c.severity, "")
    return f"{emoji} **{c.category.capitalize()}**\n\n{c.body}"


async def post_review(
    owner: str,
    repo: str,
    pull_number: int,
    commit_sha: str,
    result: ReviewResult,
    token: str,
) -> None:
    """
    Submit a full PR review with inline comments in a single API call.

    Uses POST /repos/{owner}/{repo}/pulls/{pull_number}/reviews
    which batches all comments into one review object.
    """
    headers = _auth_headers(token)

    event = "APPROVE" if result.verdict == "looks-good" else "REQUEST_CHANGES"

    comments = [
        {
            "path": c.file,
            "line": c.line,
            "side": "RIGHT",  # RIGHT = new file
            "body": _format_comment(c),
        }
        for c in result.comments
    ]

    payload = {
        "commit_id": commit_sha,
        "body": result.summary,
        "event": event,
        "comments": comments,
    }

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{GITHUB_API}/repos/{owner}/{repo}/pulls/{pull_number}/reviews",
            headers=headers,
            json=payload,
        )
        resp.raise_for_status()

    logger.info(
        "Posted review on %s/%s#%d — verdict=%s, %d inline comments",
        owner, repo, pull_number, result.verdict, len(result.comments),
    )


async def post_review_safe(
    owner: str,
    repo: str,
    pull_number: int,
    commit_sha: str,
    result: ReviewResult,
    token: str,
) -> None:
    """
    Wrapper around post_review that handles 422 errors gracefully.

    If GitHub rejects inline comments (e.g. bad line numbers), falls back
    to posting just the summary without any inline comments. A bad line
    number should never silently kill the whole review.
    """
    try:
        await post_review(owner, repo, pull_number, commit_sha, result, token)
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 422:
            logger.warning(
                "Got 422 posting inline comments on %s/%s#%d — falling back to summary only",
                owner, repo, pull_number,
            )
            fallback = result.model_copy(update={"comments": []})
            await post_review(owner, repo, pull_number, commit_sha, fallback, token)
        else:
            raise


# ────────────────────────────────────────────────────────────────
# Labels
# ────────────────────────────────────────────────────────────────

BOT_LABELS = ("looks-good", "needs-work", "budget-paused")


async def set_label(
    owner: str,
    repo: str,
    issue_number: int,
    label: str,
    token: str,
) -> None:
    """
    Apply a bot label to the PR, removing any stale bot labels first.

    Labels must already exist in the repo (create 'looks-good' in green
    and 'needs-work' in red via the GitHub UI or a setup script).
    """
    headers = _auth_headers(token)

    async with httpx.AsyncClient() as client:
        # Remove old bot labels (ignore 404 if label wasn't present)
        for old_label in BOT_LABELS:
            resp = await client.delete(
                f"{GITHUB_API}/repos/{owner}/{repo}/issues/{issue_number}/labels/{old_label}",
                headers=headers,
            )
            if resp.status_code not in (200, 404):
                resp.raise_for_status()

        # Apply the new label
        resp = await client.post(
            f"{GITHUB_API}/repos/{owner}/{repo}/issues/{issue_number}/labels",
            headers=headers,
            json={"labels": [label]},
        )
        resp.raise_for_status()

    logger.info("Set label '%s' on %s/%s#%d", label, owner, repo, issue_number)
