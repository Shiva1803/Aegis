# AI-Powered GitHub PR Review Bot -- Build Steps

> A step-by-step guide to building the full project from scratch.
> Derived from `basicinfo.docx` (spec) and `pr_review_bot_flow.svg` (data-flow diagram).

---

## Overview

The bot triggers on every PR opened or updated in a GitHub repo, fetches the code diff, sends it to an LLM (Claude / GPT-4) with a code-review prompt, and posts structured inline review comments back on the PR. It also labels PRs as `looks-good` or `needs-work`.

**Stack:** Python, FastAPI, GitHub API, Claude/OpenAI API, Railway/Render, GitHub Actions

---

## Target Directory Structure

```
pr-review-bot/
├── app/
│   ├── __init__.py
│   ├── main.py              # FastAPI app, webhook endpoint
│   ├── github_client.py     # All GitHub API calls
│   ├── review_engine.py     # LLM call + structured output
│   ├── models.py            # Pydantic schemas
│   └── config.py            # Settings from environment
├── prompts/
│   └── code_review.txt      # System prompt (separate file, easy to iterate)
├── tests/
│   ├── test_github_client.py
│   ├── test_review_engine.py
│   └── fixtures/
│       └── sample_diff.txt
├── .github/
│   └── workflows/
│       ├── ci.yml            # Tests on every PR to this repo
│       └── deploy.yml        # Deploy to Railway on merge to main
├── .env.example
├── Dockerfile
├── pyproject.toml
└── README.md
```

---

## End-to-End Data Flow

```
GitHub                    Webhook Server                  LLM API
  │                            │                            │
  │  PR opened/updated         │                            │
  │ ────── POST ──────>        │                            │
  │                     Verify HMAC signature               │
  │                     (main.py)                           │
  │                            │                            │
  │                     Idempotency check                   │
  │                     (seen this commit SHA?) ── seen ──> skip
  │                            │ new                        │
  │  <──── GET diff ────Fetch PR diff                       │
  │                     (github_client.py)                  │
  │                            │                            │
  │                     Diff size guard                     │
  │                     (truncate if > 8k tokens)           │
  │                            │                            │
  │                     Build prompt          ────────>  LLM call
  │                     (review_engine.py)              (JSON structured output)
  │                            │                            │
  │                     Parse + validate  <── ReviewResult ──┘
  │                     (Pydantic model)  ── retry once ──> (on parse failure)
  │                            │                            │
  │  <───────────────── Post comments + label               │
  │                     (github_client.py)                  │
  │                            │                            │
  │  PR comments posted        │                     Log token usage
  │  label applied             │                     (cost per PR)
```

---

## Step 0: Project Scaffolding & Environment

- [ ] Create the directory structure shown above
- [ ] Initialize `pyproject.toml` with dependencies:
  - `fastapi`, `uvicorn`
  - `httpx` (async HTTP client for GitHub API)
  - `pydantic` and `pydantic-settings`
  - `anthropic` and/or `openai` (LLM SDK)
  - `pyjwt` + `cryptography` (for GitHub App auth)
  - `pytest`, `pytest-asyncio` (dev dependencies)
- [ ] Create `.env.example` with required env vars:
  ```
  GITHUB_WEBHOOK_SECRET=
  GITHUB_APP_ID=
  GITHUB_PRIVATE_KEY_PATH=
  GITHUB_INSTALLATION_ID=
  LLM_API_KEY=
  LLM_MODEL=claude-sonnet-4-20250514
  ```
- [ ] Install dependencies (`uv sync` or `pip install -e ".[dev]"`)

---

## Step 1: Pydantic Data Models (`app/models.py`)

- [ ] Define `CommentThread` model:
  ```python
  class CommentThread(BaseModel):
      file: str                                           # e.g. "src/auth/login.py"
      line: int                                           # line number in the NEW file
      severity: Literal["critical", "suggestion", "nit"]
      category: Literal["security", "logic", "style", "performance"]
      body: str
  ```
- [ ] Define `ReviewResult` model:
  ```python
  class ReviewResult(BaseModel):
      verdict: Literal["looks-good", "needs-work"]
      summary: str
      comments: list[CommentThread]
  ```
- [ ] These schemas serve a dual purpose: validating the LLM's JSON output and defining the contract between the review engine and the GitHub client.

---

## Step 2: Configuration (`app/config.py`)

- [ ] Create a `Settings` class using `pydantic-settings` to load env vars:
  - `GITHUB_WEBHOOK_SECRET`
  - `GITHUB_APP_ID`, `GITHUB_PRIVATE_KEY_PATH`, `GITHUB_INSTALLATION_ID`
  - `LLM_API_KEY`, `LLM_MODEL`
  - `DIFF_TOKEN_LIMIT` (default: 8000)
