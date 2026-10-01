# Darkrai
### Event-Driven GitHub Automation Platform

### Live Demo: [https://darkrai-one.vercel.app/](https://darkrai-one.vercel.app/)

Darkrai is an event-driven GitHub automation platform that processes repository webhooks, evaluates rule-based workflows, and executes automated actions such as issue labeling, contextual comments, and Slack notifications. The platform includes a real-time observability dashboard for monitoring event processing and automation history.

---

## ⚡ Key Capabilities 

- **Distributed Worker Queue & DLQ**: Ingests GitHub webhooks in $< 50\text{ms}$ with `X-GitHub-Delivery` deduplication, Redis asynchronous queue execution, exponential backoff retries, and Dead-Letter Queue (DLQ) routing.
- **Python AST Static Security Linter**: Inspects PR patches with Python's Abstract Syntax Tree (`ast`) to block critical anti-patterns (`eval()`, shell injection, raw SQL string formatting, hardcoded secrets/tokens, and insecure deserialization).
- **AI Automated Code Reviewer**: Generates deep architectural summaries, suggests targeted edge-case unit tests, and classifies PRs with semantic labels using Google Gemini / OpenAI with offline heuristic fallback.
- **Real-Time Observability Terminal**: Live WebSocket and Server-Sent Events (SSE) stream pushing ingestion, queue lifecycle, and AST security audits directly to a dark-mode command center with zero polling delay.
- **Zero-Config Testing & SQLite Fallback**: Automatic local SQLite fallback and 100% green isolated test suite running in $< 0.3\text{s}$ with zero required `.env` bootstrap.

---

## 🏗️ Architecture & Workflow 

```
┌─────────────────┐       ┌──────────────────────┐       ┌────────────────────────┐
│  GitHub Event   │ ────► │ FastAPI Webhook Gateway│ ────► │ Distributed Redis Queue │
│ (Issue / PR)    │       │ (< 50ms Ingestion)   │       │ (Idempotency + DLQ)    │
└─────────────────┘       └──────────┬───────────┘       └──────────┬─────────────┘
                                     │                              │
                                     │                              ▼
                                     │                   ┌────────────────────────┐
                                     │                   │ Asynchronous Worker    │
                                     │                   │  ├─ AST Security Linter │
                                     │                   │  ├─ AI PR Code Reviewer│
                                     │                   │  └─ Advanced RuleEngine│
                                     ▼                   └──────────┬─────────────┘
                          ┌──────────────────────┐                  │
                          │ PostgreSQL / SQLite  │ ◄────────────────┤
                          │ (Zero-Config Test DB)│                  ▼
                          └──────────────────────┘       ┌────────────────────────┐
                                     ▲                   │ Live WebSocket / SSE   │
                                     │                   │ Real-Time Stream Broker│
                                     │                   └──────────┬─────────────┘
                                     │                              │
                          ┌──────────┴──────────────────────────────▼─────────────┐
                          │ Next.js 14 Observability Command Center (Real-Time)   │
                          └───────────────────────────────────────────────────────┘
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
- Distributed Queue (Redis Async with Resilient In-Memory Fallback)
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

### 2. Start Backend
```bash
cd backend
python3 -m venv venv
source venv/bin/activate    # On Windows: venv\Scripts\activate
pip install -r requirements.txt
alembic upgrade head
uvicorn app.main:app --reload --port 8000
```
> API Docs available at `http://localhost:8000/docs`

### 3. Start Frontend
```bash
cd frontend
npm install
npm run dev
```
> Dashboard available at `http://localhost:3000`

### 4. Run Automated Test Suite
```bash
pytest backend/app/tests -v
```
> Runs 26 isolated integration tests in `< 0.3s` with zero configuration, validating webhook signatures, replay deduplication, AST security audits, AI code review generation, and distributed queue DLQ routing.

---

## 🌐 Production Deployment on Vercel

### 1. Database (Neon Serverless PostgreSQL)
- Create a free PostgreSQL database at [Neon.tech](https://neon.tech) and copy your connection string (format: `postgresql://...`).

### 2. Frontend Project (Vercel)
1. Import your GitHub repository into [Vercel](https://vercel.com).
2. Set the **Root Directory** to `frontend`.
3. Framework Preset will auto-detect as **Next.js**.
4. Configure Environment Variables:
   - `BACKEND_URL`: URL of your backend (or internal API proxy)

### 3. Backend Deployment Options on Vercel
- **Option A (Separate Backend Project on Vercel with Serverless Python)**:
  - Create a new project in Vercel pointing to the same repository with Root Directory set to `backend`.
  - Add Environment Variables:
    - `DATABASE_URL`: *Your Neon connection string*
    - `APP_NAME`: `Darkrai`
    - `SECRET_KEY`: `<your-secret-key>`
    - `ENCRYPTION_KEY`: `<your-encryption-key>`
    - `GITHUB_CLIENT_ID`: *Your GitHub OAuth App Client ID*
    - `GITHUB_CLIENT_SECRET`: *Your GitHub OAuth App Client Secret*
    - `GITHUB_WEBHOOK_SECRET`: `<your-webhook-secret>`
    - `WEBHOOK_BASE_URL`: `https://<your-backend-project>.vercel.app`
    - `BACKEND_CORS_ORIGINS`: `["https://<your-frontend-project>.vercel.app"]`
- **Option B (Dedicated Container / Worker Service)**:
  - If your workload requires continuous long-running background queue workers (such as indefinite WebSocket streams or long-lived consumer loops), host the backend worker container on a container runtime while serving the web layer on Vercel.

---

## 📄 License

This project is licensed under the [MIT License](LICENSE).
