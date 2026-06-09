import { useEffect, useMemo, useState } from "react";
import { api } from "./lib/api";
import type { AuditEntry, AuthStatus, ConfigView, CostSummary, ReviewDetail, ReviewFeedItem, WebhookLog } from "./lib/types";

type TabKey = "feed" | "detail" | "config" | "cost" | "webhooks";

const tabs: Array<{ key: TabKey; label: string }> = [
  { key: "feed", label: "Live Feed" },
  { key: "detail", label: "Review Detail" },
  { key: "config", label: "Configuration" },
  { key: "cost", label: "Cost" },
  { key: "webhooks", label: "Webhooks" }
];

export function App() {
  const [videoState, setVideoState] = useState<"loading" | "ready" | "error">("loading");
  const [activeTab, setActiveTab] = useState<TabKey>("feed");
  const [reviews, setReviews] = useState<ReviewFeedItem[]>([]);
  const [selectedReviewId, setSelectedReviewId] = useState<string | null>(null);
  const [detail, setDetail] = useState<ReviewDetail | null>(null);
  const [config, setConfig] = useState<ConfigView | null>(null);
  const [cost, setCost] = useState<CostSummary | null>(null);
  const [webhooks, setWebhooks] = useState<WebhookLog[]>([]);
  const [audit, setAudit] = useState<AuditEntry[]>([]);
  const [auth, setAuth] = useState<AuthStatus>({ authenticated: false });
  const [saveError, setSaveError] = useState<string>("");

  useEffect(() => {
    const load = async () => {
      const [r, c, s, w, a, authStatus] = await Promise.all([
        api.getReviews(),
        api.getConfig(),
        api.getCost(),
        api.getWebhooks(),
        api.getAudit(),
        api.getAuthStatus()
      ]);
      setReviews(r);
      setConfig(c);
      setCost(s);
      setWebhooks(w);
      setAudit(a);
      setAuth(authStatus);
      if (r[0] && !selectedReviewId) {
        setSelectedReviewId(r[0].id);
      }
    };
    void load();
  }, [selectedReviewId]);

  useEffect(() => {
    if (!selectedReviewId) return;
    void api.getReview(selectedReviewId).then(setDetail).catch(() => setDetail(null));
  }, [selectedReviewId]);

  const maxTokens = useMemo(() => Math.max(...(cost?.last_7_days.map((d) => d.token_usage) ?? [1])), [cost]);

  return (
    <main className="hero-root">
      <video
        autoPlay
        loop
        muted
        playsInline
        preload="auto"
        className={`absolute inset-0 w-full h-full object-cover z-0 hero-video ${videoState === "ready" ? "ready" : ""}`}
        onCanPlay={() => setVideoState("ready")}
        onError={() => setVideoState("error")}
      >
        <source src="/hero-bg.mp4" type="video/mp4" />
      </video>
      <div className="hero-vignette" />
      <div className="hero-grain" />
      {videoState !== "ready" ? (
        <div className="video-state">
          {videoState === "loading" ? "Loading background video..." : "Video failed to load. Check network/CORS in the in-app browser."}
        </div>
      ) : null}

      <header className="top-nav">
        <div className="brand">PR SIGNAL</div>
        <nav className="pill-nav">
          {tabs.map((tab) => (
            <button
              key={tab.key}
              className={tab.key === activeTab ? "pill active" : "pill"}
              onClick={() => setActiveTab(tab.key)}
            >
              {tab.label}
            </button>
          ))}
        </nav>
        <div className="auth-slot">
          {auth.authenticated && auth.user ? (
            <>
              <div className="user-chip">
                {auth.user.avatar_url ? <img src={auth.user.avatar_url} alt={auth.user.login} /> : null}
                <span>{auth.user.login} · {auth.user.role}</span>
              </div>
              <button className="ghost" onClick={async () => { await api.logout(); setAuth({ authenticated: false }); }}>
                Logout
              </button>
            </>
          ) : (
            <a className="ghost" href="/auth/github/login">Connect GitHub</a>
          )}
        </div>
      </header>

      <section className="hero-copy">
        <p className="kicker">AI Code Review Command Center</p>
        <h1>Supercharged PR Intelligence</h1>
        <p>Live review stream, configurable LLM controls, cost telemetry, webhook health, and audit history in one cinematic console.</p>
      </section>

      <section className="glass-stage">
        {activeTab === "feed" && (
          <div className="panel">
            <h2>Live Review Feed</h2>
            <div className="stack">
              {reviews.map((review) => (
                <button key={review.id} className="row" onClick={() => { setSelectedReviewId(review.id); setActiveTab("detail"); }}>
                  <div>
                    <strong>{review.repo} #{review.pr_number}</strong>
                    <p>{review.summary}</p>
                  </div>
                  <span className={`status ${review.verdict}`}>{review.verdict}</span>
                </button>
              ))}
            </div>
          </div>
        )}

        {activeTab === "detail" && (
          <div className="panel">
            <h2>Review Detail View</h2>
            {detail ? (
              <>
                <h3>{detail.pull_request_title}</h3>
                <p>{detail.summary}</p>
                <div className="meta-line">
                  <span>{detail.provider}</span>
                  <span>{detail.model}</span>
                  <span>{detail.comments_count} comments</span>
                </div>
                <div className="stack">
                  {detail.comments.map((comment, idx) => (
                    <article key={`${comment.file}-${idx}`} className="snippet">
                      <code>{comment.file}:{comment.line}</code>
                      <p>{comment.body}</p>
                      <small>{comment.severity} · {comment.category}</small>
                    </article>
                  ))}
                </div>
              </>
            ) : <p>Pick a review from Live Feed.</p>}
          </div>
        )}

        {activeTab === "config" && config && (
          <div className="panel">
            <div className="panel-head">
              <h2>Configuration Panel</h2>
              <button
                className="save"
                disabled={auth.user?.role !== "admin"}
                onClick={async () => {
                  try {
                    setSaveError("");
                    setConfig(await api.updateConfig(config));
                  } catch (error) {
                    setSaveError(error instanceof Error ? error.message : "Save failed");
                  }
                }}
              >
                Save Changes
              </button>
            </div>
            <div className="grid">
              <label>Provider<input value={config.llm_provider} onChange={(e) => setConfig({ ...config, llm_provider: e.target.value })} /></label>
              <label>Model<input value={config.llm_model} onChange={(e) => setConfig({ ...config, llm_model: e.target.value })} /></label>
              <label>Diff Token Limit<input type="number" value={config.diff_token_limit} onChange={(e) => setConfig({ ...config, diff_token_limit: Number(e.target.value) })} /></label>
              <label>Rate Window (s)<input type="number" value={config.rate_limit_window_seconds} onChange={(e) => setConfig({ ...config, rate_limit_window_seconds: Number(e.target.value) })} /></label>
              <label>Rate Max Reviews<input type="number" value={config.rate_limit_max_reviews} onChange={(e) => setConfig({ ...config, rate_limit_max_reviews: Number(e.target.value) })} /></label>
              <label className="toggle">Key Roulette<input type="checkbox" checked={config.key_roulette_enabled} onChange={(e) => setConfig({ ...config, key_roulette_enabled: e.target.checked })} /></label>
            </div>
            {auth.user?.role !== "admin" ? <p className="warn">Sign in as admin to edit config.</p> : null}
            {saveError ? <p className="warn">{saveError}</p> : null}
            <h3>Audit Log</h3>
            <div className="stack">
              {audit.map((entry) => (
                <p key={entry.id} className="audit-row">{entry.actor} changed {entry.changed_fields.join(", ")} at {new Date(entry.created_at).toLocaleString()}</p>
              ))}
            </div>
          </div>
        )}

        {activeTab === "cost" && cost && (
          <div className="panel">
            <h2>Cost Tracker</h2>
            <div className="cards">
              <article><h3>${cost.total_estimated_cost_usd.toFixed(2)}</h3><p>7-day spend</p></article>
              <article><h3>{cost.total_tokens.toLocaleString()}</h3><p>7-day tokens</p></article>
              <article><h3>${cost.avg_cost_per_pr_usd.toFixed(4)}</h3><p>Average / PR</p></article>
            </div>
            <div className="bars">
              {cost.last_7_days.map((day) => (
                <div key={day.date} className="bar-col">
                  <div className="bar" style={{ height: `${(day.token_usage / maxTokens) * 140 + 8}px` }} />
                  <span>{day.date.slice(5)}</span>
                </div>
              ))}
            </div>
          </div>
        )}

        {activeTab === "webhooks" && (
          <div className="panel">
            <h2>Webhook Logs</h2>
            <div className="stack">
              {webhooks.map((log) => (
                <div key={log.id} className="log-row">
                  <strong>{log.repo}</strong>
                  <span>{log.event}/{log.action}</span>
                  <span className={log.status === "processed" ? "ok" : "bad"}>{log.status}</span>
                  <span>{log.reason ?? "-"}</span>
                </div>
              ))}
            </div>
          </div>
        )}
      </section>
      <footer className="hero-footer">
        <a href="#" onClick={(event) => event.preventDefault()}>GitHub Project</a>
        <span>|</span>
        <a href="https://shivanshtripathi.vercel.app" target="_blank" rel="noreferrer">Built by Shivansh</a>
      </footer>
    </main>
  );
}
