"""MCP tools for managing WhatsApp contacts."""
import json
from pydantic import BaseModel, Field, ConfigDict
from typing import Optional
from mcp.server.fastmcp import FastMCP

from server.waha_client import waha_get, handle_error, WAHA_SESSION
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
