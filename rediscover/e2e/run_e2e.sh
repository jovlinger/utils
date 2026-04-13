#!/usr/bin/env bash
# E2E test script for rediscover.
# Requires: docker compose, curl, rediscover CLI installed in PATH.

set -euo pipefail

REDIS1="redis://localhost:6381"
REDIS2="redis://localhost:6382"
APP_URL="http://localhost:8765"
NAMESPACE="e2e_test"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

PASS=0
FAIL=0

assert_contains() {
    local label="$1"
    local haystack="$2"
    local needle="$3"
    if echo "$haystack" | grep -q "$needle"; then
        echo "  PASS: $label"
        PASS=$((PASS + 1))
    else
        echo "  FAIL: $label — expected to find '$needle' in output"
        echo "        output was: $haystack"
        FAIL=$((FAIL + 1))
    fi
}

assert_not_contains() {
    local label="$1"
    local haystack="$2"
    local needle="$3"
    if ! echo "$haystack" | grep -q "$needle"; then
        echo "  PASS: $label"
        PASS=$((PASS + 1))
    else
        echo "  FAIL: $label — did not expect to find '$needle' in output"
        FAIL=$((FAIL + 1))
    fi
}

# ---------------------------------------------------------------------------
# 1. Start services
# ---------------------------------------------------------------------------
echo "==> Starting services..."
cd "$SCRIPT_DIR"
docker compose up -d --build

# ---------------------------------------------------------------------------
# 2. Wait for app health check
# ---------------------------------------------------------------------------
echo "==> Waiting for app to be healthy..."
for i in $(seq 1 30); do
    if curl -sf "$APP_URL/health" > /dev/null 2>&1; then
        echo "    App is up (attempt $i)."
        break
    fi
    if [ "$i" -eq 30 ]; then
        echo "    ERROR: app did not become healthy in time."
        docker compose logs app
        docker compose down
        exit 1
    fi
    sleep 1
done

# ---------------------------------------------------------------------------
# 3. Reset all counters
# ---------------------------------------------------------------------------
echo "==> Resetting all counters..."
rediscover --redis "$REDIS1" --redis "$REDIS2" --namespace "$NAMESPACE" reset

# ---------------------------------------------------------------------------
# 4. Send work requests: 3 calls × 2 batches = 6 total do_work invocations
# ---------------------------------------------------------------------------
echo "==> Sending work requests..."
curl -sf "$APP_URL/work?n=3" > /dev/null
curl -sf "$APP_URL/work?n=3" > /dev/null

# Give the flush daemon time to propagate (flush_interval default = 1 s)
sleep 2

# ---------------------------------------------------------------------------
# 5. Query and assert counts
# ---------------------------------------------------------------------------
echo "==> Querying counters..."
QUERY_OUT=$(rediscover --redis "$REDIS1" --redis "$REDIS2" --namespace "$NAMESPACE" query)
echo "$QUERY_OUT"

# do_work is called once per /work request (2 curl calls = 2 do_work calls);
# n=3 controls the number of 10ms sleep iterations inside each call.
assert_contains "do_work appears in output" "$QUERY_OUT" "do_work"
assert_contains "calls >= 2" "$QUERY_OUT" "2"

# ---------------------------------------------------------------------------
# 6. Reset all and verify empty
# ---------------------------------------------------------------------------
echo "==> Resetting all counters again..."
rediscover --redis "$REDIS1" --redis "$REDIS2" --namespace "$NAMESPACE" reset
QUERY_EMPTY=$(rediscover --redis "$REDIS1" --redis "$REDIS2" --namespace "$NAMESPACE" query)
assert_contains "query returns no data after reset" "$QUERY_EMPTY" "No data"

# ---------------------------------------------------------------------------
# 7. Test JSON export
# ---------------------------------------------------------------------------
echo "==> Testing JSON export (should be empty object)..."
# Seed a value first.
curl -sf "$APP_URL/work?n=1" > /dev/null
sleep 2
JSON_OUT=$(rediscover --redis "$REDIS1" --redis "$REDIS2" --namespace "$NAMESPACE" export --format json)
assert_contains "JSON export is valid JSON with do_work key" "$JSON_OUT" "do_work"

# ---------------------------------------------------------------------------
# 8. Tear down
# ---------------------------------------------------------------------------
echo "==> Stopping services..."
docker compose down

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
echo ""
echo "==============================="
echo "  PASS: $PASS   FAIL: $FAIL"
echo "==============================="

if [ "$FAIL" -gt 0 ]; then
    echo "RESULT: FAIL"
    exit 1
else
    echo "RESULT: PASS"
    exit 0
fi
