import os
import uuid
from datetime import datetime, timezone, timedelta
import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.config import Settings, DEV_FALLBACK_SECRET_KEY, DEV_FALLBACK_ENCRYPTION_KEY
from backend.app.models.user import User
from backend.app.models.repository import Repository
from backend.app.models.event import WebhookEvent
from backend.app.services.encryption import encrypt_token, decrypt_token
from backend.app.services.event_processor import process_webhook_event
from backend.app.utils.jwt import create_session_token

def test_production_secret_validation_fail_fast():
    # 1. Production startup must fail if SECRET_KEY is missing or insecure default
    with pytest.raises(ValueError, match="SECRET_KEY is missing or using an insecure default"):
        Settings(
            APP_ENV="production",
            SECRET_KEY="",
            ENCRYPTION_KEY=DEV_FALLBACK_ENCRYPTION_KEY,
            _env_file=None
        )

    # 2. Production startup must fail if ENCRYPTION_KEY is missing or insecure default
    with pytest.raises(ValueError, match="ENCRYPTION_KEY is missing or using an insecure default"):
        Settings(
            APP_ENV="production",
            SECRET_KEY="a" * 32,
            ENCRYPTION_KEY="",
            _env_file=None
        )

    # 3. Development startup must seamlessly use safe fallbacks without failing
    dev_settings = Settings(
        APP_ENV="development",
        SECRET_KEY="",
        ENCRYPTION_KEY="",
        _env_file=None
    )
    assert dev_settings.SECRET_KEY == DEV_FALLBACK_SECRET_KEY
    assert dev_settings.ENCRYPTION_KEY == DEV_FALLBACK_ENCRYPTION_KEY

@pytest.mark.asyncio
async def test_repository_slack_credential_protection(client: AsyncClient, db_session: AsyncSession):
    # Setup authenticated user
    user = User(
        github_user_id=77777,
        github_username="secuser",
        github_access_token_encrypted=encrypt_token("tok")
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)

    token = create_session_token(str(user.id))
    headers = {"Authorization": f"Bearer {token}"}

    # Connect repository with sensitive Slack Webhook
    secret_slack_url = "https://hooks.slack.com/services/T00/B00/SECRET_WEBHOOK_KEY"
    connect_payload = {
        "github_repo_id": 999111,
        "name": "secure-repo",
        "owner": "secuser",
        "full_name": "secuser/secure-repo",
        "slack_webhook_url": secret_slack_url
    }

    res = await client.post("/api/v1/repos/connect", json=connect_payload, headers=headers)
    assert res.status_code == 201
    repo_data = res.json()

    # Verify secret plaintext URL is NEVER returned in response
    assert repo_data["slack_webhook_url"] is None
    assert repo_data["has_slack_webhook"] is True
    repo_id = repo_data["id"]

    # Verify DB has stored encrypted value
    db_repo = (await db_session.execute(select(Repository).where(Repository.id == uuid.UUID(repo_id)))).scalar_one()
    assert db_repo.slack_webhook_url_encrypted != secret_slack_url
    assert decrypt_token(db_repo.slack_webhook_url_encrypted) == secret_slack_url

    # Test listing connected repos also never exposes the decrypted URL
    list_res = await client.get("/api/v1/repos", headers=headers)
    assert list_res.status_code == 200
    found = [r for r in list_res.json() if r["id"] == repo_id][0]
    assert found["has_slack_webhook"] is True
    assert found["slack_webhook_url"] is None

    # Test rotating the credential via PATCH /api/v1/repos/{id}/slack-webhook
    new_slack_url = "https://hooks.slack.com/services/T99/B99/NEW_ROTATED_KEY"
    patch_res = await client.patch(
        f"/api/v1/repos/{repo_id}/slack-webhook",
        json={"slack_webhook_url": new_slack_url},
        headers=headers
    )
    assert patch_res.status_code == 200
    assert patch_res.json()["has_slack_webhook"] is True
    assert patch_res.json()["slack_webhook_url"] is None

    await db_session.refresh(db_repo)
    assert decrypt_token(db_repo.slack_webhook_url_encrypted) == new_slack_url

    # Test clearing the credential
    clear_res = await client.patch(
        f"/api/v1/repos/{repo_id}/slack-webhook",
        json={"slack_webhook_url": None},
        headers=headers
    )
    assert clear_res.status_code == 200
    assert clear_res.json()["has_slack_webhook"] is False
    assert clear_res.json()["slack_webhook_url"] is None

    await db_session.refresh(db_repo)
    assert db_repo.slack_webhook_url_encrypted is None

