# Guidance for Claude Code

This repo is a small MCP server that wraps WAHA (a WhatsApp HTTP API).
The README has the user-facing setup; this file is for you, future Claude.

## What this repo is, in one paragraph

A Python service that translates between MCP's tool-calling protocol and
WAHA's REST endpoints. It runs as a single Docker container, sits behind
a Caddy reverse proxy, and is consumed by Claude.ai over Streamable HTTP.
The interesting code is all in `server/`. Everything else is glue (Docker,
Caddy, scripts).

## Layout

```
server/
  main.py            ASGI entry. Wraps FastMCP with a URL-path secret check,
                     /healthz handler, and a /qr + /qr.png proxy to WAHA's
                     pairing QR. Don't add general routing here — add tools
                     as modules under tools/.
  waha_client.py     httpx wrappers around WAHA (get/post/put/delete) plus:
                     handle_error()       → user-facing strings for HTTPX exns
                     resolve_chat_id()    → digits/@c.us/@lid/@g.us normaliser
                     resolve_media_url()  → rewrites localhost:3000 → WAHA_BASE
                     waha_fetch_bytes()   → streamed media download w/ max size
  schema.py          slim_message/slim_chat/slim_contact/slim_group/
                     slim_send_result — the only place payload shapes live.
                     Every tool funnels its WAHA response through these.
  tools/
    messages.py      get_messages, get_message, send_text, mark_seen,
                     search_messages, download_media
    contacts.py      list_contacts, get_contact, check_numbers, get_profile,
                     set_profile_name/status, get_profile_picture, get_about,
                     block_contact/unblock_contact, list_blocked
    groups.py        list_chats, get_group_info, create_group,
                     add/remove/promote/demote_participants, leave_group,
                     set_group_subject/description/settings,
                     get/revoke_invite_link, join_group
    media.py         send_image, send_file, send_voice, send_location,
                     send_contact, send_poll
    actions.py       send_reaction, star_message, edit_message,
                     delete_message, forward_message, pin_message,
                     unpin_message
    presence.py      start_typing (with optional auto-stop), stop_typing,
                     set_presence, get_presence
    sessions.py      get_session_status, restart_session (gated by confirm)
    chats.py         archive/unarchive, mark_unread, clear_messages,
                     delete_chat (last two gated by confirm)
```

## Conventions to follow when editing

- **Slim every payload via `server/schema.py`.** A full WAHA chat list on an
  active account is ~6 MB and the send-* responses are ~3 KB of `messageSecret`
  bytes the model will never use. Funnel reads through `slim_message`/
  `slim_chat`/`slim_group`/`slim_contact` and writes through `slim_send_result`.
  Add a new reducer if you need a new shape — don't return raw WAHA dicts.
- **Every send/get tool that returns a WAHA Message takes `verbose: bool=False`.**
  Default is slim; `verbose=true` echoes the raw payload for debugging. Keep
  this pattern for new tools.
- **All tool inputs are Pydantic models with `extra="forbid"` and
  `str_strip_whitespace=True`.** This keeps the schema tight so Claude can't
  hallucinate extra fields. Keep this pattern.
- **Any tool that takes a recipient calls `resolve_chat_id(value)` first.**
  Users pass `@c.us`, `@lid`, `@g.us`, or a raw international number; the
  helper normalises to a canonical JID via WAHA's `check-exists`. Don't ship
  a tool that only accepts one form.
- **Every tool returns a JSON string** (use `json.dumps(..., ensure_ascii=False,
  indent=2)`). MCP tool results are text — don't return raw dicts.
- **Every tool calls `handle_error(e)` on any exception.** That function
  produces a sensible message for each WAHA failure mode (401, 404, 422, 500,
  timeout, connection refused).
- **`annotations` on each `@mcp_instance.tool` are not decorative.** Claude
  uses `readOnlyHint`/`destructiveHint`/`idempotentHint` to decide what to
  ask permission for. Be honest: `whatsapp_send_text` is not read-only;
  `whatsapp_delete_chat` is destructive.
- **Irreversible / risky tools take a `confirm: bool` flag.** See
  `whatsapp_restart_session`, `whatsapp_clear_messages`, `whatsapp_delete_chat`.
  This is a belt-and-suspenders guard on top of `destructiveHint`.
- **No comments explaining what the code does.** Names should already explain
  that. If a *why* is non-obvious (a workaround for a WAHA bug, an API quirk),
  one short line is fine.
- **Don't add OAuth scaffolding casually.** The URL-path-secret design is
  deliberate (see README "Auth via URL path"). If a future Claude.ai update
  adds a Bearer field, OAuth becomes worth doing properly; until then,
  resist.

## How auth works

`server/main.py` wraps the FastMCP ASGI app with a closure that checks
`scope["path"]` starts with `/<MCP_API_KEY>/`. The prefix is stripped before
the request reaches FastMCP so the inner app still serves `/mcp` as usual.
`/healthz` and `/health` are exempt. Anything else returns **404 Not Found**
(deliberately not 401 — we don't want to advertise that there's anything to
auth against).

Two extra paths live behind the same secret prefix:
- `/<KEY>/qr.png` — proxies WAHA's PNG QR through MCP.
- `/<KEY>/qr` — small HTML wrapper that auto-refreshes the QR every 20 s so
  the user can re-pair from a phone browser without exposing WAHA's port.

## Useful commands

The `whatsapp-mcp` user is in sudoers (password `whatsapp-mcp`) and the user
shares it freely. Standard pattern:

```bash
# Sudo without a TTY prompt
echo whatsapp-mcp | sudo -S -p '' <cmd>

# Quick rebuild + restart after a Python edit
echo whatsapp-mcp | sudo -S -p '' docker compose up -d --build

# Container logs
echo whatsapp-mcp | sudo -S -p '' docker compose logs --tail=50

# Smoke test the live URL (loads .env automatically)
bash scripts/test_mcp.sh

# Verify WAHA is reachable from inside the MCP container
echo whatsapp-mcp | sudo -S -p '' docker exec whatsapp-mcp \
  curl -s -H "X-Api-Key: $WAHA_API_KEY" http://waha:3000/api/version

# Check WAHA session state (it must be WORKING for messages to flow)
echo whatsapp-mcp | sudo -S -p '' bash -c '. /opt/whatsapp-mcp/.env; \
  curl -s -H "X-Api-Key: $WAHA_API_KEY" http://localhost:3000/api/sessions'

# Restart a stuck WAHA session — preserves pairing, ~30s STARTING → WORKING
echo whatsapp-mcp | sudo -S -p '' bash -c '. /opt/whatsapp-mcp/.env; \
  curl -s -H "X-Api-Key: $WAHA_API_KEY" -X POST \
  http://localhost:3000/api/sessions/default/restart'

# Push to GitHub: the whatsapp-mcp user has no key; root does at
# /root/.ssh/id_ed25519. Push via root:
echo whatsapp-mcp | sudo -S -p '' git -C /opt/whatsapp-mcp push origin main
```

## WAHA pitfalls you'll probably hit

- WAHA Core's WebJS engine breaks every few WhatsApp Web updates. Symptom:
  every message call returns 500 with `Cannot read properties of undefined
  (reading 'waitForChatLoading')` or a similar `Cannot read X of undefined`
  string. Fix: `docker pull devlikeapro/waha:latest && docker compose up -d
  --force-recreate` on the WAHA side. The session volume is persistent, so
  no QR re-scan is needed.
- Chat IDs are returned as objects (`{server, user, _serialized}`) in some
  endpoints and as strings in others. `_slim_chat` normalizes this to the
  string form. Use the `_serialized` field when you encounter the object.
- The session must be in state `WORKING` before any chat/message call will
  succeed. Right after a restart it goes `STOPPED → STARTING → WORKING` over
  ~30 seconds.
- Server-side message search does not exist in WAHA Core. `whatsapp_search_messages`
  fetches recent messages and filters locally. Don't promise more.
- **`POST /api/sessions/<name>/logout` actually deauthenticates WhatsApp.** It
  is not a no-op for probing — it kicks the session into `SCAN_QR_CODE` and
  requires the user to re-scan from their phone. That's why the MCP tool layer
  deliberately does NOT expose a `logout` tool. Use `restart_session` instead;
  it preserves pairing. (If you absolutely need logout, add it with
  `destructiveHint=true` AND a `confirm=true` flag.)
- WAHA media URLs come back as `http://localhost:3000/...` which only resolves
  inside the WAHA container. `resolve_media_url()` rewrites the host to
  `WAHA_BASE_URL` — apply it before exposing any URL to the LLM.
- A few endpoints are WAHA Plus only and return HTTP 501 on Core:
  `sendVideo`, `sendLinkPreview`, `sendSticker`, profile-picture write. Don't
  add tools that wrap them without the Plus license.
- Contact chat IDs on modern WhatsApp arrive as `<digits>@lid` (Linked Identity),
  not `@c.us`. The legacy `@c.us` form still works in writes but most reads
  return `@lid`. Treat both as valid input/output.

## When the user asks for a new tool

1. Pick the right `tools/*.py` (or create a new module if you have a coherent
   group of ≥3 new tools — see how `actions.py`, `presence.py`, `sessions.py`,
   `chats.py` are split).
2. Add the input model + `@mcp.tool` handler. Follow existing patterns:
   Pydantic with `extra="forbid"`, `resolve_chat_id()` on recipients,
   `handle_error(e)` in `except`, slim the response through `schema.py`,
   accept `verbose: bool=False` if you echo a WAHA Message back.
3. Set `annotations` honestly. Risky writes get `destructiveHint=true` AND a
   `confirm: bool` field.
4. If you create a new module, add `from server.tools import <module>` and
   `<module>.register(mcp)` to `server/main.py`.
5. Rebuild: `echo whatsapp-mcp | sudo -S -p '' docker compose up -d --build`.
6. Smoke-test via MCP: `bash scripts/test_mcp.sh` for the curl pattern, then
   craft a `tools/call` to your new tool.
7. Commit. The project pushes directly to `main` — no PR workflow. Push as
   root (see Useful commands above).

## What not to touch without good reason

- `mcp.server.transport_security` settings — they're load-bearing for the
  public deployment. Touching `allowed_hosts` randomly will break the
  production server with `Invalid Host header`.
- The path-prefix auth in `main.py` — see README on why it's like this.
- The slim payload reducers in `schema.py` — they exist because Claude.ai
  blew up on the full ones and the send-* responses ballooned token costs
  by ~20×.
- `resolve_chat_id()` — many tools assume any recipient passed through it
  is a real JID. Bypassing it means raw phone numbers reach WAHA as-is and
  fail with 422.

## Things the harness handles for you

- The user's VPS has the actual WAHA container running and may already be
  serving the public domain. Don't assume a clean-room setup; check
  `docker ps` and `curl -s http://localhost:3000/api/version` before
  touching anything.
- `git remote` points at the user's fork. The `whatsapp-mcp` user has no
  GitHub key — use the root pattern in "Useful commands" above.
