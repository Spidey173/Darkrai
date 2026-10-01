import asyncio
import json
import logging
from typing import List, Dict, Any
from fastapi import APIRouter, Depends, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from backend.app.api.deps import get_db, get_current_user
from backend.app.models.user import User
from backend.app.models.event import WebhookEvent
from backend.app.models.action_log import ActionLog
from backend.app.models.repository import Repository
from backend.app.services.queue import event_queue
from backend.app.services.event_stream import stream_broker

logger = logging.getLogger("app.api.v1.dashboard")
router = APIRouter()

@router.get("/stats")
async def get_dashboard_stats(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
) -> Dict[str, Any]:
    repos_query = await db.execute(
        select(Repository.id).where(Repository.user_id == current_user.id)
    )
    repo_ids = [r for r, in repos_query.all()]
    
    if not repo_ids:
        return {
            "total_events": 0,
            "successful_events": 0,
            "failed_events": 0,
            "total_actions": 0,
            "active_repositories": 0
        }

    total_events = await db.execute(
        select(func.count(WebhookEvent.id)).where(WebhookEvent.repository_id.in_(repo_ids))
    )
    successful_events = await db.execute(
        select(func.count(WebhookEvent.id)).where(
            WebhookEvent.repository_id.in_(repo_ids),
            WebhookEvent.status == "completed"
        )
    )
    failed_events = await db.execute(
        select(func.count(WebhookEvent.id)).where(
            WebhookEvent.repository_id.in_(repo_ids),
            WebhookEvent.status == "failed"
        )
    )

    event_ids_query = await db.execute(
        select(WebhookEvent.id).where(WebhookEvent.repository_id.in_(repo_ids))
    )
    event_ids = [e for e, in event_ids_query.all()]
    
    total_actions = 0
    if event_ids:
        actions_count = await db.execute(
            select(func.count(ActionLog.id)).where(ActionLog.webhook_event_id.in_(event_ids))
        )
        total_actions = actions_count.scalar() or 0

    return {
        "total_events": total_events.scalar() or 0,
        "successful_events": successful_events.scalar() or 0,
        "failed_events": failed_events.scalar() or 0,
        "total_actions": total_actions,
        "active_repositories": len(repo_ids)
    }

@router.get("/events")
async def get_recent_events(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
) -> Dict[str, Any]:
    repos_query = await db.execute(
        select(Repository.id).where(Repository.user_id == current_user.id)
    )
    repo_ids = [r for r, in repos_query.all()]

    if not repo_ids:
        return {"events": [], "total": 0}

    total_query = await db.execute(
        select(func.count(WebhookEvent.id)).where(WebhookEvent.repository_id.in_(repo_ids))
    )
    total = total_query.scalar() or 0

    events_query = await db.execute(
        select(WebhookEvent)
        .where(WebhookEvent.repository_id.in_(repo_ids))
        .order_by(WebhookEvent.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    events = events_query.scalars().all()

    serialized_events = []
    for event in events:
        action_logs_query = await db.execute(
            select(ActionLog).where(ActionLog.webhook_event_id == event.id)
        )
        logs = action_logs_query.scalars().all()

        serialized_events.append({
            "id": str(event.id),
            "delivery_id": str(event.delivery_id),
            "event_type": event.event_type,
            "action": event.action,
            "status": event.status,
            "retry_count": event.retry_count,
            "error_message": event.error_message,
            "created_at": event.created_at,
            "processed_at": event.processed_at,
            "actions": [
                {
                    "id": str(log.id),
                    "action_type": log.action_type,
                    "status": log.status,
                    "details": log.details,
                    "created_at": log.created_at
                } for log in logs
            ]
        })

    return {"events": serialized_events, "total": total}

@router.get("/queue")
async def get_queue_telemetry() -> Dict[str, Any]:
    return await event_queue.get_queue_stats()

@router.get("/logs")
async def get_recent_stream_logs() -> List[Dict[str, Any]]:
    return stream_broker.get_recent_events()

@router.get("/stream")
async def sse_event_stream():
    async def event_generator():
        q = await stream_broker.register_sse_subscriber()
        try:
            while True:
                try:
                    data = await asyncio.wait_for(q.get(), timeout=15.0)
                    yield f"data: {json.dumps(data)}\n\n"
                except asyncio.TimeoutError:
                    yield ": heartbeat\n\n"
        except asyncio.CancelledError:
            pass
        finally:
            await stream_broker.unregister_sse_subscriber(q)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )

@router.websocket("/ws")
async def websocket_event_stream(websocket: WebSocket):
    await websocket.accept()
    await stream_broker.register_websocket(websocket)
    try:
        while True:
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_text(json.dumps({"type": "pong"}))
    except WebSocketDisconnect:
        await stream_broker.unregister_websocket(websocket)
    except Exception as exc:
        logger.debug("WebSocket terminated: %s", exc)
        await stream_broker.unregister_websocket(websocket)
