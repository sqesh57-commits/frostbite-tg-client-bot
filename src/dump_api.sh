#!/bin/bash
# Run this ON THE SERVER to dump 3x-ui API structure
# Usage: bash dump_api.sh <panel_url> <username> <password>
#
# Example:
#   bash dump_api.sh http://127.0.0.1:21443 admin mypassword
#   bash dump_api.sh https://panel.example.com:20576 admin mypassword

URL="${1:-http://127.0.0.1:21443}"
USER="${2:-admin}"
PASS="${3:-}"

COOKIES=$(mktemp)
trap "rm -f $COOKIES" EXIT

echo "=== 3x-ui API Dump ==="
echo "Panel: $URL"
echo ""

# 1. Get CSRF + base-path from HTML
echo "--- Step 1: GET / (CSRF + base-path) ---"
HTML=$(curl -sk -c "$COOKIES" "$URL/" 2>/dev/null)
CSRF=$(echo "$HTML" | grep -oP 'name="csrf-token"\s+content="\K[^"]+')
BASEPATH=$(echo "$HTML" | grep -oP 'name="base-path"\s+content="\K[^"]+')
echo "CSRF token: ${CSRF:-(none)}"
echo "Base path: ${BASEPATH:-(none)}"

# Build CSRF header
CSRF_HEADER=""
if [ -n "$CSRF" ]; then
    CSRF_HEADER="-H \"X-CSRF-Token: $CSRF\""
fi

# 2. Login
echo ""
echo "--- Step 2: POST /login ---"
LOGIN_RESP=$(curl -sk -b "$COOKIES" -c "$COOKIES" \
    -H "X-CSRF-Token: $CSRF" \
    -X POST "$URL/login" \
    -d "username=$USER&password=$PASS" 2>/dev/null)
echo "Response: $LOGIN_RESP"

# 3. Try API paths
echo ""
echo "--- Step 3: Testing API paths ---"

for PREFIX in "" "/panel"; do
    for ENDPOINT in "/api/inbounds/list" "/api/inbounds/get/3" "/api/inbounds"; do
        FULL="${URL}${PREFIX}${ENDPOINT}"
        STATUS=$(curl -sk -o /dev/null -w "%{http_code}" \
            -b "$COOKIES" -H "X-CSRF-Token: $CSRF" "$FULL" 2>/dev/null)
        BODY=$(curl -sk -b "$COOKIES" -H "X-CSRF-Token: $CSRF" "$FULL" 2>/dev/null | head -c 200)
        echo "  $STATUS $PREFIX$ENDPOINT"
        if [ "$STATUS" = "200" ]; then
            echo "    → $BODY"
        fi
    done
done

# 4. Get panel version
echo ""
echo "--- Step 4: Panel info ---"
VERSION=$(curl -sk -b "$COOKIES" -H "X-CSRF-Token: $CSRF" "$URL/api/server/get" 2>/dev/null | head -c 300)
echo "Server info: $VERSION"

echo ""
echo "=== Done ==="
echo "Send this output to the bot developer."
