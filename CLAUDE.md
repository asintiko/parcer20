# Parcer 2.0 (TBSparcer) — Project Knowledge Base

> **Этот файл Claude Code грузит автоматически в КАЖДОЙ сессии.** Это постоянная база
> знаний проекта (замена Obsidian-вольта, которого нет). Держи актуальным: при крупных
> изменениях архитектуры/деплоя — правь соответствующий раздел здесь.
>
> Источники истины по слоям: `CHANGELOG.md` (что менялось, до v1.4.12), `agentcontinue.md`
> (прод-доступы и деплой — СОДЕРЖИТ СЕКРЕТЫ), `.remember/` (хронология сессий),
> auto-memory в `~/.claude/projects/-Users-kulacidmyt-Documents-parcer2-0/memory/`.

---

## 1. Что это

High-load парсер банковских чеков Узбекистана (Uzcard/Humo). Принимает чеки из Telegram
(бот + userbot/TDLib) и SMS (Android-апп), парсит каскадом regex→AI→OCR/Vision, кладёт
в Postgres как транзакции, отдаёт в desktop-клиент (React+Electron) со строгим
data-dense UI, AI-агентом (DeepSeek) и аналитикой.

**Текущая версия:** 1.4.12 (frontend `package.json` + backend `APP_VERSION`).
**Продукт = Electron desktop** (Windows). На проде фронт-контейнера фактически нет —
Caddy отдаёт только API + mini-app; клиенты ставят .exe с auto-update.

## 2. Топология репозитория

| Каталог | Что | Стек |
|---|---|---|
| `backend/` | FastAPI API + воркеры + ingestion + парсеры (~45k LOC py, 151 файл) | Python 3.11, FastAPI, SQLAlchemy, Celery, Redis, TDLib, DeepSeek |
| `frontend/` | Desktop-клиент (ПРОД) — `name: tbsparcer` v1.4.12 | React+Vite+TS, motion@12, MUI7, TanStack table/query/virtual, dexie, react-router7, Electron |
| `design-sandbox/` | Песочница редизайна (mock-данные). Зеркало `frontend/src`, источник миграции | то же + `mockClient/mockData/mockTelegram` |
| `mini-app/` | Telegram Mini App (QR-подтверждение входа). Есть и inline-версия в `backend/api/main.py:716` (`/mini-app`) | — |
| `pdf_receipt_bot/` | Standalone PDF-чек бот (отдельный venv) | Python |
| `windows-customer-bundle/` | Клиентская сборка-бандл под Windows | — |
| `security/` | `root-access.server.json`, `client-access.json` + `*.example.json` шаблоны. СЕКРЕТЫ — не коммитим | — |
| `deploy/` | `Caddyfile`, `atomic_swap_*.sh`, `server-rollout-ai-agent.sh` | — |
| `recipts/` | Тестовый корпус чеков | — |
| `.remember/` `.serena/` | Память между сессиями (хронология / Serena) | — |

**Git:** репозиторий НЕ инициализирован локально (`git rev-parse` → not a repo). Удалённый:
`github.com/asintiko/parcer20` (код) + `asintiko/parcer20-updates` (только .exe для auto-update).

## 3. Backend — карта

### Boot (`backend/api/main.py`)
`uvicorn api.main:app`, 1 воркер. Lifespan (`:605`): `init_db` → seed system_settings →
TDLib manager (singleton) → AI-agent scheduler → tg auto-monitor task → resume running
history-loaders. Shutdown останавливает всё аккуратно (`scheduler.shutdown(wait=True)`).

**Middleware-стек** (порядок применения снизу вверх, `:527-549`):
`SecurityHeaders` → `ApiVersionHeader` (X-API-Version) → `LaunchSession` →
`SystemAccess` → `CSRF` → `RequestLogging` → `ErrorHandling` → `RateLimit` (100/min,
sync-роуты отдельный бакет, Redis-бакет с memory-fallback). CORS — белый список origin
(no wildcard), `app://.`/`file://` для Electron.

### Роутеры (`api/routes/*.py`, монтаж `main.py:1075`)
`auth`, `admin`, `ai_agent`, `transactions` (`/api/transactions`), `analytics`,
`reference`, `logs`, `automation`, `reconciliation`, `userbot`, `telegram_client`
(+`files_router`+`ws_router`), `security` (+`internal_router`), `periods`,
`system_settings`, `two_factor`, `audit`, `sync`, `sms`.

