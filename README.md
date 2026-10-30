# ⚡ Darkrai — Event-Driven DevSecOps Automation & AST Linter

[![CI Pipeline](https://github.com/Spidey173/Darkrai/actions/workflows/ci.yml/badge.svg)](https://github.com/Spidey173/Darkrai/actions/workflows/ci.yml)
[![Tests](https://img.shields.io/badge/Pytest-44%20Tests%20Passing-brightgreen?style=flat-square&logo=pytest)](tests/)
[![Backend](https://img.shields.io/badge/Backend-FastAPI-009688?style=flat-square&logo=fastapi&logoColor=white)](backend/)
[![Frontend](https://img.shields.io/badge/Frontend-Next.js%2016-black?style=flat-square&logo=next.js&logoColor=white)](frontend/)
[![Queue](https://img.shields.io/badge/Queue-Redis%20%2B%20DLQ-DC382D?style=flat-square&logo=redis&logoColor=white)](backend/queue/)
[![License](https://img.shields.io/badge/License-MIT-lightgrey?style=flat-square)](LICENSE)

🔗 **[Live Monitoring Console](https://darkrai17.vercel.app/)** | 📦 **[GitHub Repository](https://github.com/Spidey173/Darkrai)**

---

## ⚡ At A Glance: Problem, Architecture, Proof & Scope

| Dimension | Specification |
| :--- | :--- |
| **Problem** | Brittle regex checkers produce excessive false alerts on benign variable names while missing multi-line injection flaws, and synchronous webhook handlers crash or drop events during GitHub traffic bursts. |
| **Architecture** | **Asynchronous FastAPI webhook gateway** with sub-5ms HMAC-SHA256 signature verification over raw request bytes, **Transactional Outbox** pattern with lease recovery, **Redis worker queue with Dead Letter Queue (DLQ)**, and formal **Python Abstract Syntax Tree (`ast`) inspection**. |
| **Evidence & Benchmarks** | **Sub-5ms** webhook HMAC signature verification and ingestion latency under burst load, zero dropped events across worker crashes via outbox lease recovery, verified by **44 automated Pytests**. |
| **Scope & Boundaries** | **Simulated Event Streams**: Replayed & synthetic GitHub webhook payloads (push, PR, secret leaks) with valid and malformed signatures. **Deployment**: Next.js 16 real-time monitoring console live on Vercel with simulated SSE event streams; FastAPI worker and Redis queue run in local container environment. |
| **Verified Test Suite** | **44 / 44 Pytests passing** (HMAC validation, queue retries, outbox recovery, AST vulnerability detection). |

---

## 🏗️ Architecture Slice: Webhook Gateway & AST Linter

```text
┌─────────────────┐       ┌────────────────────────┐       ┌────────────────────────┐       ┌─────────────────┐
│ GitHub Webhook  │ ────► │ FastAPI Webhook Ingest │ ────► │ Transactional Outbox   │ ────► │ Redis Worker    │ ────► Python AST Linter
│ (HMAC-SHA256)   │       │ (<5ms Raw Byte Verify) │       │ (PostgreSQL / SQLite)  │       │ (Retry + DLQ)   │       (eval, exec, sql inject)
└─────────────────┘       └────────────────────────┘       └────────────────────────┘       └─────────┬───────┘
                                                                                                      │
                                                                                                      ▼
                                                                                           ┌──────────────────────┐
                                                                                           │ Real-Time SSE Stream │ ──► Next.js 16 Console
                                                                                           │ (Telemetry & Logs)   │     (Zero dropped events)
                                                                                           └──────────────────────┘
```

* **Guarantee**: Replaces brittle regex matching with full syntax tree traversal, eliminating false positives while intercepting critical code injection patterns before merge.

---

## 🚀 Quickstart: Reproduce in 30 Seconds

```bash
# 1. Clone repository & setup virtual environment
git clone https://github.com/Spidey173/Darkrai.git
cd Darkrai
python3 -m venv venv && source venv/bin/activate

# 2. Install backend dependencies
pip install -r requirements.txt

# 3. Run verified test suite (44 automated Pytests)
pytest -v

# 4. Run local development API
uvicorn main:app --reload
```
*Open [http://localhost:8000](http://localhost:8000) or navigate the live console at [darkrai17.vercel.app](https://darkrai17.vercel.app/).*

---

## 📚 Appendices & Deep Design Rationale

<details>
<summary><strong>1. Python Abstract Syntax Tree (AST) Security Rules</strong></summary>

Rather than relying on fragile regex text scans that flag comments or harmless strings, Darkrai compiles incoming Python pull request diffs into formal AST nodes (`ast.parse`):
- `ast.Call`: Intercepts dangerous built-in execution calls (`eval()`, `exec()`, `compile()`).
- `subprocess.Popen` / `os.system`: Detects unescaped shell execution (`shell=True`).
- Raw SQL String Formatting: Identifies formatted string literals (`f"SELECT ... WHERE id = {var}"`) feeding database execute calls.
- Hardcoded Secrets: Flags high-entropy strings assigned to variable identifiers like `API_KEY`, `SECRET_KEY`, or `AWS_SECRET`.
</details>

<details>
<summary><strong>2. Transactional Outbox Pattern & Lease Recovery</strong></summary>

- **Atomic State Transitions**: Webhooks are written to an `outbox_events` table within the same transaction that updates local application state.
- **Worker Lease Recovery**: If a worker node crashes midway through processing an event, the recovery scanner detects expired worker leases (`WHERE status = 'processing' AND updated_at < NOW() - INTERVAL '60 seconds'`) and safely returns the event to the queue.
- **Dead Letter Queue (DLQ)**: Payloads failing repeatedly after 3 exponential backoff attempts are isolated in a quarantine queue with stack trace metadata.
</details>

<details>
<summary><strong>3. Tech Stack & Directory Tree</strong></summary>

```
Darkrai/
├── backend/
│   ├── main.py             # FastAPI webhook routes & SSE telemetry endpoints
│   ├── security/           # HMAC-SHA256 signature verifiers & token guards
│   ├── linter/             # Python AST code inspection engine
│   ├── queue/              # Redis worker queue & DLQ handlers
│   └── models/             # SQLAlchemy schemas & outbox tables
├── frontend/               # Next.js 16 App Router real-time monitoring dashboard
└── tests/                  # 44 automated Pytest tests
```
</details>

---

## 📄 License
This project is open-source under the [MIT License](LICENSE).
