# Changelog

## 1.4.24 — 2026-07-13

- Авторизация переведена на обязательные зарегистрированные server-side сессии:
  refresh/pre-2FA/legacy QR токены больше нельзя использовать как обычный bearer,
  а Redis-сбой закрывает доступ вместо fail-open.
- Права пользователя, источники, папки, периоды и блокировки повторно проверяются
  непосредственно перед AI/worker/receipt мутациями; запрещённый чек не оставляет
  транзакцию, служебные метаданные или audit-запись.
- Telegram-файлы и WebSocket привязаны к владельцу чата/сообщения и живой сессии;
  internal API поддерживает ротацию нескольких ключей и строгую проверку origin.
- Android SMS-клиент 1.0.3 использует уникальные ключи устройств и проверяет digest,
  package id и подпись APK; общий ключ удалён из приложения.
- Electron хранит refresh-токен через `safeStorage`, не передаёт system token в renderer,
  включает sandbox/CSP и проверку подписи Windows-обновлений. Axios и React Router
  обновлены, неиспользуемый уязвимый `xlsx` удалён.
- Проверка автообновления Electron запускается сразу после загрузки интерфейса и затем
  повторяется каждые 6 часов; ошибки проверки обрабатываются без необработанных Promise.
- Первый запуск Electron безопасно переносит legacy refresh-токен в `safeStorage` до
  удаления plaintext; Android upgrade принудительно останавливает мониторинг до ввода
  персонального device ID/key.
- Userbot получил отдельный volume только для Telethon-сессии, вынесен в явный profile
  и не имеет доступа к TDLib. Для backend/workers/auth-bot/PostgreSQL/Caddy включена
  ротация JSON-логов 20 MB × 3; Redis сохранён без пересоздания до staged volume migration.
- Добавлена миграция 0025 для полного набора событий AI-агента, лимиты фоновых задач
  и синхронизации мониторируемых чатов, а также типизированный API страницы автоматизации.
- Прод развернут готовым локальным amd64 image поверх TDLib 1.8.65 без server-side build.
  9 997 старых active-инцидентов сообщений 2020–2025 архивированы и переведены в
  `resolved`; транзакции и Telegram-сообщения не удалялись.

## 1.4.23 — 2026-07-12

- Telegram catch-up теперь жёстко ограничен началом текущего года: дата исходного
  сообщения и дата распознанной транзакции проверяются до сохранения, а worker
  повторно подтверждает, что AUTO-источник включён в `monitored_bot_chats`.
- Устранён инцидент rollout: 8 504 ошибочно импортированные транзакции 2021–2025
  удалены после проверенного backup; более 1 800 сообщений receipt-логгера удалены из
  Telegram forum topic. Исторический cursor закреплён на последнем сообщении.
- `UBpay_demo` включён как обычный мониторируемый источник; встроенная metadata-only
  блокировка снята, старый history не переигрывается благодаря закреплённому cursor.
- Telegram auto-monitor переведён на durable DB outbox: bounded queue, устойчивый
  scan cursor, повтор transient-сбоев без пропусков и OCR/AI вне event loop API.
- Celery разделён на fast/OCR/maintenance очереди; добавлены heartbeat, bounded retry,
  watchdog recovery, Alembic-managed DLQ и безопасная загрузка файлов до 25 MB.
- Fingerprint теперь только кандидат для ручной сверки: автоматическая идемпотентность
  основана на Telegram/SMS source identity, cross-source чеки больше не склеиваются.
- Исправлены суммы с локальными разделителями, AI Decimal/schema/date validation,
  русские P2P-поля и Unicode-маппинг операторов.
- Второй AI-вызов для application mapping по умолчанию отключён; неизвестные операторы
  сохраняются для справочника/сверки без замедления основного ingestion.
- Force reparse обновляет существующую транзакцию с before/after audit; миграции 0023–0024
  исправляют знак исторических сумм и активные дубли инцидентов.
- Метрики backend/Celery агрегируются через Redis без блокировки event loop. Перед
  rollout снят RDB snapshot; persistent Redis volume отложен до безопасной staged
  миграции. TDLib 1.8.65 упакован локально в amd64 release image.

## 1.4.17–1.4.19 — 2026-06-04/05

- **1.4.19 (2026-06-05): фича «Описание»** — операторно-привязанное описание транзакции:
  миграция **0021**, резолв при чтении, общая сущность, вкладка «Описания» в Справочнике,
  агентские тулзы `auto_describe_operators` + web-search + rollback, причёсан UI агента.