### Auth & access control (`api/dependencies.py`)
- **JWT bearer** → `get_current_user` / `_optional` / `get_current_app_user`.
  `AUTH_REQUIRED` (`:52`) дефолт true; false игнорируется вне dev/test, если только не
  `ALLOW_INSECURE_NO_AUTH=true` / `APP_ENV in {dev,development,local,test,testing}` / `DEBUG`.
  **Это была BLOCKER-дыра v1.4.9** — env-bypass auth. Проверяй при аудите.
- **RBAC:** роли `admin` (всё) / `operator` (по `allowed_tabs/folders/sources`,
  `forbidden_periods`). `require_admin_user`, `require_tab_access(tab)`.
- **Scope/OTP** (Hybrid DB+config): `get_scope_context_optional`, `require_transactions_scope`,
  `require_sources_scope`. Токен `X-Access-Token`. Admin всегда full-access.
- **Системные шлюзы:** `X-System-Access` (root-access config, mandatory если enforced),
  `X-Internal-Api-Key` (сервис-сервис, bypass CSRF+System), `X-Launch-Session`
  (launch-gate, если включён в system_settings), `X-Chat-Access` (пароль на чат),
  `X-Mobile-Ingest-Key` (только `/api/sms/*`, `secrets.compare_digest`).

### AI-агент (`services/ai_agent/`)
- `orchestrator.py` — цикл запроса, tool-calls (лимит `AI_MAX_TOOL_CALLS_PER_REQUEST=4`).
- `tool_registry.py` + `tools/*` — инструменты: analytics, audit, automation, cache, calc,
  diagnostics, filter, mutation, navigation, report, ui_action. Схемы — `tool_schemas*.py`
  (есть v5).
- `scheduler_service.py` — AsyncIOScheduler в backend (НЕ Celery). С v1.4.10 здесь же
  `_run_monitored_chat_sync` (флаг `MONITORED_CHAT_SYNC_VIA_BACKEND`).
- `confirm_service` / `session_service` / `notification_service` / `report_service` /
  `weekly_publisher` (отчёт Пн 12:00 Asia/Tashkent) / `run_watchdog`.
- **ИЗВЕСТНЫЙ BLOCKER:** `AgentRunEvent.event_type='tool_failed'` нарушает CHECK-constraint
  (orchestrator пишет значение, которого нет в CHECK из migration 015 / models.py). Валит
  ~27% ран. Проверяй `models.py` AgentRunEvent + alembic 0015 перед правкой агента.

### Telegram ingestion
- `services/telegram_tdlib_manager.py` — **singleton** TDLib-клиент, сессия в
  `/app/sessions/tdlib` (volume, authed ~1.27GB). Был баг: `self._loop` кэшировался на
  закрытый loop при `asyncio.run` per-tick (фикс v1.4.10 — sync переехал в backend loop).
- `services/monitored_chat_sync.py` — `sync_one_chat`: TDLib `getChatHistory` отдаёт
  сообщения СТАРШЕ `from_message_id`; идём от latest(0) назад до `cursor_message_id`,
  курсор двигаем ТОЛЬКО при `failed_ids == set()` (защита от дыр). `tg_chat_messages` +
  `tg_history_cursors`.
- `ingestion/telegram_userbot.py` (MTProto auto-monitor) + `ingestion/telegram_bot.py`
  (aiogram, ручной ввод) + `services/auth_bot_handler.py` (auth-бот, OTP/сессии).

### Парсинг (`parsers/`)
Каскад `parser_orchestrator.py`: `regex_parser` (форматы Humo-emoji / SMS-inline /
Semicolon / CardXabar) → AI text (`ai_receipt_parser.py`, DeepSeek) → PDF/OCR
(`pdf_extractor.py`: pdfplumber→PyMuPDF→Tesseract) → GPT Vision (compat). `operator_mapper.py`
маппит оператора→приложение (100+ правил, таблица `operator_reference`). Результат →
`receipt_processor.py` → транзакция с SHA256-fingerprint (dedup, `.quantize(0.01)`).
**История багов:** см. `PARSER_FIXES.md` (emoji-несовпадения, txn_type/transaction_type
знак суммы расходился между receipt_processor и celery_worker).

### Фоновые задачи
- **Celery** (`workers/celery_worker.py`, `acks_late`, DLQ): обработка чеков, manual
  fallback для monitored_chat_sync (НЕ в ротации — celery_worker без TDLib volume!).
- **Backend AsyncIOScheduler**: monitored_chat_sync (v1.4.10+), weekly report, watchdog.

