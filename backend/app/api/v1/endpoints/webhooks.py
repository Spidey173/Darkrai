import json
import logging
import uuid as _uuid_module
from fastapi import APIRouter, Request, Header, HTTPException, status, Depends, Response
from sqlalchemy import select
from sqlalchemy.orm import joinedload, selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.api.deps import get_db
from backend.app.models.repository import Repository
from backend.app.models.event import WebhookEvent
from backend.app.utils.signature import verify_signature
from backend.app.services.encryption import decrypt_token
from backend.app.services.queue import event_queue
from backend.app.services.event_stream import stream_broker
from backend.app.core.config import settings

logger = logging.getLogger("app.api.v1.webhooks")
router = APIRouter()

@router.post("/github", status_code=status.HTTP_202_ACCEPTED)
async def github_webhook_receiver(
    request: Request,
    response: Response,
    x_github_event: str = Header(...),
    x_github_delivery: str = Header(...),
    x_hub_signature_256: str = Header(...),
    db: AsyncSession = Depends(get_db)
) -> dict:
    body = await request.body()
    try:
        payload = json.loads(body.decode("utf-8"))
    except json.JSONDecodeError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Malformed JSON payload.")

    repo_name = payload.get("repository", {}).get("full_name")
    if not repo_name:
        logger.warning("Received webhook event '%s' missing repository metadata.", x_github_delivery)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, 
            detail="Missing repository metadata in payload."
        )

    result = await db.execute(
        select(Repository)
        .options(joinedload(Repository.user), selectinload(Repository.rules))
        .where(Repository.full_name == repo_name)
    )
    repo = result.scalar_one_or_none()
    if not repo:
        logger.warning("Received event for unconnected repository '%s'.", repo_name)
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, 
            detail="Repository not connected to database."
        )

    webhook_secret = decrypt_token(repo.webhook_secret_encrypted)
    if not verify_signature(body, x_hub_signature_256, webhook_secret):
        logger.warning("Webhook signature verification failed for repo: %s", repo_name)
        await stream_broker.broadcast("webhook:auth_failed", {
            "delivery_id": x_github_delivery,
            "repo": repo_name,
            "event_type": x_github_event
        }, level="WARNING")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, 
            detail="HMAC signature verification failed."
        )

    try:
        parsed_delivery_id = _uuid_module.UUID(x_github_delivery)
    except Exception:
        parsed_delivery_id = _uuid_module.uuid5(_uuid_module.NAMESPACE_DNS, x_github_delivery)

    evt_check = await db.execute(
        select(WebhookEvent).where(WebhookEvent.delivery_id == parsed_delivery_id)
    )
    existing_event = evt_check.scalar_one_or_none()
    if existing_event:
        logger.info("Webhook delivery ID '%s' already ingested. Skipping duplicate.", x_github_delivery)
        response.status_code = status.HTTP_200_OK
        return {"detail": "Webhook event delivery duplicate, skipped processing."}

    action = payload.get("action")

    new_event = WebhookEvent(
        repository_id=repo.id,
        delivery_id=parsed_delivery_id,
        event_type=x_github_event,
        action=action,
        payload=payload,
        status="pending",
        retry_count=0
    )
    db.add(new_event)
    await db.commit()
    await db.refresh(new_event)

    await stream_broker.broadcast("webhook:ingested", {
        "event_id": str(new_event.id),
        "delivery_id": str(x_github_delivery),
        "event_type": x_github_event,
        "action": action,
        "repository": repo_name
    })

    if x_github_event in ("issues", "pull_request"):
        await event_queue.enqueue(
            event_id=str(new_event.id),
            delivery_id=str(x_github_delivery),
            payload_summary={
                "event_type": x_github_event,
                "action": action,
                "repo": repo_name
            }
        )
        if settings.VERCEL:
            from backend.app.services.event_processor import process_webhook_event
            try:
                await process_webhook_event(
                    event_id=str(new_event.id),
                    db=db,
                    event=new_event,
                    repository=repo,
                    owner_user=repo.user
                )
            except Exception as proc_err:
                logger.error("Failed processing event inline on Vercel: %s", proc_err, exc_info=True)

        return {
            "detail": "Webhook event accepted and queued for processing.",
            "event_id": str(new_event.id),
            "delivery_id": str(x_github_delivery),
            "queue_backend": event_queue.metrics["backend"]
        }
    else:
        new_event.status = "completed"
        await db.commit()
        return {"detail": f"Webhook event type '{x_github_event}' ingested. No rule actions executed."}
