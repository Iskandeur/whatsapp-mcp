"""MCP tools for managing WhatsApp contacts."""
import json
from pydantic import BaseModel, Field, ConfigDict
from mcp.server.fastmcp import FastMCP

from server.waha_client import waha_get, handle_error, WAHA_SESSION


def register(mcp_instance: FastMCP):

    class GetContactInput(BaseModel):
        model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
        phone: str = Field(
            ...,
            description="Numéro de téléphone avec indicatif pays, sans '+' ni espaces. Ex: '33612345678'",
        )

    @mcp_instance.tool(
        name="whatsapp_get_contact",
        annotations={
            "title": "Obtenir les infos d'un contact WhatsApp",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
    )
    async def whatsapp_get_contact(params: GetContactInput) -> str:
        """Vérifie si un numéro est sur WhatsApp et retourne ses infos."""
        try:
            result = await waha_get(
                "/api/contacts/check-exists",
                params={"phone": params.phone, "session": WAHA_SESSION},
            )
            return json.dumps(result, ensure_ascii=False, indent=2)
        except Exception as e:
            return handle_error(e)

    @mcp_instance.tool(
        name="whatsapp_list_contacts",
        annotations={
            "title": "Lister tous les contacts WhatsApp",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
    )
    async def whatsapp_list_contacts() -> str:
        """Retourne la liste de tous les contacts WhatsApp enregistrés."""
        try:
            result = await waha_get("/api/contacts/all", params={"session": WAHA_SESSION})
            if isinstance(result, list) and len(result) > 200:
                result = {
                    "total": len(result),
                    "note": "Résultats tronqués à 200. Utilise whatsapp_get_contact pour chercher un contact précis.",
                    "contacts": result[:200],
                }
            return json.dumps(result, ensure_ascii=False, indent=2)
        except Exception as e:
            return handle_error(e)
