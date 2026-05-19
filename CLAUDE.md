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
  main.py            ASGI entry. Wraps FastMCP with a URL-path secret check
                     and a /healthz handler. Don't add general routing here —
                     add new tools as modules under tools/.
  waha_client.py     httpx wrappers around WAHA, plus handle_error() that
                     produces user-facing strings from HTTPX exceptions.
  tools/
    messages.py      get/send/seen/search messages
    contacts.py      contact lookups
    groups.py        chat list + group ops. Note _slim_chat() — see below.
    media.py         send image/file/voice
```

## Conventions to follow when editing

- **Slim every payload that goes back to the LLM.** A full WAHA chat list on
  an active account is ~6 MB — it will blow the model's context. `groups.py`
  defines `_slim_chat()` and `messages.py` defines `_slim_message()`; when
  you add a new "list/get" tool, write a similar reducer. As a rule of thumb:
  ≤2 KB per entity, drop nested `_data` blobs.
- **All tool inputs are Pydantic models with `extra="forbid"` and
  `str_strip_whitespace=True`.** This keeps the schema tight so Claude can't
  hallucinate extra fields. Keep this pattern.
- **Every tool returns a JSON string** (use `json.dumps(..., ensure_ascii=False,
  indent=2)`). MCP tool results are text — don't return raw dicts.
- **Every tool calls `handle_error(e)` on any exception.** That function
  produces a sensible message for each WAHA failure mode (401, 404, 422, 500,
  timeout, connection refused).
- **`annotations` on each `@mcp_instance.tool` are not decorative.** Claude
  uses `readOnlyHint`/`destructiveHint`/`idempotentHint` to decide what to
  ask permission for. Be honest: `whatsapp_send_text` is not read-only.
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

## Useful commands

```bash
# Quick rebuild + restart after a Python edit
sudo docker compose up -d --build

# Container logs
sudo docker compose logs -f --tail=50

# Smoke test the live URL
bash scripts/test_mcp.sh

# Verify WAHA is reachable from inside the MCP container
sudo docker exec whatsapp-mcp curl -s -H "X-Api-Key: $WAHA_API_KEY" \
  http://waha:3000/api/version

# Check WAHA session state (it must be WORKING for messages to flow)
curl -s -H "X-Api-Key: $WAHA_API_KEY" http://localhost:3000/api/sessions | jq

# Restart a stuck WAHA session
curl -s -H "X-Api-Key: $WAHA_API_KEY" -X POST \
  http://localhost:3000/api/sessions/default/restart
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

## When the user asks for a new tool

1. Add the input model + `@mcp.tool` handler in the right `tools/*.py`.
   Follow existing patterns (Pydantic input, `_slim_X` if there's a payload
   to shrink, `handle_error` in `except`).
2. Add `register(mcp)` only if you create a new module; existing modules
   are already imported and registered in `main.py`.
3. Rebuild: `sudo docker compose up -d --build`.
4. Test the tool via MCP (initialize, get session id, call `tools/call`).
   `scripts/test_mcp.sh` shows the curl pattern.
5. Commit. The project pushes directly to `main` — no PR workflow.

## What not to touch without good reason

- `mcp.server.transport_security` settings — they're load-bearing for the
  public deployment. Touching `allowed_hosts` randomly will break the
  production server with `Invalid Host header`.
- The path-prefix auth in `main.py` — see README on why it's like this.
- The slim payload reducers — they exist because Claude.ai blew up
  on the full ones.

## Things the harness handles for you

- The user's VPS has the actual WAHA container running and may already be
  serving the public domain. Don't assume a clean-room setup; check
  `docker ps` and `curl -s http://localhost:3000/api/version` before
  touching anything.
- `git remote` points at the user's fork. `git push` should work via SSH
  if a key is present.
