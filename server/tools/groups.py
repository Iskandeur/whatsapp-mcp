"""MCP tools for WhatsApp chats and groups."""
import json
from pydantic import BaseModel, Field, ConfigDict
from typing import List, Optional
from mcp.server.fastmcp import FastMCP

from server.waha_client import waha_get, waha_post, resolve_chat_id, handle_error, WAHA_SESSION
from server.schema import slim_chat, slim_group


def register(mcp_instance: FastMCP):

    class ListChatsInput(BaseModel):
        model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
        name_contains: Optional[str] = Field(
            default=None,
            description="Filtrer par nom (sous-chaîne, insensible à la casse).",
        )
        only_groups: Optional[bool] = Field(
            default=False,
            description="Si True, ne retourne que les groupes (@g.us).",
        )
        only_contacts: Optional[bool] = Field(
            default=False,
            description="Si True, ne retourne que les contacts (exclut les groupes).",
        )
        only_unread: Optional[bool] = Field(
            default=False,
            description="Si True, ne retourne que les chats avec unreadCount > 0.",
        )
        include_archived: Optional[bool] = Field(
            default=False,
            description="Inclure les chats archivés. Par défaut, ils sont exclus.",
        )
        since_timestamp: Optional[int] = Field(
            default=None,
            description="Unix timestamp (secondes). Ne retourne que les chats actifs après ce moment.",
        )
        limit: Optional[int] = Field(
            default=50,
            description="Nombre max de chats à retourner après filtrage (1-500).",
            ge=1,
            le=500,
        )
        offset: Optional[int] = Field(
            default=0,
            description="Offset pour paginer dans la liste filtrée.",
            ge=0,
        )
        sort_by: Optional[str] = Field(
            default="timestamp",
            description="Tri: 'timestamp' (activité récente, défaut), 'unread' (non lus en premier), 'name' (alpha).",
        )

    @mcp_instance.tool(
        name="whatsapp_list_chats",
        annotations={
            "title": "Lister les conversations WhatsApp (filtré, paginé)",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
    )
    async def whatsapp_list_chats(params: Optional[ListChatsInput] = None) -> str:
        """Retourne les conversations actives, en version slim et filtrée.

        WAHA renvoie tous les chats du compte (600+ possible). Filtrer côté serveur
        avec `name_contains`/`only_groups`/`only_unread` avant pagination.
        """
        if params is None:
            params = ListChatsInput()
        try:
            result = await waha_get(f"/api/{WAHA_SESSION}/chats")
            if not isinstance(result, list):
                return json.dumps(result, ensure_ascii=False, indent=2)

            total_raw = len(result)
            slim = [slim_chat(c) for c in result]

            if not params.include_archived:
                slim = [c for c in slim if not c.get("archived")]
            if params.name_contains:
                q = params.name_contains.lower()
                slim = [c for c in slim if c.get("name") and q in c["name"].lower()]
            if params.only_groups:
                slim = [c for c in slim if c.get("isGroup")]
            if params.only_contacts:
                slim = [c for c in slim if not c.get("isGroup")]
            if params.only_unread:
                slim = [c for c in slim if (c.get("unreadCount") or 0) > 0]
            if params.since_timestamp:
                slim = [c for c in slim if (c.get("timestamp") or 0) >= params.since_timestamp]

            sort_by = (params.sort_by or "timestamp").lower()
            if sort_by == "unread":
                slim.sort(key=lambda c: (c.get("unreadCount") or 0, c.get("timestamp") or 0), reverse=True)
            elif sort_by == "name":
                slim.sort(key=lambda c: (c.get("name") or "").lower())
            else:
                slim.sort(key=lambda c: c.get("timestamp") or 0, reverse=True)

            total_matching = len(slim)
            offset = params.offset or 0
            limit = params.limit or 50
            page = slim[offset: offset + limit]
            next_offset = offset + len(page) if (offset + len(page)) < total_matching else None
            return json.dumps(
                {
                    "total_raw": total_raw,
                    "total_matching": total_matching,
                    "returned": len(page),
                    "offset": offset,
                    "next_offset": next_offset,
                    "chats": page,
                },
                ensure_ascii=False,
                indent=2,
            )
        except Exception as e:
            return handle_error(e)

    class GetGroupInput(BaseModel):
        model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
        group_id: str = Field(..., description="ID du groupe, format: '<digits>@g.us'")
        verbose: Optional[bool] = Field(default=False, description="Retourne le payload WAHA brut.")

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
            if params.verbose:
                return json.dumps(result, ensure_ascii=False, indent=2)
            return json.dumps(slim_group(result), ensure_ascii=False, indent=2)
        except Exception as e:
            return handle_error(e)

    class CreateGroupInput(BaseModel):
        model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
        name: str = Field(..., description="Nom du groupe", min_length=1, max_length=100)
        participants: List[str] = Field(
            ...,
            description="IDs participants, format: ['<digits>@c.us', '<digits>@lid', ...].",
            min_length=1,
        )
        verbose: Optional[bool] = Field(default=False, description="Retourne le payload WAHA brut.")

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
        """Crée un nouveau groupe WhatsApp avec les participants indiqués.

        Chaque participant peut être un chat_id (@c.us/@lid) ou un numéro brut
        — la résolution vers le JID canonique est faite via check-exists.
        """
        try:
            resolved = [await resolve_chat_id(p) for p in params.participants]
            body = {
                "name": params.name,
                "participants": [{"id": p} for p in resolved],
            }
            result = await waha_post(f"/api/{WAHA_SESSION}/groups", body)
            if params.verbose:
                return json.dumps(result, ensure_ascii=False, indent=2)
            return json.dumps(slim_group(result), ensure_ascii=False, indent=2)
        except Exception as e:
            return handle_error(e)
