import asyncio
import hashlib
import json
import uuid
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.models.user import User
from backend.app.models.repository import Repository
from backend.app.models.rule import Rule
from backend.app.models.event import WebhookEvent
from backend.app.models.action_log import ActionLog
from backend.app.services.encryption import encrypt_token
from backend.app.services.event_processor import process_webhook_event
from backend.app.services.queue import EventQueue, event_queue
from backend.app.utils.jwt import create_session_token

@pytest.mark.asyncio
async def test_concurrent_multiple_workers_competing(db_session: AsyncSession):
    """
    Verifies that multiple worker instances competing for the same event
    atomically acquire exclusive lease ownership without duplicate execution.
    """
    user = User(
        github_user_id=121212,
        github_username="concur_user",
        github_access_token_encrypted=encrypt_token("gh_token_1212")
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)

    repo = Repository(
        user_id=user.id,
        github_repo_id=989898,
        name="concur-repo",
        owner="concur_user",
        full_name="concur_user/concur-repo",
        is_active=True
    )
    db_session.add(repo)
    await db_session.commit()
    await db_session.refresh(repo)

    event = WebhookEvent(
        repository_id=repo.id,
        delivery_id=uuid.uuid4(),
        event_type="issues",
        action="opened",
        payload={"issue": {"number": 1, "title": "Test Concurrency", "body": "Body"}},
        status="pending"
    )
    db_session.add(event)
    await db_session.commit()
    await db_session.refresh(event)

    # Spawn 3 concurrent worker attempts with distinct worker IDs
    worker_1_id = "worker-alpha-001"
    worker_2_id = "worker-beta-002"
    worker_3_id = "worker-gamma-003"

    results = await asyncio.gather(
        process_webhook_event(str(event.id), db=None, worker_id=worker_1_id),
        process_webhook_event(str(event.id), db=None, worker_id=worker_2_id),
        process_webhook_event(str(event.id), db=None, worker_id=worker_3_id),
        return_exceptions=False
    )

    # Refresh event from DB
    await db_session.refresh(event)
    assert event.status == "completed"
    # Exactly one worker claimed and owned the execution
    assert event.retry_count == 0

@pytest.mark.asyncio
async def test_slow_job_lease_renewal_prevents_theft(db_session: AsyncSession):
    """
    Verifies that a slow-running job actively renews its worker lease,
    preventing the recovery scanner from reclaiming an ongoing task.
    """
    user = User(
        github_user_id=131313,
        github_username="slow_user",
        github_access_token_encrypted=encrypt_token("gh_token_slow")
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)

    repo = Repository(
        user_id=user.id,
        github_repo_id=767676,
        name="slow-repo",
        owner="slow_user",
        full_name="slow_user/slow-repo",
        is_active=True
    )
    db_session.add(repo)
    await db_session.commit()
    await db_session.refresh(repo)

    event = WebhookEvent(
        repository_id=repo.id,
        delivery_id=uuid.uuid4(),
        event_type="issues",
        action="opened",
        payload={"issue": {"number": 2, "title": "Slow Task", "body": "Body"}},
        status="pending"
    )
    db_session.add(event)
    await db_session.commit()
    await db_session.refresh(event)

    worker_id = "worker-slow-101"
    # Claim event with a short 2-second lease
    now = datetime.now(timezone.utc)
    event.status = "processing"
    event.worker_id = worker_id
    # Set lease to be in the FUTURE (active job)
    event.lease_expires_at = now + timedelta(seconds=60)
    await db_session.commit()

    # Run recovery scanner
    test_queue = EventQueue()
    recovered = await test_queue.recover_stranded_events(stale_seconds=30)

    # Active lease must NOT be reclaimed
    await db_session.refresh(event)
    assert event.status == "processing"
    assert event.worker_id == worker_id
    assert recovered == 0

