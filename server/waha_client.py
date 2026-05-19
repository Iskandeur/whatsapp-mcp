"""Shared WAHA HTTP client. Wraps the WAHA Core REST API."""
import os
import httpx
from typing import Any, Optional

WAHA_BASE = os.getenv("WAHA_BASE_URL", "http://waha:3000")
WAHA_SESSION = os.getenv("WAHA_SESSION", "default")
WAHA_API_KEY = os.getenv("WAHA_API_KEY", "")
TIMEOUT = 30.0


def _headers() -> dict:
    h = {"Content-Type": "application/json", "Accept": "application/json"}
    if WAHA_API_KEY:
        h["X-Api-Key"] = WAHA_API_KEY
    return h


async def waha_get(path: str, params: Optional[dict] = None) -> Any:
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        r = await client.get(f"{WAHA_BASE}{path}", headers=_headers(), params=params or {})
        r.raise_for_status()
        return r.json()


async def waha_post(path: str, body: dict) -> Any:
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        r = await client.post(f"{WAHA_BASE}{path}", headers=_headers(), json=body)
        r.raise_for_status()
        return r.json()


async def waha_put(path: str, body: dict) -> Any:
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        r = await client.put(f"{WAHA_BASE}{path}", headers=_headers(), json=body)
        r.raise_for_status()
        return r.json()


async def waha_delete(path: str) -> Any:
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        r = await client.delete(f"{WAHA_BASE}{path}", headers=_headers())
        r.raise_for_status()
        if r.text:
            try:
                return r.json()
            except Exception:
                return {"ok": True}
        return {"ok": True}


def handle_error(e: Exception) -> str:
    if isinstance(e, httpx.HTTPStatusError):
        code = e.response.status_code
        body = e.response.text[:500]
        if code == 401:
            return "Erreur 401 : clé API WAHA invalide (WAHA_API_KEY)."
        if code == 404:
            return f"Erreur 404 : ressource introuvable. Vérifier le chatId ou que la session WAHA '{WAHA_SESSION}' existe et est démarrée. Détail: {body}"
        if code == 422:
            return f"Erreur 422 : paramètres invalides → {body}"
        if code == 502 or code == 503:
            return f"Erreur {code} : WAHA indisponible ou session non démarrée. Détail: {body}"
        return f"Erreur HTTP {code} : {body}"
    if isinstance(e, httpx.TimeoutException):
        return "Timeout : WAHA ne répond pas. Vérifier que le container tourne."
    if isinstance(e, httpx.ConnectError):
        return f"Connexion impossible à WAHA ({WAHA_BASE}). Vérifier WAHA_BASE_URL et le réseau Docker."
    return f"Erreur inattendue : {type(e).__name__} — {str(e)}"
