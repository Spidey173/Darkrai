import hmac
import hashlib
import uuid
import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.models.user import User
from backend.app.models.repository import Repository
from backend.app.models.rule import Rule
from backend.app.models.event import WebhookEvent
from backend.app.services.encryption import encrypt_token

def compute_signature(payload: bytes, secret: str) -> str:
    sig = hmac.new(
        key=secret.encode("utf-8"),
        msg=payload,
        digestmod=hashlib.sha256
    ).hexdigest()
    return f"sha256={sig}"

@pytest.mark.asyncio
async def test_health_check(client: AsyncClient):
    response = await client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json()["status"] == "healthy"

@pytest.mark.asyncio
async def test_webhook_unconnected_repository(client: AsyncClient):
    payload = {
        "action": "opened",
        "repository": {
            "full_name": "nonexistent/repo"
        }
    }
    response = await client.post(
        "/api/v1/webhooks/github",
        json=payload,
        headers={
            "X-GitHub-Event": "issues",
            "X-GitHub-Delivery": str(uuid.uuid4()),
            "X-Hub-Signature-256": "sha256=some_sig"
        }
    )
    assert response.status_code == 404
    assert "Repository not connected" in response.json()["detail"]

@pytest.mark.asyncio
async def test_webhook_unauthorized_signature(client: AsyncClient, db_session: AsyncSession):
    # Setup mock User and Repository
    user = User(
        github_user_id=12345,
        github_username="testuser",
        github_access_token_encrypted=encrypt_token("mock_token")
    )
    db_session.add(user)
    await db_session.flush()

    repo = Repository(
        user_id=user.id,
        github_repo_id=98765,
        name="test-repo",
        owner="testuser",
        full_name="testuser/test-repo",
        is_active=True,
        webhook_secret_encrypted=encrypt_token("repo_secret"),
        webhook_id=11111
    )
    db_session.add(repo)
    await db_session.commit()

    payload = {
        "action": "opened",
        "issue": {
            "number": 1,
            "title": "A critical bug here"
        },
        "repository": {
            "full_name": "testuser/test-repo"
        }
    }

    response = await client.post(
        "/api/v1/webhooks/github",
        json=payload,
        headers={
            "X-GitHub-Event": "issues",
            "X-GitHub-Delivery": str(uuid.uuid4()),
            "X-Hub-Signature-256": "sha256=invalid_signature"
        }
    )
    assert response.status_code == 401
    assert "signature verification failed" in response.json()["detail"]

@pytest.mark.asyncio
async def test_webhook_successful_ingestion_and_deduplication(client: AsyncClient, db_session: AsyncSession):
    # Setup mock User and Repository
    user = User(
        github_user_id=54321,
        github_username="webhookuser",
        github_access_token_encrypted=encrypt_token("mock_token_2")
    )
    db_session.add(user)
    await db_session.flush()

    repo = Repository(
        user_id=user.id,
        github_repo_id=112233,
        name="webhook-repo",
        owner="webhookuser",
        full_name="webhookuser/webhook-repo",
        is_active=True,
        webhook_secret_encrypted=encrypt_token("my_webhook_secret"),
        webhook_id=22222
    )
    db_session.add(repo)
    await db_session.commit()

    payload = {
        "action": "opened",
        "issue": {
            "number": 42,
            "title": "Unexpected crashing bug in home page",
            "body": "It crashes when clicking search button."
        },
        "repository": {
            "full_name": "webhookuser/webhook-repo"
        }
    }
    
    import json
    raw_payload_bytes = json.dumps(payload).encode("utf-8")
    sig = compute_signature(raw_payload_bytes, "my_webhook_secret")
    delivery_id = str(uuid.uuid4())

    # Send correct webhook
    response = await client.post(
        "/api/v1/webhooks/github",
        content=raw_payload_bytes,
        headers={
            "Content-Type": "application/json",
            "X-GitHub-Event": "issues",
            "X-GitHub-Delivery": delivery_id,
            "X-Hub-Signature-256": sig
        }
    )
    assert response.status_code == 202
    assert response.json()["detail"] == "Webhook event accepted and queued for processing."
    event_id = response.json()["event_id"]

    # Verify event stored in database
    parsed_evt_id = uuid.UUID(event_id) if isinstance(event_id, str) else event_id
    evt_query = await db_session.execute(
        select(WebhookEvent).where(WebhookEvent.id == parsed_evt_id)
    )
    db_evt = evt_query.scalar_one_or_none()
    assert db_evt is not None
    assert db_evt.delivery_id == uuid.UUID(delivery_id)
    assert db_evt.status == "pending"

    # Send the exact same webhook delivery ID to verify deduplication (idempotency check)
    response_dup = await client.post(
        "/api/v1/webhooks/github",
        content=raw_payload_bytes,
        headers={
            "Content-Type": "application/json",
            "X-GitHub-Event": "issues",
            "X-GitHub-Delivery": delivery_id,
            "X-Hub-Signature-256": sig
        }
    )
    assert response_dup.status_code == 200
    assert response_dup.json()["detail"] == "Webhook event delivery duplicate, skipped processing."
