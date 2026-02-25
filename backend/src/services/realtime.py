from __future__ import annotations

import asyncio
import json
from collections import defaultdict
from typing import Any

from fastapi import WebSocket


class RealtimeHub:
    def __init__(self) -> None:
        self._channels: dict[str, set[WebSocket]] = defaultdict(set)
        self._lock = asyncio.Lock()

    async def connect(self, channel: str, websocket: WebSocket) -> None:
        await websocket.accept()
        async with self._lock:
            self._channels[channel].add(websocket)

    async def disconnect(self, channel: str, websocket: WebSocket) -> None:
        async with self._lock:
            conns = self._channels.get(channel)
            if not conns:
                return
            conns.discard(websocket)
            if not conns:
                self._channels.pop(channel, None)

    async def broadcast(self, channel: str, payload: dict[str, Any]) -> None:
        async with self._lock:
            sockets = list(self._channels.get(channel, set()))
        if not sockets:
            return

        failed: list[WebSocket] = []
        message = json.dumps(payload)
        for socket in sockets:
            try:
                await socket.send_text(message)
            except Exception:
                failed.append(socket)

        if failed:
            async with self._lock:
                conns = self._channels.get(channel)
                if not conns:
                    return
                for socket in failed:
                    conns.discard(socket)
                if not conns:
                    self._channels.pop(channel, None)


realtime_hub = RealtimeHub()
