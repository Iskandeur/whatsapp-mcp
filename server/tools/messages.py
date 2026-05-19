"""MCP tools for reading and sending WhatsApp messages."""
import asyncio
import base64
import json
from pydantic import BaseModel, Field, ConfigDict
from typing import List, Optional
from mcp.server.fastmcp import FastMCP

from server.waha_client import (
    waha_get, waha_post, waha_fetch_bytes, resolve_media_url, resolve_chat_id,
    handle_error, WAHA_SESSION,
)
from server.schema import slim_message, slim_send_result


def register(mcp_instance: FastMCP):

    class GetMessagesInput(BaseModel):
        model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
        chat_id: str = Field(
            ...,
            description="Chat: '<digits>@lid' (récent), '<digits>@c.us' (legacy), '<digits>@g.us' (groupe), ou un numéro brut comme '33612345678' (résolu en JID via check-exists).",
        )
        limit: Optional[int] = Field(
            default=20,
            description="Nombre de messages à récupérer (1-200)",
            ge=1,
            le=200,
        )
        download_media: Optional[bool] = Field(
            default=False,
            description="Si True, demande à WAHA d'inclure le bloc media (url, mimetype, filename, size) pour les messages avec hasMedia=true.",
        )
        since_timestamp: Optional[int] = Field(
            default=None,
            description="Unix timestamp (secondes). Ne retourne que les messages postérieurs à ce moment.",
        )
        from_me: Optional[bool] = Field(
            default=None,
            description="Filtre: True = uniquement mes messages, False = uniquement ceux du correspondant, None = tous.",
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
        """Récupère les derniers messages d'une conversation WhatsApp (slim).

        Retourne `{count, messages: [{id, timestamp, from, to, fromMe, pushName,
        type, body, ack, hasMedia, media?, hasQuoted, quotedBody}]}`. Triés du
        plus ancien au plus récent.
        """
        try:
            chat_id = await resolve_chat_id(params.chat_id)
            result = await waha_get(
                f"/api/{WAHA_SESSION}/chats/{chat_id}/messages",
                params={
                    "limit": params.limit,
                    "downloadMedia": str(bool(params.download_media)).lower(),
                },
            )
            if isinstance(result, list):
                slim = [slim_message(m, include_media=bool(params.download_media)) for m in result]
                if (
                    not chat_id.endswith("@g.us")
                    and any(not m.get("pushName") and not m.get("fromMe") for m in slim)
                ):
                    try:
                        contact = await waha_get(f"/api/{WAHA_SESSION}/contacts/{chat_id}")
                        fallback = None
                        if isinstance(contact, dict):
                            fallback = (contact.get("name") or contact.get("pushname")
                                        or contact.get("shortName"))
                        if fallback:
                            for m in slim:
                                if not m.get("pushName") and not m.get("fromMe"):
                                    m["pushName"] = fallback
                    except Exception:
                        pass
                if params.since_timestamp:
                    slim = [m for m in slim if (m.get("timestamp") or 0) >= params.since_timestamp]
                if params.from_me is not None:
                    slim = [m for m in slim if bool(m.get("fromMe")) == params.from_me]
                slim.sort(key=lambda m: m.get("timestamp") or 0)
                return json.dumps({"count": len(slim), "messages": slim}, ensure_ascii=False, indent=2)
            return json.dumps(result, ensure_ascii=False, indent=2)
        except Exception as e:
            return handle_error(e)

    class SendTextInput(BaseModel):
        model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
        chat_id: str = Field(
            ...,
            description="Destinataire: '<digits>@lid', '<digits>@c.us', '<digits>@g.us', ou un numéro brut comme '33612345678' (résolu automatiquement).",
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
        verbose: Optional[bool] = Field(
            default=False,
            description="Si True, retourne le payload WAHA brut au lieu du résumé {success, message_id, ...}.",
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
        """Envoie un message texte à un contact ou un groupe WhatsApp.

        Retourne par défaut `{success, message_id, chat_id, timestamp, type, ack}`.
        Passe `verbose=true` pour récupérer le payload WAHA complet.
        """
        try:
            chat_id = await resolve_chat_id(params.chat_id)
            body = {
                "session": WAHA_SESSION,
                "chatId": chat_id,
                "text": params.text,
            }
            if params.reply_to:
                body["reply_to"] = params.reply_to
            result = await waha_post("/api/sendText", body)
            if params.verbose:
                return json.dumps(result, ensure_ascii=False, indent=2)
            return json.dumps(slim_send_result(result, chat_id_hint=chat_id),
                              ensure_ascii=False, indent=2)
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
        """Marque un chat ou un message spécifique comme lu (double coche bleue).

        WAHA renvoie un payload peu informatif (`{"ids": null}`) — on le remplace
        par `{success: true, chat_id, message_id?}`.
        """
        try:
            chat_id = await resolve_chat_id(params.chat_id)
            body = {"session": WAHA_SESSION, "chatId": chat_id}
            if params.message_id:
                body["messageId"] = params.message_id
            await waha_post("/api/sendSeen", body)
            out = {"success": True, "chat_id": chat_id}
            if params.message_id:
                out["message_id"] = params.message_id
            return json.dumps(out, ensure_ascii=False, indent=2)
        except Exception as e:
            return handle_error(e)

    class GetMessageInput(BaseModel):
        model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
        chat_id: str = Field(..., description="ID du chat contenant le message.")
        message_id: str = Field(..., description="ID complet du message (ex: 'true_<chat>_<hex>').")
        download_media: Optional[bool] = Field(
            default=False,
            description="Inclure le bloc media (url, mimetype, filename, size) si hasMedia=true.",
        )

    @mcp_instance.tool(
        name="whatsapp_get_message",
        annotations={
            "title": "Récupérer un message WhatsApp par ID",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
    )
    async def whatsapp_get_message(params: GetMessageInput) -> str:
        """Récupère un message unique sans relire tout l'historique du chat."""
        try:
            chat_id = await resolve_chat_id(params.chat_id)
            qp = {"downloadMedia": str(bool(params.download_media)).lower()}
            result = await waha_get(
                f"/api/{WAHA_SESSION}/chats/{chat_id}/messages/{params.message_id}",
                params=qp,
            )
            return json.dumps(slim_message(result, include_media=bool(params.download_media)),
                              ensure_ascii=False, indent=2)
        except Exception as e:
            return handle_error(e)

    class DownloadMediaInput(BaseModel):
        model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
        chat_id: str = Field(..., description="ID du chat contenant le message.")
        message_id: str = Field(..., description="ID complet du message à télécharger.")
        include_base64: Optional[bool] = Field(
            default=True,
            description="Si True, télécharge le binaire et l'inclut en base64 (utile pour les agents distants).",
        )
        max_bytes: Optional[int] = Field(
            default=5_000_000,
            description="Taille max (octets) si include_base64=true. Au-delà, le téléchargement échoue et seul l'URL est renvoyé.",
            ge=1024,
            le=50_000_000,
        )

    @mcp_instance.tool(
        name="whatsapp_download_media",
        annotations={
            "title": "Télécharger le média d'un message WhatsApp",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
    )
    async def whatsapp_download_media(params: DownloadMediaInput) -> str:
        """Récupère le média (image, audio, vidéo, document) d'un message donné.

        Retourne `{success, message_id, mimetype, filename, size, url, base64?}`.
        Si include_base64=true et la taille ≤ max_bytes, le binaire est inclus
        en base64 — pratique pour qu'un agent traite l'image directement.
        """
        try:
            chat_id = await resolve_chat_id(params.chat_id)
            msg = await waha_get(
                f"/api/{WAHA_SESSION}/chats/{chat_id}/messages/{params.message_id}",
                params={"downloadMedia": "true"},
            )
            if not isinstance(msg, dict):
                return json.dumps({"success": False, "error": "Message introuvable."},
                                  ensure_ascii=False, indent=2)
            media = msg.get("media") or {}
            if not msg.get("hasMedia") or not isinstance(media, dict) or not media.get("url"):
                return json.dumps({
                    "success": False,
                    "error": "Ce message ne contient pas de média téléchargeable.",
                    "message_id": params.message_id,
                    "type": (msg.get("_data") or {}).get("type") or msg.get("type"),
                }, ensure_ascii=False, indent=2)

            url = resolve_media_url(media.get("url"))
            out = {
                "success": True,
                "message_id": params.message_id,
                "chat_id": chat_id,
                "mimetype": media.get("mimetype"),
                "filename": media.get("filename"),
                "size": media.get("filesize") or media.get("size"),
                "url": url,
            }

            if params.include_base64:
                try:
                    raw, ctype = await waha_fetch_bytes(url, max_bytes=params.max_bytes)
                    out["size"] = out["size"] or len(raw)
                    out["mimetype"] = out["mimetype"] or ctype
                    out["base64"] = base64.b64encode(raw).decode("ascii")
                except ValueError as ve:
                    out["base64_skipped"] = str(ve)
                except Exception as fe:
                    out["base64_skipped"] = f"download failed: {type(fe).__name__}"

            return json.dumps(out, ensure_ascii=False, indent=2)
        except Exception as e:
            return handle_error(e)

    class BatchSendTextInput(BaseModel):
        model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
        chat_ids: List[str] = Field(
            ...,
            min_length=1, max_length=50,
            description="Liste de destinataires (chat_ids ou numéros bruts). Résolus automatiquement.",
        )
        text: str = Field(..., min_length=1, max_length=65536, description="Texte commun à tous les destinataires.")
        delay_between_seconds: Optional[float] = Field(
            default=1.0, ge=0.0, le=30.0,
            description="Pause entre chaque envoi (anti rate-limit WhatsApp).",
        )
        confirm: bool = Field(
            ...,
            description="Doit être True. Garde-fou contre les envois en masse accidentels.",
        )

    @mcp_instance.tool(
        name="whatsapp_batch_send_text",
        annotations={
            "title": "Envoyer le même texte à plusieurs chats",
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": True,
        },
    )
    async def whatsapp_batch_send_text(params: BatchSendTextInput) -> str:
        """Envoie le même texte à N destinataires (séquentiel, avec pause configurable).

        Retourne `{count, sent: [...], failed: [...]}`. Échec sur l'un n'arrête pas
        les suivants. Garde-fou: `confirm=true` obligatoire.
        """
        if not params.confirm:
            return json.dumps({"success": False, "error": "confirm doit être True pour un envoi en masse."},
                              ensure_ascii=False, indent=2)
        sent, failed = [], []
        for i, raw_chat in enumerate(params.chat_ids):
            try:
                chat_id = await resolve_chat_id(raw_chat)
                r = await waha_post("/api/sendText", {
                    "session": WAHA_SESSION,
                    "chatId": chat_id,
                    "text": params.text,
                })
                sent.append(slim_send_result(r, chat_id_hint=chat_id))
            except Exception as e:
                failed.append({"chat_id": raw_chat, "error": handle_error(e)})
            if i < len(params.chat_ids) - 1 and params.delay_between_seconds:
                await asyncio.sleep(params.delay_between_seconds)
        return json.dumps({"count": len(params.chat_ids), "sent_count": len(sent),
                           "failed_count": len(failed), "sent": sent, "failed": failed},
                          ensure_ascii=False, indent=2)

    class ReplyToMessageInput(BaseModel):
        model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
        chat_id: str = Field(..., description="Chat contenant le message original.")
        message_id: str = Field(..., description="ID du message auquel répondre.")
        text: str = Field(..., min_length=1, max_length=65536, description="Texte de la réponse.")
        verbose: Optional[bool] = Field(default=False, description="Retourne le payload WAHA brut.")

    @mcp_instance.tool(
        name="whatsapp_reply_to_message",
        annotations={
            "title": "Répondre à un message WhatsApp (avec citation)",
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": True,
        },
    )
    async def whatsapp_reply_to_message(params: ReplyToMessageInput) -> str:
        """Répond à un message en le citant. Fetch automatiquement le message original
        pour inclure un aperçu (200 chars) dans la réponse — pratique pour confirmer
        à l'agent ce qui est cité.
        """
        try:
            chat_id = await resolve_chat_id(params.chat_id)
            quoted_preview = None
            try:
                orig = await waha_get(
                    f"/api/{WAHA_SESSION}/chats/{chat_id}/messages/{params.message_id}",
                    params={"downloadMedia": "false"},
                )
                if isinstance(orig, dict):
                    quoted_preview = (orig.get("body") or "")[:200]
            except Exception:
                pass
            result = await waha_post("/api/sendText", {
                "session": WAHA_SESSION,
                "chatId": chat_id,
                "text": params.text,
                "reply_to": params.message_id,
            })
            if params.verbose:
                return json.dumps(result, ensure_ascii=False, indent=2)
            out = slim_send_result(result, chat_id_hint=chat_id)
            out["quoted"] = {"message_id": params.message_id, "body_preview": quoted_preview}
            return json.dumps(out, ensure_ascii=False, indent=2)
        except Exception as e:
            return handle_error(e)

    class ChatScanInput(BaseModel):
        model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
        chat_id: str = Field(..., description="Chat à scanner.")
        scan_limit: Optional[int] = Field(
            default=200, ge=1, le=1000,
            description="Nombre de messages récents à scanner (la recherche reste locale).",
        )

    @mcp_instance.tool(
        name="whatsapp_get_chat_media_count",
        annotations={
            "title": "Compter les médias d'un chat par type",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
    )
    async def whatsapp_get_chat_media_count(params: ChatScanInput) -> str:
        """Scanne les `scan_limit` derniers messages d'un chat et compte par type.

        Retourne `{total_scanned, counts: {chat: N, image: N, video: N, audio: N,
        ptt: N, document: N, sticker: N, location: N, vcard: N, poll_creation: N,
        ...}, media_total}`. Le total média exclut les messages texte (`chat`).
        """
        try:
            chat_id = await resolve_chat_id(params.chat_id)
            msgs = await waha_get(
                f"/api/{WAHA_SESSION}/chats/{chat_id}/messages",
                params={"limit": params.scan_limit, "downloadMedia": "false"},
            )
            if not isinstance(msgs, list):
                return json.dumps({"success": False, "error": "Réponse WAHA inattendue."},
                                  ensure_ascii=False, indent=2)
            counts: dict[str, int] = {}
            media_total = 0
            for m in msgs:
                t = (m.get("_data") or {}).get("type") or m.get("type") or "unknown"
                counts[t] = counts.get(t, 0) + 1
                if m.get("hasMedia"):
                    media_total += 1
            return json.dumps({
                "chat_id": chat_id,
                "total_scanned": len(msgs),
                "counts": dict(sorted(counts.items(), key=lambda kv: -kv[1])),
                "media_total": media_total,
            }, ensure_ascii=False, indent=2)
        except Exception as e:
            return handle_error(e)

    class ListForwardedInput(BaseModel):
        model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
        chat_id: str = Field(..., description="Chat à scanner.")
        scan_limit: Optional[int] = Field(
            default=500, ge=1, le=2000,
            description="Profondeur de scan (messages récents).",
        )
        limit: Optional[int] = Field(
            default=20, ge=1, le=200,
            description="Nombre max de résultats à retourner.",
        )

    @mcp_instance.tool(
        name="whatsapp_list_forwarded_messages",
        annotations={
            "title": "Lister les messages transférés d'un chat",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
    )
    async def whatsapp_list_forwarded_messages(params: ListForwardedInput) -> str:
        """Liste les messages marqués 'forwarded' dans un chat (champ `_data.isForwarded`).

        Retourne aussi `forwardsCount` quand WAHA le fournit (≥ 5 = 'frequently
        forwarded' dans l'UI WhatsApp).
        """
        try:
            chat_id = await resolve_chat_id(params.chat_id)
            msgs = await waha_get(
                f"/api/{WAHA_SESSION}/chats/{chat_id}/messages",
                params={"limit": params.scan_limit, "downloadMedia": "false"},
            )
            if not isinstance(msgs, list):
                return json.dumps({"success": False, "error": "Réponse WAHA inattendue."},
                                  ensure_ascii=False, indent=2)
            forwarded = [
                slim_message(m, include_media=False)
                for m in msgs
                if (m.get("_data") or {}).get("isForwarded")
            ]
            forwarded.sort(key=lambda m: m.get("timestamp") or 0, reverse=True)
            return json.dumps({
                "chat_id": chat_id,
                "total_scanned": len(msgs),
                "count": len(forwarded),
                "messages": forwarded[: params.limit],
            }, ensure_ascii=False, indent=2)
        except Exception as e:
            return handle_error(e)

    class SearchMessagesInput(BaseModel):
        model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
        query: str = Field(..., description="Texte à rechercher (insensible à la casse)", min_length=1)
        chat_id: Optional[str] = Field(
            default=None,
            description="Limiter la recherche à un chat. Si absent, cherche dans les 5 chats les plus récents.",
        )
        limit: Optional[int] = Field(default=20, ge=1, le=100)
        scan_per_chat: Optional[int] = Field(
            default=200,
            ge=20,
            le=1000,
            description="Nombre de messages récents à scanner par chat (fallback local, WAHA Core n'a pas de search serveur).",
        )

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
        `scan_per_chat` messages les plus récents par chat et on filtre localement.
        """
        try:
            if params.chat_id:
                chats_to_search = [await resolve_chat_id(params.chat_id)]
            else:
                chats = await waha_get(f"/api/{WAHA_SESSION}/chats", params={"limit": 10})
                chats_to_search = []
                for c in chats[:10]:
                    cid = c.get("id")
                    if isinstance(cid, dict):
                        cid = cid.get("_serialized")
                    if cid:
                        chats_to_search.append(cid)
                chats_to_search = chats_to_search[:5]

            matches = []
            q = params.query.lower()
            for cid in chats_to_search:
                try:
                    msgs = await waha_get(
                        f"/api/{WAHA_SESSION}/chats/{cid}/messages",
                        params={"limit": params.scan_per_chat, "downloadMedia": "false"},
                    )
                    for m in msgs:
                        body_txt = (m.get("body") or "").lower()
                        if q in body_txt:
                            matches.append(slim_message(m, include_media=False))
                            if len(matches) >= params.limit:
                                break
                except Exception:
                    continue
                if len(matches) >= params.limit:
                    break
            return json.dumps(
                {"query": params.query, "count": len(matches), "messages": matches},
                ensure_ascii=False,
                indent=2,
            )
        except Exception as e:
            return handle_error(e)
