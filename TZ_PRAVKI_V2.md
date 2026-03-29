# ТЕХНИЧЕСКОЕ ЗАДАНИЕ — PARCER 2.0: БЛОК ПРАВОК V2

**Дата:** 2026-02-13
**Проект:** TBSparcer (Parcer 2.0)
**Стек:** FastAPI + PostgreSQL + Redis + Celery (бэкенд, сервер) | React + Electron + Dexie (фронт, локально)
**Архитектура:** Фронтенд локально на ПК пользователя (Electron), бэкенд на удалённом сервере (Docker)

---

## ОГЛАВЛЕНИЕ

1. [БЛОК 1 — Полная локальная синхронизация БД](#блок-1--полная-локальная-синхронизация-бд)
2. [БЛОК 2 — Исправление скрытия чатов в TG-клиенте](#блок-2--исправление-скрытия-чатов-в-tg-клиенте)
3. [БЛОК 3 — Telegram-бот аутентификатор + пароли на чаты](#блок-3--telegram-бот-аутентификатор--пароли-на-чаты)
4. [БЛОК 4 — Управление доступом: пароль запуска + блокировка периодов](#блок-4--управление-доступом-пароль-запуска--блокировка-периодов)
5. [ОБЩИЕ ТРЕБОВАНИЯ](#общие-требования)
6. [КАРТА ЗАТРАГИВАЕМЫХ ФАЙЛОВ](#карта-затрагиваемых-файлов)
7. [ПОРЯДОК РЕАЛИЗАЦИИ](#порядок-реализации)

---

## БЛОК 1 — Полная локальная синхронизация БД

### 1.1 Текущее состояние

Сейчас на фронтенде используется Dexie (IndexedDB) для кэширования транзакций. Реализация находится в:
- `frontend/src/storage/db.ts` — схема Dexie, одна таблица `transactions` + `meta`
- `frontend/src/hooks/useOfflineTransactions.ts` — логика синхронизации: подкачка страницами по 1000 штук, upsert по id, хранение `lastSyncAt`

Проблема: синхронизируются **только транзакции**. Справочники, маппинги операторов, логи парсинга, скоупы, настройки мониторинга, скрытые чаты — всё остаётся только на сервере. При потере связи с сервером фронт работает в крайне ограниченном режиме.

### 1.2 Целевое состояние

Полная зеркальная копия серверной PostgreSQL-базы в локальном хранилище (Dexie/IndexedDB). Все таблицы. При каждом подключении к серверу — инкрементальная синхронизация «сервер → локальная БД». Сервер — единственный источник правды (master). Локальная копия — read-only реплика.

### 1.3 Требования

#### 1.3.1 Расширение Dexie-схемы

Добавить в `frontend/src/storage/db.ts` все таблицы серверной БД:

| Таблица (Dexie) | Модель (SQLAlchemy) | Ключевые индексы |
|---|---|---|
| `transactions` | Transaction | id, transaction_date, currency, card_last_4, application_mapped |
| `operatorMappings` | OperatorMapping | id, operator_pattern, priority |
| `operatorReferences` | OperatorReference | id, operator_name, application_name |
| `monitoredBotChats` | MonitoredBotChat | chat_id, enabled |
| `hiddenBotChats` | HiddenBotChat | chat_id |
| `parsingLogs` | ParsingLog | id, transaction_id, created_at |
| `hourlyReports` | HourlyReport | id, report_hour |
| `accessScopes` | AccessScope | id, name, is_active |
| `accessAuditLog` | AccessAuditLog | id, created_at |
| `receiptProcessingTasks` | ReceiptProcessingTask | id, status |
| `syncMeta` | — (новая) | table_name, last_sync_at, last_server_id, checksum |

Версионирование Dexie-схемы: увеличить до version(2) с миграцией.

#### 1.3.2 Бэкенд: API инкрементальной синхронизации

Новый роутер: `backend/api/routes/sync.py`

**Эндпоинт:** `GET /api/sync/{table_name}`

Параметры:
- `since` (datetime, optional) — дата последней синхронизации. Если не указана — полная выгрузка.
- `since_id` (int, optional) — id последней полученной записи (для таблиц с auto-increment).
- `limit` (int, default=5000) — размер страницы.
- `offset` (int, default=0) — смещение.

Ответ:
```json
{
  "table": "transactions",
  "rows": [...],
  "total_count": 150000,
  "has_more": true,
  "server_checksum": "sha256:...",
  "server_time": "2026-02-13T12:00:00Z",
  "deleted_ids": [123, 456]
}
```

Поле `deleted_ids` — список id записей, удалённых на сервере с момента `since`. Для этого:

**Новая таблица на сервере: `sync_deletions`**
```python
class SyncDeletion(Base):
    __tablename__ = "sync_deletions"
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    table_name = Column(String(100), nullable=False, index=True)
    record_id = Column(BigInteger, nullable=False)
    deleted_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
```

При удалении записи из любой таблицы — добавлять запись в `sync_deletions`. Реализовать через SQLAlchemy event listener `after_delete` или явно в сервисных методах.

**Эндпоинт:** `GET /api/sync/manifest`

Возвращает метаданные для всех таблиц:
```json
{
  "tables": {
    "transactions": { "row_count": 150000, "last_updated": "...", "checksum": "..." },
    "operatorMappings": { "row_count": 234, "last_updated": "...", "checksum": "..." },
    ...
  },
  "server_time": "2026-02-13T12:00:00Z"
}
```

Чексумма: SHA256 от конкатенации `id:updated_at` последних 100 записей. Используется клиентом для определения, нужна ли синхронизация.

#### 1.3.3 Фронтенд: менеджер синхронизации

Новый сервис: `frontend/src/services/syncManager.ts`

Логика:
1. При запуске приложения — запросить `/api/sync/manifest`.
2. Сравнить с локальными чексуммами в таблице `syncMeta`.
3. Для каждой рассинхронизированной таблицы — запустить инкрементальную подкачку.
4. Порядок синхронизации (по приоритету): `accessScopes` → `operatorMappings` → `operatorReferences` → `transactions` → остальные.
5. Транзакции качать страницами по 5000, остальные таблицы — одним запросом (они маленькие).
6. Удаления: применить `deleted_ids` из ответа — удалить из локальной Dexie.
7. После завершения — обновить `syncMeta` для таблицы.

Фоновый режим:
- Интервал: каждые 5 минут (настраиваемо).
- При ошибке: экспоненциальный backoff (5 мин → 10 мин → 20 мин → 30 мин макс).
- Статус синхронизации: отображать в UI (иконка + тултип: «Синхронизировано 2 минуты назад» / «Синхронизация...» / «Ошибка синхронизации»).

Конфликт-резолюция: **сервер всегда побеждает**. Локальная БД — read-only копия. Никаких локальных изменений данных (кроме UI-состояний типа "выделенные строки").

#### 1.3.4 Отображение статуса в UI

В хедере приложения (или в сайдбаре) добавить индикатор:
- Зелёная точка + «Синхронизировано» — всё актуально
- Синяя точка + спиннер + «Синхронизация...» — идёт процесс
- Жёлтая точка + «Отстаёт на N записей» — частично синхронизировано
- Красная точка + «Нет связи с сервером» — оффлайн

При клике — дропдаун с деталями по каждой таблице (количество записей, время последней синхронизации).

#### 1.3.5 Офлайн-режим

Когда сервер недоступен, приложение переключается в режим чтения из локальной Dexie:
- Просмотр транзакций — да (из локальной копии)
- Фильтрация, сортировка, поиск — да (Dexie-запросы)
- Экспорт в Excel — да (из локальных данных, с пометкой «данные на момент последней синхронизации»)
- Парсинг новых чеков — нет (требует бэкенд)
- Редактирование маппингов — нет (read-only)
- Работа с TG-клиентом — нет (требует TDLib на сервере)

Индикатор: баннер вверху экрана «Автономный режим — данные на [дата последней синхронизации]»

---

## БЛОК 2 — Исправление скрытия чатов в TG-клиенте

### 2.1 Текущее состояние

Скрытие чатов реализовано в:
- Бэкенд: `telegram_tdlib_manager.py` → методы `hide_chat()`, `unhide_chat()`, фильтрация в `list_chats()`
- Фронт: `UserbotPage.tsx` → state `showHidden`, toggle иконки Eye/EyeOff
- БД: таблица `hidden_bot_chats` (chat_id PK, title_snapshot, hidden_at)

Баг: при выборе чата и его скрытии, другие чаты могут «вылезти» — вероятная причина: при скрытии текущего выбранного чата UI не сбрасывает выбор, и рендер списка ломается (индекс выбранного чата указывает на несуществующую позицию).

### 2.2 Требования

#### 2.2.1 Бэкенд: гарантированная фильтрация

В `telegram_tdlib_manager.py` → `list_chats()`:
- Параметр `include_hidden` должен строго по умолчанию быть `False`.
- Кэш `hidden_ids` загружать **до** начала итерации по чатам, не лениво.
- Если `include_hidden=False` — **ни один** скрытый чат не должен попасть в ответ, даже если он был загружен из TDLib-кэша до проверки.
- Добавить unit-тест: скрыть N чатов → запросить список без `include_hidden` → assert ни один из скрытых не в результате.

В роутере `telegram_client.py`:
- Эндпоинт `GET /api/tg/chats`:
  - query-параметр `include_hidden` типа `bool`, default=`False`
  - Не принимать его из тела запроса, только из query string
- Эндпоинт `PUT /api/tg/chats/{chat_id}/hidden`:
  - Тело: `{ "hidden": true/false }`
  - Ответ: `{ "chat_id": ..., "hidden": true/false, "updated_at": "..." }`

#### 2.2.2 Фронтенд: корректное UI-состояние

В `UserbotPage.tsx`:

1. **При скрытии текущего выбранного чата:**
   - Сбросить `selectedChat` на `null`
   - Очистить панель сообщений (показать плейсхолдер «Выберите чат»)
   - Анимация: чат плавно уходит из списка (opacity transition 300ms)

2. **Список чатов:**
   - Если `showHidden=false` — фильтровать НА КЛИЕНТЕ дополнительно (двойная проверка: сервер + клиент)
   - При переключении `showHidden` — не менять `selectedChat`, если выбранный чат виден в новом списке
   - Если выбранный чат стал невидим — сбросить на `null`

3. **Оптимистичные обновления:**
   - При нажатии «скрыть» — **немедленно** убрать чат из списка, не дожидаясь ответа сервера
   - При ошибке сервера — откатить: вернуть чат на место + toast «Не удалось скрыть чат»
   - React Query: `useMutation` с `onMutate` (optimistic), `onError` (rollback), `onSettled` (refetch)

4. **Счётчик скрытых:**
   - В хедере списка чатов: «Чаты (145)» или «Чаты (145, скрыто: 12)»
   - Кнопка «Показать скрытые» — toggle, не отдельная страница

#### 2.2.3 Edge-кейсы

- Скрыть все чаты → список пуст → показать «Все чаты скрыты. Нажмите 👁 чтобы показать»
- Скрыть чат, который мониторится (MonitoredBotChat) → **мониторинг продолжает работать**, скрытие — только UI
- Повторный вызов hide для уже скрытого чата → идемпотентная операция, без ошибки
- Чат удалён в Telegram → при следующем list_chats он не вернётся → из hidden_bot_chats НЕ чистить (garbage collection отдельной задачей, не критично)

---

## БЛОК 3 — Telegram-бот аутентификатор + пароли на чаты

### 3.1 Концепция

Создаётся отдельный Telegram-бот-аутентификатор (далее «AuthBot»). Вся система паролей на папки/скоупы **заменяется** на OTP-коды через этого бота. При каждом запросе доступа бот отправляет 6-значный код на заранее настроенные Telegram ID.

Дополнительно: в нашем TG-клиенте (TDLib на фронте) — возможность поставить пароль на конкретный чат. При попытке открыть защищённый чат — обязательный запрос пароля.

### 3.2 AuthBot: бэкенд

#### 3.2.1 Новый сервис: `backend/services/auth_bot_service.py`

**Бот создаётся через @BotFather, отдельный от существующего receipt-бота.**

Конфигурация (`.env`):
```
AUTH_BOT_TOKEN=bot_token_from_botfather
AUTH_ADMIN_IDS=123456789,987654321
AUTH_CODE_TTL_SECONDS=120
AUTH_CODE_LENGTH=6
AUTH_MAX_ATTEMPTS=3
```

- `AUTH_ADMIN_IDS` — Telegram user ID, которым отправляются коды и которые могут управлять ботом.
- Код живёт 120 секунд (настраиваемо).
- Максимум 3 попытки ввода одного кода. После 3 ошибок — код сгорает, нужно запрашивать новый.

#### 3.2.2 Генерация OTP-кодов

```python
class OTPManager:
    """Хранение кодов в Redis (не в БД — они временные)."""

    async def generate_code(self, purpose: str, context: dict) -> str:
        """
        purpose: "scope_access" | "app_launch" | "period_unlock"
        context: {"scope_id": 2025, "requester_ip": "..."}

        Returns: 6-значный код
        """
        code = secrets.token_hex(3)[:6].upper()  # криптостойкий
        # Если нужны только цифры:
        code = ''.join([str(secrets.randbelow(10)) for _ in range(6)])

        key = f"otp:{purpose}:{code}"
        await redis.setex(key, AUTH_CODE_TTL_SECONDS, json.dumps({
            "code": code,
            "purpose": purpose,
            "context": context,
            "attempts": 0,
            "created_at": datetime.utcnow().isoformat()
        }))
        return code

    async def verify_code(self, purpose: str, input_code: str) -> tuple[bool, dict]:
        """Возвращает (success, context)"""
        key = f"otp:{purpose}:{input_code}"
        data = await redis.get(key)
        if not data:
            return False, {}

        data = json.loads(data)
        data["attempts"] += 1

        if data["attempts"] >= AUTH_MAX_ATTEMPTS:
            await redis.delete(key)
            return False, {"error": "max_attempts"}

        if data["code"] == input_code:
            await redis.delete(key)  # одноразовый
            return True, data["context"]

        await redis.setex(key, AUTH_CODE_TTL_SECONDS, json.dumps(data))
        return False, {"attempts_left": AUTH_MAX_ATTEMPTS - data["attempts"]}
```

#### 3.2.3 Telegram-бот: команды и обработчики

Фреймворк: **Aiogram 3** (уже используется в проекте).

Файл: `backend/services/auth_bot_handler.py`

Команды бота (доступны только `AUTH_ADMIN_IDS`):

| Команда | Действие |
|---|---|
| `/start` | Приветствие + инструкция |
| `/status` | Текущий статус: активные сессии, ожидающие коды |
| `/set_launch_password <password>` | Установить/сменить пароль запуска программы |
| `/lock_period <start> <end>` | Заблокировать период (формат: YYYY-MM-DD) |
| `/unlock_period <start> <end>` | Разблокировать период |
| `/list_periods` | Показать все заблокированные периоды |
| `/list_scopes` | Показать все скоупы и их статус |
| `/toggle_scope <id>` | Включить/выключить скоуп |
| `/set_chat_password <chat_id> <password>` | Установить пароль на чат в TG-клиенте |
| `/remove_chat_password <chat_id>` | Убрать пароль с чата |
| `/list_chat_passwords` | Показать защищённые чаты |
| `/sessions` | Активные сессии (кто залогинен, откуда) |
| `/kill_session <session_id>` | Принудительно завершить сессию |

Уведомления (отправляются всем `AUTH_ADMIN_IDS`):

| Событие | Текст уведомления |
|---|---|
| Запрос кода доступа к скоупу | `🔐 Запрос доступа к "Папка 2025"\nIP: 192.168.1.5\nКод: 847291\nДействует 2 минуты` |
| Запрос кода запуска приложения | `🚀 Запрос запуска приложения\nIP: 192.168.1.5\nКод: 193847\nДействует 2 минуты` |
| Запрос разблокировки периода | `📅 Запрос доступа к периоду 2025-01-01 — 2025-06-30\nIP: 192.168.1.5\nКод: 582910\nДействует 2 минуты` |
| Неудачная попытка ввода кода | `⚠️ Неверный код! Попытка 2/3\nIP: 192.168.1.5\nЦель: "Папка 2025"` |
| Код истёк | `⏰ Код 847291 истёк (не использован)\nЦель: "Папка 2025"` |
| Успешный вход | `✅ Доступ предоставлен: "Папка 2025"\nIP: 192.168.1.5` |

#### 3.2.4 Безопасность AuthBot

1. **Проверка `user_id`** — каждое сообщение боту проверяется: `message.from_user.id in AUTH_ADMIN_IDS`. Если нет — бот молча игнорирует (не отвечает вообще).
2. **Нет публичных команд** — бот не отвечает никому, кроме администраторов.
3. **Rate limiting** — максимум 10 запросов кодов в минуту (Redis counter). При превышении — блокировка на 5 минут + уведомление.
4. **Аудит** — все действия логируются в `AccessAuditLog`: кто запросил код, какой purpose, IP, результат.
5. **Код криптостойкий** — `secrets.randbelow()`, не `random.randint()`.
6. **Одноразовость** — код удаляется из Redis после успешной проверки. Повторное использование невозможно.
7. **TTL жёсткий** — Redis автоматически удаляет ключ через `AUTH_CODE_TTL_SECONDS`. Не полагаемся на проверку в коде.
8. **Нет inline-кнопок «Подтвердить»** — только ручной ввод кода. Кнопки можно перехватить.

### 3.3 Замена паролей скоупов на OTP

#### 3.3.1 Изменения в `access_control_service.py`

Текущая логика: пользователь вводит пароль → `verify_password()` → если ok → `create_scope_token()` (JWT 12 часов).

Новая логика:
1. Пользователь нажимает «Открыть папку» → фронт вызывает `POST /api/security/scope/{scope_id}/request-code`
2. Бэкенд генерирует OTP через `OTPManager`, отправляет через AuthBot всем `AUTH_ADMIN_IDS`
3. Фронт показывает поле ввода 6-значного кода + таймер 120 секунд
4. Пользователь вводит код → фронт вызывает `POST /api/security/scope/{scope_id}/verify-code`
5. Бэкенд проверяет OTP → если ok → `create_scope_token()` (JWT, как раньше)
6. Токен кэшируется на клиенте (как сейчас в `api.ts`)

**Новые эндпоинты в `backend/api/routes/security.py`:**

```
POST /api/security/scope/{scope_id}/request-code
  Body: {} (пустое, context берётся из request.client.host)
  Response: { "status": "code_sent", "expires_in": 120, "code_length": 6 }

POST /api/security/scope/{scope_id}/verify-code
  Body: { "code": "847291" }
  Response: { "token": "jwt...", "scope": {...}, "expires_at": "..." }
  Errors:
    401 { "error": "invalid_code", "attempts_left": 2 }
    429 { "error": "code_expired" }
    423 { "error": "locked", "locked_until": "..." }
```

#### 3.3.2 Удаление старых паролей

- Из `root-access.server.json` → убрать поля `password` из секции `scopes`.
- Из таблицы `access_scopes` → поля `password_hash`, `salt` можно оставить (для обратной совместимости), но не использовать.
- Миграция Alembic: добавить колонку `auth_method` в `access_scopes` (enum: `password` | `otp`), default=`otp`.
- Старый эндпоинт `POST /api/security/scope/{scope_id}/unlock` — пометить как deprecated, оставить рабочим на переходный период.

### 3.4 Пароли на чаты в TG-клиенте (TDLib)

#### 3.4.1 Новая таблица: `chat_passwords`

```python
class ChatPassword(Base):
    __tablename__ = "chat_passwords"

    chat_id = Column(BigInteger, primary_key=True)
    password_hash = Column(String(512), nullable=False)
    salt = Column(String(128), nullable=False)
    hash_method = Column(String(50), default="pbkdf2_sha256")
    failed_attempts = Column(Integer, default=0)
    locked_until = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
```

Хеширование: PBKDF2-SHA256, 200k итераций (как в `access_control_service.py`).
Блокировка: 5 неудачных попыток → блокировка на 15 минут.

#### 3.4.2 Бэкенд: API паролей на чаты

В роутере `telegram_client.py`:

```
POST /api/tg/chats/{chat_id}/password
  Body: { "password": "mypassword123" }
  Response: { "chat_id": ..., "protected": true }
  Действие: Хешировать пароль, сохранить в chat_passwords

DELETE /api/tg/chats/{chat_id}/password
  Response: { "chat_id": ..., "protected": false }
  Действие: Удалить запись из chat_passwords
  Защита: Требует текущий пароль в теле { "password": "current" }

POST /api/tg/chats/{chat_id}/password/verify
  Body: { "password": "mypassword123" }
  Response:
    200 { "verified": true, "session_token": "temp_jwt...", "expires_in": 3600 }
    401 { "verified": false, "attempts_left": 3 }
    423 { "locked": true, "locked_until": "..." }

GET /api/tg/chats/{chat_id}/password/status
  Response: { "protected": true|false, "locked": false }
```

**Сессионный токен чата:**
После успешной верификации пароля выдаётся временный JWT (1 час). Фронтенд прикрепляет его к последующим запросам к этому чату в заголовке `X-Chat-Access: <token>`. Бэкенд проверяет этот токен при каждом запросе к защищённому чату (сообщения, документы, отправка).

#### 3.4.3 Бэкенд: защита эндпоинтов чатов

В `telegram_client.py` — middleware-проверка для всех эндпоинтов конкретного чата:

```python
async def require_chat_access(chat_id: int, request: Request, db: Session):
    """Dependency: проверяет, что чат не защищён паролем,
    или что предоставлен валидный X-Chat-Access токен."""
    chat_pwd = db.get(ChatPassword, chat_id)
    if not chat_pwd:
        return  # чат не защищён, доступ свободный

    token = request.headers.get("X-Chat-Access")
    if not token:
        raise HTTPException(403, detail={"error": "chat_locked", "chat_id": chat_id})

    payload = decode_chat_token(token)
    if not payload or payload.get("chat_id") != chat_id:
        raise HTTPException(403, detail={"error": "chat_locked", "chat_id": chat_id})
```

Эндпоинты, требующие `require_chat_access`:
- `GET /api/tg/chats/{chat_id}/messages`
- `POST /api/tg/chats/{chat_id}/send`
- `GET /api/tg/chats/{chat_id}/documents`
- `GET /api/tg/chats/{chat_id}/documents/{doc_id}`

НЕ требуют (информация о чате доступна всем):
- `GET /api/tg/chats` — список чатов (но protected-чаты отмечены иконкой замка)
- `GET /api/tg/chats/{chat_id}` — метаданные чата (название, тип), без сообщений
- `POST /api/tg/chats/{chat_id}/password/verify` — собственно верификация

#### 3.4.4 Фронтенд: UI защиты чатов

В `UserbotPage.tsx`:

1. **Список чатов:**
   - Защищённые чаты отмечены иконкой 🔒 рядом с названием
   - При клике на защищённый чат — открывается модальное окно ввода пароля
   - Поле пароля (type=password) + кнопка «Войти»
   - При ошибке — shake-анимация + текст «Неверный пароль (осталось N попыток)»
   - При блокировке — таймер обратного отсчёта «Заблокировано на NN:NN»
   - После успешного ввода — токен сохраняется в React state (НЕ в localStorage — при перезагрузке нужно вводить заново)

2. **Контекстное меню чата (правый клик или three-dot menu):**
   - «Установить пароль» — для незащищённых чатов
   - «Сменить пароль» — для защищённых (требует ввод текущего пароля)
   - «Снять пароль» — для защищённых (требует ввод текущего пароля)

3. **Управление через AuthBot:**
   - Альтернативный способ: админ отправляет `/set_chat_password <chat_id> <password>` боту
   - Бот → бэкенд API → `ChatPassword` таблица
   - `/remove_chat_password <chat_id>` — снятие без ввода текущего пароля (привилегированная операция)

#### 3.4.5 Edge-кейсы паролей на чаты

- Установить пароль на чат, который уже скрыт → ОК, пароль применяется. При показе скрытых — чат виден, но залочен.
- Забыли пароль → снять через бота командой `/remove_chat_password`. Других способов нет.
- Мониторинг защищённого чата → **продолжает работать**. Пароль — только для UI-доступа к сообщениям. Автоматический парсинг чеков не блокируется.
- Сессионный токен истёк (1 час) → при следующем действии с чатом — снова запрос пароля.

---

## БЛОК 4 — Управление доступом: пароль запуска + блокировка периодов

### 4.1 Пароль на запуск приложения

#### 4.1.1 Концепция

При каждом запуске Electron-приложения — экран ввода пароля. Пароль задаётся и меняется **только через AuthBot** командой `/set_launch_password`.

#### 4.1.2 Бэкенд: хранение и проверка

Новая таблица (или секция в `root-access.server.json`):

```python
class AppLaunchConfig(Base):
    __tablename__ = "app_launch_config"

    id = Column(Integer, primary_key=True, default=1)  # всегда одна запись
    password_hash = Column(String(512), nullable=False)
    salt = Column(String(128), nullable=False)
    hash_method = Column(String(50), default="pbkdf2_sha256")
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    updated_by_tg_id = Column(BigInteger)  # кто менял через бота
```

Эндпоинты:

```
POST /api/security/app/verify-launch
  Body: { "password": "..." }
  Response:
    200 { "verified": true, "session_token": "jwt...", "expires_at": "..." }
    401 { "verified": false, "attempts_left": N }
    423 { "locked": true, "locked_until": "..." }

GET /api/security/app/launch-status
  Response: { "password_set": true|false, "locked": false }
```

Блокировка: 5 неудачных попыток → 30 минут блокировки (жёстче, чем для чатов — это входная дверь).

**Смена пароля через бота:**
Команда `/set_launch_password новый_пароль` → бот вызывает внутренний API `POST /api/internal/app/set-launch-password` с заголовком `X-Internal-API-Key` → хеширование → сохранение в БД.

#### 4.1.3 Фронтенд: экран входа

В Electron-приложении — **ДО** основного интерфейса показывается экран входа:

Файл: `frontend/src/pages/LaunchGate.tsx`

UI:
- Полноэкранный минимальный UI (тёмный фон, по центру — логотип + поле пароля)
- Поле пароля (type=password, autofocus)
- Кнопка «Войти» или Enter
- При ошибке: shake-анимация, текст «Неверный пароль (попыток осталось: N)»
- При блокировке: поле неактивно, таймер обратного отсчёта
- **Нет кнопки «Забыл пароль»** — сброс только через бота

Логика:
- При старте приложения → `GET /api/security/app/launch-status`
- Если `password_set=false` → пропускаем экран входа (пароль ещё не задан через бота)
- Если `password_set=true` → показываем LaunchGate
- После успешного ввода → получаем `session_token` → сохраняем в памяти (не localStorage!) → переходим к основному интерфейсу
- Этот `session_token` прикрепляется ко всем последующим API-запросам в заголовке `X-Launch-Session`
- TTL сессии: 24 часа. По истечении — снова экран входа.

#### 4.1.4 Бэкенд: middleware проверки launch-сессии

Новый middleware (или dependency):

```python
async def require_launch_session(request: Request):
    """Проверяет, что приложение авторизовано для запуска."""
    config = get_app_launch_config()
    if not config or not config.password_hash:
        return  # пароль не задан, пропускаем

    token = request.headers.get("X-Launch-Session")
    if not token:
        raise HTTPException(403, detail={"error": "launch_required"})

    payload = verify_launch_token(token)
    if not payload:
        raise HTTPException(403, detail={"error": "launch_expired"})
```

Применяется ко ВСЕМ эндпоинтам `/api/*`, кроме:
- `POST /api/security/app/verify-launch`
- `GET /api/security/app/launch-status`
- Healthcheck эндпоинты

### 4.2 Блокировка периодов

#### 4.2.1 Концепция

Владелец (через AuthBot) может заблокировать любой произвольный период дат. Заблокированный период недоступен ВООБЩЕ НИКОМУ — ни владельцу, ни кому-либо ещё. Разблокировка — только через бота.

Блокируются ВСЕ действия с данными за этот период: просмотр, фильтрация, анализ, обработка, экспорт в Excel.

#### 4.2.2 Новая таблица: `locked_periods`

```python
class LockedPeriod(Base):
    __tablename__ = "locked_periods"

    id = Column(Integer, primary_key=True, autoincrement=True)
    date_from = Column(Date, nullable=False)
    date_to = Column(Date, nullable=False)
    reason = Column(String(500), nullable=True)
    locked_by_tg_id = Column(BigInteger, nullable=False)
    locked_at = Column(DateTime(timezone=True), server_default=func.now())
    is_active = Column(Boolean, default=True, index=True)

    __table_args__ = (
        CheckConstraint('date_from <= date_to', name='check_period_valid'),
    )
```

#### 4.2.3 Бэкенд: фильтрация по заблокированным периодам

Новый сервис: `backend/services/period_lock_service.py`

```python
class PeriodLockService:
    def get_active_locks(self, db: Session) -> list[LockedPeriod]:
        """Все активные блокировки."""
        return db.query(LockedPeriod).filter(LockedPeriod.is_active == True).all()

    def is_date_locked(self, date: datetime.date, db: Session) -> bool:
        """Проверяет, попадает ли дата в заблокированный период."""
        return db.query(LockedPeriod).filter(
            LockedPeriod.is_active == True,
            LockedPeriod.date_from <= date,
            LockedPeriod.date_to >= date
        ).first() is not None

    def filter_locked_range(self, start: date, end: date, db: Session) -> list[tuple[date, date]]:
        """Возвращает список РАЗРЕШЁННЫХ подпериодов внутри запрошенного диапазона.
        Пример: запрос [Jan 1 — Dec 31], заблокировано [Mar 1 — Jun 30]
        → вернёт [(Jan 1, Feb 28), (Jul 1, Dec 31)]
        """
        ...

    def lock_period(self, date_from: date, date_to: date, tg_id: int, reason: str, db: Session) -> LockedPeriod:
        """Создать блокировку. Может перекрываться с существующими."""
        ...

    def unlock_period(self, lock_id: int, db: Session) -> bool:
        """Деактивировать блокировку (is_active=False)."""
        ...
```

#### 4.2.4 Интеграция в существующие роуты

**В `backend/api/routes/transactions.py`:**

Все эндпоинты, возвращающие транзакции:
1. `GET /api/transactions` — пагинация
2. `GET /api/transactions/export` — если есть
3. Любые агрегации / аналитика

Логика:
```python
@router.get("/transactions")
async def list_transactions(
    date_from: date,
    date_to: date,
    ...,
    db: Session = Depends(get_db),
    scope = Depends(require_transactions_scope)
):
    # 1. Clamp по скоупу (как сейчас)
    effective_from, effective_to, is_disjoint = clamp_requested_range(scope, date_from, date_to)

    # 2. NEW: Вычесть заблокированные периоды
    allowed_ranges = period_lock_service.filter_locked_range(effective_from, effective_to, db)

    if not allowed_ranges:
        return {"items": [], "total": 0, "locked_notice": "Запрошенный период полностью заблокирован"}

    # 3. Запрос с фильтром по разрешённым подпериодам
    query = build_query_for_ranges(allowed_ranges, ...)
    ...
```

#### 4.2.5 Блокировка экспорта в Excel

**Критическая доработка.** Сейчас экспорт целиком на фронтенде (`excelExport.ts`) — берёт данные из React-стейта и формирует XLSX.

Проблема: если транзакции УЖЕ загружены в UI (или в локальную Dexie), пользователь может экспортировать заблокированный период из кэша.

Решение — **двухуровневая защита:**

**Уровень 1 (бэкенд):** Транзакции за заблокированный период **не отдаются** API. Если фронт запрашивает данные — получает только разрешённые. Это уже покрывается п. 4.2.4.

**Уровень 2 (фронтенд):**
- При экспорте → перед формированием файла → запросить `GET /api/security/locked-periods`
- Отфильтровать из выгрузки все транзакции, попадающие в заблокированные периоды
- Если ВСЕ данные заблокированы — показать ошибку «Экспорт невозможен: период заблокирован»
- В экспортированный файл НЕ включать заблокированные строки

**Уровень 3 (локальная БД Dexie):**
- При синхронизации — НЕ синхронизировать транзакции из заблокированных периодов
- При запросе `/api/sync/transactions` бэкенд применяет те же фильтры
- Если период был заблокирован ПОСЛЕ синхронизации — при следующей синхронизации фронт получает `deleted_ids` для записей попавших в блокировку и удаляет их из Dexie

#### 4.2.6 Эндпоинты управления периодами

```
GET /api/security/locked-periods
  Response: { "periods": [{ "id": 1, "date_from": "2025-01-01", "date_to": "2025-06-30", "reason": "...", "locked_at": "..." }] }

POST /api/security/locked-periods  (только через internal API / AuthBot)
  Body: { "date_from": "2025-01-01", "date_to": "2025-06-30", "reason": "аудит" }
  Headers: X-Internal-API-Key: ...
  Response: { "id": 1, "status": "locked" }

DELETE /api/security/locked-periods/{id}  (только через internal API / AuthBot)
  Headers: X-Internal-API-Key: ...
  Response: { "id": 1, "status": "unlocked" }
```

Прямого доступа через UI к управлению блокировками НЕТ. Только AuthBot.

#### 4.2.7 Фронтенд: отображение блокировок

- В таблице транзакций: если запрошенный период частично заблокирован — баннер сверху: «Период [дата — дата] заблокирован. Показаны данные за доступные периоды.»
- В фильтрах: заблокированные даты визуально отмечены (красная штриховка в date-picker)
- Кнопка экспорта: если ВСЕ видимые данные заблокированы — кнопка неактивна + тултип «Экспорт недоступен: период заблокирован»

---

## ОБЩИЕ ТРЕБОВАНИЯ

### Безопасность

1. Все пароли хешируются PBKDF2-SHA256 (200k итераций) или Argon2id.
2. Все OTP-коды генерируются через `secrets` (криптостойкий ГПСЧ).
3. Все временные токены (OTP, chat-session, launch-session) хранятся в Redis с жёстким TTL.
4. Все действия логируются в `AccessAuditLog`.
5. Rate limiting: 100 req/min на IP (существующий middleware).
6. Lockout: 5 неудачных попыток → блокировка (настраиваемая длительность).
7. Transmission: все данные между фронтом и бэкендом — HTTPS.
8. AuthBot: проверка `user_id` в каждом хендлере, игнорирование неизвестных пользователей.
9. Internal API: `X-Internal-API-Key` для бот → бэкенд коммуникации.

### Миграции БД (Alembic)

Новые таблицы:
- `sync_deletions`
- `chat_passwords`
- `app_launch_config`
- `locked_periods`

Изменения существующих:
- `access_scopes` — добавить колонку `auth_method` (enum: password|otp, default: otp)

### Docker

Новый сервис в `docker-compose.yml`:
```yaml
auth_bot:
  build: .
  command: python -m backend.services.auth_bot_handler
  env_file: .env
  depends_on:
    - postgres
    - redis
  restart: unless-stopped
  mem_limit: 128m
```

### Переменные окружения (новые)

```env
# AuthBot
AUTH_BOT_TOKEN=...
AUTH_ADMIN_IDS=123456789,987654321
AUTH_CODE_TTL_SECONDS=120
AUTH_CODE_LENGTH=6
AUTH_MAX_ATTEMPTS=3

# Launch password
LAUNCH_LOCKOUT_MINUTES=30
LAUNCH_MAX_ATTEMPTS=5
LAUNCH_SESSION_TTL_HOURS=24

# Chat passwords
CHAT_PASSWORD_LOCKOUT_MINUTES=15
CHAT_PASSWORD_MAX_ATTEMPTS=5
CHAT_SESSION_TTL_HOURS=1

# Sync
SYNC_INTERVAL_MINUTES=5
SYNC_PAGE_SIZE=5000
```

---

## КАРТА ЗАТРАГИВАЕМЫХ ФАЙЛОВ

### Новые файлы

| Файл | Назначение |
|---|---|
| `backend/services/auth_bot_handler.py` | Aiogram-бот аутентификатор |
| `backend/services/auth_bot_service.py` | OTP-менеджер, Redis-хранение кодов |
| `backend/services/period_lock_service.py` | Управление блокировками периодов |
| `backend/api/routes/sync.py` | API синхронизации: manifest + incremental |
| `backend/database/models.py` → новые модели | SyncDeletion, ChatPassword, AppLaunchConfig, LockedPeriod |
| `frontend/src/services/syncManager.ts` | Менеджер полной синхронизации |
| `frontend/src/pages/LaunchGate.tsx` | Экран ввода пароля при запуске |
| `frontend/src/components/ChatPasswordModal.tsx` | Модальное окно ввода пароля чата |
| `frontend/src/components/SyncStatus.tsx` | Индикатор статуса синхронизации |
| `frontend/src/components/LockedPeriodBanner.tsx` | Баннер заблокированного периода |

### Изменяемые файлы

| Файл | Что меняется |
|---|---|
| `frontend/src/storage/db.ts` | Расширение Dexie-схемы (все таблицы), version(2) |
| `frontend/src/hooks/useOfflineTransactions.ts` | Интеграция с syncManager, fallback на локальные данные |
| `frontend/src/services/excelExport.ts` | Проверка locked periods перед экспортом |
| `frontend/src/services/api.ts` | Новые эндпоинты, заголовки X-Launch-Session и X-Chat-Access |
| `frontend/src/pages/UserbotPage.tsx` | Фикс скрытия чатов, UI паролей на чаты, иконки замков |
| `frontend/src/App.tsx` (или роутер) | Обёртка LaunchGate, SyncStatus в layout |
| `backend/services/telegram_tdlib_manager.py` | Проверка chat_passwords, фикс hidden-фильтрации |
| `backend/services/access_control_service.py` | OTP вместо паролей для скоупов |
| `backend/api/routes/security.py` | Новые эндпоинты: request-code, verify-code, locked-periods |
| `backend/api/routes/telegram_client.py` | Эндпоинты паролей на чаты, dependency require_chat_access |
| `backend/api/routes/transactions.py` | Фильтрация по locked periods |
| `backend/api/dependencies.py` | require_launch_session dependency |
| `backend/api/main.py` | Middleware launch-session |
| `docker-compose.yml` | Сервис auth_bot |
| `.env` / `.env.example` | Новые переменные |

---

## ПОРЯДОК РЕАЛИЗАЦИИ

### Фаза 1: Фундамент (не зависит от остального)
1. **Блок 2** — Фикс скрытия чатов. Быстрая правка, минимум зависимостей.
2. Миграции Alembic: создать все новые таблицы.

### Фаза 2: AuthBot + OTP-ядро
3. `auth_bot_service.py` — OTPManager (Redis).
4. `auth_bot_handler.py` — Telegram-бот, все команды.
5. Docker-сервис `auth_bot`.
6. Тестирование бота: отправка кодов, проверка, rate limiting.

### Фаза 3: Замена паролей на OTP
7. Новые эндпоинты в `security.py`: request-code, verify-code.
8. Фронтенд: UI ввода 6-значного кода вместо пароля.
9. Deprecation старого password-эндпоинта.

### Фаза 4: Пароль запуска + блокировка периодов
10. `AppLaunchConfig` + эндпоинты.
11. `LaunchGate.tsx` — экран входа в Electron.
12. `LockedPeriod` + `PeriodLockService` + эндпоинты.
13. Интеграция в `transactions.py` — фильтрация заблокированных периодов.
14. `excelExport.ts` — блокировка экспорта.
15. Команды бота: `/lock_period`, `/unlock_period`, `/set_launch_password`.

### Фаза 5: Пароли на чаты
16. `ChatPassword` таблица + эндпоинты.
17. `require_chat_access` dependency.
18. `ChatPasswordModal.tsx` — UI.
19. Контекстное меню чатов: установка/смена/снятие пароля.
20. Команды бота: `/set_chat_password`, `/remove_chat_password`.

### Фаза 6: Полная синхронизация БД
21. `SyncDeletion` таблица + event listeners.
22. `sync.py` роутер: manifest + incremental endpoints.
23. Расширение Dexie-схемы.
24. `syncManager.ts` — полный цикл синхронизации.
25. `SyncStatus.tsx` — индикатор в UI.
26. Интеграция locked periods в синхронизацию.

### Фаза 7: Тестирование и интеграция
27. E2E тесты: полный цикл от запуска до работы с данными.
28. Нагрузочное тестирование синхронизации (150k+ транзакций).
29. Тест отказоустойчивости: обрыв связи в процессе синхронизации.
30. Тест безопасности: попытки обхода блокировок, brute-force кодов.

---

**Конец документа.**
