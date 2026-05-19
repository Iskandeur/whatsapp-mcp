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


def slim_message(m: dict, include_media: bool = True) -> dict:
    """Reduce a WAHA message object to the fields a model actually consumes."""
    if not isinstance(m, dict):
        return m
    data = m.get("_data") or {}

    msg_type = m.get("type") or data.get("type") or ""

    push = (
        data.get("notifyName")
        or data.get("pushname")
        or m.get("pushName")
        or m.get("_pushName")
        or ""
    )

    quoted = m.get("hasQuotedMsg") or data.get("quotedMsg") is not None
    quoted_body = ""
    if quoted:
        q = data.get("quotedMsg") or {}
        quoted_body = (q.get("body") or "")[:200]

    out = {
        "id": _serialize_id(m.get("id")),
        "timestamp": m.get("timestamp") or data.get("t"),
        "from": _serialize_id(m.get("author") or m.get("from")),
        "to": _serialize_id(m.get("to")),
        "fromMe": m.get("fromMe", False),
        "pushName": push,
        "type": msg_type,
        "body": (m.get("body") or "")[:4000],
        "ack": m.get("ack"),
        "hasMedia": m.get("hasMedia", False),
        "hasQuoted": quoted,
        "quotedBody": quoted_body,
        "hasReaction": bool(data.get("hasReaction")),
        "isForwarded": bool(data.get("isForwarded")),
        "forwardsCount": data.get("forwardsCount") or data.get("forwardingScore") or 0,
        "starred": bool(data.get("star")),
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
    """Reduce a WAHA chat list entry."""
    if not isinstance(c, dict):
        return c
    cid = _serialize_id(c.get("id"))
    last = c.get("lastMessage") or {}
    last_body = (last.get("body") or "")[:200] if isinstance(last, dict) else ""
    last_ts = last.get("timestamp") if isinstance(last, dict) else None
    unread = c.get("unreadCount") or 0
    if unread < 0:
        unread = 0
    return {
        "id": cid,
        "name": c.get("name"),
        "isGroup": c.get("isGroup", False) or (isinstance(cid, str) and cid.endswith("@g.us")),
        "unreadCount": unread,
        "timestamp": c.get("timestamp") or last_ts,
        "lastMessagePreview": last_body,
        "archived": c.get("archived", False),
        "pinned": c.get("pinned", False),
        "muted": c.get("isMuted", False),
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
