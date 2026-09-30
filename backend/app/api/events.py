"""In-process event bus + WebSocket connection manager.

Services publish domain events; connected dashboard clients receive them in
real time (no refresh needed). Audience scoping follows the same RBAC rules as
the REST API: an agent only receives events for conversations they may see.

Single-instance by design. For horizontal scaling, replace `EventBus` with a
Redis pub/sub fan-out (documented in docs/ARCHITECTURE.md §scaling).
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from typing import Any

from fastapi import WebSocket

logger = logging.getLogger("app.events")


@dataclass
class ConnectedClient:
    ws: WebSocket
    user_id: int
    permissions: set[str]
    account_ids: set[int]  # eitaa accounts this agent may see (empty + view_all = everything)
    can_view_all: bool
    queue: asyncio.Queue = field(default_factory=lambda: asyncio.Queue(maxsize=256))


class EventBus:
    def __init__(self) -> None:
        self._clients: dict[int, ConnectedClient] = {}
        self._lock = asyncio.Lock()
        self._next_handle = 0

    async def connect(self, client: ConnectedClient) -> int:
        async with self._lock:
            self._next_handle += 1
            self._clients[self._next_handle] = client
            return self._next_handle

    async def disconnect(self, handle: int) -> None:
        async with self._lock:
            self._clients.pop(handle, None)

    @property
    def online_user_ids(self) -> set[int]:
        return {c.user_id for c in self._clients.values()}

    # ------------------------------------------------------------------ publish
    async def publish(
        self,
        event_type: str,
        payload: dict[str, Any],
        *,
        account_id: int | None = None,
        conversation_id: int | None = None,
        target_user_ids: set[int] | None = None,
    ) -> None:
        """Broadcast to every client allowed to see this event.

        - `account_id`: conversation belongs to this Eitaa account; agents
          linked to it (or users with conversation.view.all) receive it.
        - `target_user_ids`: private events (e.g., notifications).
        """
        message = json.dumps(
            {"type": event_type, "payload": payload, "conversation_id": conversation_id},
            ensure_ascii=False,
            default=str,
        )
        async with self._lock:
            clients = list(self._clients.values())
        for client in clients:
            if not self._may_receive(client, account_id, target_user_ids):
                continue
            try:
                client.queue.put_nowait(message)
            except asyncio.QueueFull:  # slow consumer — drop rather than block
                logger.warning("dropping event for slow ws client user=%s", client.user_id)

    def _may_receive(
        self,
        client: ConnectedClient,
        account_id: int | None,
        target_user_ids: set[int] | None,
    ) -> bool:
        if target_user_ids is not None:
            return client.user_id in target_user_ids
        if client.can_view_all:
            return True
        if account_id is not None:
            return account_id in client.account_ids
        return False


bus = EventBus()


async def sender_loop(client: ConnectedClient) -> None:
    """Per-connection writer task."""
    while True:
        message = await client.queue.get()
        await client.ws.send_text(message)
