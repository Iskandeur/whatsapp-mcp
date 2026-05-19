"""Normalized payload reducers shared by every MCP tool.

Goal: every tool returns a tight, predictable JSON shape so the LLM doesn't
pay 3000 tokens to read a single send-message acknowledgement. WAHA payloads
are kept around behind a `verbose` flag for the rare debug case.
"""
from typing import Any, Optional


def _serialize_id(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return value.get("_serialized") or value.get("user") or None
    return str(value)


_NOWEB_TYPE_MAP = {
    "conversation": "chat",
    "extendedTextMessage": "chat",
    "imageMessage": "image",
    "videoMessage": "video",
    "audioMessage": "audio",
    "documentMessage": "document",
    "documentWithCaptionMessage": "document",
    "stickerMessage": "sticker",
    "locationMessage": "location",
    "liveLocationMessage": "location",
    "contactMessage": "vcard",
    "contactsArrayMessage": "vcard_multi",
    "pollCreationMessage": "poll_creation",
    "pollCreationMessageV3": "poll_creation",
    "pollUpdateMessage": "poll_vote",
    "reactionMessage": "reaction",
    "protocolMessage": "revoked",
    "groupInviteMessage": "groups_v4_invite",
    "buttonsMessage": "buttons",
    "listMessage": "list",
}


def _noweb_message_view(data: dict) -> dict:
    """Pull type / body / contextInfo out of Baileys-style `_data.message`."""
    out = {"type": None, "body": "", "context": None, "ptt": False}
    if not isinstance(data, dict):
        return out
    msg = data.get("message")
    if not isinstance(msg, dict):
        return out
    for k, v in msg.items():
        if k not in _NOWEB_TYPE_MAP:
            continue
        out["type"] = _NOWEB_TYPE_MAP[k]
        if k == "audioMessage" and isinstance(v, dict) and v.get("ptt"):
            out["type"] = "ptt"
            out["ptt"] = True
        if isinstance(v, dict):
            if k == "conversation":
                out["body"] = v if isinstance(v, str) else ""
            else:
                out["body"] = (
                    v.get("text")
                    or v.get("caption")
                    or v.get("fileName")
                    or v.get("contentText")
                    or ""
                )
            out["context"] = v.get("contextInfo")
        elif k == "conversation":
            out["body"] = v if isinstance(v, str) else ""
        break
    return out


def slim_message(m: dict, include_media: bool = True) -> dict:
    """Reduce a WAHA message object to the fields a model actually consumes.

    Handles both WEBJS (`_data.type` etc.) and NOWEB (Baileys, `_data.message`,
    `_data.key`) shapes so downstream code is engine-agnostic.
    """
    if not isinstance(m, dict):
        return m
    data = m.get("_data") or {}
    noweb = _noweb_message_view(data)
    ctx = noweb["context"] if isinstance(noweb["context"], dict) else {}

    msg_type = m.get("type") or data.get("type") or noweb["type"] or ""

    push = (
        data.get("notifyName")
        or data.get("pushname")
        or data.get("pushName")
        or m.get("pushName")
        or m.get("_pushName")
        or ""
    )

    # WEBJS quoted shape
    quoted = bool(m.get("hasQuotedMsg") or data.get("quotedMsg"))
    quoted_body = ""
    if quoted:
        q = data.get("quotedMsg") or {}
        quoted_body = (q.get("body") or "")[:200]
    # NOWEB quoted shape
    if not quoted and ctx.get("quotedMessage"):
        quoted = True
        qmsg = ctx.get("quotedMessage") or {}
        quoted_body = (
            qmsg.get("conversation")
            or (qmsg.get("extendedTextMessage") or {}).get("text")
            or (qmsg.get("imageMessage") or {}).get("caption")
            or (qmsg.get("videoMessage") or {}).get("caption")
            or ""
        )[:200]

    body = m.get("body") or noweb["body"] or ""

    key = data.get("key") if isinstance(data.get("key"), dict) else {}
    remote_jid = _serialize_id(key.get("remoteJid"))
    participant = _serialize_id(key.get("participant"))
    self_lid = _serialize_id(data.get("originalSelfAuthorUserJidString"))
    is_group = bool(remote_jid and remote_jid.endswith("@g.us"))
    is_from_me = bool(m.get("fromMe", False))

    chat_id_field = remote_jid or _serialize_id(m.get("to") or m.get("from"))
    raw_from = _serialize_id(m.get("author") or m.get("from"))
    if is_from_me:
        sender = self_lid or (raw_from if (raw_from and raw_from != remote_jid) else None)
    else:
        sender = participant or raw_from if is_group else (raw_from or remote_jid)
    to = chat_id_field if is_from_me else (self_lid or None)

    has_media = m.get("hasMedia")
    if has_media is None:
        has_media = msg_type in ("image", "video", "audio", "ptt", "document", "sticker")

    is_forwarded = bool(data.get("isForwarded") or ctx.get("isForwarded"))
    forwards_count = (
        data.get("forwardsCount")
        or data.get("forwardingScore")
        or ctx.get("forwardingScore")
        or 0
    )

    out = {
        "id": _serialize_id(m.get("id")),
        "timestamp": m.get("timestamp") or data.get("t") or data.get("messageTimestamp"),
        "from": sender,
        "to": to,
        "chat_id": chat_id_field,
        "fromMe": is_from_me,
        "pushName": push,
        "type": msg_type,
        "body": body[:4000],
        "ack": m.get("ack") if m.get("ack") is not None else data.get("status"),
        "hasMedia": bool(has_media),
        "hasQuoted": quoted,
        "quotedBody": quoted_body,
        "hasReaction": bool(data.get("hasReaction")),
        "isForwarded": is_forwarded,
        "forwardsCount": forwards_count,
        "starred": bool(data.get("star") or data.get("starred")),
    }

    if include_media:
        media = m.get("media")
        if isinstance(media, dict):
            from server.waha_client import resolve_media_url
            out["media"] = {
                "url": resolve_media_url(media.get("url")),
                "mimetype": media.get("mimetype"),
                "filename": media.get("filename"),
                "size": media.get("filesize") or media.get("size"),
            }

    location = m.get("location")
    if isinstance(location, dict):
        out["location"] = {
            "lat": location.get("latitude") or location.get("lat"),
            "lng": location.get("longitude") or location.get("lng"),
            "name": location.get("name"),
            "address": location.get("address"),
        }

    vcards = m.get("vCards")
    if vcards:
        out["vCardsCount"] = len(vcards)

    return out


def slim_send_result(r: dict, chat_id_hint: Optional[str] = None) -> dict:
    """Reduce a WAHA send-* response to {success, message_id, chat_id, ...}.

    WAHA returns a full Message object on success — we only surface the bits an
    agent needs to follow up (react, edit, delete, quote).
    """
    if not isinstance(r, dict):
        return {"success": True, "raw": r}
    data = r.get("_data") or {}
    msg_id = _serialize_id(r.get("id")) or _serialize_id(data.get("id"))
    chat_id = (
        _serialize_id(r.get("to"))
        or _serialize_id(data.get("to"))
        or chat_id_hint
    )
    return {
        "success": True,
        "message_id": msg_id,
        "chat_id": chat_id,
        "timestamp": r.get("timestamp") or data.get("t"),
        "type": r.get("type") or data.get("type") or "chat",
        "ack": r.get("ack"),
    }


def slim_chat(c: dict) -> dict:
    """Reduce a WAHA chat list entry. Handles WEBJS and NOWEB shapes."""
    if not isinstance(c, dict):
        return c
    cid = _serialize_id(c.get("id"))
    last = c.get("lastMessage") or {}
    last_body = (last.get("body") or "")[:200] if isinstance(last, dict) else ""
    last_ts = last.get("timestamp") if isinstance(last, dict) else None
    ts = (
        c.get("timestamp")
        or c.get("conversationTimestamp")
        or last_ts
        or c.get("lastMessageRecvTimestamp")
    )
    unread = c.get("unreadCount")
    if unread is None:
        unread = c.get("unreadMentionCount") or 0
    if unread < 0:
        unread = 0
    return {
        "id": cid,
        "name": c.get("name") or (c.get("subject") if not isinstance(c.get("subject"), dict) else None),
        "isGroup": c.get("isGroup", False) or (isinstance(cid, str) and cid.endswith("@g.us")),
        "unreadCount": unread,
        "timestamp": ts,
        "lastMessagePreview": last_body,
        "archived": bool(c.get("archived", False)),
        "pinned": bool(c.get("pinned", False)),
        "muted": bool(c.get("isMuted") or c.get("muteEndTime", 0) > 0),
    }


def slim_contact(c: dict) -> dict:
    """Reduce a WAHA contact/check-exists response."""
    if not isinstance(c, dict):
        return {"raw": c}
    return {
        "exists": c.get("numberExists", c.get("exists")),
        "chat_id": _serialize_id(c.get("chatId") or c.get("id")),
        "phone": c.get("phone") or c.get("number"),
        "name": c.get("name") or c.get("pushname") or c.get("verifiedName"),
        "isBusiness": c.get("isBusiness", False),
        "isMyContact": c.get("isMyContact"),
    }


def slim_group(g: dict, include_participants: bool = True) -> dict:
    """Reduce a WAHA group object (create/get-group response)."""
    if not isinstance(g, dict):
        return {"raw": g}
    out = {
        "id": _serialize_id(g.get("id")) or _serialize_id(g.get("gid")),
        "name": g.get("name") or g.get("subject"),
        "description": g.get("description") or (g.get("groupMetadata") or {}).get("desc"),
        "owner": _serialize_id(g.get("owner") or (g.get("groupMetadata") or {}).get("owner")),
        "createdAt": g.get("createdAt") or (g.get("groupMetadata") or {}).get("creation"),
    }
    if include_participants:
        meta = g.get("groupMetadata") or g
        parts = meta.get("participants") or g.get("participants") or []
        slim_parts = []
        for p in parts:
            if not isinstance(p, dict):
                continue
            slim_parts.append({
                "id": _serialize_id(p.get("id")),
                "isAdmin": p.get("isAdmin", False) or p.get("admin") in ("admin", "superadmin"),
                "isSuperAdmin": p.get("isSuperAdmin", False) or p.get("admin") == "superadmin",
            })
        out["participants"] = slim_parts
        out["participantsCount"] = len(slim_parts)
    return out


def ok(payload: Any = None, **extra) -> dict:
    """Build a success envelope."""
    out: dict = {"success": True}
    if payload is not None:
        out["data"] = payload
    out.update(extra)
    return out
