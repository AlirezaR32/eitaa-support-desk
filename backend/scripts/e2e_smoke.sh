#!/usr/bin/env bash
# E2E: serve backend (8010) + built frontend (4173) and verify the full flow via curl.
set -e
cd "$(dirname "$0")/.."

export DATABASE_URL="postgresql+asyncpg://postgres@127.0.0.1:5432/eitaa_desk"
export UPLOADS_DIR="/tmp/eitaa-uploads"
export RUN_SYNC_WORKER=false EITAA_SYNC_ENABLED=false RUN_NOTIFICATION_WORKER=false
export LOG_LEVEL=WARNING
export CORS_ORIGINS="http://127.0.0.1:4173,http://localhost:4173"

PORT=8010
./.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port $PORT > /tmp/backend.log 2>&1 &
BACKEND_PID=$!
trap 'kill $BACKEND_PID $FRONT_PID 2>/dev/null || true' EXIT

cd ../frontend
bun run preview --port 4173 > /tmp/frontend.log 2>&1 &
FRONT_PID=$!

for i in $(seq 1 15); do
  curl -sf "http://127.0.0.1:$PORT/health" > /dev/null && break
  sleep 1
done

echo "=== backend health ==="
curl -sf "http://127.0.0.1:$PORT/health"
echo

echo "=== frontend served ==="
curl -sf "http://127.0.0.1:4173/" | rg -o "<title>[^<]+</title>"

echo "=== API through same flow ==="
RESP=$(curl -sf -X POST "http://127.0.0.1:$PORT/api/v1/auth/login" \
  -H 'Content-Type: application/json' \
  -d '{"email":"owner@desk.local","password":"OwnerPass!123"}')
echo "$RESP" | python3 -c "import sys,json; d=json.load(sys.stdin); open('/tmp/token.txt','w').write(d['access_token']); print('login:', d['user']['role'])"
TOKEN=$(cat /tmp/token.txt)

curl -sf "http://127.0.0.1:$PORT/api/v1/conversations" -H "Authorization: Bearer $TOKEN" \
  | python3 -c "import sys,json; d=json.load(sys.stdin); print('conversations total:', d['total']); assert d['total'] >= 8"

curl -sf "http://127.0.0.1:$PORT/api/v1/dashboard/stats" -H "Authorization: Bearer $TOKEN" \
  | python3 -c "import sys,json; d=json.load(sys.stdin); print('dashboard: unanswered', d['unanswered'], '| unread', d['unread'], '| closed', d['closed'], '| messages_today', d['messages_today'])"

CONV_ID=$(curl -sf "http://127.0.0.1:$PORT/api/v1/conversations" -H "Authorization: Bearer $TOKEN" \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['items'][0]['id'])")

curl -sf "http://127.0.0.1:$PORT/api/v1/conversations/$CONV_ID/messages" -H "Authorization: Bearer $TOKEN" \
  | python3 -c "import sys,json; d=json.load(sys.stdin); print('messages in first conversation:', d['total'])"

echo "E2E SMOKE OK"
