import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from backend.app.services.event_stream import EventStreamBroker
from backend.app.models.user import User
from backend.app.services.encryption import encrypt_token
from backend.app.utils.jwt import create_session_token

@pytest.mark.asyncio
async def test_stream_broker_broadcast_and_history():
    broker = EventStreamBroker(buffer_size=10)

    msg = await broker.broadcast("test:event", {"foo": "bar"}, level="INFO", user_id="user_123")
    assert msg["type"] == "test:event"
    assert msg["data"]["foo"] == "bar"
    assert "timestamp" in msg

    history = broker.get_recent_events(user_id="user_123")
    assert len(history) >= 1
    assert history[-1]["type"] == "test:event"

    other_history = broker.get_recent_events(user_id="user_999")
    assert len(other_history) == 0

@pytest.mark.asyncio
async def test_stream_broker_tenant_isolation():
    broker = EventStreamBroker()
    q1 = await broker.register_sse_subscriber(user_id="user_1")
    q2 = await broker.register_sse_subscriber(user_id="user_2")
    assert broker.subscriber_count == 2

    # Broadcast event scoped strictly to user_1
    await broker.broadcast("alert:user1", {"info": "user1 only"}, level="WARNING", user_id="user_1")
    event1 = await q1.get()
    assert event1["type"] == "alert:user1"
    assert q2.empty()

    await broker.unregister_sse_subscriber(q1)
    await broker.unregister_sse_subscriber(q2)
    assert broker.subscriber_count == 0

@pytest.mark.asyncio
async def test_dashboard_endpoints_require_auth(client: AsyncClient):
    # Unauthenticated requests must fail with 401
    q_resp = await client.get("/api/v1/dashboard/queue")
    assert q_resp.status_code == 401
    assert "Not authenticated" in q_resp.json()["detail"]

    l_resp = await client.get("/api/v1/dashboard/logs")
    assert l_resp.status_code == 401
    assert "Not authenticated" in l_resp.json()["detail"]

@pytest.mark.asyncio
async def test_dashboard_endpoints_authenticated(client: AsyncClient, db_session: AsyncSession):
    user = User(
        github_user_id=88888,
        github_username="dashuser",
        github_access_token_encrypted=encrypt_token("mock_token")
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)

    token = create_session_token(str(user.id))
    headers = {"Authorization": f"Bearer {token}"}

    q_resp = await client.get("/api/v1/dashboard/queue", headers=headers)
    assert q_resp.status_code == 200
    data = q_resp.json()
    assert "backend" in data
    assert "pending_events" in data
    assert "total_enqueued" in data

    l_resp = await client.get("/api/v1/dashboard/logs", headers=headers)
    assert l_resp.status_code == 200
    assert isinstance(l_resp.json(), list)