@pytest.mark.asyncio
async def test_atomic_event_claiming_prevents_duplicate_processing(db_session: AsyncSession):
    user = User(
        github_user_id=66666,
        github_username="claimuser",
        github_access_token_encrypted=encrypt_token("tok")
    )
    db_session.add(user)
    await db_session.flush()

    repo = Repository(
        user_id=user.id,
        github_repo_id=55555,
        name="claim-repo",
        owner="claimuser",
        full_name="claimuser/claim-repo",
        is_active=True,
        webhook_secret_encrypted=encrypt_token("sec")
    )
    db_session.add(repo)
    await db_session.flush()

    evt = WebhookEvent(
        repository_id=repo.id,
        delivery_id=uuid.uuid4(),
        event_type="issues",
        action="opened",
        payload={"action": "opened", "issue": {"number": 1, "title": "Test"}},
        status="processing",  # Already claimed by another worker
        retry_count=0
    )
    db_session.add(evt)
    await db_session.commit()
    await db_session.refresh(evt)

    # Calling process_webhook_event on an already processing event must skip safely without raising
    await process_webhook_event(event_id=str(evt.id), db=db_session)
    await db_session.refresh(evt)
    # Status remains processing, was not re-claimed
    assert evt.status == "processing"

@pytest.mark.asyncio
async def test_recovery_scanner_processes_stranded_pending_events(db_session: AsyncSession):
    user = User(
        github_user_id=10101,
        github_username="recuser",
        github_access_token_encrypted=encrypt_token("tok")
    )
    db_session.add(user)
    await db_session.flush()

    repo = Repository(
        user_id=user.id,
        github_repo_id=20202,
        name="rec-repo",
        owner="recuser",
        full_name="recuser/rec-repo",
        is_active=True,
        webhook_secret_encrypted=encrypt_token("sec")
    )
    db_session.add(repo)
    await db_session.flush()

    # Stranded pending event created 10 seconds ago (never enqueued due to simulated crash)
    ten_seconds_ago = datetime.now(timezone.utc) - timedelta(seconds=10)
    evt = WebhookEvent(
        repository_id=repo.id,
        delivery_id=uuid.uuid4(),
        event_type="issues",
        action="opened",
        payload={"action": "opened", "issue": {"number": 99, "title": "Recovered Bug"}},
        status="pending",
        retry_count=0,
        created_at=ten_seconds_ago
    )
    db_session.add(evt)
    await db_session.commit()
    await db_session.refresh(evt)

    # Trigger recovery scan
    from backend.app.services.queue import event_queue
    recovered = await event_queue.recover_stranded_events()
    assert recovered >= 1

    await db_session.refresh(evt)
    assert evt.status == "completed"

@pytest.mark.asyncio
async def test_recovery_scanner_detects_worker_lease_expiration_and_dlq(db_session: AsyncSession):
    user = User(
        github_user_id=30303,
        github_username="leaseuser",
        github_access_token_encrypted=encrypt_token("tok")
    )
    db_session.add(user)
    await db_session.flush()

    repo = Repository(
        user_id=user.id,
        github_repo_id=40404,
        name="lease-repo",
        owner="leaseuser",
        full_name="leaseuser/lease-repo",
        is_active=True,
        webhook_secret_encrypted=encrypt_token("sec")
    )
    db_session.add(repo)
    await db_session.flush()

    # Event stranded in 'processing' whose worker died over 300s ago, with max retries exceeded
    stale_time = datetime.now(timezone.utc) - timedelta(seconds=350)
    evt = WebhookEvent(
        repository_id=repo.id,
        delivery_id=uuid.uuid4(),
        event_type="issues",
        action="opened",
        payload={"action": "opened", "issue": {"number": 100, "title": "Dead Worker Event"}},
        status="processing",
        retry_count=3,  # Max retries
        updated_at=stale_time
    )
    db_session.add(evt)
    await db_session.commit()
    await db_session.refresh(evt)

    from backend.app.services.queue import event_queue
    await event_queue.recover_stranded_events(stale_seconds=300)

    await db_session.refresh(evt)
    assert evt.status == "failed"
    assert "lease expired" in evt.error_message
