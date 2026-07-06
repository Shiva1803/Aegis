import { Suspense, lazy, useEffect, useMemo, useRef, useState } from "react";
import { api } from "./lib/api";
import type { AuditEntry, AuthStatus, ConfigView, CostSummary, ReviewDetail, ReviewFeedItem, WebhookLog } from "./lib/types";

type TabKey = "feed" | "detail" | "config" | "cost" | "webhooks" | "about" | "privacy";

const tabs: Array<{ key: TabKey; label: string }> = [
  { key: "feed", label: "Live Feed" },
  { key: "detail", label: "Review Detail" },
  { key: "config", label: "Configuration" },
  { key: "cost", label: "Cost" },
  { key: "webhooks", label: "Webhooks" }
];

const ShaderGradientCanvas = lazy(() =>
  import("@shadergradient/react").then((module) => ({ default: module.ShaderGradientCanvas }))
);
const ShaderGradient = lazy(() =>
  import("@shadergradient/react").then((module) => ({ default: module.ShaderGradient }))
);

const TAB_TITLES: Record<TabKey, string> = {
  feed: "Live Review Feed",
  detail: "Review Detail",
  config: "Configuration",
  cost: "Cost Tracker",
  webhooks: "Webhook Logs",
  about: "About Aegis",
  privacy: "Privacy & Terms"
};

const PROVIDER_MODELS: Record<string, string[]> = {
  nvidia_nim: ["deepseek-ai/deepseek-v4-pro", "deepseek-ai/deepseek-r1", "meta/llama-3.1-405b-instruct"],
  groq: ["llama-3.3-70b-versatile", "llama-3.1-8b-instant", "mixtral-8x7b-32768", "gemma2-9b-it"],
  openai: ["gpt-4o", "gpt-4o-mini", "o3-mini", "o1-mini"],
  anthropic: ["claude-sonnet-4-20250514", "claude-3-haiku-20240307", "claude-3-5-sonnet-20241022"],
  gemini: ["gemini-2.5-pro", "gemini-2.0-flash", "gemini-2.5-flash", "gemini-1.5-pro"]
};

