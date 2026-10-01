import asyncio
import json
import logging
from collections import deque
from datetime import datetime, timezone
from typing import Dict, Any, List, Set, Optional
from starlette.websockets import WebSocket, WebSocketState

logger = logging.getLogger("app.services.event_stream")

class EventStreamBroker:
    """
    Central real-time Pub/Sub broker for Darkrai dashboard observability.
    Supports WebSocket connections, Server-Sent Events (SSE), and retains a ring buffer
    of recent activity logs for newly connected clients.
    """

    def __init__(self, buffer_size: int = 100):
        self._websockets: Set[WebSocket] = set()
        self._sse_queues: Set[asyncio.Queue] = set()
        self._recent_events: deque = deque(maxlen=buffer_size)
        self._lock = asyncio.Lock()

    async def register_websocket(self, websocket: WebSocket) -> None:
        """Registers a new active WebSocket connection and transmits event history."""
        async with self._lock:
            self._websockets.add(websocket)
            logger.info("WebSocket client registered. Active clients: %d", len(self._websockets))
            # Replay recent events for immediate context
            history = list(self._recent_events)
        
        # Send history outside the lock
        for event in history:
            try:
                await websocket.send_text(json.dumps(event))
            except Exception:
                break

    async def unregister_websocket(self, websocket: WebSocket) -> None:
        """Removes a disconnected WebSocket connection."""
        async with self._lock:
            self._websockets.discard(websocket)
            logger.info("WebSocket client disconnected. Active clients: %d", len(self._websockets))

    async def register_sse_subscriber(self) -> asyncio.Queue:
        """Registers a new SSE listener queue and feeds history."""
        queue: asyncio.Queue = asyncio.Queue(maxsize=200)
        async with self._lock:
            self._sse_queues.add(queue)
            history = list(self._recent_events)

        for event in history:
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                pass
        return queue

    async def unregister_sse_subscriber(self, queue: asyncio.Queue) -> None:
        """Removes an active SSE listener queue."""
        async with self._lock:
            self._sse_queues.discard(queue)

    async def broadcast(self, event_type: str, data: Dict[str, Any], level: str = "INFO") -> Dict[str, Any]:
        """
        Broadcasts an event to all connected WebSocket clients and SSE streams.
        Formats payload with timestamp, log level, and structured metadata.
        """
        message = {
            "type": event_type,
            "level": level,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "data": data
        }

        async with self._lock:
            self._recent_events.append(message)
            dead_websockets = set()
            for ws in self._websockets:
                try:
                    if ws.client_state == WebSocketState.CONNECTED:
                        await ws.send_text(json.dumps(message))
                    else:
                        dead_websockets.add(ws)
                except Exception as err:
                    logger.debug("Failed sending to WebSocket client: %s", err)
                    dead_websockets.add(ws)
            self._websockets.difference_update(dead_websockets)

            dead_sse = set()
            for q in self._sse_queues:
                try:
                    q.put_nowait(message)
                except asyncio.QueueFull:
                    # Drop oldest and enqueue
                    try:
                        q.get_nowait()
                        q.put_nowait(message)
                    except Exception:
                        dead_sse.add(q)
            self._sse_queues.difference_update(dead_sse)

        return message

    def get_recent_events(self) -> List[Dict[str, Any]]:
        """Returns snapshot of recent broadcast events in chronological order."""
        return list(self._recent_events)

    @property
    def subscriber_count(self) -> int:
        return len(self._websockets) + len(self._sse_queues)

# Global singleton instance
stream_broker = EventStreamBroker()
