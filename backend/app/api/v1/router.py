"""API v1 router aggregation."""

from fastapi import APIRouter

from app.api.v1 import (
    agents,
    auth,
    conversations,
    eitaa_accounts,
    messages,
    misc,
    ws,
)

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(agents.router)
api_router.include_router(eitaa_accounts.router)

# conversations + nested messages/notes
api_router.include_router(conversations.router)
api_router.add_api_route(
    "/conversations/{conversation_id}/messages",
    messages.list_messages,
    methods=["GET"],
)
api_router.add_api_route(
    "/conversations/{conversation_id}/messages",
    messages.send_message_endpoint,
    methods=["POST"],
    status_code=201,
)

api_router.include_router(messages.messages_router)
api_router.include_router(messages.attachments_router)
api_router.include_router(misc.router)
api_router.include_router(misc.dashboard_router)
api_router.include_router(misc.audit_router)
api_router.include_router(misc.capabilities_router)
api_router.include_router(ws.router)
