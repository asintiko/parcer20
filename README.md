# Uzbek Receipt Parser

High-load financial transaction parsing system for Uzbek banking receipts (Uzcard/Humo).

## Architecture Overview

This system combines deterministic text processing with AI-powered parsing to transform unstructured receipt data into structured analytics. It monitors Telegram chats automatically and provides a strict business-style React interface for data visualization.

### Key Components

1. **Data Ingestion Layer**
   - Telegram Bot (Aiogram) - Manual receipt input
   - MTProto Userbot (Telethon) - Auto-monitoring of target chats
   - Redis queue for async processing

2. **Parsing Engine**
   - Regex parser (3 receipt formats: Humo, SMS, Semicolon)
   - DeepSeek text fallback with Structured Outputs-compatible responses
   - Vision/image receipt path kept as compatibility flow for image/PDF parsing
   - Operator-to-Application mapping (100+ rules)

3. **Backend API**
   - FastAPI with PostgreSQL
   - Transaction CRUD with pagination/filtering
   - Analytics endpoints ("Top Agent")

4. **Frontend**
   - React + Vite + TypeScript
   - TanStack Table (strict design)
   - Built-in AI agent drawer with reports, notifications, and navigation intents
   - Real-time updates with TanStack Query

## Quick Start

### Prerequisites

- Docker and Docker Compose
- Telegram API credentials (API_ID, API_HASH, BOT_TOKEN)
- DeepSeek API key for text AI paths
- OpenAI API key only if image/vision receipt compatibility flow is still used

### Setup

1. **Clone and configure environment**

```bash
cp .env.example .env
# Edit .env with your credentials
```

2. **Prepare mandatory root-access config**

```bash
cp security/root-access.server.example.json security/root-access.server.json
# Replace bootstrap hashes/tokens before production use
```

3. **Start services with Docker Compose**

```bash
# Secure/default (no source-code bind mounts)
docker compose up -d

# Development hot-reload (adds ./backend:/app mount)
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d
```

4. **Run DB migrations and seed operators**

```bash
docker compose exec backend alembic upgrade head
docker compose exec backend python -m database.seed_operators
```

5. **AI agent environment**

Set these variables in `.env` before bringing up the web stack:

```bash
DEEPSEEK_API_KEY=...
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_TEXT_MODEL=deepseek-chat
AI_REQUEST_TIMEOUT_SECONDS=60
AI_MAX_TOOL_CALLS_PER_REQUEST=4
AI_RETRY_COUNT=2
AI_AGENT_WEEKLY_REPORTS_ENABLED=true
APP_TIMEZONE=Asia/Tashkent
```

5. **Initialize Userbot session** (first time only)

```bash
docker compose exec userbot python -m ingestion.telegram_userbot
# Follow prompts to authenticate with your phone number
```

### Access

- **Frontend**: http://localhost:5173
- **API Docs**: http://localhost:8000/docs
- **Database**: localhost:5432

## Development

### Backend

```bash
cd backend
pip install -r requirements.txt
uvicorn api.main:app --reload
```

### Alembic Migrations

```bash
cd backend
alembic upgrade head
```

Create a new migration revision:

```bash
cd backend
alembic revision -m "describe change"
```

### Frontend

```bash
cd frontend
npm install
npm run dev
```

### Electron (Local Frontend + Local Backend)

Run only backend stack in Docker, and use desktop UI locally via Electron:

```bash
# from project root
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d postgres redis backend userbot telegram_bot celery_worker
docker compose stop frontend

# in another terminal
cd frontend
npm install
npm run electron:dev
```

Notes:
- In Electron runtime, frontend API defaults to `http://127.0.0.1:8000`.
- Electron now requires `client-access.json`:
  - Installer build: `%ProgramData%/TBSparcer/security/client-access.json`
  - Portable build: `<portable-folder>/security/client-access.json`
  - Example template: `security/client-access.example.json`
- Optional manual override in DevTools: `localStorage.setItem('api_base_url_override', 'http://127.0.0.1:8000')`.
- To clear override: `localStorage.removeItem('api_base_url_override')`.

### Windows Auto-Update via GitHub Releases (EXE-only)