## 4. Данные

SQLAlchemy `database/models.py`, миграции `backend/alembic/versions/` (17 шт):
`0001` v1.2.0 security+sync baseline → `0002` schema hotfix → `0003` sms source type →
`0004` RBAC users → `0005` system_settings → `0006` 2FA → `0007` full audit core →
`0008` user telegram fields → `0009` chat_message↔receipt link → `0010` automation task
type → `0011` automation aux tables → `0012` receipt_task raw_message → `0013` session TTL →
`0014` ai_agent core → `0015` ai_agent v4 runtime → `0016` agent_run_status len →
`0017` locked_period exclusions.

Ключевые таблицы: `transactions` (раньше был split `Check`/`Transaction` — консолидирован),
`operator_reference` (справочник, seed через `database/seed_operators.py` /
`import_operators.py` / `import_operators_data.sql`), `users`, `access_scopes`,
`locked_periods` (+`excluded_user_ids` JSONB), `tg_chat_messages`, `tg_history_cursors`,
`monitored_bot_chats` (колонка `enabled`, НЕ `is_active`!), `agent_*`, `audit_log`,
`app_launch_config`. **Дыра v1.4.9:** 0 selectinload/joinedload на 38.9k LOC (N+1).
Postgres 15, контейнер `uzbek_parser_db`, `127.0.0.1:9990:5432`.

## 5. Docker-стек (`docker-compose.yml`) — «он сам всё берёт»

Все backend-сервисы из ОДНОГО образа (`backend/Dockerfile`): multistage, собирает **TDLib
из исходников** (cmake, ~30 мин!) + Tesseract(rus/eng) + poppler. Поэтому на проде
hotfix-ят через `docker commit`, а НЕ rebuild (см. memory `parcer-python-hotfix`).

| Сервис | Контейнер | Команда | Volumes | Порт |
|---|---|---|---|---|
| postgres | uzbek_parser_db | — | postgres_data | 127.0.0.1:9990→5432 |
| redis | uzbek_parser_redis | requirepass | — | 127.0.0.1:9991→6379 |
| backend | uzbek_parser_backend | uvicorn | root-access(ro), backend_sessions, **tdlib_data, tdlib_files** | 8000 |
| userbot | uzbek_parser_userbot | telegram_userbot | backend_sessions, **tdlib_data, tdlib_files** | — |
| telegram_bot | uzbek_parser_telegram_bot | telegram_bot | — | — |
| auth_bot | uzbek_parser_auth_bot | auth_bot_handler | root-access(ro) | — (mem 128m) |
| celery_worker | uzbek_parser_celery_worker | celery worker | **❌ НЕТ tdlib volume** | — |
| frontend | uzbek_parser_frontend | nginx | — | 127.0.0.1:5173→80 |
| caddy | uzbek_parser_caddy | reverse-proxy | Caddyfile(ro), caddy_data/config | 80, 443 |

**КРИТИЧНО:** только `backend` и `userbot` монтируют `tdlib_data`/`tdlib_files`.
`celery_worker` — НЕТ → у него пустая 12KB неаутентифицированная TDLib-сессия. Поэтому
monitored_chat_sync был перенесён в backend-scheduler (v1.4.10). Не возвращай sync в Celery
без монтирования volume.

Dev-оверрайд: `docker-compose.dev.yml` добавляет bind-mount `./backend:/app` (hot-reload).

**Caddy** (`deploy/Caddyfile`): домен `64.188.106.221.nip.io`, проксирует `/mini-app*` и
`/api/*` на `backend:8000`, инжектит `X-System-Access: {$SYSTEM_ACCESS_TOKEN}`, `/health` и
SPA-shell на frontend. zstd/gzip, авто-TLS через nip.io.

## 6. Прод и деплой

- **Сервер:** `64.188.106.221`, root, path `/opt/receipt-parser`. SSH через пароль —
  см. memory `parcer-server-ssh-via-password` (`sshpass -e`). Доступы/пароли в
  `agentcontinue.md` (НЕ дублировать сюда).
- ⚠️ `PROJECT_AGENT_GUIDE.md` УСТАРЕЛ — там старый IP `144.31.17.123`. Актуальный —
  `64.188.106.221`.
- **Деплой кода:** `rsync` → `docker compose up -d --build` в `/opt/receipt-parser`.
  Python-hotfix БЕЗ rebuild: `docker cp` + `docker commit` (TDLib не пересобирать).
  `deploy/atomic_swap_*.sh`, `deploy/server-rollout-ai-agent.sh`.