@pytest.mark.asyncio
async def test_dead_worker_lease_expiration_reclaimed(db_session: AsyncSession):
    """
    Verifies that if a worker crashes and stops renewing its lease,
    the recovery scanner detects the expired lease and reclaims the event.
    """
    user = User(
        github_user_id=141414,
        github_username="crashed_user",
        github_access_token_encrypted=encrypt_token("gh_token_crash")
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)

    repo = Repository(
        user_id=user.id,
        github_repo_id=545454,
        name="crashed-repo",
        owner="crashed_user",
        full_name="crashed_user/crashed-repo",
        is_active=True
    )
    db_session.add(repo)
    await db_session.commit()
    await db_session.refresh(repo)

    # Event stranded in 'processing' with an EXPIRED lease (worker died)
    expired_time = datetime.now(timezone.utc) - timedelta(seconds=10)
    event = WebhookEvent(
        repository_id=repo.id,
        delivery_id=uuid.uuid4(),
        event_type="issues",
        action="opened",
        payload={"issue": {"number": 3, "title": "Crash Recovery", "body": "Body"}},
        status="processing",
        worker_id="dead-worker-999",
        lease_expires_at=expired_time,
        retry_count=0
    )
    db_session.add(event)
    await db_session.commit()
    await db_session.refresh(event)

    test_queue = EventQueue()
    recovered = await test_queue.recover_stranded_events(stale_seconds=5)

    assert recovered == 1
    await db_session.refresh(event)
    assert event.status == "completed"
    assert event.retry_count == 1

@pytest.mark.asyncio
async def test_action_idempotency_prevents_duplicate_side_effects(db_session: AsyncSession):
    """
    Verifies that if a worker executes an action (e.g. comment or label),
    then crashes before marking the event complete, subsequent retries reconcile
    the completed action state and do NOT duplicate external API calls.
    """
    user = User(
        github_user_id=151515,
        github_username="idem_user",
        github_access_token_encrypted=encrypt_token("gh_token_idem")
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)

    repo = Repository(
        user_id=user.id,
        github_repo_id=323232,
        name="idem-repo",
        owner="idem_user",
        full_name="idem_user/idem-repo",
        is_active=True
    )
    db_session.add(repo)
    await db_session.commit()
    await db_session.refresh(repo)

    rule = Rule(
        repository_id=repo.id,
        name="Idempotent Rule",
        event_type="issues",
        conditions={"field": "issue.title", "operator": "contains", "value": "Bug"},
        actions=[
            {"type": "create_comment", "value": "Automated bug acknowledgement"},
            {"type": "add_label", "value": "triage:needed"}
        ],
        is_active=True
    )
    db_session.add(rule)
    await db_session.commit()
    await db_session.refresh(rule)

    event = WebhookEvent(
        repository_id=repo.id,
        delivery_id=uuid.uuid4(),
        event_type="issues",
        action="opened",
        payload={"issue": {"number": 42, "title": "Critical Bug in Auth", "body": "Details"}},
        status="pending"
    )
    db_session.add(event)
    await db_session.commit()
    await db_session.refresh(event)

    # First attempt: simulate mock GitHub calls
    with patch("backend.app.services.github_client.GitHubClient.add_comment_to_issue", new_callable=AsyncMock) as mock_comment, \
         patch("backend.app.services.github_client.GitHubClient.add_label_to_issue", new_callable=AsyncMock) as mock_label:

        mock_comment.return_value = {"id": 1001, "body": "Automated bug acknowledgement"}
        mock_label.return_value = [{"name": "triage:needed"}]

        # Run first attempt
        await process_webhook_event(str(event.id), db=db_session, worker_id="worker-run-1")

        assert mock_comment.call_count == 1
        assert mock_label.call_count == 1

        # Verify ActionLog entries were created with deterministic idempotency keys
        logs = (await db_session.execute(
            select(ActionLog).where(ActionLog.webhook_event_id == event.id)
        )).scalars().all()
        assert len(logs) == 2
        for l in logs:
            assert l.status == "success"
            assert l.idempotency_key is not None

        # Simulate a crash/retry scenario: reset event status to 'pending' to re-run
        event.status = "pending"
        await db_session.commit()

        # Run second attempt (retry)
        await process_webhook_event(str(event.id), db=db_session, worker_id="worker-run-2")

        # Mock calls must NOT have been called again (call counts remain 1)
        assert mock_comment.call_count == 1
        assert mock_label.call_count == 1

