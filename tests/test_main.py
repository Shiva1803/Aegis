from __future__ import annotations

import hashlib
import hmac
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch, ANY

from fastapi.testclient import TestClient

from app.main import app
from app.models import ReviewResult
from app.review_engine import RoutingDecision, TokenUsage


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
        model_auto_routing_enabled=False,
        auto_route_simple_model="",
        auto_route_complex_model="",
        key_failure_cooldown_seconds=900,
        diff_token_limit=8000,
        monthly_budget_cap=0.0,
        llm_api_key="nim-key",
        nvidia_nim_base_url="https://integrate.api.nvidia.com/v1",
        nvidia_nim_disable_thinking=True,
        admin_users=set(),
        resolved_private_key="pem",
        api_keys=["nim-key"],
        model_copy=lambda update=None, **kwargs: SimpleNamespace(**{**_settings().__dict__, **((update or kwargs.get("update")) or {})}),
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
                 return_value=(
                     ReviewResult(
                         verdict="needs-work",
                         summary="Found issue",
                         comments=[],
                     ),
                     TokenUsage(input_tokens=150, output_tokens=50),
                     RoutingDecision(
                         provider="nvidia_nim",
                         model="deepseek-ai/deepseek-v4-pro",
                         tier="standard",
                         reason="Smart routing disabled; using the configured default model.",
                     ),
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


def test_webhook_skipped_when_budget_cap_exceeded():
    payload = {
        "action": "opened",
        "pull_request": {
            "number": 42,
            "head": {"sha": "abc123def456"},
            "title": "A pricey PR",
            "body": "This PR should be budget-paused",
        },
        "repository": {"name": "demo-repo", "owner": {"login": "demo-owner"}},
    }
    body = json.dumps(payload).encode()

    settings_mock = _settings()
    settings_mock.monthly_budget_cap = 10.0  # budget limit is $10.00

    with patch("app.main.get_settings", return_value=settings_mock), \
         patch("app.main._get_current_month_cost", return_value=12.50), \
         patch("app.main.get_installation_token", return_value="test-token"), \
         patch("app.main.set_label", new=AsyncMock()) as set_label_mock, \
         patch("app.main.review_diff", new=AsyncMock()) as review_diff_mock:

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
        assert response.json()["status"] == "skipped"
        assert response.json()["reason"] == "budget cap exceeded"

        # Verify the budget-paused label was applied
        set_label_mock.assert_called_once_with(
            "demo-owner", "demo-repo", 42, "budget-paused", ANY
        )
        # Verify the review was skipped (LLM not called)
        review_diff_mock.assert_not_called()

        webhooks = client.get("/api/dashboard/webhooks").json()
        assert len(webhooks) >= 1
        assert webhooks[0]["status"] == "skipped"
        assert "monthly budget cap exceeded" in webhooks[0]["reason"]
