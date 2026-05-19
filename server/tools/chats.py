"""MCP tools for chat-level management: archive, mark unread, clear, delete."""
import json
from pydantic import BaseModel, Field, ConfigDict
from mcp.server.fastmcp import FastMCP

from server.waha_client import (
    waha_post, waha_delete, resolve_chat_id, handle_error, WAHA_SESSION,
)


def register(mcp_instance: FastMCP):

    class ChatIdInput(BaseModel):
        model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
        chat_id: str = Field(..., description="Chat cible (chat_id ou numéro brut).")

    @mcp_instance.tool(
        name="whatsapp_archive_chat",
        annotations={
            "title": "Archiver un chat WhatsApp",
            "readOnlyHint": False, "destructiveHint": False,
            "idempotentHint": True, "openWorldHint": True,
        },
    )
    async def whatsapp_archive_chat(params: ChatIdInput) -> str:
        """Archive un chat (le retire de la liste principale)."""
        try:
            chat_id = await resolve_chat_id(params.chat_id)
            await waha_post(f"/api/{WAHA_SESSION}/chats/{chat_id}/archive", {})
            return json.dumps({"success": True, "chat_id": chat_id, "archived": True},
                              ensure_ascii=False, indent=2)
        except Exception as e:
            return handle_error(e)

    @mcp_instance.tool(
        name="whatsapp_unarchive_chat",
        annotations={
            "title": "Désarchiver un chat WhatsApp",
            "readOnlyHint": False, "destructiveHint": False,
            "idempotentHint": True, "openWorldHint": True,
        },
    )
    async def whatsapp_unarchive_chat(params: ChatIdInput) -> str:
        """Sort un chat des archives."""
        try:
            chat_id = await resolve_chat_id(params.chat_id)
            await waha_post(f"/api/{WAHA_SESSION}/chats/{chat_id}/unarchive", {})
            return json.dumps({"success": True, "chat_id": chat_id, "archived": False},
                              ensure_ascii=False, indent=2)
        except Exception as e:
            return handle_error(e)

    @mcp_instance.tool(
        name="whatsapp_mark_unread",
        annotations={
            "title": "Marquer un chat comme non-lu",
            "readOnlyHint": False, "destructiveHint": False,
            "idempotentHint": True, "openWorldHint": True,
        },
    )
    async def whatsapp_mark_unread(params: ChatIdInput) -> str:
        """Marque un chat comme non-lu (utile pour reprendre plus tard)."""
        try:
            chat_id = await resolve_chat_id(params.chat_id)
            await waha_post(f"/api/{WAHA_SESSION}/chats/{chat_id}/unread", {})
            return json.dumps({"success": True, "chat_id": chat_id, "unread": True},
                              ensure_ascii=False, indent=2)
        except Exception as e:
            return handle_error(e)

    class ClearMessagesInput(BaseModel):
        model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
        chat_id: str = Field(..., description="Chat à vider.")
        confirm: bool = Field(
            ...,
            description="Doit être True. Garde-fou contre les suppressions accidentelles.",
        )

    @mcp_instance.tool(
        name="whatsapp_clear_messages",
        annotations={
            "title": "Vider tous les messages d'un chat",
            "readOnlyHint": False, "destructiveHint": True,
            "idempotentHint": True, "openWorldHint": True,
        },
    )
    async def whatsapp_clear_messages(params: ClearMessagesInput) -> str:
        """Supprime localement tous les messages d'un chat (le chat lui-même reste)."""
        if not params.confirm:
            return json.dumps({"success": False, "error": "confirm doit être True."},
                              ensure_ascii=False, indent=2)
        try:
            chat_id = await resolve_chat_id(params.chat_id)
            await waha_delete(f"/api/{WAHA_SESSION}/chats/{chat_id}/messages")
            return json.dumps({"success": True, "chat_id": chat_id, "messages_cleared": True},
                              ensure_ascii=False, indent=2)
        except Exception as e:
            return handle_error(e)

    class DeleteChatInput(BaseModel):
        model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
        chat_id: str = Field(..., description="Chat à supprimer.")
        confirm: bool = Field(
            ...,
            description="Doit être True. Garde-fou — opération non réversible côté local.",
        )

    @mcp_instance.tool(
        name="whatsapp_delete_chat",
        annotations={
            "title": "Supprimer un chat WhatsApp",
            "readOnlyHint": False, "destructiveHint": True,
            "idempotentHint": True, "openWorldHint": True,
        },
    )
    async def whatsapp_delete_chat(params: DeleteChatInput) -> str:
        """Supprime un chat de la liste (l'historique local part avec)."""
        if not params.confirm:
            return json.dumps({"success": False, "error": "confirm doit être True."},
                              ensure_ascii=False, indent=2)
        try:
            chat_id = await resolve_chat_id(params.chat_id)
            await waha_delete(f"/api/{WAHA_SESSION}/chats/{chat_id}")
            return json.dumps({"success": True, "chat_id": chat_id, "deleted": True},
                              ensure_ascii=False, indent=2)
        except Exception as e:
            return handle_error(e)
