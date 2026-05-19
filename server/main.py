"""
WhatsApp MCP server entrypoint.
Transport: Streamable HTTP (Claude.ai-compatible remote MCP).
Auth: Bearer token via MCP_API_KEY env var.
"""
import os
import logging
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from server.tools import messages, contacts, groups, media, actions, presence

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
Tu as accès à WhatsApp via ces outils.

Formats de chat_id :
- Contact moderne : '<digits>@lid' (Linked Identity, WhatsApp récent)
- Contact legacy  : '<digits>@c.us' (toujours accepté, ex: '33612345678@c.us')
- Groupe          : '<digits>@g.us'
La plupart des contacts récents arrivent en @lid. Découvre l'ID exact via
whatsapp_list_chats (filtre `name_contains`) ou whatsapp_get_contact (numéro
brut → chat_id canonique).

Confirmation : avant d'envoyer un message, confirme toujours le destinataire
avec l'utilisateur. Jamais d'envoi en masse sans accord explicite.

Verbosité : les tools d'envoi/lecture retournent un résumé compact par défaut
(`{success, message_id, chat_id, ...}`). Passe `verbose=true` uniquement si
tu as besoin du payload WAHA brut.
""",
)

messages.register(mcp)
contacts.register(mcp)
groups.register(mcp)
media.register(mcp)
actions.register(mcp)
presence.register(mcp)

logger.info("Outils MCP WhatsApp enregistrés.")

MCP_API_KEY = os.getenv("MCP_API_KEY", "")
_base_app = mcp.streamable_http_app()


async def _healthz(scope, receive, send):
    from starlette.responses import JSONResponse
    resp = JSONResponse({"status": "ok", "service": "whatsapp-mcp"})
    await resp(scope, receive, send)


async def _waha_qr_png(scope, receive, send):
    """Proxy WAHA's auth QR PNG through MCP."""
    import httpx
    from starlette.responses import Response, PlainTextResponse
    from server.waha_client import WAHA_BASE, WAHA_API_KEY, WAHA_SESSION
    headers = {"X-Api-Key": WAHA_API_KEY} if WAHA_API_KEY else {}
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get(
                f"{WAHA_BASE}/api/{WAHA_SESSION}/auth/qr",
                headers={**headers, "Accept": "image/png"},
                params={"format": "image"},
            )
        if r.status_code != 200:
            resp = PlainTextResponse(
                f"WAHA returned HTTP {r.status_code} fetching QR: {r.text[:200]}",
                status_code=502,
            )
        else:
            resp = Response(
                r.content,
                media_type=r.headers.get("content-type", "image/png"),
                headers={"Cache-Control": "no-store"},
            )
    except Exception as e:
        resp = PlainTextResponse(f"QR fetch failed: {type(e).__name__}: {e}",
                                  status_code=502)
    await resp(scope, receive, send)


async def _waha_qr_html(scope, receive, send):
    """Self-refreshing HTML page so the QR stays valid while the user scans."""
    from starlette.responses import HTMLResponse
    html = """<!doctype html><html><head><meta charset='utf-8'>
<title>WAHA QR</title>
<meta name='viewport' content='width=device-width,initial-scale=1'>
<style>
body{font-family:system-ui;background:#111;color:#eee;margin:0;display:flex;
flex-direction:column;align-items:center;justify-content:center;min-height:100vh;
gap:1rem;padding:1rem;text-align:center}
img{background:#fff;padding:12px;border-radius:8px;max-width:90vw}
small{opacity:.6}
</style></head><body>
<h2>Scan dans WhatsApp → Appareils connectés</h2>
<img id='qr' src='qr.png?t=0' alt='QR'>
<small>Rafraîchit toutes les 20s. Recharge la page si nécessaire.</small>
<script>
let n=1;setInterval(()=>{document.getElementById('qr').src='qr.png?t='+(n++);},20000);
</script></body></html>"""
    resp = HTMLResponse(html, headers={"Cache-Control": "no-store"})
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
            if new_path == "/qr.png":
                return await _waha_qr_png(scope, receive, send)
            if new_path in ("/qr", "/qr/"):
                return await _waha_qr_html(scope, receive, send)
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