- **2026-06-04: agent UX** — FAB/прогресс/`verify_receipt_parse`, убрано «Без маппинга»;
  cross-source обогащение `/api/sms/ingest`; Android 1.0.2 — 2 вкладки + GitHub-апдейтер.

## 1.4.16 — 2026-05-31

### AI-агент: рутины по описанию, команды, богатый рендер, уведомления

- **Рутины исполняют своё описание.** Тип «Другое» (custom) теперь реально
  прогоняет сохранённый текст задачи через ИИ-агента (только безопасные
  инструменты — правки данных не применяются автоматически, требуют
  подтверждения). Раньше описание игнорировалось.
- **Встроенная рутина «Аудит чеков».** Ежедневно сверяет локально скачанные
  Telegram-чеки с базой, проверяет точность парсинга (совпало / пропало /
  не разобралось / без маппинга) и публикует отчёт в канал логирования — туда
  же, куда приходят логи обработки чеков.
- **Упрощённое расписание рутин.** Вместо ручного cron — переключатель
  «Разово / Еженедельно / Ежедневно», выбор дней недели и времени, дата для
  разовых. Разовая рутина срабатывает один раз и выключается.
- **Палитра команд в чате.** Кнопка-«/» в строке ввода открывает список
  быстрых команд (как в ChatGPT): «Подсчёт затрат», «Сводка за период»,
  «Сверка чеков» и свои. Клик отправляет заготовку, агент сам уточняет детали.
  Админы создают и удаляют команды прямо из палитры.
- **Богатое оформление ответов.** Ответы ИИ теперь рендерятся как Markdown:
  заголовки, таблицы, списки, разделители, блоки кода с кнопкой копирования.
  Агент может рисовать встроенные SVG-графики (безопасная фильтрация).
- **Уведомления чинятся и дублируются в Telegram.** Колокольчик в шапке
  агента открывает панель уведомлений (раньше не реагировал). Каждое
  уведомление агента дублируется в канал логирования.

---

## 1.4.15 — 2026-05-30

### Доработки по код-ревью

- Сценарии быстрого старта: увеличен таймаут ожидания результата (45с → 120с),
  чтобы карточка с итогом чаще успевала прийти в чат на больших батчах.
- Сверка чеков теперь учитывает права оператора по источникам (RBAC): оператор
  видит только свои чаты, не все.
- Escape в панели рутин больше не закрывает всю панель, если открыт диалог
  подтверждения удаления.
- Переключатель «вкл/выкл» рутины откликается мгновенно (оптимистичное обновление).
- Опрос фоновой задачи: ранний выход при удалении задачи, монотонные часы,
  убран недостижимый код параметров.

---

## 1.4.14 — 2026-05-30

### Рутины в AI-агенте + живые результаты сценариев

- **Управление рутинами прямо в агенте**: кнопка-календарь в шапке дровера (для
  админов) открывает панель — список рутин (вкл/выкл, расписание, статус), создание
  по форме (пресеты расписания) и запуск/удаление, не уходя из чата.
- **4 сценария быстрого старта теперь показывают результат в чате**. Раньше
  «Сопоставление»/«Проверка»/«Сверка» отвечали только «запущено N» — итог уходил в
  фон. Теперь агент дожидается завершения и показывает карточку с реальными
  счётчиками (предложения/исправления/совпадения) + кнопку «Открыть Автоматизацию».
- **Починен раздел «Автоматизация»**: `/automation` больше не редиректит обратно —
  открывает страницу проверки предложений; кнопка из чата ведёт на нужную вкладку с
  результатами конкретной задачи.
- Уточнены подсказки на карточках сценариев.

---

## 1.4.13 — 2026-05-30

### Feature: AI-рутины (плановые задачи агента)

Новый раздел «Рутины» в клиенте: агент по расписанию (cron, Asia/Tashkent)
выполняет безопасные примитивы — сверку (`reconcile`), сводку (`summary`) —
и присылает отчёт в Telegram-канал и в чат агента. Выполнение НЕ запускает
сгенерированный код, только проверенные параметризованные инструменты
(`weekly_health_check` / `chat_vs_db_reconcile` / `period_summary`).

- `pages/RoutinesPage.tsx`: CRUD рутин, пресеты расписания, история запусков,
  запуск «сейчас», переключатель активности.