- [ ] Expose a singleton `settings = Settings()` for import

---

## Step 3: GitHub App Authentication (`app/github_client.py` -- auth section)

- [ ] Implement `get_installation_token()`:
  1. Sign a JWT with the app's private key (`iat`, `exp`, `iss`)
  2. Exchange JWT for an installation access token via `POST /app/installations/{id}/access_tokens`
  3. Cache the token and refresh before expiry (tokens are valid for 1 hour)
- [ ] Use a GitHub App instead of a PAT -- the app has its own identity, scoped permissions, and auto-rotating tokens
- [ ] Store the private key PEM file securely (never commit it)

---

## Step 4: Webhook Endpoint & Signature Verification (`app/main.py`)

- [ ] Create FastAPI app with a single `POST /webhook` endpoint
- [ ] **HMAC-SHA256 signature verification** (first thing to implement, before any review logic):
  - Read `X-Hub-Signature-256` header
  - Compute `HMAC-SHA256(secret, raw_body)` and compare using `hmac.compare_digest`
  - Return `403` immediately if the signature is invalid
- [ ] Parse the `X-GitHub-Event` header -- only process `pull_request` events with action `opened` or `synchronize`
- [ ] Extract `owner`, `repo`, `pull_number`, and `head.sha` from the payload
- [ ] Hand off to the review pipeline (Steps 5-9)

---

## Step 5: Idempotency Check

- [ ] Before calling the LLM, check if this `commit_sha + pr_number` has already been reviewed
- [ ] Store seen IDs in one of:
  - An in-memory `set` (simplest, lost on restart)
  - A SQLite table (persistent, single-file)
  - Redis (if you already have it)
- [ ] If already seen, return early -- do NOT call the LLM again
- [ ] This prevents double-posting when GitHub resends a webhook (which it does when your server responds slowly)

---

## Step 6: Fetch the PR Diff (`app/github_client.py` -- diff section)

- [ ] Call `GET /repos/{owner}/{repo}/pulls/{pull_number}` with the `Accept: application/vnd.github.v3.diff` header to get the raw unified diff
- [ ] Implement `annotate_diff(raw_diff)` to prepend each diff line with its new-file line number:
  ```
  [L42] +    new_code_here()
  [L43]      context_line()
  ```
- [ ] This is critical -- the LLM needs these line numbers to produce accurate inline comments, and GitHub's API only accepts line numbers that exist in the diff

---

## Step 7: Diff Size Guard

- [ ] Count tokens in the annotated diff (use a simple heuristic or `tiktoken`)
- [ ] If diff exceeds `DIFF_TOKEN_LIMIT` (~8,000 tokens):
  - Truncate to the most important hunks
  - Post a fallback comment on the PR: "This PR is too large for automated review. Please consider breaking it into smaller PRs."
  - Skip the LLM call
- [ ] This prevents runaway costs and typically produces better reviews anyway

---

## Step 8: Build Prompt & Call LLM (`app/review_engine.py`)

- [ ] Load the system prompt from `prompts/code_review.txt` (kept separate for fast iteration)
- [ ] Construct the user message with the annotated diff
- [ ] In the prompt, instruct the model:
  - "When referencing a line, use the `[L{n}]` number shown in the diff"
  - "Only comment on lines that have a line number label"
  - "Return your review as JSON matching the ReviewResult schema"
- [ ] Call the LLM API (Claude or OpenAI) with **structured output / JSON mode**
- [ ] **Log token usage** from the response (`usage.input_tokens`, `usage.output_tokens`) for cost tracking

---

## Step 9: Parse & Validate LLM Response

- [ ] Parse the LLM's JSON response into a `ReviewResult` Pydantic model
- [ ] If parsing fails (malformed JSON, missing fields):
  - **Retry once** with a stricter prompt
  - If it fails again, create a minimal fallback `ReviewResult` with just a summary: "Review generation failed -- see logs"
- [ ] Never silently fail -- silent failures on GitHub PRs are invisible and confusing

---

## Step 10: Post Review to GitHub (`app/github_client.py` -- posting section)

- [ ] Use `POST /repos/{owner}/{repo}/pulls/{pull_number}/reviews` (NOT the issues endpoint):
  - `commit_id`: HEAD commit SHA of the PR
  - `body`: the review summary
  - `event`: `"APPROVE"` if verdict is `looks-good`, else `"REQUEST_CHANGES"`
  - `comments`: array of inline comments with `path`, `line`, `side: "RIGHT"`, and `body`
- [ ] Format each comment with severity emoji and category:
  ```
  🚨 **Security**
  
  SQL injection risk -- use parameterized queries.
  ```
