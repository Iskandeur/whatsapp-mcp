"""MCP tools for sending WhatsApp media (images, files, voice)."""
import json
from pydantic import BaseModel, Field, ConfigDict
from typing import Optional
from mcp.server.fastmcp import FastMCP

from server.waha_client import waha_post, resolve_chat_id, handle_error, WAHA_SESSION
from server.schema import slim_send_result


def register(mcp_instance: FastMCP):

    def _wrap(result, chat_id: str, verbose: bool) -> str:
        if verbose:
            return json.dumps(result, ensure_ascii=False, indent=2)
        return json.dumps(slim_send_result(result, chat_id_hint=chat_id),
                          ensure_ascii=False, indent=2)

    class SendImageInput(BaseModel):
        model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
        chat_id: str = Field(..., description="Destinataire: chat_id (@c.us/@lid/@g.us) ou numéro brut '33612345678' (résolu automatiquement).")
        url: str = Field(
            ...,
            description="URL publique de l'image (https://...). WAHA la télécharge et l'envoie.",
        )
        caption: Optional[str] = Field(default=None, description="Légende sous l'image")
        verbose: Optional[bool] = Field(default=False, description="Retourne le payload WAHA brut.")

    @mcp_instance.tool(
        name="whatsapp_send_image",
        annotations={
            "title": "Envoyer une image WhatsApp",
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": True,
        },
    )
    async def whatsapp_send_image(params: SendImageInput) -> str:
        """Envoie une image depuis une URL publique vers un contact ou groupe WhatsApp.

        Retourne `{success, message_id, chat_id, ...}` par défaut.
        """
        try:
            chat_id = await resolve_chat_id(params.chat_id)
            body = {
                "session": WAHA_SESSION,
                "chatId": chat_id,
                "file": {"url": params.url},
            }
            if params.caption:
                body["caption"] = params.caption
            result = await waha_post("/api/sendImage", body)
            return _wrap(result, chat_id, bool(params.verbose))
        except Exception as e:
            return handle_error(e)

    class SendFileInput(BaseModel):
        model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
        chat_id: str = Field(..., description="Destinataire: chat_id (@c.us/@lid/@g.us) ou numéro brut '33612345678' (résolu automatiquement).")
        url: str = Field(..., description="URL publique du fichier à envoyer")
        filename: Optional[str] = Field(
            default=None,
            description="Nom du fichier affiché dans WhatsApp. Ex: 'rapport.pdf'",
        )
        caption: Optional[str] = Field(default=None, description="Légende sous le fichier")
        verbose: Optional[bool] = Field(default=False, description="Retourne le payload WAHA brut.")

    @mcp_instance.tool(
        name="whatsapp_send_file",
        annotations={
            "title": "Envoyer un fichier WhatsApp",
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": True,
        },
    )
    async def whatsapp_send_file(params: SendFileInput) -> str:
        """Envoie un fichier (PDF, ZIP, etc.) depuis une URL publique."""
        try:
            chat_id = await resolve_chat_id(params.chat_id)
            file_obj = {"url": params.url}
            if params.filename:
                file_obj["filename"] = params.filename
            body = {
                "session": WAHA_SESSION,
                "chatId": chat_id,
                "file": file_obj,
            }
            if params.caption:
                body["caption"] = params.caption
            result = await waha_post("/api/sendFile", body)
            return _wrap(result, chat_id, bool(params.verbose))
        except Exception as e:
            return handle_error(e)

    class SendVoiceInput(BaseModel):
        model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
        chat_id: str = Field(..., description="ID du destinataire")
        url: str = Field(..., description="URL publique du fichier audio (OGG/Opus recommandé)")
        verbose: Optional[bool] = Field(default=False, description="Retourne le payload WAHA brut.")

    @mcp_instance.tool(
        name="whatsapp_send_voice",
        annotations={
            "title": "Envoyer un message vocal WhatsApp",
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": True,
        },
    )
    async def whatsapp_send_voice(params: SendVoiceInput) -> str:
        """Envoie un message vocal depuis une URL audio publique."""
        try:
            chat_id = await resolve_chat_id(params.chat_id)
            body = {
                "session": WAHA_SESSION,
                "chatId": chat_id,
                "file": {"url": params.url},
            }
            result = await waha_post("/api/sendVoice", body)
            return _wrap(result, chat_id, bool(params.verbose))
        except Exception as e:
            return handle_error(e)
