from __future__ import annotations

import asyncio
import json
import logging
from collections import defaultdict
from typing import Any, Optional

from fastapi import WebSocket

from src.constants import REDIS_URL

logger = logging.getLogger(__name__)

_BUS = "pw:realtime"


class RealtimeHub:
    """WebSocket channels. Each uvicorn worker holds its own sockets, so a broadcast is published
    on Redis and every worker (this one included) delivers it to the sockets it holds - a user on
    worker 2 sees an update raised on worker 1. If Redis is unreachable, delivery falls back to
    this worker's sockets only (the single-worker behaviour)."""

    def __init__(self) -> None:
        self._channels: dict[str, set[WebSocket]] = defaultdict(set)
        self._lock = asyncio.Lock()
        self._bus_lock = asyncio.Lock()
        self._redis: Any = None
        self._listener: Optional[asyncio.Task] = None

    async def _ensure_bus(self) -> bool:
        if self._listener is not None and not self._listener.done():
            return True
        async with self._bus_lock:  # one listener per worker, or messages arrive twice
            if self._listener is not None and not self._listener.done():
                return True
            return await self._start_bus()

    async def _start_bus(self) -> bool:
        try:
            import redis.asyncio as aioredis
            if self._redis is None:
                self._redis = aioredis.from_url(REDIS_URL, socket_connect_timeout=2)
            pubsub = self._redis.pubsub()
            await pubsub.subscribe(_BUS)
            self._listener = asyncio.create_task(self._listen(pubsub))
            return True
        except Exception as exc:
            logger.warning("realtime: Redis bus unavailable (%s); broadcasting to this worker only", exc)
            self._redis = None
            return False

    async def _listen(self, pubsub) -> None:
        try:
            async for msg in pubsub.listen():
                if msg.get("type") != "message":
                    continue
                try:
                    data = json.loads(msg["data"])
                    await self._deliver(data["channel"], data["message"])
                except Exception as exc:
                    logger.warning("realtime: bad bus message: %s", exc)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("realtime: Redis bus listener stopped (%s); will resubscribe on next use", exc)

    async def connect(self, channel: str, websocket: WebSocket) -> None:
        await websocket.accept()
        async with self._lock:
            self._channels[channel].add(websocket)
        await self._ensure_bus()

    async def disconnect(self, channel: str, websocket: WebSocket) -> None:
        async with self._lock:
            conns = self._channels.get(channel)
            if not conns:
                return
            conns.discard(websocket)
            if not conns:
                self._channels.pop(channel, None)

    async def broadcast(self, channel: str, payload: dict[str, Any]) -> None:
        message = json.dumps(payload, default=str)
        if await self._ensure_bus():
            try:
                await self._redis.publish(_BUS, json.dumps({"channel": channel, "message": message}))
                return  # every worker, this one included, delivers it from the bus
            except Exception as exc:
                logger.warning("realtime: publish failed (%s); delivering on this worker only", exc)
        await self._deliver(channel, message)

    def broadcast_threadsafe(self, channel: str, payload: dict[str, Any]) -> None:
        """Best-effort broadcast from sync code (handlers in the thread pool, background threads)."""
        try:
            asyncio.get_running_loop().create_task(self.broadcast(channel, payload))
            return
        except RuntimeError:
            pass  # no loop in this thread
        try:
            import redis
            message = json.dumps(payload, default=str)
            redis.Redis.from_url(REDIS_URL, socket_connect_timeout=2, socket_timeout=3).publish(
                _BUS, json.dumps({"channel": channel, "message": message}))
        except Exception as exc:
            logger.warning("realtime: threadsafe broadcast on %s dropped: %s", channel, exc)

    async def _deliver(self, channel: str, message: str) -> None:
        async with self._lock:
            sockets = list(self._channels.get(channel, set()))
        if not sockets:
            return

        failed: list[WebSocket] = []
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
