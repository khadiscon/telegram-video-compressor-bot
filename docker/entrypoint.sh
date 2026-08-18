#!/bin/sh
set -eu

mkdir -p \
  "${TELEGRAM_WORK_DIR:-/var/lib/telegram-bot-api}" \
  "${TELEGRAM_TEMP_DIR:-/tmp/telegram-bot-api}" \
  "${DATA_DIR:-/app/data}" \
  "${TEMP_DIR:-/tmp/tg_video_compressor}"

if [ -z "${BOT_TOKEN:-}" ]; then
  echo "BOT_TOKEN is required"
  exit 1
fi

if [ -z "${TELEGRAM_API_ID:-}" ] || [ -z "${TELEGRAM_API_HASH:-}" ]; then
  echo "TELEGRAM_API_ID and TELEGRAM_API_HASH are required for files up to 500 MB."
  echo "Create an app at https://my.telegram.org and set both variables."
  exit 1
fi

# Railway health check — bind $PORT immediately so the deploy does not time out
if [ -n "${PORT:-}" ]; then
  python3 - <<'PY' &
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

class Health(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(b"ok\n")

    def log_message(self, *args):
        return

ThreadingHTTPServer(("0.0.0.0", int(os.environ["PORT"])), Health).serve_forever()
PY
fi

HTTP_PORT="${TELEGRAM_HTTP_PORT:-8081}"

telegram-bot-api \
  --dir="${TELEGRAM_WORK_DIR:-/var/lib/telegram-bot-api}" \
  --temp-dir="${TELEGRAM_TEMP_DIR:-/tmp/telegram-bot-api}" \
  --http-port="$HTTP_PORT" \
  --local \
  --verbosity="${TELEGRAM_VERBOSITY:-1}" \
  &
API_PID=$!

python3 - "$HTTP_PORT" <<'PY'
import socket, sys, time
port = int(sys.argv[1])
for _ in range(90):
    try:
        s = socket.create_connection(("127.0.0.1", port), 1)
        s.close()
        sys.exit(0)
    except OSError:
        time.sleep(1)
print("telegram-bot-api did not open port", port, file=sys.stderr)
sys.exit(1)
PY

export TELEGRAM_LOCAL_API=true
export TELEGRAM_API_URL="${TELEGRAM_API_URL:-http://127.0.0.1:${HTTP_PORT}}"
export TELEGRAM_FILE_URL="${TELEGRAM_FILE_URL:-http://127.0.0.1:${HTTP_PORT}}"
export DOWNLOAD_LIMIT_MB="${DOWNLOAD_LIMIT_MB:-500}"
export UPLOAD_LIMIT_MB="${UPLOAD_LIMIT_MB:-500}"
export MAX_CONCURRENT_JOBS="${MAX_CONCURRENT_JOBS:-1}"
export JOB_TIMEOUT_SEC="${JOB_TIMEOUT_SEC:-3600}"

python3 -m compressor &
BOT_PID=$!

term() {
  kill "$BOT_PID" "$API_PID" 2>/dev/null || true
}
trap term INT TERM

while kill -0 "$API_PID" 2>/dev/null && kill -0 "$BOT_PID" 2>/dev/null; do
  sleep 2
done

echo "a process exited; shutting down"
term
wait || true
exit 1
