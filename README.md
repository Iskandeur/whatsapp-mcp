# whatsapp-mcp

A small remote [MCP](https://modelcontextprotocol.io/) server that exposes
WhatsApp as a set of tools for Claude.ai (or any MCP client that speaks
Streamable HTTP). It is a thin wrapper around [WAHA](https://waha.devlike.pro/) —
the heavy lifting (WhatsApp Web automation, session management, media handling)
is done by WAHA; this project translates between WAHA's REST API and MCP's
tool-calling protocol.

Once deployed, the server lives on a domain you control, and any Claude.ai
session (web, desktop, mobile) can use it after a one-line setup in
**Settings → Integrations → Add a custom connector**.

## What you get

~55 tools registered with the MCP client, grouped by module under `server/tools/`:

| Module | Tools |
| --- | --- |
| **messages** | `get_messages`, `get_message`, `send_text`, `mark_seen`, `search_messages`, `download_media` |
| **contacts** | `list_contacts`, `get_contact`, `check_numbers`, `get_profile`, `set_profile_name`, `set_profile_status`, `get_profile_picture`, `get_about`, `block_contact`, `unblock_contact`, `list_blocked` |
| **groups** | `list_chats`, `get_group_info`, `create_group`, `add_participants`, `remove_participants`, `promote_participants`, `demote_participants`, `leave_group`, `set_group_subject`, `set_group_description`, `set_group_settings`, `get_invite_link`, `revoke_invite_link`, `join_group` |
| **media** | `send_image`, `send_file`, `send_voice`, `send_location`, `send_contact`, `send_poll` |
| **actions** | `send_reaction`, `star_message`, `edit_message`, `delete_message`, `forward_message`, `pin_message`, `unpin_message` |
| **presence** | `start_typing`, `stop_typing`, `set_presence`, `get_presence` |
| **sessions** | `get_session_status`, `restart_session` |
| **chats** | `archive_chat`, `unarchive_chat`, `mark_unread`, `clear_messages`, `delete_chat` |

All `chat_id` arguments accept `<digits>@lid` (modern), `<digits>@c.us` (legacy),
`<digits>@g.us` (groups), or a raw international number like `33612345678`
(resolved automatically via `check-exists`). Send / write tools return a compact
`{success, message_id, chat_id, timestamp, type, ack}` envelope by default —
pass `verbose=true` to get the raw WAHA payload.

Read / list tools always return slim entities (≤2 KB each, no nested `_data`
blobs). Don't change them to return raw WAHA objects without thinking about
context-window cost (a full chat list on a busy account is multi-megabyte).

## Architecture

```
Claude.ai
   │ HTTPS — URL contains the secret API key as a path prefix
   ▼
your.domain.tld           ← Caddy (TLS via Let's Encrypt)
   │ HTTP (loopback)
   ▼
whatsapp-mcp container    ← this repo, port 8765
   │ HTTP (docker network)
   ▼
WAHA container            ← devlikeapro/waha:latest, port 3000
   │
   ▼
WhatsApp Web
```

A few non-obvious design choices:

- **Auth via URL path, not Bearer header.** Claude.ai's custom-connector UI
  currently has no Bearer-token field — only URL + (optional) OAuth client ID/
  secret. So the secret lives in the URL itself: `https://your.domain/<secret>/mcp`.
  Anything outside that prefix returns 404. The path is effectively a long
  random password; treat the URL like one.
- **Streamable HTTP**, not stdio. The server has to be reachable from
  Claude.ai's backend, so we use the MCP HTTP transport behind a normal HTTPS
  proxy.
- **`mcp.server.transport_security`** is configured with an allow-list of
  hostnames (DNS-rebinding protection). If you change the domain after first
  setup, update `MCP_ALLOWED_HOSTS` in `.env`.
- **`/<MCP_API_KEY>/qr`** (HTML) and **`/<MCP_API_KEY>/qr.png`** proxy WAHA's
  pairing QR through the same secret prefix, so you can re-pair from a phone
  browser if the session drops without exposing WAHA's port publicly.

## Prerequisites

- A VPS (any Linux) with Docker and Docker Compose
- A domain name you control, with DNS pointed at the VPS
- [Caddy](https://caddyserver.com/) installed on the host (any reverse proxy
  works — the snippet in `caddy/mcp.example.caddy` is the easy path)
- A working WAHA container ([setup docs](https://waha.devlike.pro/docs/overview/quick-start/))
  on the same Docker network or reachable by HTTP

## Setup

```bash
git clone https://github.com/<your-fork>/whatsapp-mcp.git
cd whatsapp-mcp

cp .env.example .env
# Edit .env:
#   - WAHA_API_KEY:        the X-Api-Key your WAHA expects
#   - MCP_API_KEY:         openssl rand -hex 32   (becomes part of the URL)
#   - MCP_ALLOWED_HOSTS:   your public hostname, first in the list

bash scripts/deploy.sh        # builds the image, starts the container
bash scripts/install_caddy.sh # appends a vhost to /etc/caddy/Caddyfile and reloads
bash scripts/test_mcp.sh      # smoke test against the public URL
```

If you don't already run Caddy, `caddy/mcp.example.caddy` is a self-contained
vhost block — copy and adapt for whatever proxy you do use.

### Connecting Claude.ai

In Claude.ai → **Settings** → **Integrations** → **Add a custom connector**:

- **URL**: `https://your.domain.tld/<MCP_API_KEY>/mcp`
  - Note the path: it's the full value of `MCP_API_KEY` followed by `/mcp`
- Leave the OAuth fields empty.

Once added, the tools are available in any Claude.ai session — no local
process needed.

### Docker network

`docker-compose.yml` joins the `waha_network` external network. If your WAHA
container lives in a different network, edit `docker-compose.yml` to match.
You can find your WAHA container's network with:

```bash
docker inspect <waha-container> --format '{{json .NetworkSettings.Networks}}'
```

## Security model

- The MCP server itself has **no other auth** than the URL-path secret.
  Anyone with that URL can use the connected WhatsApp account.
- `.env` is git-ignored. **Never commit it.**
- The `.env.example` contains placeholders only.
- The MCP container binds to `127.0.0.1:8765` — only Caddy on the same host
  can reach it directly.
- The chat-list and message-list tools redact payloads to a slim shape before
  returning them to the LLM. Don't change them to return raw WAHA objects
  without thinking about context-window cost (a full chat list on a busy
  account is multi-megabyte).

If you want stronger auth, OAuth 2.1 is the standard way to authenticate MCP
servers per the spec, but Claude.ai's current custom-connector UI does not
implement it as cleanly as URL-only setups. PRs welcome.

## Troubleshooting

**`Cannot read properties of undefined (reading 'waitForChatLoading')`**
A WAHA Core / WebJS engine bug, triggered when WhatsApp Web pushes JS
updates that break the scraper. Pull the latest WAHA image
(`docker pull devlikeapro/waha:latest`) and recreate the container. If it
keeps happening on every WhatsApp update, switch the WAHA engine to NOWEB
(set `WHATSAPP_DEFAULT_ENGINE=NOWEB` in your WAHA env — note that switching
engines invalidates the session and requires re-scanning the QR code).

**`Invalid Host header`**
FastMCP's DNS-rebinding protection rejects unknown Host values. Add your
public hostname to `MCP_ALLOWED_HOSTS` in `.env` and restart the container.

**Caddy can't get a cert**
DNS is not pointing at your VPS yet (Let's Encrypt does a CAA/DNS lookup and
fails with NXDOMAIN). After the A record lands, run `sudo systemctl reload
caddy` to kick the retry loop.

**Claude.ai blew up on a tool call**
Probably hit the context limit on a large response. The slim-payload reducers
live in `server/schema.py` (`slim_message`, `slim_chat`, `slim_send_result`,
`slim_contact`, `slim_group`); every read / list / send tool funnels through
them. When you add a new tool, reuse the existing reducer or add one alongside
— don't return raw WAHA dicts.

**Session went to `SCAN_QR_CODE`**
WAHA lost the pairing (logout, container wipe, or WhatsApp signed you out).
Visit `https://your.domain.tld/<MCP_API_KEY>/qr` on a second screen and scan
from your phone. The session volume is persistent, so once paired the QR
endpoint goes quiet again.

## License

MIT. WAHA itself is licensed separately — see
[waha.devlike.pro](https://waha.devlike.pro/).
