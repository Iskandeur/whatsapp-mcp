"""MCP tools for presence (typing indicator, online/offline)."""
import json
import asyncio
from pydantic import BaseModel, Field, ConfigDict
from typing import Optional
from mcp.server.fastmcp import FastMCP

from server.waha_client import (
    waha_get, waha_post, resolve_chat_id, handle_error, WAHA_SESSION,
)


def register(mcp_instance: FastMCP):

    class TypingInput(BaseModel):
        model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
        chat_id: str = Field(..., description="Chat dans lequel afficher l'indicateur.")
        duration_seconds: Optional[int] = Field(
            default=None,
            ge=1, le=30,
            description="Si défini, attend cette durée puis arrête automatiquement le typing.",
        )

    @mcp_instance.tool(
        name="whatsapp_start_typing",
        annotations={
            "title": "Afficher 'en train d'écrire...' dans un chat",
            "readOnlyHint": False, "destructiveHint": False,
            "idempotentHint": True, "openWorldHint": True,
        },
    )
    async def whatsapp_start_typing(params: TypingInput) -> str:
        """Affiche l'indicateur 'en train d'écrire...' chez le destinataire.

        Si `duration_seconds` est fourni, l'indicateur s'arrête automatiquement
        après la durée — utile pour simuler une frappe humaine avant un send_text.
        """
        try:
            chat_id = await resolve_chat_id(params.chat_id)
            await waha_post("/api/startTyping", {"session": WAHA_SESSION, "chatId": chat_id})
            if params.duration_seconds:
                await asyncio.sleep(params.duration_seconds)
                await waha_post("/api/stopTyping", {"session": WAHA_SESSION, "chatId": chat_id})
                return json.dumps({"success": True, "chat_id": chat_id,
                                   "typing_for_seconds": params.duration_seconds},
                                  ensure_ascii=False, indent=2)
            return json.dumps({"success": True, "chat_id": chat_id, "typing": True},
                              ensure_ascii=False, indent=2)
        except Exception as e:
            return handle_error(e)

    class StopTypingInput(BaseModel):
        model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
        chat_id: str = Field(..., description="Chat où arrêter l'indicateur.")

    @mcp_instance.tool(
        name="whatsapp_stop_typing",
        annotations={
            "title": "Arrêter l'indicateur 'en train d'écrire'",
            "readOnlyHint": False, "destructiveHint": False,
            "idempotentHint": True, "openWorldHint": True,
        },
    )
    async def whatsapp_stop_typing(params: StopTypingInput) -> str:
        """Arrête l'indicateur 'en train d'écrire...' dans un chat."""
        try:
            chat_id = await resolve_chat_id(params.chat_id)
            await waha_post("/api/stopTyping", {"session": WAHA_SESSION, "chatId": chat_id})
            return json.dumps({"success": True, "chat_id": chat_id, "typing": False},
                              ensure_ascii=False, indent=2)
        except Exception as e:
            return handle_error(e)

    class SetPresenceInput(BaseModel):
        model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
        presence: str = Field(
            ...,
            description="Statut: 'online' ou 'offline'.",
            pattern="^(online|offline)$",
        )

    @mcp_instance.tool(
        name="whatsapp_set_presence",
        annotations={
            "title": "Passer le compte WhatsApp en online/offline",
            "readOnlyHint": False, "destructiveHint": False,
            "idempotentHint": True, "openWorldHint": True,
        },
    )
    async def whatsapp_set_presence(params: SetPresenceInput) -> str:
        """Affiche le compte comme online ou offline pour les contacts qui suivent ton statut."""
        try:
            await waha_post(f"/api/{WAHA_SESSION}/presence", {"presence": params.presence})
            return json.dumps({"success": True, "presence": params.presence},
                              ensure_ascii=False, indent=2)
        except Exception as e:
            return handle_error(e)

    class GetPresenceInput(BaseModel):
        model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
        chat_id: str = Field(..., description="Chat à interroger.")

    @mcp_instance.tool(
        name="whatsapp_get_presence",
        annotations={
            "title": "Obtenir le statut de présence d'un contact",
            "readOnlyHint": True, "destructiveHint": False,
            "idempotentHint": True, "openWorldHint": True,
        },
    )
    async def whatsapp_get_presence(params: GetPresenceInput) -> str:
        """Retourne le statut (online / dernière vue) d'un contact, si disponible.

        WhatsApp masque souvent cette info selon les paramètres de confidentialité
        du contact — ne pas s'attendre à ce que ça marche pour tout le monde.
        """
        try:
            chat_id = await resolve_chat_id(params.chat_id)
            result = await waha_get(f"/api/{WAHA_SESSION}/presence/{chat_id}")
            return json.dumps(result if isinstance(result, dict) else {"raw": result},
                              ensure_ascii=False, indent=2)
        except Exception as e:
            return handle_error(e)
