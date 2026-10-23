import asyncio
import json
import logging
from collections import deque
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional
from starlette.websockets import WebSocket, WebSocketState

logger = logging.getLogger("app.services.event_stream")

class EventStreamBroker:
    """
    Central real-time Pub/Sub broker for Darkrai dashboard observability.
    Supports authenticated WebSocket connections, Server-Sent Events (SSE), and retains a ring buffer
    of recent activity logs partitioned/filtered by user tenant.
    """

    def __init__(self, buffer_size: int = 100):
        # Map connection -> optional user_id
        self._websockets: Dict[WebSocket, Optional[str]] = {}
        self._sse_queues: Dict[asyncio.Queue, Optional[str]] = {}
        self._recent_events: deque = deque(maxlen=buffer_size)
        self._lock = asyncio.Lock()

    async def register_websocket(self, websocket: WebSocket, user_id: Optional[str] = None) -> None:
        """Registers a new active WebSocket connection and transmits user-scoped event history."""
        str_user_id = str(user_id) if user_id else None
        async with self._lock:
            self._websockets[websocket] = str_user_id
            logger.info("WebSocket client registered (user: %s). Active clients: %d", str_user_id, len(self._websockets))
            history = [
                e for e in self._recent_events
                if e.get("user_id") is None or str_user_id is None or e.get("user_id") == str_user_id
            ]

        for event in history:
            try:
                await websocket.send_text(json.dumps(event))
            except Exception:
                break

    async def unregister_websocket(self, websocket: WebSocket) -> None:
        """Removes a disconnected WebSocket connection."""
        async with self._lock:
            self._websockets.pop(websocket, None)
            logger.info("WebSocket client disconnected. Active clients: %d", len(self._websockets))

    async def register_sse_subscriber(self, user_id: Optional[str] = None) -> asyncio.Queue:
        """Registers a new SSE listener queue and feeds user-scoped history."""
        str_user_id = str(user_id) if user_id else None
        queue: asyncio.Queue = asyncio.Queue(maxsize=200)
        async with self._lock:
            self._sse_queues[queue] = str_user_id
            history = [
                e for e in self._recent_events
                if e.get("user_id") is None or str_user_id is None or e.get("user_id") == str_user_id
            ]

        for event in history:
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                pass
        return queue

    async def unregister_sse_subscriber(self, queue: asyncio.Queue) -> None:
        """Removes an active SSE listener queue."""
        async with self._lock:
            self._sse_queues.pop(queue, None)

    async def broadcast(
        self,
        event_type: str,
        data: Dict[str, Any],
        level: str = "INFO",
        user_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Broadcasts an event to authorized WebSocket clients and SSE streams.
        Formats payload with timestamp, log level, user_id context, and structured metadata.
        """
        str_user_id = str(user_id) if user_id else None
        message = {
            "type": event_type,
            "level": level,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "data": data,
            "user_id": str_user_id
        }

        async with self._lock:
            self._recent_events.append(message)
            dead_websockets = []
            for ws, ws_user_id in list(self._websockets.items()):
                # Only dispatch if system event (str_user_id is None) or matching subscriber
                if str_user_id is not None and ws_user_id is not None and ws_user_id != str_user_id:
                    continue
                try:
                    if ws.client_state == WebSocketState.CONNECTED:
                        await ws.send_text(json.dumps(message))
                    else:
                        dead_websockets.append(ws)
                except Exception as err:
                    logger.debug("Failed sending to WebSocket client: %s", err)
                    dead_websockets.append(ws)
            for ws in dead_websockets:
                self._websockets.pop(ws, None)

            dead_sse = []
            for q, sse_user_id in list(self._sse_queues.items()):
                if str_user_id is not None and sse_user_id is not None and sse_user_id != str_user_id:
                    continue
                try:
                    q.put_nowait(message)
                except asyncio.QueueFull:
                    try:
                        q.get_nowait()
                        q.put_nowait(message)
                    except Exception:
                        dead_sse.append(q)
            for q in dead_sse:
                self._sse_queues.pop(q, None)

        return message

    def get_recent_events(self, user_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """Returns snapshot of recent broadcast events, filtered by user tenant if specified."""
        str_user_id = str(user_id) if user_id else None
        if str_user_id is None:
            return list(self._recent_events)
        return [
            e for e in self._recent_events
            if e.get("user_id") is None or e.get("user_id") == str_user_id
        ]

    @property
    def subscriber_count(self) -> int:
        return len(self._websockets) + len(self._sse_queues)

# Global singleton instance
stream_broker = EventStreamBroker()

