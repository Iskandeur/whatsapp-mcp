#!/usr/bin/env bash
# Re-apply the NOWEB store config to the default WAHA session when it gets
# dropped on a container (re)start. Workaround for WAHA issue #868: on the CORE
# tier the per-session store flag is NOT persisted across container restarts, so
# chats/contacts/messages start returning HTTP 400 ("Enable NOWEB store ...")
# even though the synced store.sqlite3 is still on disk.
#
# Idempotent: it only PUTs the config when the store endpoint is actually
# disabled, so a healthy session is never needlessly stopped/started.
#
# Deployed on the VPS at /opt/whatsapp-bot/deploy/ensure-noweb-store.sh and run
# by the systemd units in this directory. This copy is kept in the repo as a
# reproducible record.
set -uo pipefail

ENV_FILE=/opt/whatsapp-bot/deploy/.env
[ -f "$ENV_FILE" ] && { set -a; . "$ENV_FILE"; set +a; }

WAHA="${WAHA_LOCAL_URL:-http://localhost:3000}"
S="${WAHA_SESSION:-default}"
hdr=(-H "X-Api-Key: ${WAHA_API_KEY:-}" -H "Content-Type: application/json")

# Wait for the session to be WORKING (the container may have just started).
for _ in $(seq 1 40); do
  st=$(curl -s --max-time 5 "${hdr[@]}" "$WAHA/api/sessions/$S" 2>/dev/null \
       | python3 -c 'import sys,json;print(json.load(sys.stdin).get("status",""))' 2>/dev/null)
  [ "$st" = "WORKING" ] && break
  sleep 3
done

# If the store already serves chats, there is nothing to do.
code=$(curl -s -o /dev/null --max-time 8 -w '%{http_code}' "${hdr[@]}" "$WAHA/api/$S/chats?limit=1" 2>/dev/null)
if [ "$code" = "200" ]; then
  echo "noweb store already enabled (HTTP 200); no action."
  exit 0
fi

echo "noweb store disabled (HTTP ${code:-000}); re-applying store config..."
curl -s --max-time 15 "${hdr[@]}" -X PUT "$WAHA/api/sessions/$S" \
  -d '{"config":{"noweb":{"store":{"enabled":true,"fullSync":true}}}}' \
  -o /dev/null -w 'PUT -> HTTP %{http_code}\n'
