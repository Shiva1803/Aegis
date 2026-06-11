from __future__ import annotations

import hashlib
import hmac
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from app.main import app
from app.models import ReviewResult


def _signature(secret: str, body: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def _settings() -> SimpleNamespace:
    return SimpleNamespace(
        github_webhook_secret="test-secret",
        rate_limit_window_seconds=60,
        rate_limit_max_reviews=3,
        github_private_key_path=SimpleNamespace(read_text=lambda: "pem"),
        github_private_key="",
        github_app_id=1,
        github_installation_id=2,
        github_oauth_client_id="",
        github_oauth_client_secret="",
        github_oauth_redirect_uri="http://127.0.0.1:8000/auth/github/callback",
        dashboard_session_secret="test-secret",
        dashboard_admin_users="",
        frontend_url="http://127.0.0.1:5173",
        llm_provider="nvidia_nim",
        llm_model="deepseek-ai/deepseek-v4-pro",
        key_roulette_enabled=False,
        diff_token_limit=8000,
        llm_api_key="nim-key",
        nvidia_nim_base_url="https://integrate.api.nvidia.com/v1",
        nvidia_nim_disable_thinking=True,
        admin_users=set(),
        resolved_private_key="pem",
        model_copy=lambda update: SimpleNamespace(**{**_settings().__dict__, **update}),
    )


def test_pull_request_webhook_populates_dashboard():
    payload = {
        "action": "opened",
        "pull_request": {
            "number": 12,
            "head": {"sha": "abc123def456"},
            "title": "Test PR",
            "body": "Body",
        },
        "repository": {"name": "demo-repo", "owner": {"login": "demo-owner"}},
    }
    body = json.dumps(payload).encode()

    with patch("app.main.get_settings", return_value=_settings()), \
         patch("app.main.get_installation_token", return_value="ghs_test"), \
         patch("app.main.fetch_pr_diff", new=AsyncMock(return_value="@@ -1 +1 @@\n-print(1)\n+print(2)")), \
         patch("app.main.post_review_safe", new=AsyncMock()), \
         patch("app.main.set_label", new=AsyncMock()), \
         patch(
             "app.main.review_diff",
             new=AsyncMock(
                 return_value=ReviewResult(
                     verdict="needs-work",
                     summary="Found issue",
                     comments=[],
                 )
             ),
         ):
        client = TestClient(app)
        response = client.post(
            "/webhook",
            data=body,
            headers={
                "X-Hub-Signature-256": _signature("test-secret", body),
                "X-GitHub-Event": "pull_request",
                "Content-Type": "application/json",
            },
        )

        assert response.status_code == 200
        assert response.json()["status"] == "reviewed"

        feed = client.get("/api/dashboard/reviews").json()
        assert len(feed) >= 1
        assert feed[0]["repo"] == "demo-owner/demo-repo"

        webhooks = client.get("/api/dashboard/webhooks").json()
        assert len(webhooks) >= 1
        assert webhooks[0]["status"] == "processed"
        assert webhooks[0]["event"] == "pull_request"

        cost = client.get("/api/dashboard/cost").json()
        assert cost["total_reviews"] >= 1


def test_non_pull_request_events_are_logged_as_ignored():
    payload = {"zen": "keep it logically awesome"}
    body = json.dumps(payload).encode()

    with patch("app.main.get_settings", return_value=_settings()):
        client = TestClient(app)
        response = client.post(
            "/webhook",
            data=body,
            headers={
                "X-Hub-Signature-256": _signature("test-secret", body),
                "X-GitHub-Event": "ping",
                "Content-Type": "application/json",
            },
        )

        assert response.status_code == 200
        assert response.json()["status"] == "ignored"

        webhooks = client.get("/api/dashboard/webhooks").json()
        assert len(webhooks) >= 1
        assert webhooks[0]["status"] == "ignored"
        assert webhooks[0]["event"] == "ping"


def test_closed_pull_request_is_logged_but_not_reviewed():
    payload = {
        "action": "closed",
        "pull_request": {
            "number": 13,
            "merged": True,
            "head": {"sha": "def789abc123"},
            "title": "Merged PR",
            "body": "",
        },
        "repository": {"name": "demo-repo", "owner": {"login": "demo-owner"}},
    }
    body = json.dumps(payload).encode()

    with patch("app.main.get_settings", return_value=_settings()), \
         patch("app.main.review_diff", new=AsyncMock()) as review_diff:
        client = TestClient(app)
        response = client.post(
            "/webhook",
            data=body,
            headers={
                "X-Hub-Signature-256": _signature("test-secret", body),
                "X-GitHub-Event": "pull_request",
                "Content-Type": "application/json",
            },
        )

        assert response.status_code == 200
        assert response.json()["status"] == "ignored"
        assert "merged PR does not trigger review" in response.json()["reason"]
        review_diff.assert_not_called()

        webhooks = client.get("/api/dashboard/webhooks").json()
        assert len(webhooks) >= 1
        assert webhooks[0]["status"] == "ignored"
        assert webhooks[0]["action"] == "closed"
