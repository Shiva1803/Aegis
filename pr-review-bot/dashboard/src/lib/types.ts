export type Verdict = "looks-good" | "needs-work";

export interface ReviewFeedItem {
  id: string;
  repo: string;
  pr_number: number;
  verdict: Verdict;
  comments_count: number;
  summary: string;
  provider: string;
  model: string;
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
  diff_token_limit: number;
  rate_limit_window_seconds: number;
  rate_limit_max_reviews: number;
  has_api_keys: boolean;
}

export interface CostSummary {
  last_7_days: Array<{
    date: string;
    token_usage: number;
    estimated_cost_usd: number;
    reviews: number;
  }>;
  total_reviews: number;
  total_tokens: number;
  total_estimated_cost_usd: number;
  avg_cost_per_pr_usd: number;
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
