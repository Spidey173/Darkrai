import asyncio
import uuid
import pytest
from backend.app.services.queue import EventQueue

@pytest.mark.asyncio
async def test_queue_enqueue_and_idempotency():
    queue = EventQueue()
    queue._is_redis_available = False
    queue.metrics["backend"] = "in_memory"

    delivery_id = str(uuid.uuid4())
    event_id = str(uuid.uuid4())

    enqueued = await queue.enqueue(event_id, delivery_id, {"repo": "test/repo"})
    assert enqueued is True
    assert queue.metrics["enqueued"] == 1

    duplicate_enqueued = await queue.enqueue(str(uuid.uuid4()), delivery_id)
    assert duplicate_enqueued is False
    assert queue.metrics["enqueued"] == 1

@pytest.mark.asyncio
async def test_queue_telemetry_stats():
    queue = EventQueue()
    queue._is_redis_available = False
    queue.metrics["backend"] = "in_memory"

    stats = await queue.get_queue_stats()
    assert "backend" in stats
    assert "pending_events" in stats
    assert "dlq_events" in stats
    assert "total_enqueued" in stats
    assert stats["backend"] == "in_memory"

@pytest.mark.asyncio
async def test_queue_worker_execution_and_dlq(monkeypatch):
    queue = EventQueue()
    queue._is_redis_available = False
    queue.metrics["backend"] = "in_memory"

    call_count = 0
    async def failing_processor(event_id: str):
        nonlocal call_count
        call_count += 1
        raise RuntimeError("Simulated transient processing failure")

    import backend.app.services.event_processor as ep
    monkeypatch.setattr(ep, "process_webhook_event", failing_processor)

    delivery_id = str(uuid.uuid4())
    event_id = str(uuid.uuid4())
    await queue.enqueue(event_id, delivery_id)

    await queue.start_worker()
    await asyncio.sleep(0.1)
    await queue.stop_worker()

    assert call_count >= 1
