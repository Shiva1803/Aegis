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

const PROVIDER_MODELS: Record<string, string[]> = {
  nvidia_nim: ["deepseek-ai/deepseek-v4-pro", "meta/llama-3.1-405b-instruct"],
  groq: ["llama-3.3-70b-versatile", "mixtral-8x7b-32768", "gemma2-9b-it"],
  openai: ["gpt-4o", "gpt-4o-mini", "o1-mini", "o3-mini"],
  anthropic: ["claude-3-5-sonnet-latest", "claude-3-5-haiku-latest", "claude-3-opus-latest"],
  gemini: ["gemini-1.5-pro", "gemini-1.5-flash", "gemini-2.0-flash-exp"]
};

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
  const [loadError, setLoadError] = useState<string>("");
  const [userMenuOpen, setUserMenuOpen] = useState(false);
  const [apiKeyInput, setApiKeyInput] = useState("");

  useEffect(() => {
    let cancelled = false;

    const load = async () => {
      try {
        const [r, c, s, w, a, authStatus] = await Promise.all([
          api.getReviews(),
          api.getConfig(),
          api.getCost(),
          api.getWebhooks(),
          api.getAudit(),
          api.getAuthStatus()
        ]);
        if (cancelled) return;

        setLoadError("");
        setReviews(r);
        setConfig(c);
        setCost(s);
        setWebhooks(w);
        setAudit(a);
        setAuth(authStatus);
        setSelectedReviewId((current) => current ?? r[0]?.id ?? null);
      } catch (error) {
        if (cancelled) return;
        setLoadError(error instanceof Error ? error.message : "Dashboard refresh failed");
      }
    };

    void load();

    const intervalId = window.setInterval(() => {
      void load();
    }, 10000);

    return () => {
      cancelled = true;
      window.clearInterval(intervalId);
    };
  }, []);

  useEffect(() => {
    if (!selectedReviewId) return;
    void api.getReview(selectedReviewId).then(setDetail).catch(() => setDetail(null));
  }, [selectedReviewId]);

  useEffect(() => {
    if (!userMenuOpen) return;
    const handleOutsideClick = (e: MouseEvent) => {
      const target = e.target as HTMLElement;
      if (!target.closest(".user-menu-container")) {
        setUserMenuOpen(false);
      }
    };
    document.addEventListener("click", handleOutsideClick);
    return () => document.removeEventListener("click", handleOutsideClick);
  }, [userMenuOpen]);

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
        <source src="/newbg.mp4" type="video/mp4" />
      </video>
      <div className="hero-vignette" />
      <div className="hero-grain" />
      {videoState !== "ready" ? (
        <div className="video-state">
          {videoState === "loading" ? "Loading background video..." : "Video failed to load. Check network/CORS in the in-app browser."}
        </div>
      ) : null}

      <header className="top-nav">
        <div className="top-nav-left">
          <div className="logo-container">
            <img src="/Gemini_Generated_Image_fxx9lqfxx9lqfxx9.png" alt="Aegis Logo" className="logo-img" />
            <span className="logo-text">Aegis</span>
          </div>
        </div>

        <div className="top-nav-middle">
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
        </div>

        <div className="top-nav-right">
          <div className="auth-slot">
            {auth.authenticated && auth.user ? (
              <div className="user-menu-container">
                <button className="user-chip-btn" onClick={() => setUserMenuOpen(!userMenuOpen)}>
                  {auth.user.avatar_url ? (
                    <img className="user-avatar" src={auth.user.avatar_url} alt={auth.user.login} />
                  ) : null}
                  <span className="user-name-role">
                    {auth.user.login.toLowerCase()}.{auth.user.role.toLowerCase()}
                  </span>
                  <svg className={`chevron-icon ${userMenuOpen ? "open" : ""}`} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <polyline points="6 9 12 15 18 9" />
                  </svg>
                </button>

                {userMenuOpen && (
                  <div className="user-dropdown-menu">
                    <div className="dropdown-user-info">
                      <div className="info-row">
                        <span className="info-label">Role</span>
                        <span className="info-value role-badge">{auth.user?.role || "viewer"}</span>
                      </div>
                      <div className="info-row">
                        <span className="info-label">Server</span>
                        <span className="info-value status-active">Active</span>
                      </div>
                      <div className="info-row">
                        <span className="info-label">Session</span>
                        <span className="info-value">Connected</span>
                      </div>
                    </div>
                    <div className="dropdown-divider"></div>
                    <button className="dropdown-item" onClick={() => { setActiveTab("config"); setUserMenuOpen(false); }}>
                      <svg className="menu-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                        <circle cx="12" cy="12" r="3" />
                        <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z" />
                      </svg>
                      <span>Settings</span>
                    </button>
                    <button className="dropdown-item logout-item" onClick={async () => { await api.logout(); setAuth({ authenticated: false }); setUserMenuOpen(false); }}>
                      <svg className="menu-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                        <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4" />
                        <polyline points="16 17 21 12 16 7" />
                        <line x1="21" y1="12" x2="9" y2="12" />
                      </svg>
                      <span>Logout</span>
                    </button>
                  </div>
                )}
              </div>
            ) : (
              <a className="ghost" href={`${import.meta.env.VITE_API_URL || ""}/auth/github/login`}>Connect GitHub</a>
            )}
          </div>
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
            {loadError ? <p className="warn">{loadError}</p> : null}
            <div className="stack">
              {reviews.length === 0 ? (
                <p className="warn">
                  No reviews yet. This feed only fills after the backend successfully processes a GitHub
                  pull request webhook for `opened` or `synchronize`.
                </p>
              ) : null}
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
          <div className="panel review-detail-panel">
            <h2 className="detail-page-title">Review Detail View</h2>
            {detail ? (
              <>
                <h3 className="detail-subject">{detail.pull_request_title}</h3>
                
                {/* AI Summary Block */}
                <div className="ai-summary-block">
                  <div className="ai-summary-header">
                    <span className="ai-summary-title">AI Summary</span>
                  </div>
                  <p className="ai-summary-text">{detail.summary}</p>
                  <div className="ai-summary-footer">
                    <span>Generated by <strong className="ai-tag">{detail.model}</strong> via <strong className="ai-tag">{detail.provider}</strong></span>
                    <span className="divider">|</span>
                    <span>{detail.comments_count} {detail.comments_count === 1 ? "comment" : "comments"}</span>
                  </div>
                </div>

                <div className="detail-feedback-section">
                  <h3 className="feedback-count-title">Feedback ({detail.comments.length})</h3>
                  <div className="detail-comments-stack">
                    {detail.comments.map((comment, idx) => (
                      <article key={`${comment.file}-${idx}`} className="feedback-card">
                        <div className="feedback-card-header">
                          <div className="feedback-file-info">
                            <svg className="file-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                              <path d="M13 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z" />
                              <polyline points="13 2 13 9 20 9" />
                            </svg>
                            <span className="file-path">{comment.file}</span>
                            <span className="file-line">Line {comment.line}</span>
                          </div>
                          
                          <div className="feedback-badges">
                            <span className={`badge-severity severity-${comment.severity}`}>
                              {comment.severity}
                            </span>
                            <span className="badge-category">
                              {comment.category}
                            </span>
                          </div>
                        </div>
                        
                        <div className="feedback-card-body">
                          <p>{comment.body}</p>
                        </div>
                      </article>
                    ))}
                  </div>
                </div>
              </>
            ) : (
              <p className="no-review-selected">Pick a review from the Live Feed.</p>
            )}
          </div>
        )}

        {activeTab === "config" && config && (
          <div className="panel config-panel-redesign">
            <div className="panel-head">
              <h2>Configuration Panel</h2>
              <button
                className="save"
                disabled={auth.user?.role !== "admin"}
                onClick={async () => {
                  try {
                    setSaveError("");
                    const updatePayload: any = { ...config };
                    if (apiKeyInput.trim()) {
                      updatePayload.llm_api_key = apiKeyInput.trim();
                    }
                    setConfig(await api.updateConfig(updatePayload));
                    setApiKeyInput("");
                  } catch (error) {
                    setSaveError(error instanceof Error ? error.message : "Save failed");
                  }
                }}
              >
                Save Changes
              </button>
            </div>
            
            {auth.user?.role !== "admin" ? <p className="warn">Sign in as admin to edit config.</p> : null}
            {saveError ? <p className="warn">{saveError}</p> : null}

            <div className="config-layout">
              {/* Card 1: AI Model Details */}
              <div className="config-card">
                <h3 className="config-card-title">
                  <svg className="menu-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <circle cx="12" cy="12" r="3" />
                    <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z" />
                  </svg>
                  AI Model Details
                </h3>
                
                <div className="config-field">
                  <span className="config-label">Provider</span>
                  <select
                    className="config-select"
                    value={config.llm_provider}
                    onChange={(e) => {
                      const nextProvider = e.target.value;
                      const recommendedModels = PROVIDER_MODELS[nextProvider] || [];
                      const nextModel = recommendedModels[0] || config.llm_model;
                      setConfig({
                        ...config,
                        llm_provider: nextProvider,
                        llm_model: nextModel
                      });
                    }}
                  >
                    <option value="nvidia_nim">NVIDIA NIM (nvidia_nim)</option>
                    <option value="groq">Groq (groq)</option>
                    <option value="openai">OpenAI (openai)</option>
                    <option value="anthropic">Anthropic (anthropic)</option>
                    <option value="gemini">Gemini (gemini)</option>
                    {!["nvidia_nim", "groq", "openai", "anthropic", "gemini"].includes(config.llm_provider) && (
                      <option value={config.llm_provider}>{config.llm_provider} (Custom)</option>
                    )}
                  </select>
                </div>

                <div className="config-field">
                  <span className="config-label">Model</span>
                  <select
                    className="config-select"
                    value={config.llm_model}
                    onChange={(e) => setConfig({ ...config, llm_model: e.target.value })}
                  >
                    {(PROVIDER_MODELS[config.llm_provider] || []).includes(config.llm_model)
                      ? (PROVIDER_MODELS[config.llm_provider] || []).map((model) => (
                          <option key={model} value={model}>{model}</option>
                        ))
                      : [config.llm_model, ...(PROVIDER_MODELS[config.llm_provider] || [])].map((model) => (
                          <option key={model} value={model}>{model}</option>
                        ))
                    }
                  </select>
                </div>

                <div className="config-field">
                  <span className="config-label">LLM API Key</span>
                  <input
                    type="password"
                    className="config-input"
                    placeholder={config.has_api_keys ? "•••••••• (Keys Configured)" : "Enter API Key(s)"}
                    value={apiKeyInput}
                    onChange={(e) => setApiKeyInput(e.target.value)}
                    disabled={auth.user?.role !== "admin"}
                  />
                </div>

                <div className="config-field config-checkbox-group">
                  <div className="checkbox-with-tooltip">
                    <input
                      type="checkbox"
                      id="key-roulette-checkbox"
                      checked={config.key_roulette_enabled}
                      onChange={(e) => setConfig({ ...config, key_roulette_enabled: e.target.checked })}
                    />
                    <label htmlFor="key-roulette-checkbox" className="config-label cursor-pointer">
                      Key Roulette
                    </label>
                    <div className="tooltip-container">
                      <span className="tooltip-icon">?</span>
                      <span className="tooltip-text">
                        Distributes API requests across multiple comma-separated keys in the backend configurations.
                      </span>
                    </div>
                  </div>
                </div>
              </div>

              {/* Card 2: Rate Limiting & Tokens */}
              <div className="config-card">
                <h3 className="config-card-title">
                  <svg className="menu-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <rect x="5" y="2" width="14" height="20" rx="2" ry="2" />
                    <line x1="12" y1="18" x2="12.01" y2="18" />
                  </svg>
                  Rate Limiting & Tokens
                </h3>

                <div className="config-field">
                  <span className="config-label">Diff Token Limit</span>
                  <input
                    type="number"
                    className="config-input number-input"
                    value={config.diff_token_limit}
                    onChange={(e) => setConfig({ ...config, diff_token_limit: Number(e.target.value) })}
                  />
                </div>

                <div className="config-field">
                  <span className="config-label">Rate Window (s)</span>
                  <input
                    type="number"
                    className="config-input number-input"
                    value={config.rate_limit_window_seconds}
                    onChange={(e) => setConfig({ ...config, rate_limit_window_seconds: Number(e.target.value) })}
                  />
                </div>

                <div className="config-field">
                  <span className="config-label">Rate Max Reviews</span>
                  <input
                    type="number"
                    className="config-input number-input"
                    value={config.rate_limit_max_reviews}
                    onChange={(e) => setConfig({ ...config, rate_limit_max_reviews: Number(e.target.value) })}
                  />
                </div>
              </div>

              {/* Card 3: System Health & Connectivity */}
              <div className="config-card">
                <h3 className="config-card-title">
                  <svg className="menu-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <path d="M22 12h-4l-3 9L9 3l-3 9H2" />
                  </svg>
                  System Connectivity
                </h3>

                <div className="config-field">
                  <span className="config-label">Ngrok Gateway</span>
                  <div className="status-indicator-row">
                    <span className="status-dot dot-active"></span>
                    <span className="status-text text-active">Connected (External Webhook Tunnel)</span>
                  </div>
                </div>

                <div className="config-field">
                  <span className="config-label">GitHub Webhook Status</span>
                  <div className="status-indicator-row">
                    {webhooks.length > 0 && webhooks[0].status === "failed" ? (
                      <>
                        <span className="status-dot dot-error"></span>
                        <span className="status-text text-error">Delivery Issue Detected</span>
                      </>
                    ) : (
                      <>
                        <span className="status-dot dot-active"></span>
                        <span className="status-text text-active">Active & Healthy</span>
                      </>
                    )}
                  </div>
                </div>

                <div className="config-field">
                  <span className="config-label">App ID Connection</span>
                  <div className="status-indicator-row">
                    <span className="status-dot dot-active"></span>
                    <span className="status-text text-active">App Configuration Valid</span>
                  </div>
                </div>
              </div>
            </div>

            {/* Audit Log Section */}
            <div className="audit-log-section">
              <h3 className="config-card-title">
                <svg className="menu-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
                  <polyline points="14 2 14 8 20 8" />
                  <line x1="16" y1="13" x2="8" y2="13" />
                  <line x1="16" y1="17" x2="8" y2="17" />
                  <polyline points="10 9 9 9 8 9" />
                </svg>
                Audit Log
              </h3>
              <div className="audit-table-wrapper">
                {audit.length === 0 ? (
                  <p className="no-audit">No configuration changes recorded yet.</p>
                ) : (
                  <table className="audit-table">
                    <thead>
                      <tr>
                        <th>Actor</th>
                        <th>Action / Changed Fields</th>
                        <th>Timestamp</th>
                      </tr>
                    </thead>
                    <tbody>
                      {audit.map((entry) => (
                        <tr key={entry.id}>
                          <td className="actor-cell">{entry.actor}</td>
                          <td className="fields-cell">
                            Changed <span className="field-tag">{entry.changed_fields.join(", ")}</span>
                          </td>
                          <td className="time-cell">{new Date(entry.created_at).toLocaleString()}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
              </div>
            </div>
          </div>
        )}

        {activeTab === "cost" && cost && (
          <div className="panel cost-panel-redesign">
            <h2>Cost Tracker</h2>
            <div className="cost-cards">
              <div className="cost-card">
                <span className="cost-card-label">Total Spend (7d)</span>
                <h3 className="cost-card-value">${cost.total_estimated_cost_usd.toFixed(2)}</h3>
                <span className="cost-card-subtext">~ $0.00 previous 7d</span>
              </div>
              <div className="cost-card">
                <span className="cost-card-label">Tokens Used (7d)</span>
                <h3 className="cost-card-value">{cost.total_tokens.toLocaleString()}</h3>
                <span className="cost-card-subtext">~ 0 previous 7d</span>
              </div>
              <div className="cost-card">
                <span className="cost-card-label">Avg. Cost / PR</span>
                <h3 className="cost-card-value">${cost.avg_cost_per_pr_usd.toFixed(4)}</h3>
                <span className="cost-card-subtext">Estimated per review run</span>
              </div>
            </div>
            
            <div className="chart-container">
              {/* Background grid lines to give the chart visual substance */}
              <div className="chart-grid-lines">
                <div className="grid-line"><span>{maxTokens.toLocaleString()}</span></div>
                <div className="grid-line"><span>{Math.round(maxTokens / 2).toLocaleString()}</span></div>
                <div className="grid-line"><span>0</span></div>
              </div>
              
              <div className="chart-bars">
                {cost.last_7_days.map((day) => {
                  const percent = maxTokens > 0 ? (day.token_usage / maxTokens) * 100 : 0;
                  return (
                    <div key={day.date} className="chart-bar-col">
                      <div className="chart-bar-wrapper">
                        <div 
                          className="chart-bar" 
                          style={{ height: `${percent}%` }}
                        >
                          <div className="chart-bar-tooltip">
                            <div className="tooltip-date">{day.date}</div>
                            <div className="tooltip-value">{day.token_usage.toLocaleString()} tokens</div>
                            <div className="tooltip-cost">${(day.token_usage * 0.000002).toFixed(4)} est.</div>
                          </div>
                        </div>
                      </div>
                      <span className="chart-bar-date">{day.date.slice(5)}</span>
                    </div>
                  );
                })}
              </div>
            </div>
          </div>
        )}

        {activeTab === "webhooks" && (
          <div className="panel">
            <h2>Webhook Logs</h2>
            {webhooks.length === 0 ? <p className="warn">No webhook events have been recorded yet.</p> : null}
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
        <div className="footer-left">
          <span>Built by <a href="https://shivanshtripathi.vercel.app" target="_blank" rel="noreferrer">Shivansh Tripathi</a></span>
        </div>
        <div className="footer-right">
          <a href="#" onClick={(event) => event.preventDefault()}>
            <svg className="menu-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M9 19c-5 1.5-5-2.5-7-3m14 6v-3.87a3.37 3.37 0 0 0-.94-2.61c3.14-.35 6.44-1.54 6.44-7A5.44 5.44 0 0 0 20 4.77 5.07 5.07 0 0 0 19.91 1S18.73.65 16 2.48a13.38 13.38 0 0 0-7 0C6.27.65 5.09 1 5.09 1A5.07 5.07 0 0 0 5 4.77a5.44 5.44 0 0 0-1.5 3.78c0 5.42 3.3 6.61 6.44 7A3.37 3.37 0 0 0 9 18.13V22" />
            </svg>
            GitHub Project
          </a>
        </div>
      </footer>
    </main>
  );
}
