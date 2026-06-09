import type { AuditEntry, AuthStatus, ConfigView, CostSummary, ReviewDetail, ReviewFeedItem, WebhookLog } from "./types";

async function get<T>(path: string): Promise<T> {
  const response = await fetch(path, { credentials: "include" });
  if (!response.ok) {
    throw new Error(`Request failed: ${response.status}`);
  }
  const contentType = response.headers.get("content-type") ?? "";
  if (!contentType.includes("application/json")) {
    throw new Error(`Expected JSON but got ${contentType || "unknown content type"} from ${path}`);
  }
  return response.json() as Promise<T>;
}

export const api = {
  getReviews: () => get<ReviewFeedItem[]>("/api/dashboard/reviews"),
  getReview: (id: string) => get<ReviewDetail>(`/api/dashboard/reviews/${id}`),
  getConfig: () => get<ConfigView>("/api/dashboard/config"),
  getCost: () => get<CostSummary>("/api/dashboard/cost"),
  getWebhooks: () => get<WebhookLog[]>("/api/dashboard/webhooks"),
  getAudit: () => get<AuditEntry[]>("/api/dashboard/audit"),
  updateConfig: async (payload: Partial<ConfigView>) => {
    const response = await fetch("/api/dashboard/config", {
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
  getAuthStatus: () => get<AuthStatus>("/auth/status"),
  logout: async () => {
    const response = await fetch("/auth/logout", {
      method: "POST",
      credentials: "include"
    });
    if (!response.ok) {
      throw new Error(`Logout failed: ${response.status}`);
    }
  }
};
