"""MCP tool for ingesting WhatsApp native chat exports (text files).

WAHA WEBJS doesn't backfill chat history, and even NOWEB is capped at what
the WhatsApp server itself retains. For deep retro analysis (years back),
the WhatsApp app's native export ("Settings → Chats → Export chat") is the
ground truth. This tool parses that export into the same shape the rest of
the MCP uses.
"""
import json
import re
from datetime import datetime
from pydantic import BaseModel, Field, ConfigDict
from typing import Optional
from mcp.server.fastmcp import FastMCP

from server.waha_client import handle_error


_TS_LINE_RE = re.compile(
    r"""^
    [\[\(]?
    (?P<date>\d{1,2}[/.\-]\d{1,2}[/.\-]\d{2,4})
    [,\s]+
    (?P<time>\d{1,2}:\d{2}(?::\d{2})?(?: ?[APap][Mm]\.?)?)
    [\]\)]?
    \s*[-–—]?\s*
    (?:(?P<sender>[^:]{1,80}?):\s+)?
    (?P<body>.*)$
    """,
    re.VERBOSE,
)

_DATE_FORMATS = [
    "%d/%m/%Y %H:%M:%S", "%d/%m/%Y %H:%M",
    "%d.%m.%Y %H:%M:%S", "%d.%m.%Y %H:%M",
    "%d-%m-%Y %H:%M:%S", "%d-%m-%Y %H:%M",
    "%m/%d/%Y %H:%M:%S", "%m/%d/%Y %H:%M",
    "%m/%d/%y %H:%M:%S", "%m/%d/%y %H:%M",
    "%d/%m/%y %H:%M:%S", "%d/%m/%y %H:%M",
    "%d/%m/%Y %I:%M:%S %p", "%d/%m/%Y %I:%M %p",
    "%m/%d/%Y %I:%M:%S %p", "%m/%d/%y %I:%M:%S %p",
]


def _try_parse_ts(date_str: str, time_str: str) -> Optional[int]:
    clean_time = time_str.replace(" ", " ").strip().rstrip(".")
    combined = f"{date_str} {clean_time}"
    for fmt in _DATE_FORMATS:
        try:
            return int(datetime.strptime(combined, fmt).timestamp())
        except ValueError:
            continue
    return None


def _parse_export(content: str, max_messages: int) -> dict:
    raw_lines = content.replace("‎", "").replace("‏", "").splitlines()
    messages: list[dict] = []
    current: Optional[dict] = None
    senders: dict[str, int] = {}
    media_count = 0

    for line in raw_lines:
        m = _TS_LINE_RE.match(line)
        if m:
            if current:
                messages.append(current)
                if current.get("is_media"):
                    media_count += 1
                if current.get("sender"):
                    senders[current["sender"]] = senders.get(current["sender"], 0) + 1
            date_s, time_s = m.group("date"), m.group("time")
            sender = (m.group("sender") or "").strip() or None
            body = m.group("body") or ""
            ts = _try_parse_ts(date_s, time_s)
            is_media = bool(re.search(
                r"<(?:M[ée]dia omis|Media omitted|attached|joint)>|image omise|audio omis|vid[ée]o omise",
                body, re.IGNORECASE,
            ))
            current = {
                "timestamp": ts,
                "date": date_s,
                "time": time_s,
                "sender": sender,
                "is_system": sender is None,
                "is_media": is_media,
                "body": body,
            }
        else:
            if current and line:
                current["body"] += "\n" + line
        if len(messages) >= max_messages:
            break

    if current and len(messages) < max_messages:
        messages.append(current)
        if current.get("is_media"):
            media_count += 1
        if current.get("sender"):
            senders[current["sender"]] = senders.get(current["sender"], 0) + 1

    first_ts = next((m["timestamp"] for m in messages if m.get("timestamp")), None)
    last_ts = next((m["timestamp"] for m in reversed(messages) if m.get("timestamp")), None)
    return {
        "count": len(messages),
        "first_timestamp": first_ts,
        "last_timestamp": last_ts,
        "senders": dict(sorted(senders.items(), key=lambda kv: -kv[1])),
        "media_count": media_count,
        "messages": messages,
    }


def register(mcp_instance: FastMCP):

    class ParseExportInput(BaseModel):
        model_config = ConfigDict(str_strip_whitespace=False, extra="forbid")
        content: str = Field(
            ...,
            min_length=10,
            max_length=4_000_000,
            description="Contenu texte brut d'un export WhatsApp (fichier .txt obtenu via 'Paramètres → Discussions → Exporter la discussion → Sans média'). Coller tel quel.",
        )
        max_messages: Optional[int] = Field(
            default=2000,
            ge=1, le=10000,
            description="Plafond de messages parsés. Évite d'écraser le contexte de l'agent.",
        )
        body_max_chars: Optional[int] = Field(
            default=2000,
            ge=50, le=10000,
            description="Tronque le corps de chaque message à cette longueur.",
        )

    @mcp_instance.tool(
        name="whatsapp_parse_export",
        annotations={
            "title": "Parser un export texte de chat WhatsApp",
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    )
    async def whatsapp_parse_export(params: ParseExportInput) -> str:
        """Parse un export WhatsApp natif (.txt) en messages structurés.

        Couvre les formats iOS (`[DD/MM/YYYY, HH:MM:SS] Sender: body`),
        Android (`DD/MM/YYYY, HH:MM - Sender: body`), et les variantes US
        (`MM/DD/YY, HH:MM:SS AM/PM`). Les lignes sans timestamp sont
        considérées comme la continuation du dernier message.

        Retourne `{count, first_timestamp, last_timestamp, senders: {name: N},
        media_count, messages: [{timestamp, date, time, sender, is_system,
        is_media, body}]}`. Idéal pour analyser des conversations remontant
        au-delà de la fenêtre que WAHA garde.
        """
        try:
            result = _parse_export(params.content, params.max_messages)
            for m in result["messages"]:
                if isinstance(m.get("body"), str) and len(m["body"]) > params.body_max_chars:
                    m["body"] = m["body"][: params.body_max_chars] + "…"
            return json.dumps(result, ensure_ascii=False, indent=2)
        except Exception as e:
            return handle_error(e)