- [ ] **Handle the 422 gracefully**: if GitHub rejects inline comments (bad line numbers), fall back to posting just the summary without inline comments
- [ ] Batch all comments into a single review submission -- do NOT make one API call per comment

---

## Step 11: Set PR Labels

- [ ] Use `POST /repos/{owner}/{repo}/issues/{issue_number}/labels` to apply `looks-good` or `needs-work`
- [ ] Before applying, remove old bot labels (`looks-good`, `needs-work`) via `DELETE`
- [ ] Pre-create the labels in the repo (green for `looks-good`, red for `needs-work`) either manually or with a setup script

---

## Step 12: Rate Limiting

- [ ] Implement a simple rate limiter per repo
- [ ] If a developer pushes 10 commits in a minute, you don't want 10 LLM calls
- [ ] Use an in-memory counter (or Redis) with a cooldown window
- [ ] When rate-limited, skip the review or queue it for later

---

## Step 13: Cost Logging

- [ ] Log `input_tokens` and `output_tokens` from every LLM response
- [ ] Calculate cost per PR based on the model's pricing
- [ ] Store in a log file, SQLite, or observability platform
- [ ] You want to know whether a large PR costs $0.002 or $0.08 before you've run it on 500 PRs

---

## Step 14: System Prompt (`prompts/code_review.txt`)

- [ ] Write the code review system prompt covering:
  - What to look for: security issues, logic bugs, style violations, performance problems
  - How to classify severity (`critical`, `suggestion`, `nit`)
  - Output format instructions (JSON matching `ReviewResult`)
  - Line number referencing rules (use `[L{n}]` labels from the diff)
- [ ] Keep this as a plain text file, NOT a string in Python -- you will iterate on it constantly

---

## Step 15: Tests

- [ ] `tests/fixtures/sample_diff.txt` -- a real diff to test against locally
- [ ] `test_review_engine.py`:
  - Test prompt construction
  - Test parsing valid and malformed LLM responses
  - Test the retry/fallback logic
- [ ] `test_github_client.py`:
  - Mock the GitHub API
  - Test signature verification with valid/invalid signatures
  - Test diff annotation with various hunk formats
  - Test 422 fallback behavior
- [ ] Run with `pytest`

---

## Step 16: Dockerfile

- [ ] Create a `Dockerfile` for deployment:
  ```dockerfile
  FROM python:3.12-slim
  WORKDIR /app
  COPY pyproject.toml .
  RUN pip install .
  COPY . .
  CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
  ```
- [ ] Keep the image minimal -- no dev dependencies in production

---

## Step 17: CI/CD with GitHub Actions

- [ ] `.github/workflows/ci.yml`:
  - Trigger on PRs to the bot's own repo
  - Install dependencies, run `pytest`
  - Lint with `ruff` or `flake8`
- [ ] `.github/workflows/deploy.yml`:
  - Trigger on merge to `main`
  - Build Docker image and deploy to Railway/Render
  - Set environment variables via the platform's secrets

---

## Step 18: Deployment & GitHub App Setup

- [ ] **Register a GitHub App** (not a PAT) at `github.com/settings/apps`:
  - Permissions: `pull_requests: write`, `issues: write`, `contents: read`
  - Subscribe to events: `pull_request`
  - Set the webhook URL to your deployed server's `/webhook` endpoint
  - Generate and download the private key
- [ ] Deploy the FastAPI server to Railway, Render, or AWS Lambda
- [ ] Set all environment variables on the deployment platform
- [ ] Install the GitHub App on the target repo(s)
- [ ] Open a test PR and verify the bot posts a review

---

## Step 19: Polish & Hardening

- [ ] Add structured logging (JSON logs for production)
- [ ] Add health check endpoint (`GET /health`)
- [ ] Handle edge cases:
  - Draft PRs (skip or review?)
  - PRs with no code changes (only markdown, config, etc.)
  - PRs by the bot itself (avoid infinite loops)
- [ ] Add a `.prreviewignore` or config file for users to exclude paths
- [ ] Write the `README.md` with setup instructions

---

## Execution Order Summary

| Phase | Steps | What You'll Have |
|-------|-------|------------------|
| **Foundation** | 0-2 | Scaffolding, models, config |
| **Auth & Webhook** | 3-4 | Secure webhook receiving events |
| **Core Pipeline** | 5-9 | Diff -> LLM -> structured review |
| **Post Back** | 10-11 | Comments + labels on the PR |
| **Guardrails** | 12-13 | Rate limiting, cost tracking |
| **Prompt** | 14 | Tuned review prompt |
| **Quality** | 15-16 | Tests, Docker |
| **Ship** | 17-18 | CI/CD, deployment, GitHub App |
| **Harden** | 19 | Production-ready polish |
