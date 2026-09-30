#!/usr/bin/env bash
# Dev helper: start backend against the sandbox PostgreSQL, run a smoke test, stop.
# Usage: bash scripts/smoke_backend.sh
set -e
cd "$(dirname "$0")/.."

# Explicit override — the surrounding dev sandbox may export its own DATABASE_URL.
export DATABASE_URL="postgresql+asyncpg://postgres@127.0.0.1:5432/eitaa_desk"
export UPLOADS_DIR="${UPLOADS_DIR:-/tmp/eitaa-uploads}"
export RUN_SYNC_WORKER=false EITAA_SYNC_ENABLED=false RUN_NOTIFICATION_WORKER=false
export LOG_LEVEL=WARNING

PORT="${PORT:-8010}"
./.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port "$PORT" > /tmp/backend.log 2>&1 &
SERVER_PID=$!
trap 'kill $SERVER_PID 2>/dev/null || true' EXIT
sleep 4

echo "=== health ==="
curl -sf "http://127.0.0.1:$PORT/health"
echo; echo "=== ready ==="
for i in 1 2 3 4 5; do
  READY=$(curl -s "http://127.0.0.1:$PORT/ready")
  echo "$READY" | rg -q '"database":true' && { echo "$READY"; break; }
  sleep 1
done
echo "$READY" | rg -q '"database":true' || { echo "READY FAILED: $READY"; exit 1; }

echo "=== login ==="
RESP=$(curl -sf -X POST "http://127.0.0.1:$PORT/api/v1/auth/login" \
  -H 'Content-Type: application/json' \
  -d '{"email":"owner@desk.local","password":"OwnerPass!123"}' -c /tmp/cookies.txt)
echo "$RESP" | python3 -c "import sys,json; d=json.load(sys.stdin); open('/tmp/token.txt','w').write(d['access_token']); print('login ok:', d['user']['email'], d['user']['role'])"
TOKEN=$(cat /tmp/token.txt)

echo "=== me ==="
curl -sf "http://127.0.0.1:$PORT/api/v1/auth/me" -H "Authorization: Bearer $TOKEN" \
  | python3 -c "import sys,json; d=json.load(sys.stdin); print('me:', d['email'], d['role'], 'perms:', len(d['permissions']))"

echo "=== conversations ==="
curl -sf "http://127.0.0.1:$PORT/api/v1/conversations" -H "Authorization: Bearer $TOKEN" \
  | python3 -c "import sys,json; d=json.load(sys.stdin); print('total:', d['total'])"

echo "=== dashboard ==="
curl -sf "http://127.0.0.1:$PORT/api/v1/dashboard/stats" -H "Authorization: Bearer $TOKEN" \
  | python3 -c "import sys,json; d=json.load(sys.stdin); print('total:', d['total_conversations'], '| unanswered:', d['unanswered'], '| unassigned:', d['unassigned'])"

echo "=== agents ==="
curl -sf "http://127.0.0.1:$PORT/api/v1/agents" -H "Authorization: Bearer $TOKEN" \
  | python3 -c "import sys,json; d=json.load(sys.stdin); print('agents:', d['total'])"

echo "=== refresh rotation ==="
curl -sf -X POST "http://127.0.0.1:$PORT/api/v1/auth/refresh" -b /tmp/cookies.txt \
  -H "Origin: http://localhost:5173" \
  | python3 -c "import sys,json; d=json.load(sys.stdin); print('refresh ok:', len(d['access_token'])>50)"
# second refresh with OLD cookie must now fail (rotation + reuse detection)
CODE=$(curl -s -o /dev/null -w "%{http_code}" -X POST "http://127.0.0.1:$PORT/api/v1/auth/refresh" -b /tmp/cookies.txt -H "Origin: http://localhost:5173")
echo "old-cookie refresh status (expect 401): $CODE"

echo "=== capabilities ==="
curl -sf "http://127.0.0.1:$PORT/api/v1/capabilities" | python3 -c "import sys,json; d=json.load(sys.stdin); print('sync_interval:', d['sync_interval_seconds'], '| max_upload_mb:', d['max_upload_size_mb'])"

echo "SMOKE OK"