- Рейл `Рутины` (admin), роут `/routines`, `routinesApi` в `services/api.ts`.
- Backend (уже на проде с 29 мая): модель `AgentRoutine`/`AgentRoutineRun` +
  миграция 0018, `routine_service`, `routes/routines.py`, динамическая
  cron-регистрация в scheduler, agent-tools `create_routine` / `list_routines`
  (создание рутины фразой в чате).

---

## 1.4.12 — 2026-05-25

### Fix: порядок сообщений в чате

В Telegram-вкладке сообщения шли сверху вниз "новые → старые" (как отдаёт
TDLib `getChatHistory`). Telegram-style ожидание — "старые сверху, новые
внизу", и `MessageStream` так и реализован (`messages[length-1]` это
последнее сообщение, autoscroll-to-bottom при новых).

`pages/UserbotPage.tsx`: теперь `allMessages` сортируется asc по
`message.date` (fallback на numeric `id` для записей без даты, и стабильная
вторичная сортировка по id). Backend payload не меняется — это чисто
клиентский fix.

---

## 1.4.11 — 2026-05-25

### Electron client UX

- **DevTools доступны** через нативное меню `Инструменты → Открыть DevTools`,
  горячую клавишу `F12` (или `Ctrl+Shift+I`). Раньше меню было скрыто
  (`Menu.setApplicationMenu(null)` + `setMenuBarVisibility(false)`), F12 ловил
  только webContents — на Windows иногда не срабатывало из-за фокуса.
- Добавлен пункт `Инструменты → Очистить кэш и перезагрузить` (`Ctrl+Shift+R`)
  — чистит cookies / localStorage / IndexedDB / serviceWorkers / cacheStorage
  и `reloadIgnoringCache()`. Это нужно после v1.4.10 hotfix'а: backend начал
  отдавать свежие сообщения, но локальный кэш клиента может держать старый
  snapshot.
- F12 / Ctrl+Shift+I дублируется через `before-input-event` listener — даже
  если страница глотает эти клавиши, главное окно перехватит их и откроет
  DevTools.
- Добавлено меню `Файл / Правка / Вид / Инструменты / Помощь` (на русском).

Файл: `frontend/electron/main.cjs`. Backend bumped до 1.4.11 для синхрона
версий.

---

## 1.4.10 — 2026-05-25

### Hotfix: monitored-chat sync теперь реально пишет в БД

**Симптом.** В Telegram-вкладке клиента последнее сообщение для активных чатов
(HUMO Card / NBU Card / CardXabar) застряло на старых датах — у HUMO Card
последняя запись была от 19 мая, у юзера в клиенте даже Dec 2025.
`tg_chat_messages` не обновлялся свежими сообщениями.

**Root cause** (две независимые баги, складывающиеся):
1. **Worker без TDLib volume.** `docker-compose.yml` секция `celery_worker`
   не монтирует `tdlib_data`/`tdlib_files` (в отличие от `backend`/`userbot`).
   Внутри worker'а `/app/sessions/tdlib/db.sqlite` — пустая 12 KB SQLite из
   image, TDLib session **не аутентифицирована**. Любой `getChatHistory`
   падает с error.
2. **Singleton lop bug.** `monitored_chat_sync_tick_task` зовёт `asyncio.run`
   каждый тик → новый event loop. `TelegramTDLibManager` (singleton) кэширует
   `self._loop` при первом fetch. На втором тике `self._loop` указывает на
   закрытый loop → `ValueError: future belongs to different loop`.

В итоге `monitored_chat_sync_tick` возвращал `new_rows: 0, pages_done: 0` для
каждого чата, а в логах был spam `Event loop is closed` + `future belongs to
different loop`.

**Fix.** `_run_monitored_chat_sync` теперь крутится **в backend
AsyncIOScheduler** (uvicorn loop, долгоживущий), вызывая
`sync_all_active_chats(fetch_callable=...)` напрямую через authed singleton
`TelegramTDLibManager` backend'а. Никаких `asyncio.run` per tick — нет
recreated loop'ов. Backend имеет authed TDLib session (1.27 GB volume,
realtime updates приходят) → `getChatHistory` реально возвращает сообщения.

