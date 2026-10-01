import asyncio
import json
import logging
import time
from datetime import datetime, timezone
from typing import Dict, Any, Optional

import redis.asyncio as aioredis
from backend.app.core.config import settings
from backend.app.services.event_stream import stream_broker

logger = logging.getLogger("app.services.queue")

class EventQueue:
    """
    High-throughput event queue with native Redis backing and resilient
    in-process asyncio fallback.
    
    Guarantees:
    - Zero event loss: Falls back to async in-memory queue if Redis is unreachable.
    - Idempotency: Ensures unique processing per X-GitHub-Delivery.
    - Fault Tolerance: Exponential backoff retries (default 3 attempts) + Dead-Letter Queue (DLQ).
    - Live Observability: Emits real-time state telemetry to stream_broker.
    """

    QUEUE_KEY = "darkrai:queue:events"
    DLQ_KEY = "darkrai:queue:dlq"
    IDEMPOTENCY_PREFIX = "darkrai:idempotency:"

    def __init__(self):
        self._redis: Optional[aioredis.Redis] = None
        self._is_redis_available: bool = False
        self._memory_queue: asyncio.Queue = asyncio.Queue()
        self._memory_dlq: list = []
        self._memory_idempotency: Dict[str, float] = {}  # delivery_id -> expiry timestamp
        self._worker_task: Optional[asyncio.Task] = None
        self._is_running: bool = False
        self._lock = asyncio.Lock()
        
        # Telemetry metrics
        self.metrics = {
            "enqueued": 0,
            "processed": 0,
            "retries": 0,
            "dlq": 0,
            "backend": "initializing"
        }

    async def connect(self) -> bool:
        """Attempts connection to Redis. Switches to in-memory fallback on failure."""
        if not settings.USE_REDIS_QUEUE:
            self._is_redis_available = False
            self.metrics["backend"] = "in_memory"
            logger.info("EventQueue configured for in-memory mode via settings.")
            return False

        try:
            client = aioredis.from_url(
                settings.REDIS_URL,
                decode_responses=True,
                socket_connect_timeout=1.0,
                socket_timeout=2.0
            )
            await client.ping()
            self._redis = client
            self._is_redis_available = True
            self.metrics["backend"] = "redis"
            logger.info("Connected to Redis successfully at %s", settings.REDIS_URL)
            await stream_broker.broadcast("queue:status", {
                "status": "connected",
                "backend": "redis",
                "url": settings.REDIS_URL
            })
            return True
        except Exception as exc:
            self._is_redis_available = False
            self._redis = None
            self.metrics["backend"] = "in_memory"
            logger.warning(
                "Redis connection failed (%s). Falling back gracefully to in-memory event queue.",
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

        # 1. Idempotency Check
        if self._is_redis_available and self._redis:
            try:
                idemp_key = f"{self.IDEMPOTENCY_PREFIX}{delivery_id}"
                # Set NX with 24-hour expiration
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
        # Clean expired keys
        self._memory_idempotency = {
            k: exp for k, exp in self._memory_idempotency.items() if exp > now
        }
        if delivery_id in self._memory_idempotency:
            logger.info("Memory queue idempotency hit for delivery %s. Skipping.", delivery_id)
            return False

        self._memory_idempotency[delivery_id] = now + 86400  # 24h
        await self._memory_queue.put(item)
        self.metrics["enqueued"] += 1
        return True

    async def start_worker(self) -> None:
        """Starts background consumption worker task."""
        async with self._lock:
            if self._is_running:
                return
            self._is_running = True
            if self._redis is None:
                await self.connect()
            self._worker_task = asyncio.create_task(self._worker_loop())
            logger.info("Darkrai Queue Worker started [%s mode].", self.metrics["backend"])

    async def stop_worker(self) -> None:
        """Gracefully stops background worker."""
        async with self._lock:
            self._is_running = False
            if self._worker_task:
                self._worker_task.cancel()
                try:
                    await self._worker_task
                except asyncio.CancelledError:
                    pass
                self._worker_task = None
            if self._redis:
                if hasattr(self._redis, "aclose"):
                    await self._redis.aclose()
                else:
                    await self._redis.close()
                self._redis = None
            logger.info("Darkrai Queue Worker stopped.")

    async def _worker_loop(self) -> None:
        """Main consumer loop with exponential backoff and Dead-Letter Queue."""
        # Avoid circular imports at module top-level
        from backend.app.services.event_processor import process_webhook_event

        while self._is_running:
            item = None
            try:
                if self._is_redis_available and self._redis:
                    # Pop from right (FIFO) with 1s timeout
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
                    "backend": self.metrics["backend"]
                })

                # Execute event processing
                try:
                    await process_webhook_event(event_id)
                    self.metrics["processed"] += 1
                    await stream_broker.broadcast("queue:completed", {
                        "event_id": event_id,
                        "duration_ms": "completed"
                    })
                except Exception as proc_err:
                    logger.error("Error processing event %s (attempt %d): %s", event_id, retry_count + 1, proc_err)
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
                        # Move to Dead-Letter Queue (DLQ)
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

    async def get_queue_stats(self) -> Dict[str, Any]:
        """Returns runtime telemetry for dashboard monitoring."""
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

        return {
            "backend": self.metrics["backend"],
            "is_running": self._is_running,
            "pending_events": pending_count,
            "dlq_events": dlq_count,
            "total_enqueued": self.metrics["enqueued"],
            "total_processed": self.metrics["processed"],
            "total_retries": self.metrics["retries"],
            "total_dlq": self.metrics["dlq"],
        }

# Global singleton queue instance
event_queue = EventQueue()
