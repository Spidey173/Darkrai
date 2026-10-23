import asyncio
import collections
import json
import logging
import time
import socket
import uuid
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, Optional, List
from uuid import UUID

try:
    import redis.asyncio as aioredis
except ImportError:
    aioredis = None

from backend.app.core.config import settings
from backend.app.core.logging import sanitize_url
from backend.app.services.event_stream import stream_broker

logger = logging.getLogger("app.services.queue")

class EventQueue:
    """
    Production-grade resilient Distributed Event Queue with:
    - Explicit worker lease ownership & active lease renewal (heartbeat)
    - Concurrency-safe Transactional Outbox recovery scanner
    - Durable Redis backend with persistence checks & monitored in-memory fallback
    - DLQ management, replay APIs, queue latency, and age alerting
    """

    QUEUE_KEY = "darkrai:queue:events"
    DLQ_KEY = "darkrai:queue:dlq"
    IDEMPOTENCY_PREFIX = "darkrai:idempotency:"

    def __init__(self):
        self.worker_id: str = f"worker-{socket.gethostname()}-{uuid.uuid4().hex[:8]}"
        self._redis: Optional[aioredis.Redis] = None
        self._is_redis_available: bool = False
        self._memory_queue: asyncio.Queue = asyncio.Queue()
        self._memory_dlq: list = []
        self._memory_idempotency: Dict[str, float] = {}  # delivery_id -> expiry timestamp
        self._worker_task: Optional[asyncio.Task] = None
        self._recovery_task: Optional[asyncio.Task] = None
        self._is_running: bool = False
        self._lock = asyncio.Lock()
        
        # Operational telemetry and latency monitoring
        self._latency_samples: collections.deque = collections.deque(maxlen=100)
        self.metrics = {
            "enqueued": 0,
            "processed": 0,
            "retries": 0,
            "dlq": 0,
            "recovered": 0,
            "replayed": 0,
            "failed_actions": 0,
            "backend": "initializing",
            "redis_persistence": "none"
        }

    async def connect(self) -> bool:
        """Attempts connection to Redis. Validates durability or switches to dev in-memory fallback."""
        if not settings.USE_REDIS_QUEUE or aioredis is None:
            if settings.APP_ENV == "production" and not settings.EXECUTE_INLINE:
                raise RuntimeError(
                    "Production configuration error: Redis queue is required in production (USE_REDIS_QUEUE=True) "
                    "when EXECUTE_INLINE is false. Ephemeral in-memory queues are not production-safe."
                )
            self._is_redis_available = False
            self.metrics["backend"] = "in_memory"
            logger.info("EventQueue configured for in-memory mode (worker_id=%s).", self.worker_id)
            return False

        try:
            client = aioredis.from_url(
                settings.REDIS_URL,
                decode_responses=True,
                socket_connect_timeout=2.0,
                socket_timeout=3.0
            )
            await client.ping()
            
            # Inspect Redis persistence configuration
            persistence_status = "active"
            try:
                info = await client.info("persistence")
                rdb_last_status = info.get("rdb_last_bgsave_status", "ok")
                aof_enabled = bool(info.get("aof_enabled", 0))
                persistence_status = f"rdb:{rdb_last_status}|aof:{aof_enabled}"
            except Exception:
                pass

            self._redis = client
            self._is_redis_available = True
            self.metrics["backend"] = "redis"
            self.metrics["redis_persistence"] = persistence_status

            safe_redis_url = sanitize_url(settings.REDIS_URL)
            logger.info("Connected to Redis at %s [Persistence: %s, worker_id=%s]", safe_redis_url, persistence_status, self.worker_id)
            await stream_broker.broadcast("queue:status", {
                "status": "connected",
                "backend": "redis",
                "persistence": persistence_status,
                "url": safe_redis_url
            })
            return True
        except Exception as exc:
            self._is_redis_available = False
            self._redis = None
            self.metrics["backend"] = "in_memory"
            
            if settings.APP_ENV == "production" and not settings.EXECUTE_INLINE:
                logger.critical("Production Redis connection failed: %s. In-memory queues cannot survive container restarts.", exc)
                raise RuntimeError(
                    f"Production startup failure: Cannot connect to Redis at {sanitize_url(settings.REDIS_URL)}. "
                    "A durable Redis instance is mandatory for multi-instance production deployments."
                ) from exc

            logger.warning(
                "Redis connection failed (%s). Falling back to in-memory event queue for development.",
                str(exc)
            )
            await stream_broker.broadcast("queue:status", {
                "status": "fallback",
                "backend": "in_memory",
                "reason": str(exc)
            }, level="WARNING")
            return False

    async def enqueue(self, event_id: str, delivery_id: str, payload_summary: Optional[Dict[str, Any]] = None) -> bool:
        """
        Enqueues an event payload with delivery idempotency.
        Returns True if newly enqueued, False if duplicate skipped.
        """
        if self._redis is None and not self._is_redis_available and self.metrics["backend"] == "initializing":
            await self.connect()

        item = {
            "event_id": str(event_id),
            "delivery_id": str(delivery_id),
            "enqueued_at": datetime.now(timezone.utc).isoformat(),
            "retry_count": 0,
            "summary": payload_summary or {}
        }

        # 1. Delivery Idempotency Check
        if self._is_redis_available and self._redis:
            try:
                idemp_key = f"{self.IDEMPOTENCY_PREFIX}{delivery_id}"
                is_new = await self._redis.set(idemp_key, event_id, nx=True, ex=86400)
                if not is_new:
                    logger.info("Redis idempotency hit for delivery %s. Skipping duplicate.", delivery_id)
                    return False
                
                await self._redis.lpush(self.QUEUE_KEY, json.dumps(item))
                self.metrics["enqueued"] += 1
            except Exception as e:
                logger.error("Redis enqueue failure, using memory fallback: %s", e)
                self._is_redis_available = False
                return await self._enqueue_memory(item, delivery_id)
        else:
            return await self._enqueue_memory(item, delivery_id)

        await stream_broker.broadcast("queue:enqueued", {
            "event_id": event_id,
            "delivery_id": delivery_id,
            "backend": self.metrics["backend"],
            "summary": payload_summary
        })
        return True

    async def _enqueue_memory(self, item: Dict[str, Any], delivery_id: str) -> bool:
        now = time.time()
        self._memory_idempotency = {
            k: exp for k, exp in self._memory_idempotency.items() if exp > now
        }
        if delivery_id in self._memory_idempotency:
            logger.info("Memory queue idempotency hit for delivery %s. Skipping duplicate.", delivery_id)
            return False

        self._memory_idempotency[delivery_id] = now + 86400  # 24h
        await self._memory_queue.put(item)
        self.metrics["enqueued"] += 1
        return True

    async def start_worker(self) -> None:
        """Starts background consumption worker task and transactional recovery scanner."""
        async with self._lock:
            if self._is_running:
                return
            self._is_running = True
            if self._redis is None:
                await self.connect()
            self._worker_task = asyncio.create_task(self._worker_loop())
            self._recovery_task = asyncio.create_task(self._recovery_loop())
            logger.info("Darkrai Queue Worker started (worker_id=%s, backend=%s).", self.worker_id, self.metrics["backend"])

    async def stop_worker(self) -> None:
        """Gracefully stops background worker and recovery scanner."""
        async with self._lock:
            self._is_running = False
            if self._worker_task:
                self._worker_task.cancel()
                try:
                    await self._worker_task
                except asyncio.CancelledError:
                    pass
                self._worker_task = None
            if self._recovery_task:
                self._recovery_task.cancel()
                try:
                    await self._recovery_task
                except asyncio.CancelledError:
                    pass
                self._recovery_task = None
            if self._redis:
                try:
                    if hasattr(self._redis, "aclose"):
                        await self._redis.aclose()
                    else:
                        await self._redis.close()
                except Exception:
                    pass
                self._redis = None
            logger.info("Darkrai Queue Worker stopped (worker_id=%s).", self.worker_id)

    async def _worker_loop(self) -> None:
        """Main consumer loop with exponential backoff and Dead-Letter Queue."""
        from backend.app.services.event_processor import process_webhook_event

        while self._is_running:
            item = None
            try:
                if self._is_redis_available and self._redis:
                    res = await self._redis.brpop(self.QUEUE_KEY, timeout=1)
                    if res:
                        _, raw_data = res
                        item = json.loads(raw_data)
                else:
                    try:
                        item = await asyncio.wait_for(self._memory_queue.get(), timeout=1.0)
                    except asyncio.TimeoutError:
                        item = None

                if not item:
                    continue

                event_id = item["event_id"]
                retry_count = item.get("retry_count", 0)

                await stream_broker.broadcast("queue:processing", {
                    "event_id": event_id,
                    "attempt": retry_count + 1,
                    "worker_id": self.worker_id,
                    "backend": self.metrics["backend"]
                })

                t0 = time.perf_counter()
                try:
                    try:
                        await process_webhook_event(event_id, worker_id=self.worker_id)
                    except TypeError:
                        await process_webhook_event(event_id)
                    duration_ms = round((time.perf_counter() - t0) * 1000, 2)
                    self._latency_samples.append(duration_ms)
                    self.metrics["processed"] += 1
                    
                    await stream_broker.broadcast("queue:completed", {
                        "event_id": event_id,
                        "worker_id": self.worker_id,
                        "duration_ms": duration_ms
                    })
                except Exception as proc_err:
                    logger.error("Error processing event %s (attempt %d, worker %s): %s", event_id, retry_count + 1, self.worker_id, proc_err)
                    self.metrics["retries"] += 1
                    
                    if retry_count + 1 < settings.MAX_EVENT_RETRIES:
                        item["retry_count"] = retry_count + 1
                        backoff_seconds = (2 ** retry_count) * 1.5
                        logger.warning(
                            "Re-enqueueing event %s for retry %d after %.1fs backoff",
                            event_id, item["retry_count"], backoff_seconds
                        )
                        await stream_broker.broadcast("queue:retry", {
                            "event_id": event_id,
                            "retry_count": item["retry_count"],
                            "next_attempt_in": backoff_seconds,
                            "error": str(proc_err)
                        }, level="WARNING")
                        
                        await asyncio.sleep(backoff_seconds)
                        if self._is_redis_available and self._redis:
                            await self._redis.lpush(self.QUEUE_KEY, json.dumps(item))
                        else:
                            await self._memory_queue.put(item)
                    else:
                        item["failed_at"] = datetime.now(timezone.utc).isoformat()
                        item["final_error"] = str(proc_err)
                        self.metrics["dlq"] += 1
                        
                        logger.critical("Event %s exceeded max retries. Routing to Dead-Letter Queue (DLQ).", event_id)
                        if self._is_redis_available and self._redis:
                            await self._redis.lpush(self.DLQ_KEY, json.dumps(item))
                        else:
                            self._memory_dlq.append(item)

                        await stream_broker.broadcast("queue:dlq", {
                            "event_id": event_id,
                            "final_error": str(proc_err),
                            "action": "moved_to_dlq"
                        }, level="ERROR")

            except asyncio.CancelledError:
                break
            except Exception as loop_err:
                logger.error("Queue worker loop error: %s", loop_err, exc_info=True)
                await asyncio.sleep(1.0)

    async def recover_stranded_events(self, stale_seconds: int = 300) -> int:
        """
        Transactional Outbox & Concurrency-Safe Recovery Scanner:
        1. Recovers stranded 'pending' events that were persisted to DB but never enqueued.
        2. Recovers abandoned 'processing' events where worker died (lease_expires_at <= now).
           Active jobs continuously renew their lease, guaranteeing slow jobs are never stolen.
        """
        from backend.app.db.session import async_session_maker
        from backend.app.models.event import WebhookEvent
        from backend.app.services.event_processor import process_webhook_event
        from sqlalchemy import select, update, or_

        recovered = 0
        now = datetime.now(timezone.utc)

        try:
            async with async_session_maker() as session:
                # 1. Stranded pending events created more than 5s ago
                pending_cutoff = now - timedelta(seconds=5)
                pending_stmt = (
                    select(WebhookEvent)
                    .where(
                        WebhookEvent.status == "pending",
                        WebhookEvent.created_at <= pending_cutoff
                    )
                    .order_by(WebhookEvent.created_at.asc())
                    .limit(20)
                )
                pending_res = await session.execute(pending_stmt)
                pending_events = pending_res.scalars().all()

                for evt in pending_events:
                    logger.warning("Recovery scanner found stranded pending event %s. Claiming.", evt.id)
                    try:
                        await process_webhook_event(str(evt.id), db=session, worker_id=self.worker_id)
                        recovered += 1
                        self.metrics["recovered"] += 1
                    except Exception as p_err:
                        logger.error("Failed processing recovered pending event %s: %s", evt.id, p_err)

                # 2. Abandoned processing events whose lease expired
                stale_stmt = (
                    select(WebhookEvent)
                    .where(
                        WebhookEvent.status == "processing",
                        or_(
                            WebhookEvent.lease_expires_at <= now,
                            (WebhookEvent.lease_expires_at == None) & (WebhookEvent.updated_at <= (now - timedelta(seconds=stale_seconds)))
                        )
                    )
                    .order_by(WebhookEvent.updated_at.asc())
                    .limit(20)
                )
                stale_res = await session.execute(stale_stmt)
                stale_events = stale_res.scalars().all()

                for evt in stale_events:
                    current_retries = evt.retry_count or 0
                    if current_retries < settings.MAX_EVENT_RETRIES:
                        logger.warning(
                            "Recovery scanner detected expired lease on event %s (worker: %s, attempt %d). Reclaiming.",
                            evt.id, evt.worker_id, current_retries + 1
                        )
                        evt.status = "pending"
                        evt.retry_count = current_retries + 1
                        evt.worker_id = None
                        evt.lease_expires_at = None
                        evt.updated_at = now
                        await session.commit()
                        try:
                            await process_webhook_event(str(evt.id), db=session, worker_id=self.worker_id)
                            recovered += 1
                            self.metrics["recovered"] += 1
                        except Exception as re_err:
                            logger.error("Failed re-processing expired lease event %s: %s", evt.id, re_err)
                    else:
                        logger.critical("Event %s lease expired and max retries reached. Routing to DLQ.", evt.id)
                        evt.status = "dlq"
                        evt.worker_id = None
                        evt.lease_expires_at = None
                        evt.error_message = f"Worker lease expired after {current_retries} attempts"
                        evt.updated_at = now
                        await session.commit()
                        self.metrics["dlq"] += 1
                        await stream_broker.broadcast("queue:dlq", {
                            "event_id": str(evt.id),
                            "final_error": evt.error_message,
                            "action": "moved_to_dlq"
                        }, level="ERROR")

        except Exception as scan_err:
            logger.error("Error during recovery scan: %s", scan_err, exc_info=True)

        return recovered

    async def replay_dlq(self, event_ids: Optional[List[str]] = None) -> int:
        """
        Replays Dead-Letter Queue (DLQ) events by resetting their status to 'pending'.
        Allows operators to re-run events after bugs are fixed or dependencies recover.
        """
        from backend.app.db.session import async_session_maker
        from backend.app.models.event import WebhookEvent
        from sqlalchemy import update

        replayed = 0
        now = datetime.now(timezone.utc)
        async with async_session_maker() as session:
            stmt = (
                update(WebhookEvent)
                .where(WebhookEvent.status.in_(["dlq", "failed"]))
            )
            if event_ids:
                parsed_ids = [UUID(str(i)) for i in event_ids]
                stmt = stmt.where(WebhookEvent.id.in_(parsed_ids))

            stmt = stmt.values(
                status="pending",
                retry_count=0,
                worker_id=None,
                lease_expires_at=None,
                error_message=None,
                updated_at=now
            )
            res = await session.execute(stmt)
            await session.commit()
            replayed = res.rowcount

        # If in-memory DLQ has items, clear them
        if not event_ids:
            self._memory_dlq.clear()

        self.metrics["replayed"] += replayed
        logger.info("DLQ Replay: Successfully requeued %d dead-letter events for re-processing.", replayed)
        await stream_broker.broadcast("queue:dlq_replayed", {
            "replayed_count": replayed
        })
        return replayed

    async def get_queue_age_seconds(self) -> float:
        """Returns the age (in seconds) of the oldest pending event in the database."""
        from backend.app.db.session import async_session_maker
        from backend.app.models.event import WebhookEvent
        from sqlalchemy import select, func

        try:
            async with async_session_maker() as session:
                res = await session.execute(
                    select(func.min(WebhookEvent.created_at))
                    .where(WebhookEvent.status == "pending")
                )
                oldest = res.scalar_one_or_none()
                if oldest:
                    if oldest.tzinfo is None:
                        oldest = oldest.replace(tzinfo=timezone.utc)
                    return round(max(0.0, (datetime.now(timezone.utc) - oldest).total_seconds()), 1)
        except Exception as e:
            logger.debug("Could not compute queue age: %s", e)
        return 0.0

    async def _recovery_loop(self) -> None:
        """Background loop executing transactional outbox recovery scans every 15 seconds."""
        try:
            await asyncio.sleep(2.0)
        except asyncio.CancelledError:
            return

        while self._is_running:
            try:
                await self.recover_stranded_events()
            except Exception as loop_err:
                logger.error("Recovery loop encountered an error: %s", loop_err, exc_info=True)

            try:
                await asyncio.sleep(15.0)
            except asyncio.CancelledError:
                break

    async def get_queue_stats(self) -> Dict[str, Any]:
        """Returns comprehensive runtime telemetry for operations and dashboard."""
        pending_count = 0
        dlq_count = 0
        if self._is_redis_available and self._redis:
            try:
                pending_count = await self._redis.llen(self.QUEUE_KEY)
                dlq_count = await self._redis.llen(self.DLQ_KEY)
            except Exception:
                pending_count = self._memory_queue.qsize()
                dlq_count = len(self._memory_dlq)
        else:
            pending_count = self._memory_queue.qsize()
            dlq_count = len(self._memory_dlq)

        queue_age = await self.get_queue_age_seconds()
        
        # Calculate latency metrics
        samples = list(self._latency_samples)
        avg_latency_ms = round(sum(samples) / len(samples), 1) if samples else 0.0
        sorted_samples = sorted(samples)
        p95_latency_ms = sorted_samples[int(len(sorted_samples) * 0.95)] if sorted_samples else 0.0

        # Evaluate operational alerts
        alerts = []
        if queue_age > 120.0:
            alerts.append({"severity": "CRITICAL", "message": f"Queue age exceeded threshold: oldest event is {queue_age}s old."})
        elif queue_age > 30.0:
            alerts.append({"severity": "WARNING", "message": f"Queue lag detected: oldest event is {queue_age}s old."})

        if dlq_count > 0:
            alerts.append({"severity": "WARNING", "message": f"Dead-letter events present: {dlq_count} failed events awaiting replay."})

        return {
            "worker_id": self.worker_id,
            "backend": self.metrics["backend"],
            "redis_persistence": self.metrics["redis_persistence"],
            "is_running": self._is_running,
            "pending_events": pending_count,
            "dlq_events": dlq_count,
            "queue_age_seconds": queue_age,
            "avg_latency_ms": avg_latency_ms,
            "p95_latency_ms": p95_latency_ms,
            "total_enqueued": self.metrics["enqueued"],
            "total_processed": self.metrics["processed"],
            "total_retries": self.metrics["retries"],
            "total_dlq": self.metrics["dlq"],
            "total_recovered": self.metrics["recovered"],
            "total_replayed": self.metrics["replayed"],
            "alerts": alerts
        }

# Global singleton queue instance
event_queue = EventQueue()
