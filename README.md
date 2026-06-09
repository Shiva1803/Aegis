# PR Review Bot

AI-powered GitHub PR code review bot that automatically reviews pull requests using AI Models (Claude, Gemini, GPT etc.)

## What It Does

- Triggers on every PR opened or updated in your GitHub repo
- Fetches the code diff via the GitHub API
- Sends the diff to an LLM with a structured code review prompt
- Posts categorized inline review comments back on the PR
- Labels PRs as `looks-good` or `needs-work`

## Stack involved

Python, FastAPI, GitHub API, Claude/OpenAI/Groq/Gemini APIs, Railway, GitHub Actions

## Quick Start

### 1. Clone and install

```bash
git clone <your-repo-url>
cd pr-review-bot
pip install -e ".[dev]"
```

### 2. Configure environment

```bash
cp .env.example .env
# Fill in your secrets in .env
```

### 3. Run tests

```bash
pytest -v
```

### 4. Run locally

```bash
uvicorn app.main:app --reload --port 8000
```

### 5. Set up GitHub App

1. Go to **github.com/settings/apps** and create a new GitHub App
2. Set permissions: `pull_requests: write`, `issues: write`, `contents: read`
3. Subscribe to events: `pull_request`
4. Set webhook URL to your deployed server's `/webhook` endpoint
5. Generate and download the private key
6. Install the app on your target repo(s)

### 6. Create repo labels

Create two labels in your repo:
- `looks-good` (green)
- `needs-work` (red)

## Project Structure

```
app/
  main.py            — Webhook endpoint + pipeline orchestration
  github_client.py   — GitHub API calls (auth, diff, reviews, labels)
  review_engine.py   — LLM integration + structured output
  models.py          — Pydantic data schemas
  config.py          — Environment settings
prompts/
  code_review.txt    — System prompt (edit this to tune reviews)
tests/               — Test suite
```

## Environment Variables

| Variable | Description |
|----------|-------------|
| `GITHUB_WEBHOOK_SECRET` | Secret for HMAC webhook verification |
| `GITHUB_APP_ID` | Your GitHub App's ID |
| `GITHUB_PRIVATE_KEY_PATH` | Path to the App's private key PEM |
| `GITHUB_INSTALLATION_ID` | Installation ID for your org/repo |
| `LLM_PROVIDER` | `anthropic`, `openai`, `groq`, `gemini`, or `nvidia_nim` |
| `LLM_API_KEY` | API key (or comma-separated keys for roulette) |
| `LLM_MODEL` | Model name (see table below) |
| `NVIDIA_NIM_BASE_URL` | NVIDIA NIM OpenAI-compatible base URL (default `https://integrate.api.nvidia.com/v1`) |
| `NVIDIA_NIM_DISABLE_THINKING` | Set `true` to send `chat_template_kwargs.thinking=false` for compatible NIM models |
| `KEY_ROULETTE_ENABLED` | `true` to enable round-robin key rotation |
| `DIFF_TOKEN_LIMIT` | Max tokens for diff (default: 8000) |
| `GITHUB_OAUTH_CLIENT_ID` | GitHub OAuth app client ID for dashboard login |
| `GITHUB_OAUTH_CLIENT_SECRET` | GitHub OAuth app client secret for dashboard login |
| `GITHUB_OAUTH_REDIRECT_URI` | OAuth callback URL (default `http://127.0.0.1:8000/auth/github/callback`) |
| `DASHBOARD_ADMIN_USERS` | Comma-separated GitHub usernames that can edit config |

## Supported Providers & Models

| Provider | Example Models | Notes |
|----------|---------------|-------|
| `anthropic` | `claude-sonnet-4-20250514` | Best quality reviews |
| `openai` | `gpt-4o` | JSON mode built-in |
| `groq` | `llama-3.3-70b-versatile`, `mixtral-8x7b-32768` | Fastest inference, lowest cost |
| `gemini` | `gemini-2.5-flash`, `gemini-2.5-pro` | Google AI, generous free tier |
| `nvidia_nim` | `deepseek-ai/deepseek-v4-pro` | OpenAI-compatible NVIDIA NIM endpoint |

## Key Roulette (Optional)

Distribute API calls across multiple keys to avoid rate limits:

```bash
# In your .env
KEY_ROULETTE_ENABLED=true
LLM_API_KEY=sk-key-1,sk-key-2,sk-key-3
```

The bot cycles through keys round-robin on each LLM call. Useful when:
- You have multiple free-tier keys (e.g. Groq, Gemini)
- You want to distribute rate limits across team members' keys
- You're running high-volume reviews

## License

MIT

## Dashboard UI (Web App)

A React/Vite dashboard is included in `dashboard/`.

### Run locally

1. Start API server:
   ```bash
   uvicorn app.main:app --reload --port 8000
   ```
2. Start dashboard:
   ```bash
   cd dashboard
   npm install
   npm run dev
   ```

The Vite dev server proxies `/api/*` calls to `http://localhost:8000`.
