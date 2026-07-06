export type Verdict = "looks-good" | "needs-work";
export type RoutingTier = "lightweight" | "standard" | "reasoning";

export interface ReviewFeedItem {
  id: string;
  repo: string;
  pr_number: number;
  verdict: Verdict;
  comments_count: number;
  summary: string;
  provider: string;
  model: string;
  routing_tier: RoutingTier;
  routing_reason: string;
  created_at: string;
}

export interface ReviewDetail extends ReviewFeedItem {
  pull_request_title: string;
  pull_request_body: string;
  comments: Array<{
    file: string;
    line: number;
    severity: "critical" | "suggestion" | "nit";
    category: "security" | "logic" | "style" | "performance";
    body: string;
  }>;
}

export interface ConfigView {
  llm_provider: string;
  llm_model: string;
  key_roulette_enabled: boolean;
  model_auto_routing_enabled: boolean;
  auto_route_simple_model: string;
  auto_route_complex_model: string;
  key_failure_cooldown_seconds: number;
  diff_token_limit: number;
  rate_limit_window_seconds: number;
  rate_limit_max_reviews: number;
  monthly_budget_cap: number;
  current_month_spend: number;
  has_api_keys: boolean;
  custom_system_prompt: string;
  active_key_count: number;
  unhealthy_key_count: number;
  key_health: KeyHealthView[];
}

export interface KeyHealthView {
  key_suffix: string;
  status: "healthy" | "cooldown";
  failure_count: number;
  last_error_status?: number | null;
  last_error_reason?: string | null;
  last_error_at?: string | null;
  disabled_until?: string | null;
}

export interface RepoCostBreakdown {
  repo_name: string;
  token_usage: number;
  estimated_cost_usd: number;
  reviews: number;
  avg_cost_per_pr_usd: number;
}

export interface CostSummary {
  last_7_days: Array<{
    date: string;
    token_usage: number;
    input_tokens?: number;
    output_tokens?: number;
    estimated_cost_usd: number;
    reviews: number;
  }>;
  total_reviews: number;
  total_tokens: number;
  total_estimated_cost_usd: number;
  avg_cost_per_pr_usd: number;
  breakdown: RepoCostBreakdown[];
}

export interface WebhookLog {
  id: string;
  repo: string;
  event: string;
  action: string;
  status: "processed" | "ignored" | "skipped" | "failed";
  reason?: string | null;
  created_at: string;
}

export interface AuditEntry {
  id: string;
  actor: string;
  changed_fields: string[];
  created_at: string;
}

export interface AuthStatus {
  authenticated: boolean;
  user?: {
    login: string;
    name: string;
    avatar_url: string;
    role: "admin" | "viewer";
  };
}

export interface GitHubStatus {
  status: "healthy" | "unconfigured" | "error";
  error: string | null;
}

export interface SeverityInsights {
  critical: number;
  suggestion: number;
  nit: number;
}

export interface CategoryInsights {
  security: number;
  performance: number;
  logic: number;
  style: number;
}

export interface ReviewInsights {
  total_comments: number;
  total_reviews: number;
  severity: SeverityInsights;
  category: CategoryInsights;
}

