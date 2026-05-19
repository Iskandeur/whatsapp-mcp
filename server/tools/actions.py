"""MCP tools for per-message actions: reactions, edit, delete, forward, pin, star."""
import json
from pydantic import BaseModel, Field, ConfigDict
from typing import Optional
from mcp.server.fastmcp import FastMCP

from server.waha_client import (
    waha_post, waha_put, waha_delete, resolve_chat_id,
    handle_error, WAHA_SESSION,
)
from server.schema import slim_send_result


def register(mcp_instance: FastMCP):

    class ReactInput(BaseModel):
        model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
        message_id: str = Field(..., description="ID du message ciblé.")
        reaction: str = Field(
            ...,
            description="Emoji de réaction. Chaîne vide pour retirer la réaction existante.",
            max_length=16,
        )

    @mcp_instance.tool(
        name="whatsapp_send_reaction",
        annotations={
            "title": "Réagir à un message WhatsApp",
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
    )
    async def whatsapp_send_reaction(params: ReactInput) -> str:
        """Ajoute ou retire une réaction emoji sur un message."""
        try:
            await waha_put("/api/reaction", {
                "session": WAHA_SESSION,
                "messageId": params.message_id,
                "reaction": params.reaction,
            })
            return json.dumps(
                {"success": True, "message_id": params.message_id, "reaction": params.reaction},
                ensure_ascii=False, indent=2,
            )
        except Exception as e:
            return handle_error(e)

    class StarInput(BaseModel):
        model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
        message_id: str = Field(..., description="ID du message à (dé)marquer.")
        starred: bool = Field(default=True, description="True = ajouter l'étoile, False = retirer.")

    @mcp_instance.tool(
        name="whatsapp_star_message",
        annotations={
            "title": "Étoiler / déstoiler un message",
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
    )
    async def whatsapp_star_message(params: StarInput) -> str:
        """Marque (ou démarque) un message avec une étoile."""
        try:
            await waha_put("/api/star", {
                "session": WAHA_SESSION,
                "messageId": params.message_id,
                "star": params.starred,
            })
            return json.dumps(
                {"success": True, "message_id": params.message_id, "starred": params.starred},
                ensure_ascii=False, indent=2,
            )
        except Exception as e:
            return handle_error(e)

    class EditInput(BaseModel):
        model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
        chat_id: str = Field(..., description="Chat contenant le message.")
        message_id: str = Field(..., description="ID du message à éditer.")
        text: str = Field(..., min_length=1, max_length=65536, description="Nouveau texte.")

    @mcp_instance.tool(
        name="whatsapp_edit_message",
        annotations={
            "title": "Éditer un message texte WhatsApp",
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": True,
        },
    )
    async def whatsapp_edit_message(params: EditInput) -> str:
        """Édite le texte d'un message déjà envoyé (uniquement les messages de l'utilisateur, <15min)."""
        try:
            chat_id = await resolve_chat_id(params.chat_id)
            result = await waha_put(
                f"/api/{WAHA_SESSION}/chats/{chat_id}/messages/{params.message_id}",
                {"text": params.text},
            )
            return json.dumps(slim_send_result(result, chat_id_hint=chat_id),
                              ensure_ascii=False, indent=2)
        except Exception as e:
            return handle_error(e)

    class DeleteInput(BaseModel):
        model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
        chat_id: str = Field(..., description="Chat contenant le message.")
        message_id: str = Field(..., description="ID du message à supprimer.")

    @mcp_instance.tool(
        name="whatsapp_delete_message",
        annotations={
            "title": "Supprimer un message WhatsApp (pour tous)",
            "readOnlyHint": False,
            "destructiveHint": True,
            "idempotentHint": True,
            "openWorldHint": True,
        },
    )
    async def whatsapp_delete_message(params: DeleteInput) -> str:
        """Supprime un message pour tous les participants (uniquement les messages de l'utilisateur)."""
        try:
            chat_id = await resolve_chat_id(params.chat_id)
            await waha_delete(
                f"/api/{WAHA_SESSION}/chats/{chat_id}/messages/{params.message_id}"
            )
            return json.dumps(
                {"success": True, "chat_id": chat_id, "message_id": params.message_id},
                ensure_ascii=False, indent=2,
            )
        except Exception as e:
            return handle_error(e)

    class ForwardInput(BaseModel):
        model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
        message_id: str = Field(..., description="ID du message à transférer.")
        to_chat_id: str = Field(..., description="Destinataire (chat_id ou numéro brut).")

    @mcp_instance.tool(
        name="whatsapp_forward_message",
        annotations={
            "title": "Transférer un message WhatsApp",
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": True,
        },
    )
    async def whatsapp_forward_message(params: ForwardInput) -> str:
        """Transfère un message vers un autre chat."""
        try:
            to = await resolve_chat_id(params.to_chat_id)
            result = await waha_post("/api/forwardMessage", {
                "session": WAHA_SESSION,
                "chatId": to,
                "messageId": params.message_id,
            })
            return json.dumps(slim_send_result(result, chat_id_hint=to),
                              ensure_ascii=False, indent=2)
        except Exception as e:
            return handle_error(e)

    class PinInput(BaseModel):
        model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
        chat_id: str = Field(..., description="Chat contenant le message.")
        message_id: str = Field(..., description="ID du message à épingler.")
        duration_seconds: Optional[int] = Field(
            default=86400,
            description="Durée d'épinglage en secondes. Valeurs WhatsApp: 86400 (24h), 604800 (7j), 2592000 (30j).",
            ge=60,
            le=2592000,
        )

    @mcp_instance.tool(
        name="whatsapp_pin_message",
        annotations={
            "title": "Épingler un message dans un chat",
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
    )
    async def whatsapp_pin_message(params: PinInput) -> str:
        """Épingle un message en tête du chat pour la durée indiquée."""
        try:
            chat_id = await resolve_chat_id(params.chat_id)
            await waha_post(
                f"/api/{WAHA_SESSION}/chats/{chat_id}/messages/{params.message_id}/pin",
                {"duration": params.duration_seconds},
            )
            return json.dumps(
                {"success": True, "chat_id": chat_id, "message_id": params.message_id,
                 "duration_seconds": params.duration_seconds},
                ensure_ascii=False, indent=2,
            )
        except Exception as e:
            return handle_error(e)

    class UnpinInput(BaseModel):
        model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
        chat_id: str = Field(..., description="Chat contenant le message.")
        message_id: str = Field(..., description="ID du message à désépingler.")

    @mcp_instance.tool(
        name="whatsapp_unpin_message",
        annotations={
            "title": "Désépingler un message",
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
    )
    async def whatsapp_unpin_message(params: UnpinInput) -> str:
        """Retire l'épinglage d'un message."""
        try:
            chat_id = await resolve_chat_id(params.chat_id)
            await waha_post(
                f"/api/{WAHA_SESSION}/chats/{chat_id}/messages/{params.message_id}/unpin",
                {},
            )
            return json.dumps(
                {"success": True, "chat_id": chat_id, "message_id": params.message_id},
                ensure_ascii=False, indent=2,
            )
        except Exception as e:
            return handle_error(e)
