"""MCP tools for inspecting and restarting the WAHA session."""
import json
from pydantic import BaseModel, Field, ConfigDict
from mcp.server.fastmcp import FastMCP

from server.waha_client import waha_get, waha_post, handle_error, WAHA_SESSION


def _slim_session(s: dict) -> dict:
    if not isinstance(s, dict):
        return {"raw": s}
    me = s.get("me") or {}
    return {
        "name": s.get("name"),
        "status": s.get("status"),
        "me_id": me.get("id") if isinstance(me, dict) else None,
        "me_pushName": me.get("pushName") if isinstance(me, dict) else None,
        "presence": s.get("presence"),
    }


def register(mcp_instance: FastMCP):

    @mcp_instance.tool(
        name="whatsapp_get_session_status",
        annotations={
            "title": "État de la session WAHA / WhatsApp",
            "readOnlyHint": True, "destructiveHint": False,
            "idempotentHint": True, "openWorldHint": True,
        },
    )
    async def whatsapp_get_session_status() -> str:
        """Retourne l'état de la session: WORKING / STARTING / STOPPED / SCAN_QR_CODE / FAILED.

        Sert à diagnostiquer pourquoi un autre tool échoue (ex: session SCAN_QR_CODE
        signifie qu'il faut re-pair via le QR code).
        """
        try:
            r = await waha_get("/api/sessions")
            if isinstance(r, list):
                ours = next((s for s in r if isinstance(s, dict) and s.get("name") == WAHA_SESSION), None)
                if ours:
                    return json.dumps(_slim_session(ours), ensure_ascii=False, indent=2)
                return json.dumps({"success": False, "error": f"Session '{WAHA_SESSION}' introuvable.",
                                   "sessions": [_slim_session(s) for s in r]},
                                  ensure_ascii=False, indent=2)
            return json.dumps({"raw": r}, ensure_ascii=False, indent=2)
        except Exception as e:
            return handle_error(e)

    class RestartInput(BaseModel):
        model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
        confirm: bool = Field(
            ...,
            description="Doit être True. Garde-fou pour éviter un restart accidentel.",
        )

    @mcp_instance.tool(
        name="whatsapp_restart_session",
        annotations={
            "title": "Redémarrer la session WAHA (sans déconnexion)",
            "readOnlyHint": False, "destructiveHint": False,
            "idempotentHint": True, "openWorldHint": True,
        },
    )
    async def whatsapp_restart_session(params: RestartInput) -> str:
        """Redémarre la session WAHA (~30s STARTING → WORKING).

        Le pairing est préservé (pas besoin de re-scanner). À utiliser si la
        session est bloquée en FAILED ou si WAHA répond avec les erreurs
        'waitForChatLoading'.
        """
        if not params.confirm:
            return json.dumps({"success": False, "error": "confirm doit être True."},
                              ensure_ascii=False, indent=2)
        try:
            await waha_post(f"/api/sessions/{WAHA_SESSION}/restart", {})
            return json.dumps({"success": True, "session": WAHA_SESSION,
                               "note": "STARTING → WORKING en ~30s. Vérifie via whatsapp_get_session_status."},
                              ensure_ascii=False, indent=2)
        except Exception as e:
            return handle_error(e)