@pytest.mark.asyncio
async def test_cookie_csrf_protection_on_state_changing_routes(client: AsyncClient, db_session: AsyncSession):
    """
    Verifies that state-changing requests authenticated via cookie are rejected
    with 403 unless a CSRF protection custom header (X-Requested-With / X-CSRF-Token) is present.
    """
    user = User(
        github_user_id=161616,
        github_username="csrf_user",
        github_access_token_encrypted=encrypt_token("tok_csrf")
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)

    token = create_session_token(str(user.id))
    client.cookies.set("session_token", token)

    repo_payload = {
        "github_repo_id": 888111,
        "name": "csrf-test",
        "owner": "csrf_user",
        "full_name": "csrf_user/csrf-test"
    }

    # 1. Without CSRF header -> Must be blocked (403)
    res_blocked = await client.post("/api/v1/repos/connect", json=repo_payload)
    assert res_blocked.status_code == 403
    assert "CSRF validation failed" in res_blocked.json()["detail"]

    # 2. With X-Requested-With header -> Allowed (201)
    res_allowed = await client.post(
        "/api/v1/repos/connect",
        json=repo_payload,
        headers={"X-Requested-With": "XMLHttpRequest"}
    )
    assert res_allowed.status_code == 201

    client.cookies.clear()

@pytest.mark.asyncio
async def test_dlq_replay_endpoint(client: AsyncClient, db_session: AsyncSession):
    """
    Verifies that dead-letter queue events can be replayed via the dashboard API.
    """
    user = User(
        github_user_id=171717,
        github_username="dlq_user",
        github_access_token_encrypted=encrypt_token("tok_dlq")
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)

    token = create_session_token(str(user.id))
    headers = {"Authorization": f"Bearer {token}"}

    # Create 2 dead-letter events
    dlq_evt1 = WebhookEvent(
        delivery_id=uuid.uuid4(),
        event_type="issues",
        payload={"issue": {"title": "Failed 1"}},
        status="dlq",
        retry_count=3,
        error_message="Downstream failure"
    )
    dlq_evt2 = WebhookEvent(
        delivery_id=uuid.uuid4(),
        event_type="pull_request",
        payload={"pull_request": {"title": "Failed 2"}},
        status="dlq",
        retry_count=3,
        error_message="Rate limit exceeded"
    )
    db_session.add_all([dlq_evt1, dlq_evt2])
    await db_session.commit()

    # Replay DLQ via API
    res = await client.post("/api/v1/dashboard/dlq/replay", json={}, headers=headers)
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "success"
    assert data["replayed_count"] >= 2

    # Verify both events were reset to 'pending' with retry_count = 0
    await db_session.refresh(dlq_evt1)
    await db_session.refresh(dlq_evt2)
    assert dlq_evt1.status == "pending"
    assert dlq_evt1.retry_count == 0
    assert dlq_evt2.status == "pending"
    assert dlq_evt2.retry_count == 0

@pytest.mark.asyncio
async def test_queue_stats_and_alerts_telemetry(client: AsyncClient, db_session: AsyncSession):
    """
    Verifies that queue telemetry returns depth, queue age, latency metrics, and alerts.
    """
    user = User(
        github_user_id=181818,
        github_username="telemetry_user",
        github_access_token_encrypted=encrypt_token("tok_telemetry")
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)

    token = create_session_token(str(user.id))
    headers = {"Authorization": f"Bearer {token}"}

    res = await client.get("/api/v1/dashboard/queue", headers=headers)
    assert res.status_code == 200
    telemetry = res.json()

    assert "worker_id" in telemetry
    assert "pending_events" in telemetry
    assert "dlq_events" in telemetry
    assert "queue_age_seconds" in telemetry
    assert "avg_latency_ms" in telemetry
    assert "p95_latency_ms" in telemetry
    assert "alerts" in telemetry
    assert isinstance(telemetry["alerts"], list)


