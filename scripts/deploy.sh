#!/bin/bash
# Build and start the whatsapp-mcp container. Idempotent.
set -euo pipefail

cd "$(dirname "$0")/.."

echo "=== Deploying WhatsApp MCP Server ==="

if [ ! -f .env ]; then
    echo "ERROR: .env not found. Copy .env.example to .env and fill in your values first."
    exit 1
fi

set -a
# shellcheck disable=SC1091
source .env
set +a

if [ -z "${MCP_API_KEY:-}" ] || [[ "$MCP_API_KEY" == REPLACE_* ]]; then
    echo "ERROR: MCP_API_KEY is not set in .env (still placeholder)."
    echo "Generate with: openssl rand -hex 32"
    exit 1
fi

if [ -z "${WAHA_API_KEY:-}" ] || [[ "$WAHA_API_KEY" == REPLACE_* ]]; then
    echo "ERROR: WAHA_API_KEY is not set in .env (still placeholder)."
    exit 1
fi

echo "→ Building image ..."
sudo docker compose build

echo "→ Starting container ..."
sudo docker compose up -d

echo "→ Waiting for the container to come up ..."
sleep 4

if sudo docker compose ps --status running | grep -q whatsapp-mcp; then
    echo "✅ Container is running"
else
    echo "❌ Container failed to start"
    sudo docker compose logs --tail=80
    exit 1
fi

echo "→ Local healthz ..."
if curl -sf http://127.0.0.1:8765/healthz > /dev/null; then
    echo "✅ /healthz OK"
else
    echo "⚠️  /healthz did not respond — see container logs:"
    sudo docker compose logs --tail=30
fi

echo "→ WAHA reachability from inside the MCP container ..."
if sudo docker exec whatsapp-mcp curl -sf -H "X-Api-Key: ${WAHA_API_KEY}" "${WAHA_BASE_URL:-http://waha:3000}/api/version" > /dev/null; then
    echo "✅ WAHA reachable"
else
    echo "⚠️  WAHA not reachable. Check docker network and credentials."
fi

echo ""
echo "Next steps (one-time):"
echo "  1. Add Caddy vhost:  bash scripts/install_caddy.sh"
echo "  2. Set DNS to point at this VPS"
echo "  3. Smoke test:       bash scripts/test_mcp.sh"
