# Darkrai Production Operations & Runbook

This runbook documents operational procedures, durability requirements, concurrency-safe recovery mechanics, secret rotation, and incident response for Darkrai in production environments.

---

## 1. Architecture & Deployment Topology

Darkrai uses a decoupled architecture separating HTTP request handling from background automation execution:

```
                  ┌──────────────────────┐
                  │ GitHub Webhooks      │
                  └──────────┬───────────┘
                             │ HTTPS POST
                             ▼
                  ┌──────────────────────┐
                  │ Web API Service      │
                  │ (FastAPI / Gunicorn) │
                  └────┬────────────┬─────┘
   Persist Event (DB)  │            │ Enqueue Delivery
                       ▼            ▼
             ┌──────────────┐  ┌─────────────┐
             │ PostgreSQL   │  │ Redis 7.x   │
             │ (Neon / RDS) │  │ Persistence │
             └──────▲───────┘  └──────┬──────┘
                    │                 │
            Lease & │                 │ Pop Event
           Outbox   │                 ▼
                    │    ┌────────────────────────┐
                    └────┤ Worker Service Replicas│
                         │ (python -m app.worker) │
                         └────────────────────────┘
```

- **Web Service (`backend.app.main`)**: Receives webhook requests, verifies HMAC signatures, streams payloads safely (with 2MB limits), commits events to PostgreSQL as the canonical transactional outbox, and enqueues event references to Redis.
- **Worker Service (`backend.app.worker`)**: Long-lived background consumer running on container/VM infrastructure. Workers pop events from Redis, claim atomic database leases (`worker_id`, `lease_expires_at`), renew leases during slow tasks, execute rule actions idempotently, and handle retries/DLQ escalation.

---

## 2. Durable Redis Configuration

In production (`APP_ENV=production`), ephemeral in-memory queues are **strictly disallowed**. The worker verifies Redis connectivity and persistence status on startup.

### Recommended Redis Settings (`redis.conf`):
```ini
# Append-Only File (AOF) for per-write durability
appendonly yes
appendfsync everysec
no-appendfsync-on-rewrite no
auto-aof-rewrite-percentage 100
auto-aof-rewrite-min-size 64mb

# Snapshotting (RDB) as secondary point-in-time backup
save 900 1
save 300 10
save 60 10000

# Memory management
maxmemory 2gb
maxmemory-policy noeviction  # Never evict queue keys silently
```

### Redis Monitoring & Health Checks:
- Monitor key depth: `darkrai:queue:events` (pending) and `darkrai:queue:dlq` (dead-letter).
- Inspect persistence health via CLI or Darkrai telemetry endpoint (`/api/v1/dashboard/queue`):
  ```bash
  redis-cli info persistence
  # Check rdb_last_bgsave_status == 'ok'
  # Check aof_enabled == 1
  ```

---

## 3. Worker Concurrency & Lease Recovery

### Concurrency Guarantees:
- **Atomic Event Claiming**: Multiple concurrent worker instances can safely poll the queue or run recovery scans. Workers claim events using an atomic conditional update:
  ```sql
  UPDATE webhook_events
  SET status = 'processing', worker_id = :worker_id, lease_expires_at = :lease_expiry, updated_at = :now
  WHERE id = :event_id
    AND (status IN ('pending', 'retrying') OR (status = 'processing' AND lease_expires_at <= :now));
  ```
- **Active Lease Renewal (Heartbeat)**: While a worker is executing slow tasks (AST analysis, AI PR review), a background renewal task extends `lease_expires_at` every 10 seconds.
- **Recovery Scanner**: If a worker crashes or is abruptly killed (`SIGKILL`), its heartbeat stops. The outbox recovery scanner automatically reclaims the event once `lease_expires_at` passes, without ever stealing work from alive, slow-running workers.

---

## 4. Action Idempotency & Reconciliation

To prevent duplicate side effects (e.g. duplicate GitHub PR comments or duplicate Slack notifications) when workers crash midway through processing:

1. Every action computes a deterministic SHA-256 fingerprint:
   `idempotency_key = sha256(f"{event.id}:{rule.id}:{action_type}:{action_value}")`
