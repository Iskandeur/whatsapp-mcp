"""MCP tools for WhatsApp chats and groups."""
import json
from pydantic import BaseModel, Field, ConfigDict
from typing import List, Optional
from mcp.server.fastmcp import FastMCP

from server.waha_client import (
    waha_get, waha_post, waha_put, waha_delete,
    resolve_chat_id, handle_error, WAHA_SESSION,
)
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

    class GroupParticipantsInput(BaseModel):
        model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
        group_id: str = Field(..., description="ID du groupe '<digits>@g.us'.")
        participants: List[str] = Field(
            ...,
            min_length=1,
            description="Liste de chat_ids ou numéros bruts. Résolus automatiquement.",
        )

    async def _resolve_participants(items):
        return [await resolve_chat_id(p) for p in items]

    @mcp_instance.tool(
        name="whatsapp_add_participants",
        annotations={
            "title": "Ajouter des participants à un groupe",
            "readOnlyHint": False, "destructiveHint": False,
            "idempotentHint": True, "openWorldHint": True,
        },
    )
    async def whatsapp_add_participants(params: GroupParticipantsInput) -> str:
        """Ajoute des participants à un groupe existant (l'utilisateur doit être admin)."""
        try:
            ids = await _resolve_participants(params.participants)
            result = await waha_post(
                f"/api/{WAHA_SESSION}/groups/{params.group_id}/participants/add",
                {"participants": [{"id": i} for i in ids]},
            )
            return json.dumps({"success": True, "group_id": params.group_id, "added": ids, "raw": result},
                              ensure_ascii=False, indent=2)
        except Exception as e:
            return handle_error(e)

    @mcp_instance.tool(
        name="whatsapp_remove_participants",
        annotations={
            "title": "Retirer des participants d'un groupe",
            "readOnlyHint": False, "destructiveHint": True,
            "idempotentHint": True, "openWorldHint": True,
        },
    )
    async def whatsapp_remove_participants(params: GroupParticipantsInput) -> str:
        """Retire des participants d'un groupe (l'utilisateur doit être admin)."""
        try:
            ids = await _resolve_participants(params.participants)
            result = await waha_post(
                f"/api/{WAHA_SESSION}/groups/{params.group_id}/participants/remove",
                {"participants": [{"id": i} for i in ids]},
            )
            return json.dumps({"success": True, "group_id": params.group_id, "removed": ids, "raw": result},
                              ensure_ascii=False, indent=2)
        except Exception as e:
            return handle_error(e)

    @mcp_instance.tool(
        name="whatsapp_promote_participants",
        annotations={
            "title": "Promouvoir des participants admin",
            "readOnlyHint": False, "destructiveHint": False,
            "idempotentHint": True, "openWorldHint": True,
        },
    )
    async def whatsapp_promote_participants(params: GroupParticipantsInput) -> str:
        """Promeut des participants en admin du groupe."""
        try:
            ids = await _resolve_participants(params.participants)
            result = await waha_post(
                f"/api/{WAHA_SESSION}/groups/{params.group_id}/admin/promote",
                {"participants": [{"id": i} for i in ids]},
            )
            return json.dumps({"success": True, "group_id": params.group_id, "promoted": ids, "raw": result},
                              ensure_ascii=False, indent=2)
        except Exception as e:
            return handle_error(e)

    @mcp_instance.tool(
        name="whatsapp_demote_participants",
        annotations={
            "title": "Rétrograder des admins",
            "readOnlyHint": False, "destructiveHint": False,
            "idempotentHint": True, "openWorldHint": True,
        },
    )
    async def whatsapp_demote_participants(params: GroupParticipantsInput) -> str:
        """Rétrograde des admins en simples membres."""
        try:
            ids = await _resolve_participants(params.participants)
            result = await waha_post(
                f"/api/{WAHA_SESSION}/groups/{params.group_id}/admin/demote",
                {"participants": [{"id": i} for i in ids]},
            )
            return json.dumps({"success": True, "group_id": params.group_id, "demoted": ids, "raw": result},
                              ensure_ascii=False, indent=2)
        except Exception as e:
            return handle_error(e)

    class GroupIdInput(BaseModel):
        model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
        group_id: str = Field(..., description="ID du groupe '<digits>@g.us'.")

    @mcp_instance.tool(
        name="whatsapp_leave_group",
        annotations={
            "title": "Quitter un groupe WhatsApp",
            "readOnlyHint": False, "destructiveHint": True,
            "idempotentHint": True, "openWorldHint": True,
        },
    )
    async def whatsapp_leave_group(params: GroupIdInput) -> str:
        """Fait quitter le compte courant du groupe."""
        try:
            await waha_post(f"/api/{WAHA_SESSION}/groups/{params.group_id}/leave", {})
            return json.dumps({"success": True, "group_id": params.group_id, "left": True},
                              ensure_ascii=False, indent=2)
        except Exception as e:
            return handle_error(e)

    class GroupSubjectInput(BaseModel):
        model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
        group_id: str = Field(..., description="ID du groupe.")
        subject: str = Field(..., min_length=1, max_length=100, description="Nouveau nom du groupe.")

    @mcp_instance.tool(
        name="whatsapp_set_group_subject",
        annotations={
            "title": "Renommer un groupe WhatsApp",
            "readOnlyHint": False, "destructiveHint": False,
            "idempotentHint": True, "openWorldHint": True,
        },
    )
    async def whatsapp_set_group_subject(params: GroupSubjectInput) -> str:
        """Change le nom (subject) d'un groupe."""
        try:
            await waha_put(
                f"/api/{WAHA_SESSION}/groups/{params.group_id}/subject",
                {"subject": params.subject},
            )
            return json.dumps({"success": True, "group_id": params.group_id, "subject": params.subject},
                              ensure_ascii=False, indent=2)
        except Exception as e:
            return handle_error(e)

    class GroupDescriptionInput(BaseModel):
        model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
        group_id: str = Field(..., description="ID du groupe.")
        description: str = Field(..., max_length=2048, description="Nouvelle description (vide pour effacer).")

    @mcp_instance.tool(
        name="whatsapp_set_group_description",
        annotations={
            "title": "Modifier la description d'un groupe",
            "readOnlyHint": False, "destructiveHint": False,
            "idempotentHint": True, "openWorldHint": True,
        },
    )
    async def whatsapp_set_group_description(params: GroupDescriptionInput) -> str:
        """Change la description d'un groupe."""
        try:
            await waha_put(
                f"/api/{WAHA_SESSION}/groups/{params.group_id}/description",
                {"description": params.description},
            )
            return json.dumps({"success": True, "group_id": params.group_id,
                               "description": params.description}, ensure_ascii=False, indent=2)
        except Exception as e:
            return handle_error(e)

    class GroupSettingsInput(BaseModel):
        model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
        group_id: str = Field(..., description="ID du groupe.")
        messages_admin_only: Optional[bool] = Field(
            default=None, description="True = seuls les admins peuvent écrire."
        )
        info_admin_only: Optional[bool] = Field(
            default=None, description="True = seuls les admins peuvent modifier nom/photo/description."
        )

    @mcp_instance.tool(
        name="whatsapp_set_group_settings",
        annotations={
            "title": "Modifier les paramètres d'un groupe",
            "readOnlyHint": False, "destructiveHint": False,
            "idempotentHint": True, "openWorldHint": True,
        },
    )
    async def whatsapp_set_group_settings(params: GroupSettingsInput) -> str:
        """Modifie les paramètres admin-only (envoi de messages, modification des infos)."""
        try:
            applied = {}
            if params.messages_admin_only is not None:
                await waha_put(
                    f"/api/{WAHA_SESSION}/groups/{params.group_id}/settings/security/messages-admin-only",
                    {"adminsOnly": params.messages_admin_only},
                )
                applied["messages_admin_only"] = params.messages_admin_only
            if params.info_admin_only is not None:
                await waha_put(
                    f"/api/{WAHA_SESSION}/groups/{params.group_id}/settings/security/info-admin-only",
                    {"adminsOnly": params.info_admin_only},
                )
                applied["info_admin_only"] = params.info_admin_only
            if not applied:
                return json.dumps({"success": False, "error": "Aucun paramètre fourni."},
                                  ensure_ascii=False, indent=2)
            return json.dumps({"success": True, "group_id": params.group_id, "applied": applied},
                              ensure_ascii=False, indent=2)
        except Exception as e:
            return handle_error(e)

    @mcp_instance.tool(
        name="whatsapp_get_invite_link",
        annotations={
            "title": "Obtenir le lien d'invitation d'un groupe",
            "readOnlyHint": True, "destructiveHint": False,
            "idempotentHint": True, "openWorldHint": True,
        },
    )
    async def whatsapp_get_invite_link(params: GroupIdInput) -> str:
        """Retourne le code et l'URL d'invitation https://chat.whatsapp.com/<code>."""
        try:
            result = await waha_get(f"/api/{WAHA_SESSION}/groups/{params.group_id}/invite-code")
            code = result.get("code") or result.get("inviteCode") or (result if isinstance(result, str) else None)
            return json.dumps({
                "success": True,
                "group_id": params.group_id,
                "code": code,
                "url": f"https://chat.whatsapp.com/{code}" if code else None,
            }, ensure_ascii=False, indent=2)
        except Exception as e:
            return handle_error(e)

    @mcp_instance.tool(
        name="whatsapp_revoke_invite_link",
        annotations={
            "title": "Révoquer (et régénérer) le lien d'invitation",
            "readOnlyHint": False, "destructiveHint": True,
            "idempotentHint": False, "openWorldHint": True,
        },
    )
    async def whatsapp_revoke_invite_link(params: GroupIdInput) -> str:
        """Invalide le lien d'invitation existant et en génère un nouveau."""
        try:
            result = await waha_post(
                f"/api/{WAHA_SESSION}/groups/{params.group_id}/invite-code/revoke", {}
            )
            code = result.get("code") or result.get("inviteCode") if isinstance(result, dict) else None
            return json.dumps({
                "success": True, "group_id": params.group_id, "new_code": code,
                "new_url": f"https://chat.whatsapp.com/{code}" if code else None,
            }, ensure_ascii=False, indent=2)
        except Exception as e:
            return handle_error(e)

    class JoinGroupInput(BaseModel):
        model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
        code: str = Field(..., min_length=1,
                          description="Code d'invitation (la partie après https://chat.whatsapp.com/).")

    @mcp_instance.tool(
        name="whatsapp_join_group",
        annotations={
            "title": "Rejoindre un groupe via lien d'invitation",
            "readOnlyHint": False, "destructiveHint": False,
            "idempotentHint": True, "openWorldHint": True,
        },
    )
    async def whatsapp_join_group(params: JoinGroupInput) -> str:
        """Rejoint un groupe via son code d'invitation."""
        try:
            code = params.code
            if "chat.whatsapp.com/" in code:
                code = code.split("chat.whatsapp.com/", 1)[1].strip("/")
            result = await waha_post(f"/api/{WAHA_SESSION}/groups/join", {"code": code})
            gid = (result.get("id") if isinstance(result, dict) else None)
            if isinstance(gid, dict):
                gid = gid.get("_serialized")
            return json.dumps({"success": True, "code": code, "group_id": gid},
                              ensure_ascii=False, indent=2)
        except Exception as e:
            return handle_error(e)