- `backend/services/ai_agent/scheduler_service.py`:
  - `_run_monitored_chat_sync` (async) заменяет `_enqueue_monitored_chat_sync`
    в registered jobs. Старый Celery enqueue остался как ручной fallback,
    активируется флагом `MONITORED_CHAT_SYNC_VIA_BACKEND=false`.
  - `stop()`: `scheduler.shutdown(wait=True)` — текущий sync-tick не
    обрывается на середине batch'а.
  - `_flag_truthy(name, default)` — единый helper для env-флагов.
- `backend/api/main.py`: `APP_VERSION` default 1.4.9 → 1.4.10.
- `frontend/package.json`: `version` 1.4.9 → 1.4.10.

**Что НЕ трогали.**
- Celery `monitored_chat_sync_tick` task в `celery_worker.py` — оставлен как
  manual fallback (можно дёрнуть руками для diagnose, неактивен в ротации).
- Volume mounts на `celery_worker` — отдельная задача (нужен TDLib login flow
  для второго клиента, не входит в scope hotfix'а).
- Photo group `-1003547724919` (UBpay_demo) — `last_processed_message_id`
  оставлен как был.

---

## 1.4.9 — 2026-05-25

### Security & data integrity
- **`excluded_user_ids` теперь enforced в lock check** (M-1): `period_lock_service.is_date_locked(value, db, user_id=...)` — пользователи в exclusion list могут писать в lock'нутый период. Все callers в `transactions.py` (PUT/PATCH/DELETE/bulk-update/bulk-delete) и `automation.py` пропускают `current_user.id`.
- **`excluded_user_ids` FK validation** (M-2): `_normalize_excluded(values, db)` reject id <= 0, проверяет существование в `users.id`, кап `EXCLUDED_USER_IDS_LIMIT=1000`. 400 с конкретным `missing` массивом если id неизвестен.
- **Audit log diff на `excluded_user_ids`** (B3): `update_period`/`create_period` теперь сохраняют `before`/`after` снапшоты в `audit_log.details_json.diff`. Скрытые admin-только изменения exclusions больше не теряются.
- **`processing_error` sanitized** (M-5): `_sanitize_processing_error` маппит raw exception в short user-facing labels (Не удалось извлечь PDF / Не удалось распознать изображение / Парсер не смог распознать чек / etc). Stack traces / paths / OpenAI bodies остаются только в backend logs.
- **`_audit` / `_publish_locked_periods_change` exception loging**: bare `except: pass` → `logger.exception(...)`. Теперь видно когда audit silent fail.

### Bug fixes
- **`sync_one_chat` cursor protection** (M-3): `_persist_messages` returns `(persisted, failed_ids)`. cursor advances ТОЛЬКО при `failed_ids == set()`. Если row упал на persist — cursor стопается на последнем гарантированно сохранённом id. Status `partial` ставится для retry.
- **Telegram processed status: 'unknown' вместо null** (M-6): `_enrich_with_receipt_status` на DB exception теперь ставит `processed=False, processed_status='unknown', processing_error='enrichment_failed'`. Frontend видит badge "статус неизвестен" вместо silent disappear.
- **`card_last_4` clearing** (P2 B10): regex `^(\d{4})?$` теперь allows empty string. Backend coerces `"" → None`. То же для `receiver_card`.
- **UI dispatch tokens теперь monotonic counter** (m-1): `Date.now()` → `nextUiActionToken()` / `nextAgentIntentToken()`. 2 messages в одном React batch получают разные токены.

### Deferred → 1.5.0
- AI agent `open_details` полный handler (modal + flash highlight) — currently degrades to highlight+scroll
- Cursor animation render (`animate_cursor` flag доставляется но не рендерится)
- Mac DMG / Linux AppImage publishing (currently Windows-only по тз)
- TDLib локальный билд (note: уже работает в v1.4.8 release pipeline через buildx amd64 → docker save → docker load на проде)
- P2 B3 concurrency control (version column на transactions + If-Match)
- P2 B5 Pydantic `extra=forbid`
- P3 localStorage state ботов + сверка last_message_id
- m-9 cursor decoupling (legacy `last_processed_message_id` vs new `cursor_message_id`)
- m-10 JSON → JSONB в SQLAlchemy model

---

## 1.4.8 — 2026-05-25

### Backend

- **P0 fix** `receipt_processor.py`: bare-name `transaction_type` → `txn_type`. Auto-monitor pipeline пропускал каждое сообщение в crash-loop с `NameError`, retried бесконечно.
- **P0 fix** `monitored_chat_sync.py`: `MonitoredBotChat.is_active` → `enabled` (правильное имя колонки), `TgHistoryCursor.last_synced_message_id` → `cursor_message_id`, удалён несуществующий `backfill_complete`.
- **P0 fix** `celery_worker.py`: `manager.get_chat_history(...)` (метод не существует) → `manager.get_messages(...)`.
- **P1 fix** `audit_tools.py weekly_health_check`: `MonitoredBotChat.is_active` → `enabled`.
- **P1c rewrite** `monitored_chat_sync.sync_one_chat`: правильное направление пагинации. TDLib `getChatHistory` возвращает сообщения **старше** `from_message_id`. Новая логика: всегда стартуем от `from_id=0` (latest), идём назад до сохранённого `cursor_message_id`, фиксируем cursor только при успешной транзакции. Добавлены `status`/`error` обновления курсора.
- **Schema** `LockedPeriod.excluded_user_ids JSONB DEFAULT '[]'`: добавлено поле + Pydantic-схемы + миграция `20260524_0017_locked_period_exclusions`.
- **Schema** `models.py`: `text` → `sql_text` (4 места) — устранён `'Column' object is not callable` шадоуинг при импорте.
- **Backend version**: env `APP_VERSION` 1.4.7 → 1.4.8.
- **API enrichment** `GET /api/tg/chats/{id}/messages`: payload `ChatMessage` теперь включает `processed`, `processed_status`, `transaction_id`, `processed_at`, `processing_error` (один bulk-SELECT).
- **PyJWT 2.8.0** теперь в Docker image (раньше отсутствовал, /api/security JWT endpoints крашились с `ModuleNotFoundError`).

### Frontend

- **P1 fix** `pages/UserbotPage.tsx`: убран polling несуществующего `/process-status`, используется `getReceiptStatus`. Добавлен `effectiveProcessedIds`/`effectiveFailedIds` мердж локального set и server-payload `processed`.
- **P2 fixes** `hooks/useInlineEdit.ts`:
  - правильные query keys (`'transactions-server*'` вместо `'transactions'`)
  - `onMutate` + `setQueriesData` оптимистичное обновление + rollback в `onError`
  - `formatLocalIso()` вместо `.toISOString()` — больше не сдвигает дату на 5 часов (UTC vs Asia/Tashkent)
  - `error.response.data.detail` в toast вместо `error.message`
- **P3 indicator** `components/telegram/ChatListItem.tsx`: `Radio` иконка для `is_monitored && monitor_enabled` (зелёная, пульсация) / `is_monitored && !monitor_enabled` (приглушённая).
- **AI agent ui_action consumer**:
  - `contexts/AiAgentContext.tsx` — `pendingUiAction` + `dispatchUiAction` + `consumeUiAction` (one-shot)
  - `components/AiAgentMessage.tsx` — extract + dispatch `content.ui_action`, `nop` muted
  - `App.tsx` — `AgentUiActionRouter` для `navigate_view`
  - `pages/TransactionsPage.tsx` — consumer effect для `apply_filters`/`clear_filters`/`mark_rows`/`scroll_to_row`/`open_details`/`export`
- **App.tsx** — переключён на `AppShell` + rightSlot (вместо устаревшего `<header>` + BurgerMenu).
- **`framer-motion` → `motion@12`**: 22 импорта переехали на `motion/react`.
- **Phase 1-7 миграции sandbox→frontend завершена**: motion/, shell/, telegram/, AiAgent v5, все CSS, новые pages.

### Designer changes (накоплены параллельно)

- Logs page редизайн: editorial DNA, фильтры, expandable rows
- Toast переписан: монохром + semantic accent
- MUI dark theme: исправлены невидимые элементы в Pickers/Calendar/Tooltip
- FAB AI agent: убран бессмысленный glow

### Known deferred (для следующего прохода)

- P2 B3 concurrency control (version column на `transactions`)
- P2 B5 Pydantic `extra=forbid` для `TransactionUpdateRequest`
- P2 B8 paste failed_ids reconcile
- P2 B10 card_last_4 clearing (regex blocks empty)
- P3 localStorage state ботов + сверка `last_message_id`

---

## 1.4.7 — 2026-05-24

- text-shadowing fix в models.py
- bump backend default version
- electron release v1.4.7

## 1.4.6 — 2026-05-21

- предыдущий public release (на момент аудита)
