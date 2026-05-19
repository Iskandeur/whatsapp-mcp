#!/bin/bash
# Substitutes ${MCP_DOMAIN} in caddy/mcp.example.caddy with the value from .env,
# appends the resulting block to /etc/caddy/Caddyfile (without duplicating),
# validates and reloads Caddy. Caddy handles Let's Encrypt issuance and renewal.
set -euo pipefail

cd "$(dirname "$0")/.."

if [ ! -f .env ]; then
    echo "ERROR: .env not found. Copy .env.example to .env and fill in your values first."
    exit 1
fi

set -a
# shellcheck disable=SC1091
source .env
set +a

if [ -z "${MCP_ALLOWED_HOSTS:-}" ]; then
    echo "ERROR: MCP_ALLOWED_HOSTS not set in .env"
    exit 1
fi

# Use the first hostname in MCP_ALLOWED_HOSTS as the vhost domain.
MCP_DOMAIN=$(echo "$MCP_ALLOWED_HOSTS" | cut -d, -f1 | xargs)

if [ -z "$MCP_DOMAIN" ] || [ "$MCP_DOMAIN" = "mcp.example.com" ]; then
    echo "ERROR: Set MCP_ALLOWED_HOSTS in .env to your real hostname (not mcp.example.com)."
    exit 1
fi

CADDYFILE="/etc/caddy/Caddyfile"
SNIPPET="caddy/mcp.example.caddy"
MARKER="$MCP_DOMAIN {"

if [ ! -f "$CADDYFILE" ]; then
    echo "ERROR: $CADDYFILE not found. Is Caddy installed?"
    exit 1
fi

if sudo grep -qF "$MARKER" "$CADDYFILE"; then
    echo "→ Vhost for $MCP_DOMAIN already in $CADDYFILE — nothing to do."
else
    echo "→ Adding vhost for $MCP_DOMAIN to $CADDYFILE ..."
    sudo cp "$CADDYFILE" "$CADDYFILE.bak.$(date +%Y%m%d-%H%M%S)"
    {
        echo ""
        sed "s|\${MCP_DOMAIN}|$MCP_DOMAIN|g" "$SNIPPET"
    } | sudo tee -a "$CADDYFILE" > /dev/null
    echo "✅ Vhost added"
fi

echo "→ Validating Caddyfile ..."
sudo caddy validate --config "$CADDYFILE"

echo "→ Reloading Caddy ..."
sudo systemctl reload caddy

echo ""
echo "✅ Caddy reconfigured. Once DNS for $MCP_DOMAIN points at this VPS,"
echo "   Caddy will obtain a Let's Encrypt cert within a minute. Test with:"
echo "   curl -I https://$MCP_DOMAIN/healthz"
