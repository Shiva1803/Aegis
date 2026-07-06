from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


RoutingTier = Literal["lightweight", "standard", "reasoning"]


class ReviewFeedItem(BaseModel):
    id: str
    repo: str
    pr_number: int
    verdict: Literal["looks-good", "needs-work"]
    comments_count: int = 0
    summary: str
    provider: str
    model: str
    routing_tier: RoutingTier = "standard"
    routing_reason: str = ""
    created_at: datetime


class ReviewDetail(ReviewFeedItem):
    pull_request_title: str
    pull_request_body: str = ""
    comments: list[dict] = Field(default_factory=list)


class WebhookLogEntry(BaseModel):
    id: str
    repo: str
    event: str
    action: str
    status: Literal["processed", "ignored", "skipped", "failed"]
    reason: str | None = None
    created_at: datetime


class CostPoint(BaseModel):
    date: str
    token_usage: int
    input_tokens: int = 0
    output_tokens: int = 0
    estimated_cost_usd: float
    reviews: int


class CostSummary(BaseModel):
    last_7_days: list[CostPoint]
    total_reviews: int
    total_tokens: int
    total_estimated_cost_usd: float
    avg_cost_per_pr_usd: float


class ConfigView(BaseModel):
    llm_provider: str
    llm_model: str
    key_roulette_enabled: bool
    model_auto_routing_enabled: bool
    auto_route_simple_model: str
    auto_route_complex_model: str
    key_failure_cooldown_seconds: int
    diff_token_limit: int
    rate_limit_window_seconds: int
    rate_limit_max_reviews: int
    monthly_budget_cap: float
    current_month_spend: float
    has_api_keys: bool
    active_key_count: int = 0
    unhealthy_key_count: int = 0
    key_health: list["KeyHealthView"] = Field(default_factory=list)


class ConfigUpdate(BaseModel):
    llm_provider: str | None = None
    llm_model: str | None = None
    key_roulette_enabled: bool | None = None
    model_auto_routing_enabled: bool | None = None
    auto_route_simple_model: str | None = None
    auto_route_complex_model: str | None = None
    key_failure_cooldown_seconds: int | None = None
    diff_token_limit: int | None = None
    rate_limit_window_seconds: int | None = None
    rate_limit_max_reviews: int | None = None
    monthly_budget_cap: float | None = None
    llm_api_key: str | None = None


class AuditEntry(BaseModel):
    id: str
    actor: str
    changed_fields: list[str]
    created_at: datetime


class KeyHealthView(BaseModel):
    key_suffix: str
    status: Literal["healthy", "cooldown"]
    failure_count: int = 0
    last_error_status: int | None = None
    last_error_reason: str | None = None
    last_error_at: datetime | None = None
    disabled_until: datetime | None = None


ConfigView.model_rebuild()
