#!/usr/bin/env bash
set -euo pipefail

REMOTE_HOST="${REMOTE_HOST:-64.188.106.221}"
REMOTE_USER="${REMOTE_USER:-root}"
REMOTE_DIR="${REMOTE_DIR:-/opt/receipt-parser}"
APP_VERSION="${APP_VERSION:-1.4.0}"
NIP_IO_HOST="${NIP_IO_HOST:-64.188.106.221.nip.io}"

if [[ -z "${DEEPSEEK_API_KEY:-}" ]]; then
  echo "DEEPSEEK_API_KEY is required" >&2
  exit 1
fi

rsync -az --delete \
  --exclude '.git' \
  --exclude 'node_modules' \
  --exclude 'frontend/node_modules' \
  --exclude 'frontend/release' \
  --exclude 'frontend/dist_backup_*' \
  --exclude 'windows-customer-bundle' \
  --exclude 'windows-test-bundle' \
  --exclude 'parcer-source.tar.gz' \
  ./ "${REMOTE_USER}@${REMOTE_HOST}:${REMOTE_DIR}/"

ssh "${REMOTE_USER}@${REMOTE_HOST}" bash <<REMOTE
set -euo pipefail
cd "${REMOTE_DIR}"

python3 - <<'PY'
from pathlib import Path
path = Path('.env')
text = path.read_text() if path.exists() else ''
updates = {
    'APP_VERSION': '${APP_VERSION}',
    'DEEPSEEK_API_KEY': '${DEEPSEEK_API_KEY}',
    'DEEPSEEK_BASE_URL': 'https://api.deepseek.com',
    'DEEPSEEK_TEXT_MODEL': 'deepseek-chat',
    'AI_REQUEST_TIMEOUT_SECONDS': '60',
    'AI_MAX_TOOL_CALLS_PER_REQUEST': '4',
    'AI_RETRY_COUNT': '2',
    'AI_AGENT_WEEKLY_REPORTS_ENABLED': 'true',
    'APP_TIMEZONE': 'Asia/Tashkent',
    'AUTOMATION_MAPPING_AI_MODEL': 'deepseek-chat',
    'AUTOMATION_VERIFY_AI_MODEL': 'deepseek-chat',
    'CSRF_TRUSTED_ORIGINS': 'http://localhost:5173,http://127.0.0.1:5173,https://${NIP_IO_HOST}',
}
lines = [line for line in text.splitlines() if line.strip()]
keys = set()
out = []
for line in lines:
    if '=' not in line or line.lstrip().startswith('#'):
        out.append(line)
        continue
    key = line.split('=', 1)[0]
    if key in updates:
        out.append(f"{key}={updates[key]}")
        keys.add(key)
    else:
        out.append(line)
for key, value in updates.items():
    if key not in keys:
        out.append(f"{key}={value}")
path.write_text('\n'.join(out) + '\n')
PY

docker compose build backend frontend celery_worker auth_bot userbot telegram_bot caddy

docker compose up -d postgres redis
sleep 5

docker compose run --rm backend bash -lc 'cd /app/backend && alembic -c alembic.ini upgrade head'

docker compose up -d backend frontend celery_worker auth_bot userbot telegram_bot caddy

curl -fsS http://127.0.0.1:8000/health
curl -fsS https://${NIP_IO_HOST}/health || true
curl -fsS https://${NIP_IO_HOST}/api/agent/threads || true
REMOTE
