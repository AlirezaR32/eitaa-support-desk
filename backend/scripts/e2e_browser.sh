#!/usr/bin/env bash
# Full E2E browser verification — backend + frontend + agent-browser in one session.
set -e
cd "$(dirname "$0")/../.."

# ---------- backend ----------
cd backend
export DATABASE_URL="postgresql+asyncpg://postgres@127.0.0.1:5432/eitaa_desk"
export UPLOADS_DIR="/tmp/eitaa-uploads"
export RUN_SYNC_WORKER=false EITAA_SYNC_ENABLED=false RUN_NOTIFICATION_WORKER=false
export LOG_LEVEL=WARNING
export CORS_ORIGINS="http://localhost:5173,http://127.0.0.1:5173"

./.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8010 > /tmp/backend.log 2>&1 &
BACKEND_PID=$!

# ---------- frontend (vite dev, /api proxied same-origin) ----------
cd ../frontend
bun run dev --port 5173 > /tmp/frontend.log 2>&1 &
FRONT_PID=$!

cleanup() { kill $BACKEND_PID $FRONT_PID 2>/dev/null || true; }
trap cleanup EXIT

for i in $(seq 1 20); do curl -sf http://127.0.0.1:8010/health > /dev/null && break; sleep 1; done
for i in $(seq 1 20); do curl -sf http://127.0.0.1:5173/ > /dev/null && break; sleep 1; done
echo "servers up"

mkdir -p /tmp/e2e-shots
PASS=0; FAIL=0
check() { if [ "$2" -ge "$3" ] 2>/dev/null; then echo "PASS: $1 = $2"; PASS=$((PASS+1)); else echo "FAIL: $1 = $2 (expected >= $3)"; FAIL=$((FAIL+1)); fi }

agent-browser cookies clear || true
agent-browser open http://localhost:5173
agent-browser wait --load networkidle
sleep 3
URL=$(agent-browser get url)
if [[ "$URL" != *"inbox"* ]]; then
  agent-browser find label "ایمیل" fill "owner@desk.local"
  agent-browser find label "گذرواژه" fill "OwnerPass!123"
  agent-browser press Enter
  agent-browser wait --url "/inbox" --timeout 10000
fi
sleep 2.5
agent-browser set viewport 1440 900
agent-browser screenshot /tmp/e2e-shots/02-inbox.png

# --- inbox ---
INBOX=$(agent-browser get count "button.border-b")
check "inbox conversations" "$INBOX" 8

# --- unread filter (before opening anything — opening marks read) ---
agent-browser open http://localhost:5173/inbox/unread
agent-browser wait --load networkidle
sleep 2
UNREAD=$(agent-browser get count "button.border-b")
check "unread conversations" "$UNREAD" 3
agent-browser open http://localhost:5173/inbox
agent-browser wait --load networkidle
sleep 2

# --- open conversation directly via route ---
CONV_URL="http://localhost:5173/conversations/1"
agent-browser open "$CONV_URL"
agent-browser wait --load networkidle
sleep 3
agent-browser screenshot /tmp/e2e-shots/03-conversation.png
BUBBLES=$(agent-browser eval "document.querySelectorAll('div[class*=\"rounded-2xl\"]').length")
check "message bubbles" "$BUBBLES" 2
COMPOSER=$(agent-browser get count "textarea")
check "composer textarea" "$COMPOSER" 1

# --- dashboard ---
agent-browser open http://localhost:5173/dashboard
agent-browser wait --load networkidle
sleep 2
agent-browser screenshot /tmp/e2e-shots/04-dashboard.png
DASH=$(agent-browser get count ".card")
check "dashboard cards" "$DASH" 6

# --- eitaa accounts ---
agent-browser open http://localhost:5173/eitaa-accounts
agent-browser wait --load networkidle
sleep 2
agent-browser screenshot /tmp/e2e-shots/05-accounts.png

# --- audit logs ---
agent-browser open http://localhost:5173/audit-logs
agent-browser wait --load networkidle
sleep 2
AUDIT=$(agent-browser get count "tbody tr")
check "audit rows" "$AUDIT" 5
agent-browser screenshot /tmp/e2e-shots/06-audit.png

# --- notifications ---
agent-browser open http://localhost:5173/notifications
agent-browser wait --load networkidle
sleep 1.5

# --- settings ---
agent-browser open http://localhost:5173/settings
agent-browser wait --load networkidle
sleep 1.5
agent-browser screenshot /tmp/e2e-shots/07-settings.png

# --- dark mode ---
agent-browser open http://localhost:5173/dashboard
sleep 1.5
agent-browser eval "document.documentElement.classList.add('dark')"
sleep 0.5
agent-browser screenshot /tmp/e2e-shots/08-dark.png

# --- errors ---
ERRORS=$(agent-browser errors 2>/dev/null || true)
echo "page errors: ${ERRORS:-none}"

echo ""
echo "RESULT: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ] && echo "BROWSER E2E OK" || exit 1
