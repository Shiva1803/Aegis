from __future__ import annotations

import hashlib
import hmac
import logging
import secrets
import time
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode
from uuid import uuid4

import httpx
from fastapi import FastAPI, Header, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse

from app.config import Settings, get_settings
from app.dashboard_models import (
    AuditEntry,
    ConfigUpdate,
    ConfigView,
    CostPoint,
    CostSummary,
    ReviewDetail,
    ReviewFeedItem,
    WebhookLogEntry,
)
from app.github_client import (
    annotate_diff,
    fetch_pr_diff,
    get_installation_token,
    post_review_safe,
    set_label,
)
from app.review_engine import count_tokens, review_diff, truncate_diff

logger = logging.getLogger(__name__)

# Force uvicorn config reload to fetch new .env variables
app = FastAPI(
    title="PR Review Bot",
    description="AI-powered GitHub PR code review bot",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

_seen_reviews: set[str] = set()
_rate_limit_log: dict[str, list[float]] = defaultdict(list)
_review_feed: list[ReviewDetail] = []
_webhook_logs: list[WebhookLogEntry] = []
_cost_metrics: dict[str, dict[str, float]] = defaultdict(
    lambda: {"token_usage": 0.0, "estimated_cost_usd": 0.0, "reviews": 0.0}
)
_audit_log: list[AuditEntry] = []
_runtime_overrides: dict[str, object] = {}
_auth_states: dict[str, float] = {}
_sessions: dict[str, dict[str, str]] = {}


def _review_key(commit_sha: str, pull_number: int) -> str:
    return f"{commit_sha}:{pull_number}"


def _is_rate_limited(repo_key: str, window: int, max_reviews: int) -> bool:
    now = time.time()
    cutoff = now - window
    _rate_limit_log[repo_key] = [t for t in _rate_limit_log[repo_key] if t > cutoff]
    if len(_rate_limit_log[repo_key]) >= max_reviews:
        return True
    _rate_limit_log[repo_key].append(now)
    return False


def _add_webhook_log(
    repo: str,
    event: str,
    action: str,
    status: str,
    reason: str | None = None,
) -> None:
    _webhook_logs.insert(
        0,
        WebhookLogEntry(
            id=str(uuid4()),
            repo=repo,
            event=event,
            action=action,
            status=status,
            reason=reason,
            created_at=datetime.now(UTC),
        ),
    )
    del _webhook_logs[200:]


def _effective_settings(settings: Settings) -> dict[str, object]:
    base = {
        "llm_provider": settings.llm_provider,
        "llm_model": settings.llm_model,
        "key_roulette_enabled": settings.key_roulette_enabled,
        "diff_token_limit": settings.diff_token_limit,
        "rate_limit_window_seconds": settings.rate_limit_window_seconds,
        "rate_limit_max_reviews": settings.rate_limit_max_reviews,
        "llm_api_key": settings.llm_api_key,
    }
    return {**base, **_runtime_overrides}


def _resolved_settings(settings: Settings) -> Settings:
    """
    Build a Settings object that reflects any dashboard runtime overrides.

    The dashboard config panel updates in-memory overrides, and webhook review
    execution should honor those values instead of only the original .env file.
    """
    return settings.model_copy(update=_effective_settings(settings))


def _today_key(offset_days: int = 0) -> str:
    day = datetime.now(UTC).date() - timedelta(days=offset_days)
    return day.isoformat()


def _prune_auth_state() -> None:
    now = time.time()
    for state, created_at in list(_auth_states.items()):
        if now - created_at > 600:
            del _auth_states[state]


def _get_session(request: Request) -> dict[str, str] | None:
    token = request.cookies.get("dashboard_session")
    if not token:
        return None
    return _sessions.get(token)


def _require_admin(request: Request) -> dict[str, str]:
    session = _get_session(request)
    if not session:
        raise HTTPException(status_code=401, detail="Authentication required")
    if session.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin role required")
    return session


def verify_signature(payload: bytes, signature_header: str, secret: str) -> bool:
    if not signature_header.startswith("sha256="):
        return False
    expected_sig = signature_header[7:]
    mac = hmac.new(secret.encode(), payload, hashlib.sha256)
    return hmac.compare_digest(mac.hexdigest(), expected_sig)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/auth/status")
async def auth_status(request: Request) -> dict[str, object]:
    session = _get_session(request)
    if not session:
        return {"authenticated": False}
    return {
        "authenticated": True,
        "user": {
            "login": session["login"],
            "name": session.get("name", ""),
            "avatar_url": session.get("avatar_url", ""),
            "role": session["role"],
        },
    }


@app.post("/auth/logout")
async def logout(response: Response, request: Request) -> dict[str, str]:
    token = request.cookies.get("dashboard_session")
    if token:
        _sessions.pop(token, None)
    response.delete_cookie("dashboard_session", path="/")
    return {"status": "ok"}


@app.get("/auth/github/login")
async def github_login() -> RedirectResponse:
    settings = get_settings()
    if not settings.github_oauth_client_id or not settings.github_oauth_client_secret:
        raise HTTPException(status_code=500, detail="GitHub OAuth is not configured")

    _prune_auth_state()
    state = secrets.token_urlsafe(24)
    _auth_states[state] = time.time()
    params = urlencode(
        {
            "client_id": settings.github_oauth_client_id,
            "redirect_uri": settings.github_oauth_redirect_uri,
            "scope": "read:user user:email",
            "state": state,
        }
    )
    return RedirectResponse(url=f"https://github.com/login/oauth/authorize?{params}")


@app.get("/auth/github/callback")
async def github_callback(code: str = "", state: str = "") -> RedirectResponse:
    settings = get_settings()
    if not code or not state:
        raise HTTPException(status_code=400, detail="Missing OAuth callback parameters")

    _prune_auth_state()
    if state not in _auth_states:
        raise HTTPException(status_code=400, detail="Invalid OAuth state")
    del _auth_states[state]

    async with httpx.AsyncClient(timeout=15) as client:
        token_resp = await client.post(
            "https://github.com/login/oauth/access_token",
            headers={"Accept": "application/json"},
            data={
                "client_id": settings.github_oauth_client_id,
                "client_secret": settings.github_oauth_client_secret,
                "code": code,
                "redirect_uri": settings.github_oauth_redirect_uri,
            },
        )
        token_resp.raise_for_status()
        token_payload = token_resp.json()
        access_token = token_payload.get("access_token")
        if not access_token:
            raise HTTPException(status_code=400, detail="GitHub token exchange failed")

        user_resp = await client.get(
            "https://api.github.com/user",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        user_resp.raise_for_status()
        user = user_resp.json()

    login = str(user.get("login", "")).lower()
    if not login:
        raise HTTPException(status_code=400, detail="Missing GitHub login in profile")

    role = "admin" if login in settings.admin_users else "viewer"
    session_token = secrets.token_urlsafe(32)
    _sessions[session_token] = {
        "login": login,
        "name": str(user.get("name", "") or ""),
        "avatar_url": str(user.get("avatar_url", "") or ""),
        "role": role,
    }

    response = RedirectResponse(url="http://127.0.0.1:5173/")
    response.set_cookie(
        key="dashboard_session",
        value=session_token,
        httponly=True,
        secure=False,
        samesite="lax",
        max_age=60 * 60 * 24,
        path="/",
    )
    return response


@app.get("/api/dashboard/reviews", response_model=list[ReviewFeedItem])
async def dashboard_reviews() -> list[ReviewFeedItem]:
    return _review_feed[:50]


@app.get("/api/dashboard/reviews/{review_id}", response_model=ReviewDetail)
async def dashboard_review_detail(review_id: str) -> ReviewDetail:
    for review in _review_feed:
        if review.id == review_id:
            return review
    raise HTTPException(status_code=404, detail="Review not found")


@app.get("/api/dashboard/webhooks", response_model=list[WebhookLogEntry])
async def dashboard_webhooks() -> list[WebhookLogEntry]:
    return _webhook_logs[:100]


@app.get("/api/dashboard/cost", response_model=CostSummary)
async def dashboard_cost() -> CostSummary:
    points: list[CostPoint] = []
    for offset in range(6, -1, -1):
        day = _today_key(offset)
        row = _cost_metrics[day]
        points.append(
            CostPoint(
                date=day,
                token_usage=int(row["token_usage"]),
                estimated_cost_usd=round(row["estimated_cost_usd"], 4),
                reviews=int(row["reviews"]),
            )
        )

    total_tokens = int(sum(point.token_usage for point in points))
    total_reviews = int(sum(point.reviews for point in points))
    total_cost = round(sum(point.estimated_cost_usd for point in points), 4)
    avg_cost = round(total_cost / total_reviews, 4) if total_reviews else 0.0

    return CostSummary(
        last_7_days=points,
        total_reviews=total_reviews,
        total_tokens=total_tokens,
        total_estimated_cost_usd=total_cost,
        avg_cost_per_pr_usd=avg_cost,
    )


@app.get("/api/dashboard/config", response_model=ConfigView)
async def dashboard_config() -> ConfigView:
    settings = get_settings()
    effective = _effective_settings(settings)
    return ConfigView(
        llm_provider=str(effective["llm_provider"]),
        llm_model=str(effective["llm_model"]),
        key_roulette_enabled=bool(effective["key_roulette_enabled"]),
        diff_token_limit=int(effective["diff_token_limit"]),
        rate_limit_window_seconds=int(effective["rate_limit_window_seconds"]),
        rate_limit_max_reviews=int(effective["rate_limit_max_reviews"]),
        has_api_keys=bool(str(effective["llm_api_key"]).strip()),
    )


@app.patch("/api/dashboard/config", response_model=ConfigView)
async def update_dashboard_config(update: ConfigUpdate, request: Request) -> ConfigView:
    session = _require_admin(request)
    payload = update.model_dump(exclude_none=True)
    if payload:
        _runtime_overrides.update(payload)
        _audit_log.insert(
            0,
            AuditEntry(
                id=str(uuid4()),
                actor=session["login"],
                changed_fields=sorted(payload.keys()),
                created_at=datetime.now(UTC),
            ),
        )
        del _audit_log[200:]
    return await dashboard_config()


@app.get("/api/dashboard/audit", response_model=list[AuditEntry])
async def dashboard_audit() -> list[AuditEntry]:
    return _audit_log[:100]


@app.post("/webhook")
async def handle_webhook(
    request: Request,
    x_hub_signature_256: str = Header(default=""),
    x_github_event: str = Header(default=""),
) -> dict[str, str]:
    settings = get_settings()
    effective = _effective_settings(settings)
    resolved_settings = _resolved_settings(settings)
    body = await request.body()

    if not verify_signature(body, x_hub_signature_256, settings.github_webhook_secret):
        logger.warning("Invalid webhook signature — rejecting request")
        _add_webhook_log("unknown", x_github_event or "unknown", "unknown", "failed", "invalid signature")
        raise HTTPException(status_code=403, detail="Invalid signature")

    payload = await request.json()

    if x_github_event != "pull_request":
        _add_webhook_log("unknown", x_github_event, "unknown", "ignored", "event filtered")
        return {"status": "ignored", "reason": f"event type: {x_github_event}"}

    pr = payload["pull_request"]
    owner = payload["repository"]["owner"]["login"]
    repo_name = payload["repository"]["name"]
    action = payload.get("action", "")
    pull_number = pr["number"]
    commit_sha = pr["head"]["sha"]
    pr_title = pr.get("title", "")
    pr_body = pr.get("body", "") or ""

    repo_key = f"{owner}/{repo_name}"
    reviewable_actions = {"opened", "synchronize", "reopened", "ready_for_review"}
    if action == "closed":
        reason = "merged PR does not trigger review" if pr.get("merged") else "PR closed without merge"
        _add_webhook_log(repo_key, x_github_event, action, "ignored", reason)
        return {"status": "ignored", "reason": reason}

    if action not in reviewable_actions:
        _add_webhook_log(
            repo_key,
            x_github_event,
            action,
            "ignored",
            "action filtered",
        )
        return {"status": "ignored", "reason": f"action: {action}"}

    logger.info(
        "Webhook received for %s#%d — event=%s action=%s commit=%s",
        repo_key,
        pull_number,
        x_github_event,
        action,
        commit_sha[:8],
    )
    key = _review_key(commit_sha, pull_number)
    if key in _seen_reviews:
        _add_webhook_log(repo_key, x_github_event, action, "skipped", "already reviewed")
        return {"status": "skipped", "reason": "already reviewed"}
    _seen_reviews.add(key)

    if _is_rate_limited(
        repo_key,
        int(effective["rate_limit_window_seconds"]),
        int(effective["rate_limit_max_reviews"]),
    ):
        _add_webhook_log(repo_key, x_github_event, action, "skipped", "rate limited")
        return {"status": "skipped", "reason": "rate limited"}

    try:
        private_key = settings.github_private_key_path.read_text()
        token = get_installation_token(
            settings.github_app_id,
            private_key,
            settings.github_installation_id,
        )

        raw_diff = await fetch_pr_diff(owner, repo_name, pull_number, token)
        diff = annotate_diff(raw_diff)

        diff, was_truncated = truncate_diff(diff, int(effective["diff_token_limit"]))
        if was_truncated:
            logger.warning("PR diff was truncated for %s#%d", repo_key, pull_number)

        result = await review_diff(
            diff,
            resolved_settings,
            pr_title=pr_title,
            pr_body=pr_body,
        )

        await post_review_safe(owner, repo_name, pull_number, commit_sha, result, token)
        await set_label(owner, repo_name, pull_number, result.verdict, token)

        review_id = str(uuid4())
        review_entry = ReviewDetail(
            id=review_id,
            repo=repo_key,
            pr_number=pull_number,
            verdict=result.verdict,
            comments_count=len(result.comments),
            summary=result.summary,
            provider=str(effective["llm_provider"]),
            model=str(effective["llm_model"]),
            created_at=datetime.now(UTC),
            pull_request_title=pr_title,
            pull_request_body=pr_body,
            comments=[comment.model_dump() for comment in result.comments],
        )
        _review_feed.insert(0, review_entry)
        del _review_feed[200:]

        token_count = count_tokens(raw_diff)
        day = _today_key()
        _cost_metrics[day]["token_usage"] += token_count
        _cost_metrics[day]["estimated_cost_usd"] += token_count * 0.000003
        _cost_metrics[day]["reviews"] += 1

        _add_webhook_log(repo_key, x_github_event, action, "processed")
        logger.info("Review complete for %s#%d — verdict: %s", repo_key, pull_number, result.verdict)
        return {"status": "reviewed", "verdict": result.verdict}
    except Exception as exc:
        _seen_reviews.discard(key)
        logger.exception("Review failed for %s#%d", repo_key, pull_number)
        _add_webhook_log(repo_key, x_github_event, action, "failed", str(exc))
        raise
