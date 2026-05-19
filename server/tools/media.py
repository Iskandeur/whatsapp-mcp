"""MCP tools for sending WhatsApp media (images, files, voice, location, contact, poll)."""
import json
from pydantic import BaseModel, Field, ConfigDict
from typing import List, Optional
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

    class SendLocationInput(BaseModel):
        model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
        chat_id: str = Field(..., description="Destinataire: chat_id (@c.us/@lid/@g.us) ou numéro brut '33612345678' (résolu automatiquement).")
        latitude: float = Field(..., ge=-90, le=90, description="Latitude WGS84.")
        longitude: float = Field(..., ge=-180, le=180, description="Longitude WGS84.")
        title: Optional[str] = Field(default=None, max_length=200, description="Nom du lieu (optionnel).")
        verbose: Optional[bool] = Field(default=False, description="Retourne le payload WAHA brut.")

    @mcp_instance.tool(
        name="whatsapp_send_location",
        annotations={
            "title": "Envoyer une localisation WhatsApp",
            "readOnlyHint": False, "destructiveHint": False,
            "idempotentHint": False, "openWorldHint": True,
        },
    )
    async def whatsapp_send_location(params: SendLocationInput) -> str:
        """Envoie un point de localisation (épingle sur carte) à un chat."""
        try:
            chat_id = await resolve_chat_id(params.chat_id)
            body = {
                "session": WAHA_SESSION,
                "chatId": chat_id,
                "latitude": params.latitude,
                "longitude": params.longitude,
            }
            if params.title:
                body["title"] = params.title
            result = await waha_post("/api/sendLocation", body)
            return _wrap(result, chat_id, bool(params.verbose))
        except Exception as e:
            return handle_error(e)

    class SendContactInput(BaseModel):
        model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
        chat_id: str = Field(..., description="Destinataire (chat_id ou numéro brut).")
        contact_ids: List[str] = Field(
            ...,
            min_length=1,
            description="Liste de chat_ids ou numéros bruts à partager (vCard auto-générée).",
        )
        verbose: Optional[bool] = Field(default=False, description="Retourne le payload WAHA brut.")

    @mcp_instance.tool(
        name="whatsapp_send_contact",
        annotations={
            "title": "Partager une fiche contact WhatsApp",
            "readOnlyHint": False, "destructiveHint": False,
            "idempotentHint": False, "openWorldHint": True,
        },
    )
    async def whatsapp_send_contact(params: SendContactInput) -> str:
        """Partage une ou plusieurs fiches contact (vCards) dans un chat."""
        try:
            chat_id = await resolve_chat_id(params.chat_id)
            ids = [await resolve_chat_id(c) for c in params.contact_ids]
            body = {
                "session": WAHA_SESSION,
                "chatId": chat_id,
                "contactsId": ids,
            }
            result = await waha_post("/api/sendContactVcard", body)
            return _wrap(result, chat_id, bool(params.verbose))
        except Exception as e:
            return handle_error(e)

    class SendPollInput(BaseModel):
        model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
        chat_id: str = Field(..., description="Destinataire (chat_id ou numéro brut).")
        question: str = Field(..., min_length=1, max_length=255, description="Question du sondage.")
        options: List[str] = Field(
            ..., min_length=2, max_length=12,
            description="Options de réponse (2 à 12).",
        )
        multiple_answers: Optional[bool] = Field(
            default=False,
            description="Si True, les votants peuvent choisir plusieurs réponses.",
        )
        verbose: Optional[bool] = Field(default=False, description="Retourne le payload WAHA brut.")

    @mcp_instance.tool(
        name="whatsapp_send_poll",
        annotations={
            "title": "Envoyer un sondage WhatsApp",
            "readOnlyHint": False, "destructiveHint": False,
            "idempotentHint": False, "openWorldHint": True,
        },
    )
    async def whatsapp_send_poll(params: SendPollInput) -> str:
        """Envoie un sondage avec 2 à 12 options, simple ou multi-réponses."""
        try:
            chat_id = await resolve_chat_id(params.chat_id)
            body = {
                "session": WAHA_SESSION,
                "chatId": chat_id,
                "poll": {
                    "name": params.question,
                    "options": list(params.options),
                    "multipleAnswers": bool(params.multiple_answers),
                },
            }
            result = await waha_post("/api/sendPoll", body)
            return _wrap(result, chat_id, bool(params.verbose))
        except Exception as e:
            return handle_error(e)