const ROUTING_BADGE_LABELS: Record<ReviewFeedItem["routing_tier"], string> = {
  lightweight: "Lightweight",
  standard: "Standard",
  reasoning: "Reasoning"
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
  const [showDiagnostics, setShowDiagnostics] = useState(false);
  const lowerHalfRef = useRef<HTMLElement | null>(null);

  const [repoList, setRepoList] = useState<string[]>([]);
  const [filter, setFilter] = useState(""); // e.g. "org:name" or "repo:name/repo"

  const orgs = useMemo(() => {
    const list = repoList.map((r) => r.split("/")[0]);
    return Array.from(new Set(list));
  }, [repoList]);

  const [lastDashboardTab, setLastDashboardTab] = useState<TabKey>("feed");

  useEffect(() => {
    if (activeTab !== "about" && activeTab !== "privacy") {
      setLastDashboardTab(activeTab);
    }
  }, [activeTab]);

  useEffect(() => {
    let cancelled = false;

    let filterParams: { repo?: string; org?: string } = {};
    if (filter.startsWith("org:")) {
      filterParams = { org: filter.slice(4) };
    } else if (filter.startsWith("repo:")) {
      filterParams = { repo: filter.slice(5) };
    }

    const load = async () => {
      try {
        const [r, c, s, w, a, authStatus, repos] = await Promise.all([
          api.getReviews(filterParams),
          api.getConfig(),
          api.getCost(filterParams),
          api.getWebhooks(filterParams),
          api.getAudit(),
          api.getAuthStatus(),
          api.getRepositories()
        ]);
        if (cancelled) return;

        setLoadError("");
        setReviews(r);
        setConfig(c);
        setCost(s);
        setWebhooks(w);
        setAudit(a);
        setAuth(authStatus);
        setRepoList(repos);
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
  }, [filter]);

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
  const isInfoPage = activeTab === "about" || activeTab === "privacy";
  const shaderGradientProps = {
    animate: "on",
    axesHelper: "off",
    bgColor1: "#000000",
    bgColor2: "#000000",
    brightness: 1.2,
    cAzimuthAngle: 180,
    cDistance: 2.9,
    cPolarAngle: 120,
    cameraZoom: 1,
    color1: "#0f172d",
    color2: "#1f3f63",
    color3: "#6faed8",
    destination: "onCanvas",
    embedMode: "off",
    envPreset: "city",
    format: "gif",
    fov: 20,
    frameRate: 10,
    gizmoHelper: "hide",
    grain: "off",
    lightType: "3d",
    pixelDensity: 1,
    positionX: 0,
    positionY: 1.8,
    positionZ: 0,
    range: "disabled",
    rangeEnd: 40,
    rangeStart: 0,
    reflection: 0.1,
    rotationX: 0,
    rotationY: 0,
    rotationZ: -90,
    shader: "defaults",
    type: "waterPlane",
    uAmplitude: 0,
    uDensity: 1,
    uFrequency: 5.5,
    uSpeed: 0.1,
    uStrength: 3,
    uTime: 0.2,
    wireframe: false
  } as const;

  useEffect(() => {
    if (!isInfoPage) return;
    window.scrollTo({ top: 0, behavior: "smooth" });
  }, [activeTab, isInfoPage]);

  const scrollToLower = () => {
    lowerHalfRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
  };

  const renderVideoBackdrop = () => (
    <>
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
    </>
  );

  const renderHeader = () => (
    <header className="top-nav">
      <div className="top-nav-left">
        <div className="logo-container">
          <img src="/Gemini_Generated_Image_fxx9lqfxx9lqfxx9.png" alt="Aegis Logo" className="logo-img" />
          <span className="logo-text">Aegis</span>
          <span className="logo-version">v2.1</span>
        </div>
        {!isInfoPage && (
          <div className="filter-container">
            <select className="filter-select" value={filter} onChange={(e) => setFilter(e.target.value)}>
              <option value="">All Repositories</option>
              {orgs.length > 0 && (
                <optgroup label="Organizations">
                  {orgs.map(org => (
                    <option key={org} value={`org:${org}`}>{org}</option>
                  ))}
                </optgroup>
              )}
              {repoList.length > 0 && (
                <optgroup label="Repositories">
                  {repoList.map(r => (
                    <option key={r} value={`repo:${r}`}>{r.split("/")[1] || r}</option>
                  ))}
                </optgroup>
              )}
            </select>
          </div>
        )}
      </div>

      <div className="top-nav-middle">
        {!isInfoPage ? (
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
        ) : (
          <button
            type="button"
            className="pill active back-home-nav-btn"
            onClick={() => setActiveTab(lastDashboardTab)}
          >
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" className="back-icon-mini">
              <line x1="19" y1="12" x2="5" y2="12" />
              <polyline points="12 19 5 12 12 5" />
            </svg>
            Back to Home
          </button>
        )}
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
  );

  const renderFooter = () => (
    <footer className="hero-footer">
      <div className="footer-left">
        <a href="#" onClick={(event) => { event.preventDefault(); setActiveTab("about"); }} className="about-link">
          <svg className="menu-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <circle cx="12" cy="12" r="10" />
            <line x1="12" y1="16" x2="12" y2="12" />
            <line x1="12" y1="8" x2="12.01" y2="8" />
          </svg>
          About Aegis
        </a>
        <span className="footer-separator">|</span>
        <a href="#" onClick={(event) => { event.preventDefault(); setActiveTab("privacy"); }} className="about-link">
          <svg className="menu-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <rect x="3" y="11" width="18" height="11" rx="2" ry="2" />
            <path d="M7 11V7a5 5 0 0 1 10 0v4" />
          </svg>
          Privacy & Terms
        </a>
      </div>
      <div className="footer-right">
        <span>Built by <a href="https://shivanshtripathi.vercel.app" target="_blank" rel="noreferrer">Shivansh Tripathi</a></span>
        <span className="footer-separator">|</span>
        <a href="https://github.com/Shiva1803/Aegis" target="_blank" rel="noreferrer" title="GitHub Project" aria-label="GitHub Project">
          <svg className="menu-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M9 19c-5 1.5-5-2.5-7-3m14 6v-3.87a3.37 3.37 0 0 0-.94-2.61c3.14-.35 6.44-1.54 6.44-7A5.44 5.44 0 0 0 20 4.77 5.07 5.07 0 0 0 19.91 1S18.73.65 16 2.48a13.38 13.38 0 0 0-7 0C6.27.65 5.09 1 5.09 1A5.07 5.07 0 0 0 5 4.77a5.44 5.44 0 0 0-1.5 3.78c0 5.42 3.3 6.61 6.44 7A3.37 3.37 0 0 0 9 18.13V22" />
          </svg>
        </a>
      </div>
    </footer>
  );

  return (
    <main className={`hero-root ${isInfoPage ? "info-page-root" : "dashboard-root"}`}>
      {renderHeader()}

      {isInfoPage ? (
        <section className="page-shell">
          {renderVideoBackdrop()}
          <div className="page-body">
            <section className="hero-copy info-hero-copy">
              <h1 className="tab-title">{TAB_TITLES[activeTab]}</h1>
            </section>
            <section className="glass-stage">
              {activeTab === "about" && (
                <div className="panel about-panel">
                  <div className="about-section">
                    <h2 className="about-heading">What is Aegis?</h2>
                    <p className="about-paragraph">
                      Aegis is an intelligent, cinematic code review command center designed to bring deep AI synthesis and telemetry to modern software workflows. By bridging the gap between automated repository operations and large language models, Aegis acts as a persistent watchdog, ensuring that every code change is thoroughly inspected, documented, and scored before reaching your main production branches.
                    </p>
                  </div>

                  <div className="about-section">
                    <h2 className="about-heading">Key Capabilities</h2>
                    <p className="about-paragraph">
                      Aegis monitors incoming webhook payloads from GitHub for pull request activity. Upon receipt, it performs semantic analysis on the code diff using your designated LLM provider. The engine automatically identifies bugs, style violations, security issues, and architectural concerns, generating formatted markdown comments directly back to the pull request in real time.
                    </p>
                  </div>

                  <div className="about-section">
                    <h2 className="about-heading">Telemetry & Control</h2>
                    <p className="about-paragraph">
                      Managing AI usage at scale requires precision. Aegis provides full token cost tracking and telemetry over a rolling seven-day window, giving engineering teams transparent visibility into API expenditures. Additionally, features like Key Roulette distribute API load across multiple backup keys, ensuring high availability and robust rate limits.
                    </p>
                  </div>

                  <div className="about-section">
                    <h2 className="about-heading">Getting Started</h2>
                    <p className="about-paragraph">
                      To activate automated code reviews, configure your GitHub App or Repository settings to send Webhook deliveries to the Aegis server gateway URL. Ensure you have provided a valid API key for your chosen provider (NVIDIA NIM, Groq, OpenAI, Anthropic, or Gemini) in the Configuration panel. Once set up, Aegis will handle the rest autonomously.
                    </p>
                    <div className="about-meta-info">
                      <div>Aegis: v 2.1</div>
                      <div>Last updated: 6 Jul 2026</div>
                    </div>
                  </div>
                </div>
              )}
              {activeTab === "privacy" && (
                <div className="panel about-panel">
                  <div className="about-section">
                    <h2 className="about-heading">Data Collection & Usage</h2>
                    <p className="about-paragraph">
                      Aegis requests access scopes for your public and private GitHub repositories solely to fetch commit diffs and publish automated code review feedback. We do not permanently copy, store, index, or sell your source code. Code diffs are held in-memory temporarily during analysis and immediately discarded.
                    </p>
                  </div>

                  <div className="about-section">
                    <h2 className="about-heading">API Key & Telemetry Security</h2>
                    <p className="about-paragraph">
                      All configured API keys and parameters are stored securely on your server instance and encrypted at rest. Telemetry tracking details, such as cost estimation charts, token usage metrics, and webhook response histories, are processed and recorded locally on your private backend database.
                    </p>
                  </div>

                  <div className="about-section">
                    <h2 className="about-heading">Third-Party AI Services</h2>
                    <p className="about-paragraph">
                      Aegis relays pull request diff payloads to the third-party Large Language Model API providers (NVIDIA NIM, Groq, OpenAI, Anthropic, or Google Gemini) according to your selected configuration. These payloads are subject to the respective providers' data privacy terms; they are not used for public model training.
                    </p>
                  </div>

                  <div className="about-section">
                    <h2 className="about-heading">Hosting & Terms</h2>
                    <p className="about-paragraph">
                      Aegis is provided as open-source software under the MIT License as-is. By connecting your GitHub account, you are responsible for maintaining compliance with your organization's internal security policies, intellectual property guidelines, and local data residency standards.
                    </p>
                  </div>
                </div>
              )}
            </section>
          </div>
          {renderFooter()}
        </section>
      ) : (
        <>
          <section className="upper-half">
            {renderVideoBackdrop()}
            <section className="hero-copy">
              <h1>Supercharged PR Intelligence</h1>
              <p>Aegis helps you automate code reviews, configure model behaviors, monitor token expenditures, and inspect system health in one cinematic console.</p>
              <button type="button" className="scroll-down-btn" onClick={scrollToLower}>
                scroll down
              </button>
            </section>
            <div className="fade-layer" />
          </section>

          <section className="lower-half" ref={lowerHalfRef}>
            <div className="shader-fallback" />
            <div className="shader-bg" aria-hidden="true">
              <Suspense fallback={null}>
                <ShaderGradientCanvas
                  className="shader-canvas"
                  style={{ width: "100%", height: "100%" }}
                  pixelDensity={1}
                  fov={20}
                  pointerEvents="none"
                >
                  <ShaderGradient {...(shaderGradientProps as any)} />
                </ShaderGradientCanvas>
              </Suspense>
            </div>
            <div className="lower-half-content">
              <h2 className="section-title">{TAB_TITLES[activeTab]}</h2>
              {config && config.monthly_budget_cap > 0 && config.current_month_spend >= config.monthly_budget_cap && (
                <div className="budget-alert-banner">
                  <div className="budget-alert-content">
                    <svg className="budget-alert-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                      <polygon points="7.86 2 16.14 2 22 7.86 22 16.14 16.14 22 7.86 22 2 16.14 2 7.86 7.86 2" />
                      <line x1="12" y1="8" x2="12" y2="12" />
                      <line x1="12" y1="16" x2="12.01" y2="16" />
                    </svg>
                    <div className="budget-alert-text">
                      <span className="budget-alert-title">Monthly Budget Cap Exceeded</span>
                      <span className="budget-alert-desc">
                        Aegis has temporarily paused automated reviews because current MTD spend is <strong>${config.current_month_spend.toFixed(2)}</strong>, exceeding your configured budget cap of <strong>${config.monthly_budget_cap.toFixed(2)}</strong>.
                      </span>
                    </div>
                  </div>
                  {activeTab !== "config" && (
                    <button
                      type="button"
                      className="budget-alert-action-btn"
                      onClick={() => setActiveTab("config")}
                    >
                      Adjust Budget
                    </button>
                  )}
                </div>
              )}
              <section className="glass-stage">
                {activeTab === "feed" && (
                  <div className="panel">

                    {loadError && auth.authenticated && (
                      <div className="diagnostics-card">
                        <div className="diagnostics-summary">
                          <div className="diagnostics-title">
                            <svg className="diagnostics-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                              <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z" />
                              <line x1="12" y1="9" x2="12" y2="13" />
                              <line x1="12" y1="17" x2="12.01" y2="17" />
                            </svg>
                            <span>Connection Sync Interrupted</span>
                          </div>
                          <p className="diagnostics-message">
                            Unable to establish a secure data stream with the Aegis backend telemetry services. Please verify that your backend server is running and reachable.
                          </p>
                          <button
                            className="diagnostics-toggle-btn"
                            onClick={() => setShowDiagnostics(!showDiagnostics)}
                          >
                            {showDiagnostics ? "Hide Diagnostics Details" : "Show Diagnostics Details"}
                          </button>
                        </div>
                        {showDiagnostics && (
                          <div className="diagnostics-details">
                            <code>{loadError}</code>
                          </div>
                        )}
                      </div>
                    )}

                    <div className="stack">
                      {reviews.length === 0 ? (
                        <div className="empty-feed-card">
                          {!auth.authenticated ? (
                            <div className="connect-prompt-container">
                              <div className="empty-feed-icon-wrapper">
                                <svg className="empty-feed-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
                                  <path d="M9 19c-5 1.5-5-2.5-7-3m14 6v-3.87a3.37 3.37 0 0 0-.94-2.61c3.14-.35 6.44-1.54 6.44-7A5.44 5.44 0 0 0 20 4.77 5.07 5.07 0 0 0 19.91 1S18.73.65 16 2.48a13.38 13.38 0 0 0-7 0C6.27.65 5.09 1 5.09 1A5.07 5.07 0 0 0 5 4.77a5.44 5.44 0 0 0-1.5 3.78c0 5.42 3.3 6.61 6.44 7A3.37 3.37 0 0 0 9 18.13V22" />
                                </svg>
                              </div>
                              <h3>Ready to review your code?</h3>
                              <p className="empty-feed-description">
                                Connect your GitHub to begin the services!
                              </p>
                              <a className="connect-btn" href={`${import.meta.env.VITE_API_URL || ""}/auth/github/login`}>
                                Connect GitHub
                              </a>
                            </div>
                          ) : (
                            <div className="waiting-prompt-container">
                              <div className="empty-feed-icon-wrapper pulse-animation">
                                <svg className="empty-feed-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
                                  <circle cx="12" cy="12" r="10" />
                                  <polyline points="12 6 12 12 16 14" />
                                </svg>
                              </div>
                              <h3>Awaiting Pull Request Events</h3>
                              <p className="empty-feed-description">
                                Aegis is successfully connected and listening for events. This feed will populate automatically once the backend processes a GitHub pull request webhook.
                              </p>
                              <div className="help-steps">
                                <div className="step-item">
                                  <span className="step-number">1</span>
                                  <span className="step-text">Configure a webhook in GitHub pointing to your Aegis endpoint.</span>
                                </div>
                                <div className="step-item">
                                  <span className="step-number">2</span>
                                  <span className="step-text">Trigger a webhook by opening or synchronizing a pull request.</span>
                                </div>
                                <div className="step-item">
                                  <span className="step-number">3</span>
                                  <span className="step-text">Watch Aegis scan, score, and stream the review back to your console.</span>
                                </div>
                              </div>
                            </div>
                          )}
                        </div>
                      ) : null}

                      {reviews.map((review) => (
                        <button key={review.id} className="row" onClick={() => { setSelectedReviewId(review.id); setActiveTab("detail"); }}>
                          <div>
                            <strong>{review.repo} #{review.pr_number}</strong>
                            <p>{review.summary}</p>
                            <span className="feed-routing-chip">{ROUTING_BADGE_LABELS[review.routing_tier]} route</span>
                          </div>
                          <span className={`status ${review.verdict}`}>{review.verdict}</span>
                        </button>
                      ))}
                    </div>
                  </div>
                )}

                {activeTab === "detail" && (
                  <div className="panel review-detail-panel">
                    {detail ? (
                      <>
                        <h2 className="detail-page-title">Review Detail View</h2>
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
                            <span>Tier <strong className="ai-tag">{ROUTING_BADGE_LABELS[detail.routing_tier]}</strong></span>
                            <span className="divider">|</span>
                            <span>{detail.comments_count} {detail.comments_count === 1 ? "comment" : "comments"}</span>
                          </div>
                          <p className="routing-reason-text">{detail.routing_reason}</p>
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
                      <div className="empty-feed-card">
                        {!auth.authenticated ? (
                          <div className="connect-prompt-container">
                            <div className="empty-feed-icon-wrapper">
                              <svg className="empty-feed-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
                                <path d="M9 19c-5 1.5-5-2.5-7-3m14 6v-3.87a3.37 3.37 0 0 0-.94-2.61c3.14-.35 6.44-1.54 6.44-7A5.44 5.44 0 0 0 20 4.77 5.07 5.07 0 0 0 19.91 1S18.73.65 16 2.48a13.38 13.38 0 0 0-7 0C6.27.65 5.09 1 5.09 1A5.07 5.07 0 0 0 5 4.77a5.44 5.44 0 0 0-1.5 3.78c0 5.42 3.3 6.61 6.44 7A3.37 3.37 0 0 0 9 18.13V22" />
                              </svg>
                            </div>
                            <h3>Ready to review your code?</h3>
                            <p className="empty-feed-description">
                              Connect your GitHub to begin the services!
                            </p>
                            <a className="connect-btn" href={`${import.meta.env.VITE_API_URL || ""}/auth/github/login`}>
                              Connect GitHub
                            </a>
                          </div>
                        ) : (
                          <div className="waiting-prompt-container">
                            <div className="empty-feed-icon-wrapper pulse-animation">
                              <svg className="empty-feed-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
                                <circle cx="12" cy="12" r="10" />
                                <polyline points="12 6 12 12 16 14" />
                              </svg>
                            </div>
                            <h3>Awaiting Pull Request Events</h3>
                            <p className="empty-feed-description">
                              Aegis is successfully connected and listening for events. Review details will appear here once a pull request has been reviewed.
                            </p>
                            <div className="help-steps">
                              <div className="step-item">
                                <span className="step-number">1</span>
                                <span className="step-text">Configure a webhook in GitHub pointing to your Aegis endpoint.</span>
                              </div>
                              <div className="step-item">
                                <span className="step-number">2</span>
                                <span className="step-text">Trigger a webhook by opening or synchronizing a pull request.</span>
                              </div>
                              <div className="step-item">
                                <span className="step-number">3</span>
                                <span className="step-text">Watch Aegis scan, score, and stream the review back to your console.</span>
                              </div>
                            </div>
                          </div>
                        )}
                      </div>
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
                            const updatePayload = {
                              llm_provider: config.llm_provider,
                              llm_model: config.llm_model,
                              key_roulette_enabled: config.key_roulette_enabled,
                              model_auto_routing_enabled: config.model_auto_routing_enabled,
                              auto_route_simple_model: config.auto_route_simple_model,
                              auto_route_complex_model: config.auto_route_complex_model,
                              key_failure_cooldown_seconds: config.key_failure_cooldown_seconds,
                              diff_token_limit: config.diff_token_limit,
                              rate_limit_window_seconds: config.rate_limit_window_seconds,
                              rate_limit_max_reviews: config.rate_limit_max_reviews,
                              monthly_budget_cap: config.monthly_budget_cap
                            };
                            if (apiKeyInput.trim()) {
                              Object.assign(updatePayload, { llm_api_key: apiKeyInput.trim() });
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

                      {/* Card 2: Smart Routing */}
                      <div className="config-card">
                        <h3 className="config-card-title">
                          <svg className="menu-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                            <path d="M16 3h5v5" />
                            <path d="M8 21H3v-5" />
                            <path d="M21 3l-7 7" />
                            <path d="M3 21l7-7" />
                          </svg>
                          Smart Model Routing
                        </h3>

                        <div className="config-field config-checkbox-group">
                          <div className="checkbox-with-tooltip">
                            <input
                              type="checkbox"
                              id="auto-routing-checkbox"
                              checked={config.model_auto_routing_enabled}
                              onChange={(e) => setConfig({ ...config, model_auto_routing_enabled: e.target.checked })}
                            />
                            <label htmlFor="auto-routing-checkbox" className="config-label cursor-pointer">
                              Enable Auto-Routing
                            </label>
                            <div className="tooltip-container">
                              <span className="tooltip-icon">?</span>
                              <span className="tooltip-text">
                                Lightweight reviews handle docs, typos, and formatting. Reasoning reviews are reserved for security, migrations, and core logic changes.
                              </span>
                            </div>
                          </div>
                        </div>

                        <p className="config-help-text">
                          Standard diffs continue to use the primary model. These selectors only override the lightweight and reasoning tiers when smart routing is enabled.
                        </p>

                        <div className="config-field">
                          <span className="config-label">Simple Diff Model</span>
                          <select
                            className="config-select"
                            value={config.auto_route_simple_model}
                            onChange={(e) => setConfig({ ...config, auto_route_simple_model: e.target.value })}
                          >
                            <option value="">Use provider default lightweight model</option>
                            {(PROVIDER_MODELS[config.llm_provider] || []).map((model) => (
                              <option key={`simple-${model}`} value={model}>{model}</option>
                            ))}
                          </select>
                        </div>

                        <div className="config-field">
                          <span className="config-label">Complex Diff Model</span>
                          <select
                            className="config-select"
                            value={config.auto_route_complex_model}
                            onChange={(e) => setConfig({ ...config, auto_route_complex_model: e.target.value })}
                          >
                            <option value="">Use provider default reasoning model</option>
                            {(PROVIDER_MODELS[config.llm_provider] || []).map((model) => (
                              <option key={`complex-${model}`} value={model}>{model}</option>
                            ))}
                          </select>
                        </div>
                      </div>

                      {/* Card 3: Rate Limiting & Tokens */}
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

                        <div className="config-field">
                          <span className="config-label">Monthly Budget Cap ($)</span>
                          <input
                            type="number"
                            step="0.01"
                            min="0"
                            className="config-input number-input"
                            value={config.monthly_budget_cap}
                            onChange={(e) => setConfig({ ...config, monthly_budget_cap: Number(e.target.value) })}
                          />
                        </div>

                        {config.monthly_budget_cap > 0 && (
                          <div className="budget-status-row">
                            <span className="budget-status-label">Month-to-Date Cost:</span>
                            <span className={`budget-status-value ${config.current_month_spend >= config.monthly_budget_cap ? "budget-exceeded" : ""}`}>
                              ${config.current_month_spend.toFixed(2)} / ${config.monthly_budget_cap.toFixed(2)}
                            </span>
                          </div>
                        )}
                      </div>

                      {/* Card 4: System Health & Connectivity */}
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

                        <div className="config-field">
                          <span className="config-label">Key Cooldown Window (s)</span>
                          <input
                            type="number"
                            className="config-input number-input"
                            value={config.key_failure_cooldown_seconds}
                            onChange={(e) => setConfig({ ...config, key_failure_cooldown_seconds: Number(e.target.value) })}
                          />
                        </div>
                      </div>

                      {/* Card 5: API Key Health */}
                      <div className="config-card">
                        <h3 className="config-card-title">
                          <svg className="menu-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                            <rect x="3" y="11" width="18" height="11" rx="2" ry="2" />
                            <path d="M7 11V7a5 5 0 0 1 10 0v4" />
                          </svg>
                          API Key Health
                        </h3>

                        {config.unhealthy_key_count > 0 ? (
                          <div className="diagnostics-card inline-diagnostics-card">
                            <div className="diagnostics-summary">
                              <div className="diagnostics-title">
                                <svg className="diagnostics-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                                  <path d="M12 9v4" />
                                  <path d="M12 17h.01" />
                                  <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z" />
                                </svg>
                                <span>Key Failover Active</span>
                              </div>
                              <p className="diagnostics-message">
                                {config.unhealthy_key_count} API {config.unhealthy_key_count === 1 ? "key is" : "keys are"} on cooldown. New reviews will fail over to the next healthy key automatically.
                              </p>
                            </div>
                          </div>
                        ) : null}

                        <div className="config-field">
                          <div className="key-health-summary">
                            <span>{config.active_key_count} healthy</span>
                            <span>{config.unhealthy_key_count} cooling down</span>
                          </div>
                          <div className="key-health-list">
                            {config.key_health.map((key) => (
                              <div key={key.key_suffix} className="key-health-row">
                                <div>
                                  <strong>{`••••${key.key_suffix}`}</strong>
                                  <p>
                                    {key.last_error_status
                                      ? `Last error ${key.last_error_status}${key.last_error_reason ? ` • ${key.last_error_reason}` : ""}`
                                      : "No recent failures recorded"}
                                  </p>
                                </div>
                                <div className="key-health-meta">
                                  <span className={key.status === "healthy" ? "status ok-pill" : "status warn-pill"}>
                                    {key.status === "healthy" ? "Healthy" : "Cooldown"}
                                  </span>
                                  <span className="key-health-time">
                                    {key.disabled_until ? `Until ${new Date(key.disabled_until).toLocaleTimeString()}` : `${key.failure_count} failures`}
                                  </span>
                                </div>
                              </div>
                            ))}
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
                    {webhooks.length === 0 ? (
                      <div className="empty-feed-card">
                        {!auth.authenticated ? (
                          <div className="connect-prompt-container">
                            <div className="empty-feed-icon-wrapper">
                              <svg className="empty-feed-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
                                <path d="M9 19c-5 1.5-5-2.5-7-3m14 6v-3.87a3.37 3.37 0 0 0-.94-2.61c3.14-.35 6.44-1.54 6.44-7A5.44 5.44 0 0 0 20 4.77 5.07 5.07 0 0 0 19.91 1S18.73.65 16 2.48a13.38 13.38 0 0 0-7 0C6.27.65 5.09 1 5.09 1A5.07 5.07 0 0 0 5 4.77a5.44 5.44 0 0 0-1.5 3.78c0 5.42 3.3 6.61 6.44 7A3.37 3.37 0 0 0 9 18.13V22" />
                              </svg>
                            </div>
                            <h3>Ready to review your code?</h3>
                            <p className="empty-feed-description">
                              Connect your GitHub to begin the services!
                            </p>
                            <a className="connect-btn" href={`${import.meta.env.VITE_API_URL || ""}/auth/github/login`}>
                              Connect GitHub
                            </a>
                          </div>
                        ) : (
                          <div className="waiting-prompt-container">
                            <div className="empty-feed-icon-wrapper pulse-animation">
                              <svg className="empty-feed-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
                                <circle cx="12" cy="12" r="10" />
                                <polyline points="12 6 12 12 16 14" />
                              </svg>
                            </div>
                            <h3>Awaiting Pull Request Events</h3>
                            <p className="empty-feed-description">
                              Aegis is successfully connected and listening for events. Webhook delivery logs will appear here once GitHub sends an event to your endpoint.
                            </p>
                            <div className="help-steps">
                              <div className="step-item">
                                <span className="step-number">1</span>
                                <span className="step-text">Configure a webhook in GitHub pointing to your Aegis endpoint.</span>
                              </div>
                              <div className="step-item">
                                <span className="step-number">2</span>
                                <span className="step-text">Trigger a webhook by opening or synchronizing a pull request.</span>
                              </div>
                              <div className="step-item">
                                <span className="step-number">3</span>
                                <span className="step-text">Watch Aegis scan, score, and stream the review back to your console.</span>
                              </div>
                            </div>
                          </div>
                        )}
                      </div>
                    ) : (
                      <>
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
                      </>
                    )}
                  </div>
                )}

              </section>
              {renderFooter()}
            </div>
          </section>
        </>
      )}
    </main>
  );
}