Use a separate binary-only GitHub repository for desktop updates (default: `asintiko/parcer20-updates`), with only minimal placeholder files (for example just `README.md`) and no project source tree.

1. Prepare env on the build machine:

```bash
export GH_TOKEN=<github_token_with_repo_access>
export UPDATER_GH_OWNER=asintiko
export UPDATER_GH_REPO=parcer20-updates
export UPDATER_KEEP_RELEASES=1
```

2. Publish release and keep only the latest release:

```bash
cd frontend
npm run electron:publish:latest
```

This command uploads installer/portable update assets (`*.exe`, `latest.yml`, `*.blockmap`) and removes older releases/tags so the update repo keeps only current versions.

#### Table Virtualization (Performance)
- The transactions grid uses `@tanstack/react-virtual` inside `TransactionTable.tsx` to only render visible rows while keeping the header sticky and all table interactions (sorting, filtering, inline edit, drag-to-select) intact.
- Row height is estimated per density (`compact`, `standard`, `comfortable`); adjust `ROW_HEIGHT_BY_DENSITY` for custom sizing if row heights change.
- Overscan is set to `10` rows; tune `overscan` in the `useVirtualizer` config for smoother scroll on slow machines (higher = fewer reflows, lower = less work per scroll).
- A dev-only guard logs a warning if a large dataset (>2000 rows) ever renders without virtualization.

### Telegram TDLib Client (bots + groups)

The `/userbot` page is now a native React UI powered by a server-side TDLib client. No iframe/WebK is used.

- Backend exposes `/api/tg/*` for auth (phone → code → password), chat listing (bots + groups/channels), hide/unhide, history, and send.
- TDLib session is stored under `sessions/tdlib` (see `docs/telegram-tdlib-deploy.md`).
- Frontend relies on the new API; hidden chats are persisted in Postgres.
- PDF чеки из групп обрабатываются через общий каскад `pdfplumber → PyMuPDF → Tesseract` с GPT Vision fallback; системные зависимости (tesseract-ocr, poppler-utils) уже установлены в `backend/Dockerfile`.

### Built-in AI Agent

- Visible `Automation` page flow is replaced by an in-app AI agent drawer.
- Legacy `/automation` now acts as a compatibility route that redirects into the main app shell and opens the agent.
- Agent capabilities include:
  - application mapping
  - data verification
  - reconciliation
  - report generation
  - issue claiming/releasing/reassigning
  - transaction navigation hints
- Weekly team report is scheduled for Monday `12:00 Asia/Tashkent` and is delivered in-app.

## Security and Access (v1.2.0)

### RBAC Login (v1)

- Primary auth flow:
  - `POST /api/auth/login` (`username + password`)
  - `GET /api/auth/me`
  - `GET /api/auth/verify`
- Roles:
  - `admin` — full tabs/folders/sources access
  - `operator` — access only from assigned `allowed_tabs`, `allowed_folders`, `allowed_sources`, `forbidden_periods`
- Admin user management API:
  - `GET /api/admin/users`
  - `POST /api/admin/users`
  - `PATCH /api/admin/users/{id}`
  - `POST /api/admin/users/{id}/reset-password`
  - `POST /api/admin/users/{id}/unlock`
  - `DELETE /api/admin/users/{id}` (soft deactivate)
- Bootstrap first admin:
  - `python backend/scripts/create_admin.py <username> <password> \"<display_name>\"`
- QR login remains as legacy compatibility flow (`/api/auth/qr/*`).

### Scope Access (Hybrid + OTP)

- Scope source mode: Hybrid (DB + config). If IDs conflict, DB scope wins.
- OTP endpoints:
  - `POST /api/security/scope/{scope_id}/request-code`
  - `POST /api/security/scope/{scope_id}/verify-code`
- Legacy fallback endpoint (deprecated):
  - `POST /api/security/unlock`

### AuthBot

- `auth_bot` service is included in `docker-compose.yml`.
- Required env vars:
  - `AUTH_BOT_TOKEN`
  - `AUTH_ADMIN_IDS`
  - `AUTH_CODE_TTL_SECONDS`
  - `AUTH_MAX_ATTEMPTS`
  - `AUTH_RATE_LIMIT_PER_MIN`
  - `AUTH_RATE_LIMIT_BLOCK_MINUTES`

