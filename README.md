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

12 tools registered with the MCP client:

| Tool | What it does |
| --- | --- |
| `whatsapp_list_chats` | List active chats. Filterable by name, group/contact, unread, with a `limit`. Returns a *slim* representation (id, name, unread, last-message preview) — don't dump full chat objects into the LLM. |
| `whatsapp_get_messages` | Fetch the last N messages of a chat. Supports `since_timestamp` for week/day queries. |
| `whatsapp_send_text` | Send a plain-text message. Supports `reply_to`. |
| `whatsapp_mark_seen` | Mark a chat (or single message) as read. |
| `whatsapp_search_messages` | Client-side search — fetches recent messages and filters by substring (WAHA Core has no server search). |
| `whatsapp_list_contacts` | List all known contacts (capped at 200 entries). |
| `whatsapp_get_contact` | Check if a phone number is on WhatsApp. |
| `whatsapp_get_group_info` | Metadata for a group (description, participants, admins). |
| `whatsapp_create_group` | Create a new group. |
| `whatsapp_send_image` | Send an image from a public URL. |
| `whatsapp_send_file` | Send a file from a public URL. |
| `whatsapp_send_voice` | Send a voice note from a public URL. |

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
Probably hit the context limit on a large response. The slim-payload pattern
in `server/tools/groups.py:_slim_chat` and `server/tools/messages.py:_slim_message`
exists for this reason — when you add new tools, follow the same approach.

## License

MIT. WAHA itself is licensed separately — see
[waha.devlike.pro](https://waha.devlike.pro/).
