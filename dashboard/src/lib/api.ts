import type { AuditEntry, AuthStatus, ConfigView, CostSummary, ReviewDetail, ReviewFeedItem, WebhookLog } from "./types";

const BASE_URL = import.meta.env.VITE_API_URL || "";

async function get<T>(path: string): Promise<T> {
  const response = await fetch(`${BASE_URL}${path}`, { credentials: "include" });
  if (!response.ok) {
    throw new Error(`Request failed: ${response.status}`);
  }
  const contentType = response.headers.get("content-type") ?? "";
  if (!contentType.includes("application/json")) {
    throw new Error(`Expected JSON but got ${contentType || "unknown content type"} from ${path}`);
  }
  return response.json() as Promise<T>;
}

type ConfigUpdatePayload = Partial<ConfigView> & {
  llm_api_key?: string;
};

export const api = {
  getReviews: (filters?: { repo?: string; org?: string }) => {
    const params = new URLSearchParams();
    if (filters?.repo) params.append("repo", filters.repo);
    if (filters?.org) params.append("org", filters.org);
    return get<ReviewFeedItem[]>(`/api/dashboard/reviews?${params.toString()}`);
  },
  getReview: (id: string) => get<ReviewDetail>(`/api/dashboard/reviews/${id}`),
  getConfig: () => get<ConfigView>("/api/dashboard/config"),
  getCost: (filters?: { repo?: string; org?: string }) => {
    const params = new URLSearchParams();
    if (filters?.repo) params.append("repo", filters.repo);
    if (filters?.org) params.append("org", filters.org);
    return get<CostSummary>(`/api/dashboard/cost?${params.toString()}`);
  },
  getWebhooks: (filters?: { repo?: string; org?: string }) => {
    const params = new URLSearchParams();
    if (filters?.repo) params.append("repo", filters.repo);
    if (filters?.org) params.append("org", filters.org);
    return get<WebhookLog[]>(`/api/dashboard/webhooks?${params.toString()}`);
  },
  getRepositories: () => get<string[]>("/api/dashboard/repositories"),
  getAudit: () => get<AuditEntry[]>("/api/dashboard/audit"),
  updateConfig: async (payload: ConfigUpdatePayload) => {
    const response = await fetch(`${BASE_URL}/api/dashboard/config`, {
      method: "PATCH",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });
    if (!response.ok) {
      throw new Error(`Config update failed: ${response.status}`);
    }
    return response.json() as Promise<ConfigView>;
  },
  getAuthStatus: () => get<AuthStatus>(`/auth/status`),
  logout: async () => {
    const response = await fetch(`${BASE_URL}/auth/logout`, {
      method: "POST",
      credentials: "include"
    });
    if (!response.ok) {
      throw new Error(`Logout failed: ${response.status}`);
    }
  }
};
