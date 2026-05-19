"""MCP tools for WhatsApp chats and groups."""
import json
from pydantic import BaseModel, Field, ConfigDict
from typing import List, Optional
from mcp.server.fastmcp import FastMCP

from server.waha_client import waha_get, waha_post, handle_error, WAHA_SESSION


def _slim_chat(c: dict) -> dict:
    """Return only the fields a model actually needs to decide what to do."""
    cid = c.get("id")
    if isinstance(cid, dict):
        cid = cid.get("_serialized") or cid.get("user")
    last = c.get("lastMessage") or {}
    last_body = (last.get("body") or "")[:200] if isinstance(last, dict) else ""
    last_ts = last.get("timestamp") if isinstance(last, dict) else None
    return {
        "id": cid,
        "name": c.get("name"),
        "isGroup": c.get("isGroup", False),
        "unreadCount": c.get("unreadCount", 0),
        "timestamp": c.get("timestamp") or last_ts,
        "lastMessagePreview": last_body,
        "archived": c.get("archived", False),
        "pinned": c.get("pinned", False),
        "muted": c.get("isMuted", False),
    }


def register(mcp_instance: FastMCP):

    class ListChatsInput(BaseModel):
        model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
        name_contains: Optional[str] = Field(
            default=None,
            description="Filtrer par nom (sous-chaîne, insensible à la casse). Ex: 'meute' pour ne récupérer que les groupes scout.",
        )
        only_groups: Optional[bool] = Field(
            default=False,
            description="Si True, ne retourne que les groupes (@g.us).",
        )
        only_unread: Optional[bool] = Field(
            default=False,
            description="Si True, ne retourne que les chats avec unreadCount > 0.",
        )
        limit: Optional[int] = Field(
            default=50,
            description="Nombre max de chats à retourner (1-200). Triés par activité récente.",
            ge=1,
            le=200,
        )

    @mcp_instance.tool(
        name="whatsapp_list_chats",
        annotations={
            "title": "Lister les conversations WhatsApp (filtré)",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
    )
    async def whatsapp_list_chats(params: Optional[ListChatsInput] = None) -> str:
        """Retourne les conversations actives, en version légère.

        Pour trouver un groupe précis, passe `name_contains='meute'` plutôt que de
        tout lister. Les groupes ont un id terminant par '@g.us', les contacts par '@c.us'.
        Chaque chat est réduit aux champs essentiels (id, name, unreadCount, lastMessagePreview).
        """
        if params is None:
            params = ListChatsInput()
        try:
            result = await waha_get(f"/api/{WAHA_SESSION}/chats")
            if not isinstance(result, list):
                return json.dumps(result, ensure_ascii=False, indent=2)

            slim = [_slim_chat(c) for c in result]
            if params.name_contains:
                q = params.name_contains.lower()
                slim = [c for c in slim if c.get("name") and q in c["name"].lower()]
            if params.only_groups:
                slim = [c for c in slim if c.get("isGroup")]
            if params.only_unread:
                slim = [c for c in slim if (c.get("unreadCount") or 0) > 0]

            slim.sort(key=lambda c: c.get("timestamp") or 0, reverse=True)
            total_matching = len(slim)
            slim = slim[: params.limit or 50]
            return json.dumps(
                {"total_matching": total_matching, "returned": len(slim), "chats": slim},
                ensure_ascii=False,
                indent=2,
            )
        except Exception as e:
            return handle_error(e)

    class GetGroupInput(BaseModel):
        model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
        group_id: str = Field(
            ...,
            description="ID du groupe, format: 'XXXXXXXXXX@g.us'",
        )

    @mcp_instance.tool(
        name="whatsapp_get_group_info",
        annotations={
            "title": "Obtenir les infos détaillées d'un groupe WhatsApp",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
    )
    async def whatsapp_get_group_info(params: GetGroupInput) -> str:
        """Retourne les métadonnées d'un groupe : description, participants, admins."""
        try:
            result = await waha_get(f"/api/{WAHA_SESSION}/groups/{params.group_id}")
            return json.dumps(result, ensure_ascii=False, indent=2)
        except Exception as e:
            return handle_error(e)

    class CreateGroupInput(BaseModel):
        model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
        name: str = Field(..., description="Nom du groupe", min_length=1, max_length=100)
        participants: List[str] = Field(
            ...,
            description="Liste des IDs participants, format: ['33612345678@c.us', ...]",
            min_length=1,
        )

    @mcp_instance.tool(
        name="whatsapp_create_group",
        annotations={
            "title": "Créer un groupe WhatsApp",
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": True,
        },
    )
    async def whatsapp_create_group(params: CreateGroupInput) -> str:
        """Crée un nouveau groupe WhatsApp avec les participants indiqués."""
        try:
            body = {
                "name": params.name,
                "participants": [{"id": p} for p in params.participants],
            }
            result = await waha_post(f"/api/{WAHA_SESSION}/groups", body)
            return json.dumps(result, ensure_ascii=False, indent=2)
        except Exception as e:
            return handle_error(e)
