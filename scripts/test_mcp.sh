#!/bin/bash
# Functional smoke test against a deployed MCP server.
# Usage: bash scripts/test_mcp.sh [base_url]
# If base_url is omitted, derived from MCP_ALLOWED_HOSTS in .env.
set -euo pipefail

cd "$(dirname "$0")/.."

set -a
# shellcheck disable=SC1091
source .env
set +a

DEFAULT_HOST=$(echo "${MCP_ALLOWED_HOSTS:-localhost}" | cut -d, -f1 | xargs)
BASE_URL="${1:-https://$DEFAULT_HOST}"

if [ -z "${MCP_API_KEY:-}" ]; then
    echo "ERROR: MCP_API_KEY not set in .env"
    exit 1
fi

echo "Test MCP server at $BASE_URL"
echo "─────────────────────────────────────"

echo "→ /healthz (public) :"
curl -s -o /tmp/health.out -w "  HTTP %{http_code}\n" "$BASE_URL/healthz"
[ -s /tmp/health.out ] && cat /tmp/health.out && echo

echo ""
echo "→ /mcp without secret (expect 404) :"
curl -s -o /dev/null -w "  HTTP %{http_code}\n" "$BASE_URL/mcp"

echo ""
echo "→ MCP initialize at /<key>/mcp :"
curl -s -X POST "$BASE_URL/$MCP_API_KEY/mcp" \
    -H "Content-Type: application/json" \
    -H "Accept: application/json, text/event-stream" \
    -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"test","version":"1.0"}}}' \
    -o /tmp/init.out -w "  HTTP %{http_code}\n"
echo "  Response (first 800 chars):"
head -c 800 /tmp/init.out 2>/dev/null
echo ""