### Launch Password Gate

- Gate toggle:
  - `LAUNCH_GATE_ENABLED=false` (default; recommended for RBAC flow)
- Status + verification:
  - `GET /api/security/app/launch-status`
  - `POST /api/security/app/verify-launch`
- Protected `/api/*` routes require `X-Launch-Session` only when `LAUNCH_GATE_ENABLED=true`.
- Internal set-password endpoint:
  - `POST /api/internal/app/set-launch-password` with `X-Internal-API-Key`

### Locked Periods

- Public read endpoint:
  - `GET /api/security/locked-periods`
- Internal management:
  - `POST /api/internal/locked-periods`
  - `DELETE /api/internal/locked-periods/{id}`
- Locked periods are excluded from transaction list/years, sync, and frontend Excel export.

### Chat Password Protection

- Password endpoints:
  - `POST /api/tg/chats/{chat_id}/password`
  - `DELETE /api/tg/chats/{chat_id}/password`
  - `POST /api/tg/chats/{chat_id}/password/verify`
  - `GET /api/tg/chats/{chat_id}/password/status`
- Protected chat operations require `X-Chat-Access`.

### Offline Sync API

- `GET /api/sync/manifest`
- `GET /api/sync/{table_name}?since=&since_id=&limit=&offset=`
- Cursor mode (recommended):
  - `GET /api/sync/{table_name}?cursor_updated_at=&cursor_id=&limit=`
- Responses include `server_checksum`, `server_time`, `deleted_ids`.
- `next_cursor` is returned for cursor-based pagination.

### Mobile SMS Ingest Channel

- API endpoints:
  - `GET /api/sms/health`
  - `POST /api/sms/ingest`
- Auth header:
  - `X-Mobile-Ingest-Key`
- Important env vars:
  - `MOBILE_SMS_INGEST_KEY`
  - `MOBILE_SMS_INGEST_RATE_LIMIT_PER_MIN`
  - `MOBILE_SMS_INGEST_MAX_BATCH`
  - `APP_TIMEZONE`
  - `FINGERPRINT_DEDUP_MODE` (`legacy|dual|v2`)
- Key rotation procedure:
  1. Generate new `MOBILE_SMS_INGEST_KEY` and set it on backend.
  2. Rebuild internal Android APK with updated key.
  3. Roll out APK to devices.
  4. Revoke old key and monitor `sms_ingest_auth_fail` for stragglers.

### Telegram History Loader (v1.3.0)

- Persisted history tables:
  - `tg_chat_messages`
  - `tg_history_cursors`
- API:
  - `POST /api/tg/chats/{chat_id}/history/load`
  - `GET /api/tg/chats/{chat_id}/history/load/status`
  - `GET /api/tg/chats/{chat_id}/history/messages`
- Aggregated userbot payload:
  - `GET /api/tg/overview`
- WebSocket:
  - `/api/tg/ws/tg` now emits real events:
    - `auth-state`
    - `new-message`
    - `monitor-state`
    - `progress`

## Configuration

### Target Chat IDs

Edit `.env` to configure which Telegram chats to monitor:

```
TARGET_CHAT_IDS=915326936,856264490,7028509569
```

### Hourly Reports

Reports are sent to the Telegram channel specified in `REPORT_CHANNEL_ID`.

## System Features

- ✅ Dual ingestion: Manual (bot) + Automatic (userbot)
- ✅ Hybrid parsing: Regex (95% confidence) + GPT fallback
- ✅ Operator normalization: 100+ mapping rules
- ✅ Strict table UI: Data-dense design with TanStack Table
- ✅ Real-time analytics: Top Agent widget, hourly reports
- ✅ Production-ready: Docker, error handling, logging

## Technology Stack

**Backend:** Python, FastAPI, Aiogram, Telethon, SQLAlchemy, Celery, Redis, OpenAI  
**Frontend:** React, TypeScript, Vite, TanStack Table, TanStack Query, Tailwind CSS  
**Database:** PostgreSQL  
**Infrastructure:** Docker, Nginx

## License

Proprietary - All rights reserved