- **Electron rollout:** `cd frontend && npm run electron:publish:latest` (GH_TOKEN,
  UPDATER_GH_OWNER=asintiko, UPDATER_GH_REPO=parcer20-updates). Кросс-сборка Win с Mac
  через buildx amd64 (5 мин vs 25 на VPS). latest.yml + sha512.
- **Известное состояние (2026-05-29):** диск прода 91%; HUMO/NBU Card sync застрял
  (cursor не двигается с 19/23 мая); 5 BLOCKER-ов v1.4.9 не закрыты. Проверь актуальность
  перед работой — это снапшот, а не текущая истина.

## 7. Frontend — карта

`frontend/src`: `App.tsx` (роутинг в `AppShell`), `main.tsx` (providers, LaunchGate —
НЕ mock-bootstrap из sandbox), `services/api.ts` (axios, Electron→`127.0.0.1:8000`,
override через `localStorage api_base_url_override`). Слои: `components/shell/` (AppShell/
Rail/Topbar/MobileDrawer), `components/motion/` (Sheet/Dialog/Popover/ConfirmDialog),
`components/telegram/` (12 компонентов TG-клиента), `components/Ai*` (агент-дровер v5),
`contexts/` (Auth/Theme/AiAgent), `hooks/` (useInlineEdit, useAiAgentStream SSE, useHistory
undo/redo). Страницы: Transactions (TanStack virtual, inline-edit, undo), Userbot (3-step
TG-auth, сообщения asc по date — фикс v1.4.12), Settings, Reference, Login, Logs, Audit.

**Design DNA (editorial monochrome):** НЕТ purple/blue/градиентов. Шрифты Instrument Serif
+ Space Grotesk + JetBrains Mono. Квадратный радиус 4px. Парные заливки
`--sp-on-ink`/`--sp-on-accent`. Motion-токены `--ease-standard/emphasized/pop/accelerate`.
Тема через `data-theme="dark"`. Токены в `src/styles/theme.css`.

**Electron** (`electron/main.cjs`): меню `Инструменты→DevTools` (F12/Ctrl+Shift+I через
`before-input-event`) + `Очистить кэш` (Ctrl+Shift+R). `client-access.json` в
`%ProgramData%/TBSparcer/security/` (installer) или `<portable>/security/`.
**Дыры:** token в localStorage (plaintext), `sandbox:false`, нет CSP, нет focus-trap в
Sheet/Dialog, MessageStream не виртуализирован.

## 8. Известные BLOCKER-ы / долг (для аудита, статус сверять с кодом!)

1. `AgentRunEvent.event_type='tool_failed'` ∉ CHECK-constraint → ~27% ран падает.
2. `AUTH_REQUIRED=false` env-bypass auth (`dependencies.py:52`).
3. `INTERNAL_API_KEY` — single-secret kill-switch (одна ротация рвёт всех).
4. Photo-group `-1003547724919` (UBpay_demo) защищена только `MonitoredBotChat.enabled=false`,
   нет blocklist в коде. Metadata-only по дизайну (memory `parcer-photo-group-metadata-only`).
5. monitored_chat_sync без cap на объём.
6. 0 selectinload/joinedload (N+1) на всём backend.
7. `python-jose` CVE-2024-33663.
8. Frontend: localStorage plaintext token, sandbox:false, no CSP.

## 9. Команды

```bash
# Backend локально
cd backend && uvicorn api.main:app --reload          # API :8000
alembic upgrade head                                  # миграции
python -m database.seed_operators                     # справочник

# Frontend / Electron
cd frontend && npm run dev                            # Vite
npm run electron:dev                                  # desktop (API→127.0.0.1:8000)
npm run electron:publish:latest                       # релиз .exe в parcer20-updates

# Docker (прод-подобный)
docker compose up -d --build
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d   # hot-reload
docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
docker logs uzbek_parser_backend
```

## 10. Конвенции (см. также `~/.claude/CLAUDE.md`)

- Русский в чате, английский в коде. Без filler-комментариев, без TODO/заглушек.
- Перед паттерном — читай 2-3 соседних файла, матчи стиль.
- Не push/merge/PR/rebuild-прод без явной просьбы. Секреты не коммитим.
- Память: при старте нетривиальной задачи — `mcp__memory__search_nodes` + проверь
  `.remember/` и auto-memory. Крупные изменения — обнови этот файл.
