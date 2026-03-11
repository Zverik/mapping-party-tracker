"""WebSocket connection manager for real-time project updates."""
import json
import logging
from collections import defaultdict
from fastapi import WebSocket

logger = logging.getLogger(__name__)


class ConnectionManager:
    def __init__(self):
        # project_id -> list of connected websockets
        self._connections: dict[int, list[WebSocket]] = defaultdict(list)

    async def connect(self, project_id: int, websocket: WebSocket):
        await websocket.accept()
        self._connections[project_id].append(websocket)
        logger.debug("WS client connected to project %d (total: %d)",
                     project_id, len(self._connections[project_id]))

    def disconnect(self, project_id: int, websocket: WebSocket):
        try:
            self._connections[project_id].remove(websocket)
        except ValueError:
            pass
        logger.debug("WS client disconnected from project %d (remaining: %d)",
                     project_id, len(self._connections[project_id]))

    async def broadcast(self, project_id: int, event: dict, exclude: WebSocket | None = None):
        """Broadcast a JSON event to all clients in a project room."""
        message = json.dumps(event)
        dead = []
        for ws in list(self._connections[project_id]):
            if ws is exclude:
                continue
            try:
                await ws.send_text(message)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(project_id, ws)


manager = ConnectionManager()


# ─── Event constructors ────────────────────────────────────────────────────────

def claimed_event(polygon_id: int, user_id: int, username: str) -> dict:
    return {
        "type": "claimed",
        "polygon_id": polygon_id,
        "user_id": user_id,
        "username": username,
    }


def released_event(polygon_id: int) -> dict:
    return {
        "type": "released",
        "polygon_id": polygon_id,
    }


def status_event(polygon_id: int, status: int) -> dict:
    return {
        "type": "status",
        "polygon_id": polygon_id,
        "status": status,
    }