@pytest.mark.asyncio
async def test_action_idempotency_reconciles_crash_before_success_log(db_session: AsyncSession):
    """
    Verifies the distributed crash scenario:
    An external service (GitHub) accepts an action (e.g. comment or label), but the worker
    crashes before saving the success log (leaving ActionLog status as 'in_progress').
    Upon retry/recovery, Darkrai reconciles against the external service via deterministic
    idempotency markers and prevents duplicate comments/labels.
    """
    user = User(
        github_user_id=191919,
        github_username="crash_user",
        github_access_token_encrypted=encrypt_token("gh_token_crash")
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)

    repo = Repository(
        user_id=user.id,
        github_repo_id=454545,
        name="crash-repo",
        owner="crash_user",
        full_name="crash_user/crash-repo",
        is_active=True
    )
    db_session.add(repo)
    await db_session.commit()
    await db_session.refresh(repo)

    rule = Rule(
        repository_id=repo.id,
        name="Crash Recovery Rule",
        event_type="issues",
        conditions={"field": "issue.title", "operator": "contains", "value": "Crash"},
        actions=[
            {"type": "create_comment", "value": "Crash recovery verification"},
            {"type": "add_label", "value": "recovered"}
        ],
        is_active=True
    )
    db_session.add(rule)
    await db_session.commit()
    await db_session.refresh(rule)

    event = WebhookEvent(
        repository_id=repo.id,
        delivery_id=uuid.uuid4(),
        event_type="issues",
        action="opened",
        payload={"issue": {"number": 99, "title": "Crash Scenario Test", "body": "Testing"}},
        status="pending"
    )
    db_session.add(event)
    await db_session.commit()
    await db_session.refresh(event)

    # Compute idempotency key for comment
    comment_val_repr = str("Crash recovery verification")
    comment_fp = f"{event.id}:{rule.id}:create_comment:{comment_val_repr}"
    comment_idemp_key = hashlib.sha256(comment_fp.encode("utf-8")).hexdigest()
    comment_marker = f"<!-- darkrai-idempotency:{comment_idemp_key} -->"

    # Compute idempotency key for label
    label_val_repr = str("recovered")
    label_fp = f"{event.id}:{rule.id}:add_label:{label_val_repr}"
    label_idemp_key = hashlib.sha256(label_fp.encode("utf-8")).hexdigest()

    # Pre-populate ActionLogs in 'in_progress' state to simulate worker crash right after GitHub accepted calls
    log_comment = ActionLog(
        webhook_event_id=event.id,
        rule_id=rule.id,
        action_type="create_comment",
        idempotency_key=comment_idemp_key,
        status="in_progress",
        details={"attempt": 1}
    )
    log_label = ActionLog(
        webhook_event_id=event.id,
        rule_id=rule.id,
        action_type="add_label",
        idempotency_key=label_idemp_key,
        status="in_progress",
        details={"attempt": 1}
    )
    db_session.add_all([log_comment, log_label])
    await db_session.commit()

    # When recovery worker runs:
    # list_issue_comments returns the comment that was accepted prior to crash
    # list_issue_labels returns the label that was accepted prior to crash
    with patch("backend.app.services.github_client.GitHubClient.list_issue_comments", new_callable=AsyncMock) as mock_list_comments, \
         patch("backend.app.services.github_client.GitHubClient.list_issue_labels", new_callable=AsyncMock) as mock_list_labels, \
         patch("backend.app.services.github_client.GitHubClient.add_comment_to_issue", new_callable=AsyncMock) as mock_add_comment, \
         patch("backend.app.services.github_client.GitHubClient.add_label_to_issue", new_callable=AsyncMock) as mock_add_label:

        mock_list_comments.return_value = [
            {"id": 555, "body": f"Crash recovery verification\n\n{comment_marker}"}
        ]
        mock_list_labels.return_value = ["recovered"]

        # Run recovery execution
        await process_webhook_event(str(event.id), db=db_session, worker_id="recovery-worker")

        # Proves NO duplicate side-effects were dispatched to GitHub
        assert mock_add_comment.call_count == 0
        assert mock_add_label.call_count == 0

        # Verifies that in_progress logs were reconciled to 'success'
        await db_session.refresh(log_comment)
        await db_session.refresh(log_label)
        assert log_comment.status == "success"
        assert log_comment.details.get("reconciled_after_crash") is True
        assert log_label.status == "success"
        assert log_label.details.get("reconciled_after_crash") is True

