import pytest
from httpx import AsyncClient
from backend.app.services.event_stream import EventStreamBroker

@pytest.mark.asyncio
async def test_stream_broker_broadcast_and_history():
    broker = EventStreamBroker(buffer_size=10)

    msg = await broker.broadcast("test:event", {"foo": "bar"}, level="INFO")
    assert msg["type"] == "test:event"
    assert msg["data"]["foo"] == "bar"
    assert "timestamp" in msg

    history = broker.get_recent_events()
    assert len(history) >= 1
    assert history[-1]["type"] == "test:event"

@pytest.mark.asyncio
async def test_stream_broker_subscriber_lifecycle():
    broker = EventStreamBroker()
    q = await broker.register_sse_subscriber()
    assert broker.subscriber_count == 1

    await broker.broadcast("alert:warning", {"msg": "high load"}, level="WARNING")
    event = await q.get()
    assert event["type"] == "alert:warning"

    await broker.unregister_sse_subscriber(q)
    assert broker.subscriber_count == 0

@pytest.mark.asyncio
async def test_dashboard_queue_endpoint(client: AsyncClient):
    resp = await client.get("/api/v1/dashboard/queue")
    assert resp.status_code == 200
    data = resp.json()
    assert "backend" in data
    assert "pending_events" in data
    assert "total_enqueued" in data

@pytest.mark.asyncio
async def test_dashboard_logs_endpoint(client: AsyncClient):
    resp = await client.get("/api/v1/dashboard/logs")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)
