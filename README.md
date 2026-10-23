# Darkrai - Event-Driven GitHub Automation Platform

### Live Demo: [https://darkrai-one.vercel.app/](https://darkrai-one.vercel.app/)

Darkrai is a production-grade, event-driven GitHub automation platform that ingests repository webhooks, evaluates rule-based workflows, and executes automated actions such as issue labeling, contextual comments, security alerts, and Slack notifications. The platform includes a real-time observability dashboard for monitoring event ingestion, queue lifecycle, and rule executions.

---

## ⚡ Key Capabilities 

- **Reliable Dual-Mode Processing**:
  - **Worker Queue Mode**: Durable Redis queue backing with exponential backoff retries, atomic DB event claiming (`UPDATE ... WHERE status = 'pending'`), and Dead-Letter Queue (DLQ) routing.
  - **Serverless / Inline Mode**: Instant, synchronous inline execution (`EXECUTE_INLINE=true`) optimized for serverless functions (e.g., Vercel) where background processes cannot outlive the HTTP request lifecycle.
- **Hardened Security & Isolation**:
  - **HMAC-SHA256 Raw Verification**: GitHub webhooks verified over raw bytes before trusting payloads, with 2MB maximum size limits and delivery deduplication.
  - **Fail-Fast Secret Validation**: Production startup enforces cryptographic strength for `SECRET_KEY` and `ENCRYPTION_KEY`, with zero-config fallbacks strictly limited to local development.
  - **Credential Masking & Rotation**: Slack webhook URLs and tokens are encrypted symmetrically at rest (Fernet) and never returned decrypted in API responses. A dedicated credential rotation endpoint (`PATCH /api/v1/repos/{id}/slack-webhook`) allows safe updates.
  - **Multi-Tenant Telemetry Isolation**: Dashboard telemetry endpoints (`/queue`, `/logs`, `/stream`, `/ws`) require authentication and strictly scope logs, SSE, and WebSocket broadcasts to the authenticated user.
- **Python AST Static Security Linter**: Inspects PR diffs and patches via Python's Abstract Syntax Tree (`ast`) to detect and flag critical vulnerabilities (`eval()`, shell command injection, raw SQL formatting, hardcoded secrets, and insecure deserialization).
- **AI Automated Code Reviewer**: Generates architectural summaries, suggests edge-case unit tests, and classifies PRs with semantic labels using Google Gemini / OpenAI with offline heuristic fallback.
- **Zero-Config Testing & Local Dev**: Seamless SQLite fallback and 100% green test suite (31 tests) running in `< 0.5s` without external services.

---

## 🏗️ Architecture & Workflow 

```
┌─────────────────┐       ┌────────────────────────┐       ┌────────────────────────┐
│  GitHub Event   │ ────► │ FastAPI Webhook Gateway│ ────► │ Atomic Event Claiming  │
│ (Issue / PR)    │       │ (HMAC Verify & Limits) │       │ (UPDATE status='proc') │
└─────────────────┘       └──────────┬─────────────┘       └──────────┬─────────────┘
                                     │                                │
                  ┌──────────────────┴──────────────────┐             ▼
                  │                                     │   ┌────────────────────────┐
                  ▼                                     ▼   │ Execution Engine       │
     [Serverless / Inline Mode]            [Worker Queue Mode]│  ├─ AST Security Linter │
     (Execute Inline before Ack)           (Durable Redis +  │  ├─ AI Code Reviewer  │
                  │                         DLQ Retries)     │  └─ Action Dispatcher  │
                  │                                     │   └──────────┬─────────────┘
                  └──────────────────┬──────────────────┘              │
                                     ▼                                 │
                          ┌──────────────────────┐                     ▼
                          │ PostgreSQL / SQLite  │ ◄───────────────────┤
                          │ (Encrypted at Rest)  │                     │
                          └──────────┬───────────┘                     ▼
                                     │                      ┌────────────────────────┐
                                     │                      │ Stream Broker (SSE/WS) │
                                     │                      │ (Tenant-Isolated)      │
                                     ▼                      └──────────┬─────────────┘
                          ┌────────────────────────────────────────────▼─────────────┐
                          │ Next.js 14 Observability Command Center (Real-Time)      │
                          └──────────────────────────────────────────────────────────┘
```

---

## 🛠️ Tech Stack

### Frontend
- Next.js 14 (App Router)
- React 18 & Lucide Icons
- Server-Sent Events (SSE) & Real-Time WebSockets
- Magma Dark Luxury CSS Design System

### Backend
- FastAPI & Starlette Async WebSockets
- Distributed Queue (Redis Async with in-process asyncio fallback)
- Python AST (`ast`) Static Security Engine
- AI PR Review Engine (Google Gemini / OpenAI / Heuristic)
- SQLAlchemy 2.0 Async (PostgreSQL + aiosqlite fallback)
- Pytest & Pytest-Asyncio (100% Green Test Suite)

### Infrastructure
- PostgreSQL (Neon Serverless)
- Redis / In-Memory Queue
- Vercel (Frontend & Backend Hosting)

---

## 🚀 Quick Start (Local Setup)

### 1. Clone & Setup Environment
```bash
git clone https://github.com/Spidey173/Darkrai.git
cd Darkrai
cp .env.example .env
```

### 2. Generate Secrets (Required for Production, Optional for Dev)
```bash
# Generate SECRET_KEY:
python3 -c "import secrets; print(secrets.token_hex(32))"

# Generate ENCRYPTION_KEY:
python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

### 3. Start Backend
```bash
cd backend
python3 -m venv venv
source venv/bin/activate    # On Windows: venv\Scripts\activate
pip install -r requirements.txt
alembic upgrade head
uvicorn app.main:app --reload --port 8000
```
> Interactive API Docs available at `http://localhost:8000/docs`

### 4. Start Frontend
```bash
cd frontend
npm install
npm run dev
```
> Dashboard available at `http://localhost:3000`

### 5. Run Automated Test Suite
```bash
pytest backend/app/tests -v
```
> Runs 31 isolated integration tests in `< 0.5s` validating secret validation, webhook signatures, deduplication, tenant telemetry isolation, AST security audits, AI code review, and atomic event claiming.

---

## 🌐 Production Deployment Architecture

### 1. Database (Neon Serverless PostgreSQL)
- Create a PostgreSQL database at [Neon.tech](https://neon.tech) and copy your connection string (format: `postgresql://...`). Darkrai automatically adapts driver schemas and connection pooling parameters.

### 2. Frontend Project (Vercel)
1. Import your GitHub repository into [Vercel](https://vercel.com).
2. Set the **Root Directory** to `frontend`.
3. Framework Preset will auto-detect as **Next.js**.
4. Configure Environment Variables:
   - `BACKEND_URL`: URL of your backend.

### 3. Backend Deployment Architecture
- **Serverless Deployments (Vercel)**:
  - In serverless runtime environments, set `EXECUTE_INLINE=true` (or let Vercel auto-detect).
  - This ensures webhooks execute all rule actions synchronously before the request lifecycle terminates.
- **Container / Dedicated Worker Deployments (Docker, ECS, Fly.io, Railway)**:
  - For continuous background consumer loops and high-concurrency event bursts, deploy the backend container with `EXECUTE_INLINE=false` and a Redis connection string (`REDIS_URL`).
  - Darkrai's atomic database state transitions (`UPDATE ... WHERE status = 'pending'`) guarantee safe event claiming across multiple concurrent worker replicas.

---

## 📄 License

This project is licensed under the [MIT License](LICENSE).
