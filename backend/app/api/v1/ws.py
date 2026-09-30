"""WebSocket endpoint: real-time inbox updates (token via ?token=)."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.api.deps import ws_auth
from app.api.events import ConnectedClient, bus, sender_loop
from app.services import agent_service

router = APIRouter(tags=["realtime"])


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    auth = await ws_auth(websocket)
    if auth is None:
        await websocket.send_text('{"type": "error", "payload": {"code": "unauthorized"}}')
        await websocket.close(code=4401)
        return

    # resolve linked account ids with a dedicated session
    from app.db.session import get_session_factory

    factory = get_session_factory()
    async with factory() as db:
        account_ids = await agent_service.agent_account_ids(db, auth.user.id)

    client = ConnectedClient(
        ws=websocket,
        user_id=auth.user.id,
        permissions=auth.permissions,
        account_ids=account_ids,
        can_view_all="conversation.view.all" in auth.permissions,
    )
    handle = await bus.connect(client)
    writer = asyncio.create_task(sender_loop(client))
    try:
        await websocket.send_text(
            '{"type": "connected", "payload": {"user_id": %d}}' % auth.user.id
        )
        while True:
            # client -> server pings/acks (text frames); we keep the socket warm
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        pass
    finally:
        writer.cancel()
        await bus.disconnect(handle)
