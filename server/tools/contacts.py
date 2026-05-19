"""MCP tools for managing WhatsApp contacts and the local profile."""
import json
from pydantic import BaseModel, Field, ConfigDict
from typing import List, Optional
from mcp.server.fastmcp import FastMCP

from server.waha_client import (
    waha_get, waha_post, waha_put, resolve_chat_id,
    handle_error, WAHA_SESSION,
)
from server.schema import slim_contact, _serialize_id


def register(mcp_instance: FastMCP):

    class GetContactInput(BaseModel):
        model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
        phone: str = Field(
            ...,
            description="Numéro avec indicatif pays, sans '+' ni espaces. Ex: '33612345678'.",
        )
        verbose: Optional[bool] = Field(default=False, description="Retourne le payload WAHA brut.")

    @mcp_instance.tool(
        name="whatsapp_get_contact",
        annotations={
            "title": "Vérifier qu'un numéro existe sur WhatsApp",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
    )
    async def whatsapp_get_contact(params: GetContactInput) -> str:
        """Vérifie si un numéro est sur WhatsApp et renvoie son chat_id canonique.

        Retourne `{exists, chat_id, phone, name?, isBusiness}`.
        """
        try:
            result = await waha_get(
                "/api/contacts/check-exists",
                params={"phone": params.phone, "session": WAHA_SESSION},
            )
            if params.verbose:
                return json.dumps(result, ensure_ascii=False, indent=2)
            return json.dumps(slim_contact(result), ensure_ascii=False, indent=2)
        except Exception as e:
            return handle_error(e)

    class ListContactsInput(BaseModel):
        model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
        name_contains: Optional[str] = Field(
            default=None,
            description="Filtre sous-chaîne sur le nom (insensible à la casse).",
        )
        limit: Optional[int] = Field(default=200, ge=1, le=1000)
        offset: Optional[int] = Field(default=0, ge=0)

    @mcp_instance.tool(
        name="whatsapp_list_contacts",
        annotations={
            "title": "Lister les contacts WhatsApp",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
    )
    async def whatsapp_list_contacts(params: Optional[ListContactsInput] = None) -> str:
        """Retourne les contacts WhatsApp (filtrés, paginés, en version slim)."""
        if params is None:
            params = ListContactsInput()
        try:
            result = await waha_get("/api/contacts/all", params={"session": WAHA_SESSION})
            if not isinstance(result, list):
                return json.dumps(result, ensure_ascii=False, indent=2)

            slim = []
            for c in result:
                if not isinstance(c, dict):
                    continue
                cid = _serialize_id(c.get("id"))
                if cid and cid.endswith("@g.us"):
                    continue
                slim.append({
                    "id": cid,
                    "name": c.get("name") or c.get("pushname") or c.get("verifiedName"),
                    "pushname": c.get("pushname"),
                    "phone": c.get("number") or c.get("phone"),
                    "isBusiness": c.get("isBusiness", False),
                    "isMyContact": c.get("isMyContact", False),
                })

            if params.name_contains:
                q = params.name_contains.lower()
                slim = [c for c in slim if (c.get("name") or "").lower().find(q) >= 0]

            total = len(slim)
            offset = params.offset or 0
            limit = params.limit or 200
            page = slim[offset: offset + limit]
            next_offset = offset + len(page) if (offset + len(page)) < total else None
            return json.dumps(
                {
                    "total_matching": total,
                    "returned": len(page),
                    "offset": offset,
                    "next_offset": next_offset,
                    "contacts": page,
                },
                ensure_ascii=False,
                indent=2,
            )
        except Exception as e:
            return handle_error(e)

    class CheckNumbersInput(BaseModel):
        model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
        phones: List[str] = Field(
            ..., min_length=1, max_length=50,
            description="Numéros avec indicatif pays, sans '+'.",
        )

    @mcp_instance.tool(
        name="whatsapp_check_numbers",
        annotations={
            "title": "Vérifier en masse si des numéros sont sur WhatsApp",
            "readOnlyHint": True, "destructiveHint": False,
            "idempotentHint": True, "openWorldHint": True,
        },
    )
    async def whatsapp_check_numbers(params: CheckNumbersInput) -> str:
        """Pour chaque numéro, indique s'il a un compte WhatsApp et son chat_id canonique."""
        results = []
        for ph in params.phones:
            digits = "".join(c for c in ph if c.isdigit())
            if not digits:
                results.append({"phone": ph, "exists": False, "error": "format invalide"})
                continue
            try:
                r = await waha_get("/api/contacts/check-exists",
                                   params={"phone": digits, "session": WAHA_SESSION})
                results.append({"phone": digits, **slim_contact(r if isinstance(r, dict) else {})})
            except Exception as e:
                results.append({"phone": digits, "error": str(type(e).__name__)})
        return json.dumps({"count": len(results), "results": results},
                          ensure_ascii=False, indent=2)

    @mcp_instance.tool(
        name="whatsapp_get_profile",
        annotations={
            "title": "Obtenir mon profil WhatsApp",
            "readOnlyHint": True, "destructiveHint": False,
            "idempotentHint": True, "openWorldHint": True,
        },
    )
    async def whatsapp_get_profile() -> str:
        """Retourne mon profil (id, nom, URL de la photo de profil, status)."""
        try:
            r = await waha_get(f"/api/{WAHA_SESSION}/profile")
            return json.dumps(r if isinstance(r, dict) else {"raw": r},
                              ensure_ascii=False, indent=2)
        except Exception as e:
            return handle_error(e)

    class SetProfileNameInput(BaseModel):
        model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
        name: str = Field(..., min_length=1, max_length=25, description="Nouveau nom affiché.")

    @mcp_instance.tool(
        name="whatsapp_set_profile_name",
        annotations={
            "title": "Changer mon nom WhatsApp",
            "readOnlyHint": False, "destructiveHint": False,
            "idempotentHint": True, "openWorldHint": True,
        },
    )
    async def whatsapp_set_profile_name(params: SetProfileNameInput) -> str:
        """Change mon nom affiché sur WhatsApp."""
        try:
            await waha_put(f"/api/{WAHA_SESSION}/profile/name", {"name": params.name})
            return json.dumps({"success": True, "name": params.name},
                              ensure_ascii=False, indent=2)
        except Exception as e:
            return handle_error(e)

    class SetProfileStatusInput(BaseModel):
        model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
        status: str = Field(..., min_length=1, max_length=139,
                            description="Nouveau statut / 'À propos' (max 139 caractères).")

    @mcp_instance.tool(
        name="whatsapp_set_profile_status",
        annotations={
            "title": "Changer mon statut / 'À propos'",
            "readOnlyHint": False, "destructiveHint": False,
            "idempotentHint": True, "openWorldHint": True,
        },
    )
    async def whatsapp_set_profile_status(params: SetProfileStatusInput) -> str:
        """Change mon statut (texte 'À propos') WhatsApp."""
        try:
            await waha_put(f"/api/{WAHA_SESSION}/profile/status", {"status": params.status})
            return json.dumps({"success": True, "status": params.status},
                              ensure_ascii=False, indent=2)
        except Exception as e:
            return handle_error(e)

    class ContactIdInput(BaseModel):
        model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
        chat_id: str = Field(..., description="Contact (chat_id ou numéro brut).")

    @mcp_instance.tool(
        name="whatsapp_get_profile_picture",
        annotations={
            "title": "Obtenir la photo de profil d'un contact",
            "readOnlyHint": True, "destructiveHint": False,
            "idempotentHint": True, "openWorldHint": True,
        },
    )
    async def whatsapp_get_profile_picture(params: ContactIdInput) -> str:
        """Retourne l'URL de la photo de profil d'un contact (ou null si masquée)."""
        try:
            chat_id = await resolve_chat_id(params.chat_id)
            r = await waha_get(f"/api/{WAHA_SESSION}/contacts/profile-picture",
                               params={"contactId": chat_id})
            url = r.get("profilePictureURL") or r.get("url") if isinstance(r, dict) else None
            return json.dumps({"success": True, "chat_id": chat_id, "url": url},
                              ensure_ascii=False, indent=2)
        except Exception as e:
            return handle_error(e)

    @mcp_instance.tool(
        name="whatsapp_get_about",
        annotations={
            "title": "Obtenir le statut 'À propos' d'un contact",
            "readOnlyHint": True, "destructiveHint": False,
            "idempotentHint": True, "openWorldHint": True,
        },
    )
    async def whatsapp_get_about(params: ContactIdInput) -> str:
        """Retourne le texte 'À propos' d'un contact (ou null si masqué)."""
        try:
            chat_id = await resolve_chat_id(params.chat_id)
            r = await waha_get(f"/api/{WAHA_SESSION}/contacts/about",
                               params={"contactId": chat_id})
            about = r.get("about") if isinstance(r, dict) else None
            return json.dumps({"success": True, "chat_id": chat_id, "about": about},
                              ensure_ascii=False, indent=2)
        except Exception as e:
            return handle_error(e)

    @mcp_instance.tool(
        name="whatsapp_block_contact",
        annotations={
            "title": "Bloquer un contact",
            "readOnlyHint": False, "destructiveHint": True,
            "idempotentHint": True, "openWorldHint": True,
        },
    )
    async def whatsapp_block_contact(params: ContactIdInput) -> str:
        """Bloque un contact WhatsApp."""
        try:
            chat_id = await resolve_chat_id(params.chat_id)
            await waha_post("/api/contacts/block",
                            {"session": WAHA_SESSION, "contactId": chat_id})
            return json.dumps({"success": True, "chat_id": chat_id, "blocked": True},
                              ensure_ascii=False, indent=2)
        except Exception as e:
            return handle_error(e)

    @mcp_instance.tool(
        name="whatsapp_unblock_contact",
        annotations={
            "title": "Débloquer un contact",
            "readOnlyHint": False, "destructiveHint": False,
            "idempotentHint": True, "openWorldHint": True,
        },
    )
    async def whatsapp_unblock_contact(params: ContactIdInput) -> str:
        """Débloque un contact WhatsApp."""
        try:
            chat_id = await resolve_chat_id(params.chat_id)
            await waha_post("/api/contacts/unblock",
                            {"session": WAHA_SESSION, "contactId": chat_id})
            return json.dumps({"success": True, "chat_id": chat_id, "blocked": False},
                              ensure_ascii=False, indent=2)
        except Exception as e:
            return handle_error(e)

    @mcp_instance.tool(
        name="whatsapp_list_blocked",
        annotations={
            "title": "Lister les contacts bloqués",
            "readOnlyHint": True, "destructiveHint": False,
            "idempotentHint": True, "openWorldHint": True,
        },
    )
    async def whatsapp_list_blocked() -> str:
        """Retourne les IDs des contacts actuellement bloqués."""
        try:
            r = await waha_get(f"/api/{WAHA_SESSION}/contacts/blocked")
            ids = []
            if isinstance(r, list):
                for item in r:
                    if isinstance(item, str):
                        ids.append(item)
                    elif isinstance(item, dict):
                        ids.append(_serialize_id(item.get("id")) or item.get("contactId"))
            return json.dumps({"count": len(ids), "blocked": ids},
                              ensure_ascii=False, indent=2)
        except Exception as e:
            return handle_error(e)
