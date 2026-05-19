"""
WhatsApp MCP server entrypoint.
Transport: Streamable HTTP (Claude.ai-compatible remote MCP).
Auth: Bearer token via MCP_API_KEY env var.
"""
import os
import logging
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from server.tools import messages, contacts, groups, media

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

ALLOWED_HOSTS = [h.strip() for h in os.getenv(
    "MCP_ALLOWED_HOSTS",
    "localhost,127.0.0.1",
).split(",") if h.strip()]

mcp = FastMCP(
    name="whatsapp_mcp",
    transport_security=TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=ALLOWED_HOSTS,
        allowed_origins=[f"https://{h}" for h in ALLOWED_HOSTS if "." in h] + ["http://localhost", "http://127.0.0.1"],
    ),
    instructions="""
Tu as accès à WhatsApp via ces outils. Conventions importantes :
- chat_id contact : '33612345678@c.us' (indicatif pays + numéro, sans '+')
- chat_id groupe  : 'XXXXXXXXXX@g.us'
- Utilise whatsapp_list_chats pour découvrir les IDs disponibles.
- Avant d'envoyer un message, confirme toujours le destinataire avec l'utilisateur.
- Ne jamais envoyer en masse sans confirmation explicite.
""",
)

messages.register(mcp)
contacts.register(mcp)
groups.register(mcp)
media.register(mcp)

logger.info("Outils MCP WhatsApp enregistrés.")

MCP_API_KEY = os.getenv("MCP_API_KEY", "")
_base_app = mcp.streamable_http_app()


async def _healthz(scope, receive, send):
    from starlette.responses import JSONResponse
    resp = JSONResponse({"status": "ok", "service": "whatsapp-mcp"})
    await resp(scope, receive, send)


async def _unauthorized(scope, receive, send):
    from starlette.responses import Response
    resp = Response("Not Found", status_code=404)
    await resp(scope, receive, send)


if MCP_API_KEY:
    SECRET_PREFIX = f"/{MCP_API_KEY}"

    async def app(scope, receive, send):
        if scope["type"] == "http":
            path = scope.get("path", "")
            if path in ("/healthz", "/health"):
                return await _healthz(scope, receive, send)
            if not path.startswith(SECRET_PREFIX + "/") and path != SECRET_PREFIX:
                return await _unauthorized(scope, receive, send)
            new_path = path[len(SECRET_PREFIX):] or "/"
            scope = {**scope, "path": new_path, "raw_path": new_path.encode("utf-8")}
        return await _base_app(scope, receive, send)

    logger.info("Auth via URL-path secret activée.")
else:
    async def app(scope, receive, send):
        if scope["type"] == "http":
            path = scope.get("path", "")
            if path in ("/healthz", "/health"):
                return await _healthz(scope, receive, send)
        return await _base_app(scope, receive, send)

    logger.warning("MCP_API_KEY non défini — serveur accessible sans auth !")


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", "8765"))
    logger.info(f"Démarrage sur 0.0.0.0:{port}")
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")