2. Before invoking GitHub or Slack APIs, the worker queries `action_logs` for an existing `success` record with that key.
3. If previously completed, the external API call is skipped and reconciled.
4. Each executed action is committed immediately upon completion.

---

## 5. PostgreSQL Migrations & Backup Procedures

### Applying Migrations:
```bash
cd backend
alembic upgrade head
```

### Automated Backup Procedure:
- Neon / AWS RDS: Ensure point-in-time recovery (PITR) is enabled with minimum 7-day retention.
- Manual Snapshot Backup:
  ```bash
  pg_dump -Fc --no-acl --no-owner -h <DB_HOST> -U <DB_USER> <DB_NAME> > darkrai_backup_$(date +%Y%m%d_%H%M%S).dump
  ```
- Restoration Procedure:
  ```bash
  pg_restore -h <DB_HOST> -U <DB_USER> -d <DB_NAME> --clean --if-exists darkrai_backup_<TIMESTAMP>.dump
  ```

---

## 6. Secret Rotation Procedures

### Rotating `SECRET_KEY` (JWT Session Tokens):
1. Generate a new cryptographically strong 32+ character string:
   ```bash
   python3 -c "import secrets; print(secrets.token_urlsafe(32))"
   ```
2. Update `SECRET_KEY` in your environment / secrets manager.
3. Restart backend services. Existing sessions will expire safely, prompting users to re-authenticate via GitHub OAuth.

### Rotating `ENCRYPTION_KEY` (Fernet Field Encryption):
1. Generate a new 32-byte url-safe base64 Fernet key:
   ```bash
   python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
   ```
2. Run Darkrai's key re-encryption rotation script across stored credentials (GitHub tokens and Slack webhook URLs):
   ```bash
   python3 -m backend.app.scripts.rotate_encryption_key --old-key <OLD_KEY> --new-key <NEW_KEY>
   ```
3. Update `ENCRYPTION_KEY` in production environment variables and deploy.

### Rotating Slack Webhook URLs:
Use the dedicated credential rotation API without exposing existing credentials:
```bash
curl -X PATCH https://<DOMAIN>/api/v1/repos/<REPO_ID>/slack-webhook \
  -H "Authorization: Bearer <TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{"slack_webhook_url": "https://hooks.slack.com/services/NEW/KEY/URL"}'
```

---

## 7. Operational Visibility, Alerting & DLQ Replay

### Monitoring Endpoints:
- `GET /api/v1/dashboard/queue`: Returns worker ID, backend mode, Redis persistence health, pending events, DLQ events, queue age in seconds, and rolling p95 latency.
- `GET /api/v1/dashboard/stats`: Returns aggregated delivery, success, failure, and action counts.

### Alerting Thresholds:
| Metric | Warning Threshold | Critical Threshold | Action |
| :--- | :--- | :--- | :--- |
| **Queue Age** | > 30 seconds | > 120 seconds | Investigate worker capacity or slow network calls |
| **DLQ Count** | > 0 events | > 10 events | Inspect error messages on DLQ events |
| **Processing Latency (p95)** | > 5,000 ms | > 15,000 ms | Check LLM / GitHub API rate limits |
| **Redis Persistence** | Degraded / In-Memory | Redis Down | Restore Redis persistence immediately |

### Dead-Letter Queue (DLQ) Replay Process:
When downstream service issues (e.g. GitHub API outage or invalid Slack URL) are resolved, replay dead-letter events for re-processing:
```bash
# Replay all DLQ events
curl -X POST https://<DOMAIN>/api/v1/dashboard/dlq/replay \
  -H "Authorization: Bearer <TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{}'

# Replay specific events by ID
curl -X POST https://<DOMAIN>/api/v1/dashboard/dlq/replay \
  -H "Authorization: Bearer <TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{"event_ids": ["3fa85f64-5717-4562-b3fc-2c963f66afa6"]}'
```
Replayed events reset their retry count and move back into `pending` status, where active workers process them idempotently without duplicating previously successful actions.
