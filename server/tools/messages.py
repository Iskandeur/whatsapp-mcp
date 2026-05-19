"""MCP tools for reading and sending WhatsApp messages."""
import json
from pydantic import BaseModel, Field, ConfigDict
from typing import Optional
from mcp.server.fastmcp import FastMCP

from server.waha_client import waha_get, waha_post, handle_error, WAHA_SESSION


def _slim_message(m: dict) -> dict:
    """Strip WAHA message to fields a summarizer actually needs."""
    if not isinstance(m, dict):
        return m
    data = m.get("_data") or {}
    author = m.get("author") or m.get("from") or ""
    if isinstance(author, dict):
        author = author.get("_serialized") or author.get("user") or ""
    return {
        "id": m.get("id") if not isinstance(m.get("id"), dict) else m["id"].get("_serialized"),
        "timestamp": m.get("timestamp"),
        "from": author,
        "fromMe": m.get("fromMe", False),
        "pushName": data.get("notifyName") or m.get("_pushName") or "",
        "type": m.get("type", ""),
        "body": (m.get("body") or "")[:4000],
        "hasMedia": m.get("hasMedia", False),
        "hasQuoted": m.get("hasQuotedMsg", False),
        "quotedBody": ((m.get("_data", {}).get("quotedMsg") or {}).get("body") or "")[:200] if m.get("hasQuotedMsg") else "",
    }


def register(mcp_instance: FastMCP):

    class GetMessagesInput(BaseModel):
        model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
        chat_id: str = Field(
            ...,
            description="ID du chat. Format contact: '33612345678@c.us'. Format groupe: 'XXXXXXXX@g.us'",
        )
        limit: Optional[int] = Field(
            default=20,
            description="Nombre de messages à récupérer (1-200)",
            ge=1,
            le=200,
        )
        download_media: Optional[bool] = Field(
            default=False,
            description="Si True, inclut les URLs des médias dans la réponse",
        )
        since_timestamp: Optional[int] = Field(
            default=None,
            description="Unix timestamp (secondes). Ne retourne que les messages postérieurs à ce moment. Utile pour 'cette semaine'.",
        )

    @mcp_instance.tool(
        name="whatsapp_get_messages",
        annotations={
            "title": "Lire les messages d'un chat WhatsApp",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
    )
    async def whatsapp_get_messages(params: GetMessagesInput) -> str:
        """Récupère les derniers messages d'une conversation WhatsApp.

        Retourne une liste de messages avec expéditeur, horodatage, contenu et type.
        Pour les groupes, chaque message inclut le nom de l'expéditeur.
        """
        try:
            result = await waha_get(
                f"/api/{WAHA_SESSION}/chats/{params.chat_id}/messages",
                params={"limit": params.limit, "downloadMedia": str(params.download_media).lower()},
            )
            if isinstance(result, list):
                slim = [_slim_message(m) for m in result]
                if params.since_timestamp:
                    slim = [m for m in slim if (m.get("timestamp") or 0) >= params.since_timestamp]
                slim.sort(key=lambda m: m.get("timestamp") or 0)
                return json.dumps({"count": len(slim), "messages": slim}, ensure_ascii=False, indent=2)
            return json.dumps(result, ensure_ascii=False, indent=2)
        except Exception as e:
            return handle_error(e)

    class SendTextInput(BaseModel):
        model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
        chat_id: str = Field(
            ...,
            description="ID du destinataire. Contact: '33612345678@c.us', Groupe: 'ID@g.us'",
        )
        text: str = Field(
            ...,
            description="Texte du message. Supporte les emojis et le markdown WhatsApp (*gras*, _italique_, ~barré~)",
            min_length=1,
            max_length=65536,
        )
        reply_to: Optional[str] = Field(
            default=None,
            description="ID du message auquel répondre (optionnel)",
        )

    @mcp_instance.tool(
        name="whatsapp_send_text",
        annotations={
            "title": "Envoyer un message texte WhatsApp",
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": True,
        },
    )
    async def whatsapp_send_text(params: SendTextInput) -> str:
        """Envoie un message texte à un contact ou un groupe WhatsApp."""
        try:
            body = {
                "session": WAHA_SESSION,
                "chatId": params.chat_id,
                "text": params.text,
            }
            if params.reply_to:
                body["reply_to"] = params.reply_to
            result = await waha_post("/api/sendText", body)
            return json.dumps(result, ensure_ascii=False, indent=2)
        except Exception as e:
            return handle_error(e)

    class MarkSeenInput(BaseModel):
        model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
        chat_id: str = Field(..., description="ID du chat à marquer comme lu")
        message_id: Optional[str] = Field(
            default=None,
            description="ID du message spécifique. Si absent, marque tous les messages du chat.",
        )

    @mcp_instance.tool(
        name="whatsapp_mark_seen",
        annotations={
            "title": "Marquer des messages comme lus",
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
    )
    async def whatsapp_mark_seen(params: MarkSeenInput) -> str:
        """Marque un chat ou un message spécifique comme lu (double coche bleue)."""
        try:
            body = {"session": WAHA_SESSION, "chatId": params.chat_id}
            if params.message_id:
                body["messageId"] = params.message_id
            result = await waha_post("/api/sendSeen", body)
            return json.dumps(result, ensure_ascii=False, indent=2)
        except Exception as e:
            return handle_error(e)

    class SearchMessagesInput(BaseModel):
        model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
        query: str = Field(..., description="Texte à rechercher", min_length=1)
        chat_id: Optional[str] = Field(
            default=None,
            description="Limiter la recherche à un chat. Si absent, cherche dans le chat le plus récent.",
        )
        limit: Optional[int] = Field(default=20, ge=1, le=100)

    @mcp_instance.tool(
        name="whatsapp_search_messages",
        annotations={
            "title": "Rechercher dans les messages WhatsApp",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
    )
    async def whatsapp_search_messages(params: SearchMessagesInput) -> str:
        """Recherche locale : récupère un lot de messages et filtre par texte côté MCP.

        WAHA Core n'a pas d'endpoint de recherche serveur, donc on récupère les
        derniers messages et on filtre localement.
        """
        try:
            if params.chat_id:
                chats_to_search = [params.chat_id]
            else:
                chats = await waha_get(f"/api/{WAHA_SESSION}/chats", params={"limit": 10})
                chats_to_search = [c.get("id") for c in chats if c.get("id")][:5]

            matches = []
            q = params.query.lower()
            for cid in chats_to_search:
                try:
                    msgs = await waha_get(
                        f"/api/{WAHA_SESSION}/chats/{cid}/messages",
                        params={"limit": 100, "downloadMedia": "false"},
                    )
                    for m in msgs:
                        body_txt = (m.get("body") or "").lower()
                        if q in body_txt:
                            matches.append(m)
                            if len(matches) >= params.limit:
                                break
                except Exception:
                    continue
                if len(matches) >= params.limit:
                    break
            return json.dumps({"query": params.query, "count": len(matches), "messages": matches},
                              ensure_ascii=False, indent=2)
        except Exception as e:
            return handle_error(e)
