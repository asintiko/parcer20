# АУДИТ РЕАЛИЗАЦИИ — PARCER 2.0 V2

**Дата аудита:** 2026-02-13
**Проверено:** 36 модифицированных файлов, 30+ новых файлов
**Метод:** Полное чтение каждого файла + сверка с ТЗ и планом реализации

---

## ОБЩИЙ ВЕРДИКТ

**Реализация на 92% соответствует плану.** Основная архитектура выполнена корректно. Обнаружены 2 критические проблемы, 1 серьёзный пробел в функционале, и несколько мелких отклонений.

---

## СВОДНАЯ ТАБЛИЦА ПО ФАЗАМ

| Фаза | Описание | Статус | Оценка |
|------|----------|--------|--------|
| 0 | Alembic инфраструктура | ⚠️ 2 бага в миграции | 90% |
| 1 | Скрытие чатов (Блок 2) | ✅ Полностью готово | 100% |
| 2 | AuthBot + OTP core | ❌ Стабы в хендлерах | 55% |
| 3 | OTP для скоупов (Hybrid) | ✅ Полностью готово | 100% |
| 4 | Пароль запуска + launch-session | ✅ Почти готово | 97% |
| 5 | Locked periods | ✅ Полностью готово | 100% |
| 6 | Пароли на чаты | ✅ Полностью готово | 100% |
| 7 | Sync PostgreSQL → Dexie | ✅ Полностью готово | 98% |
| 8 | Конфиги/compose/доки | ✅ Полностью готово | 100% |
| 9 | Тесты | ✅ Базовое покрытие | 85% |

---

## КРИТИЧЕСКИЕ ПРОБЛЕМЫ (БЛОКЕРЫ)

### КРИТ-1: AuthBot — стабы вместо реализации

**Файл:** `backend/services/auth_bot_handler.py`

**Суть:** Все команды бота существуют, но большинство — пустые стабы без реальной интеграции. Конкретно:

1. **Уведомления НЕ отправляются.** По ТЗ при запросе OTP-кода бот должен рассылать всем `AUTH_ADMIN_IDS` сообщения формата «🔐 Запрос доступа к "Папка 2025" / IP: ... / Код: ... / Действует 2 минуты». Этого нет.

2. **`/sessions` и `/kill_session`** — возвращают текст «пока недоступно». Сессионный реестр не подключён.

3. **Аудит-логирование** — ни одна команда бота не пишет в `AccessAuditLog`. Модель существует, но бот её не использует.

4. **Обработка ошибок** — все команды используют голый `SessionLocal()` без нормального cleanup. При ошибке БД — молчаливый сбой, администратор не узнает.

5. **Нет уведомлений другим админам** — когда один админ меняет пароль запуска или блокирует период, остальные `AUTH_ADMIN_IDS` не получают уведомления.

**Влияние:** AuthBot физически запустится, базовые команды (`/status`, `/list_periods`, `/list_scopes`, `/list_chat_passwords`) работают. Но ядро — OTP-рассылка — не функционирует. Без этого фаза 3 (OTP для скоупов) работает только через прямой API-вызов, но бот не уведомляет админов.

**Примечание:** `auth_bot_service.py` (OTPManager) — полностью рабочий. Redis-хранение, TTL, rate-limiting, криптостойкая генерация, `secrets.compare_digest()`. Проблема только в хендлере бота.

**Требуется:**
- Подключить OTPManager к обработчику `request-code` → при генерации кода → отправка всем `AUTH_ADMIN_IDS`
- Добавить аудит-логирование во все команды
- Реализовать `/sessions` через Redis-реестр
- Добавить error handling + уведомления об ошибках
- При изменениях (пароль, блокировка) — рассылка всем админам

---

### КРИТ-2: Миграция — ChatPassword.updated_at nullable

**Файл:** `backend/alembic/versions/20260213_0001_v120_security_sync.py`

**Суть:** В миграции поле `chat_passwords.updated_at` создаётся как `nullable=True`, но по модели оно должно быть NOT NULL (неявно через `server_default=func.now()`). Расхождение между моделью и миграцией.

**Влияние:** При первой вставке `updated_at` заполнится через `server_default`, но при ручных SQL-операциях или миграциях поле может оказаться NULL, что сломает логику проверки «когда менялся пароль».

**Исправление:** В миграции изменить `nullable=True` на `nullable=False` для столбца `updated_at` таблицы `chat_passwords`.

---

### КРИТ-3: AppLaunchConfig.id — нет server_default

**Файл:** `backend/alembic/versions/20260213_0001_v120_security_sync.py` + `backend/database/models.py`

**Суть:** Таблица `app_launch_config` спроектирована как однострочная (id всегда = 1). В модели стоит `default=1` (клиентский, SQLAlchemy-only). В миграции `server_default` не указан. Если запись создаётся не через ORM (например, через SQL или бота) — id может оказаться не 1.

**Влияние:** Средне-критичное. Если всё идёт через ORM — проблем не будет. Но для надёжности однострочного паттерна нужен `server_default`.

**Исправление:** Добавить `server_default=sa.text("1")` в миграцию для столбца `id`.

---

## СЕРЬЁЗНЫЕ ЗАМЕЧАНИЯ (НЕ БЛОКЕРЫ)

### ЗАМ-1: LaunchGate — нет shake-анимации

**Файл:** `frontend/src/pages/LaunchGate.tsx`

По ТЗ: при неверном пароле — shake-анимация поля ввода. В реализации — только текстовое сообщение об ошибке. Анимации нет.

**Влияние:** Косметическое. Функционально всё работает.

### ЗАМ-2: SyncStatus — нет жёлтого состояния

**Файл:** `frontend/src/components/SyncStatus.tsx`

По ТЗ: 4 состояния (зелёный/синий/жёлтый/красный). Жёлтый = «Отстаёт на N записей». В реализации — 3 состояния (зелёный/синий/красный). Жёлтый не реализован.

**Влияние:** Незначительное. Основные состояния покрыты.

### ЗАМ-3: Тесты скрытия чатов — минимальные

**Файл:** `backend/tests/test_tg_hidden_filter.py`

Тестирует базовый сценарий (скрыть → проверить фильтрацию → показать). Не покрывает:
- Все чаты скрыты → пустой список
- Пагинация с учётом скрытых
- Поиск среди скрытых

**Влияние:** Основная логика протестирована. Edge-кейсы — только при ручном QA.

---

## ПОКОМПОНЕНТНЫЙ РАЗБОР

### Фаза 0: Alembic

| Компонент | Статус | Детали |
|-----------|--------|--------|
| alembic.ini | ✅ | Корректная конфигурация |
| alembic/env.py | ✅ | Импорт моделей, online/offline режимы |
| Миграция v1.2.0 | ⚠️ | 2 бага (КРИТ-2, КРИТ-3) |
| connection.py | ✅ | DB_CREATE_ALL_ON_STARTUP для dev, alembic для prod |
| Новые модели | ✅ | SyncDeletion, ChatPassword, AppLaunchConfig, LockedPeriod, auth_method |

### Фаза 1: Скрытие чатов

| Компонент | Статус | Детали |
|-----------|--------|--------|
| hide_chat/unhide_chat | ✅ | Идемпотентные операции |
| list_chats фильтрация | ✅ | Set-based O(1) lookup, строгий default false |
| PUT /hidden endpoint | ✅ | Корректные Pydantic-модели, ответ с timestamp |
| Deprecated POST hide/unhide | ✅ | Делегируют в PUT |
| Фронт: selectedChat reset | ✅ | Сброс при скрытии выбранного |
| Фронт: двойная фильтрация | ✅ | Сервер + клиент |
| Фронт: optimistic mutations | ✅ | onMutate/onError/onSettled |
| Фронт: empty state | ✅ | «Все чаты скрыты...» |
| Фронт: счётчик | ✅ | «Чаты (N, скрыто: M)» |

### Фаза 2: AuthBot + OTP

| Компонент | Статус | Детали |
|-----------|--------|--------|
| OTPManager (Redis) | ✅ | secrets.randbelow, SETEX TTL, compare_digest, rate-limit |
| Token-функции | ✅ | create/verify launch_session, chat_access JWT |
| Хендлер: /start | ✅ | Текст помощи |
| Хендлер: /status | ✅ | Читает состояние БД |
| Хендлер: /set_launch_password | ⚠️ | Работает, но нет аудита и рассылки |
| Хендлер: /lock_period | ⚠️ | Работает, но нет аудита |
| Хендлер: /unlock_period | ⚠️ | Работает, но нет аудита |
| Хендлер: /list_periods | ✅ | Только чтение |
| Хендлер: /list_scopes | ✅ | Только чтение |
| Хендлер: /toggle_scope | ⚠️ | Нет аудита |
| Хендлер: /set_chat_password | ⚠️ | Нет аудита |
| Хендлер: /remove_chat_password | ⚠️ | Нет аудита |
| Хендлер: /list_chat_passwords | ✅ | Только чтение |
| Хендлер: /sessions | ❌ | Стаб: «пока недоступно» |
| Хендлер: /kill_session | ❌ | Стаб: «пока недоступно» |
| OTP-уведомления | ❌ | Не реализованы |
| Аудит-логирование | ❌ | Не подключено |

### Фаза 3: OTP для скоупов

| Компонент | Статус | Детали |
|-----------|--------|--------|
| POST /scope/{id}/request-code | ✅ | Генерация OTP, rate-limit, аудит |
| POST /scope/{id}/verify-code | ✅ | Верификация, JWT-токен, lockout |
| Hybrid mode (DB priority) | ✅ | _scope_payload_for_id() проверяет DB → config |
| POST /unlock (deprecated) | ✅ | Сохранён для обратной совместимости |
| Уведомление админов | ✅ | В security.py (lines 675-681) — отправка в бота |

### Фаза 4: Пароль запуска

| Компонент | Статус | Детали |
|-----------|--------|--------|
| AppLaunchConfig модель | ✅ | Однострочная таблица |
| GET /app/launch-status | ✅ | password_set, locked |
| POST /app/verify-launch | ✅ | Пароль → JWT launch-token |
| POST /internal/set-launch-password | ✅ | X-Internal-API-Key защита |
| LaunchSessionMiddleware | ✅ | Exempt paths, token verification |
| LaunchGate.tsx | ⚠️ | Работает, но нет shake-анимации |
| App.tsx интеграция | ✅ | LaunchGate оборачивает AppContent |
| Token в памяти (не localStorage) | ✅ | In-memory хранение |

### Фаза 5: Locked periods

| Компонент | Статус | Детали |
|-----------|--------|--------|
| LockedPeriod модель | ✅ | CHECK constraint date_from <= date_to |
| PeriodLockService | ✅ | get_active_locks, filter_locked_range, lock/unlock |
| GET /locked-periods | ✅ | Публичный |
| POST/DELETE /locked-periods | ✅ | Internal-only (X-Internal-API-Key) |
| transactions.py интеграция | ✅ | 9 точек фильтрации (list, create, update, delete, bulk) |
| excelExport.ts проверка | ✅ | Pre-export фильтр с graceful fallback |
| LockedPeriodBanner.tsx | ✅ | Баннер с сообщением |

### Фаза 6: Пароли на чаты

| Компонент | Статус | Детали |
|-----------|--------|--------|
| ChatPassword модель | ✅ | PBKDF2, lockout, timestamps |
| POST /password (установить) | ✅ | Хеширование, сохранение |
| DELETE /password (снять) | ✅ | Проверка текущего пароля |
| POST /password/verify | ✅ | Lockout, session JWT (1 час) |
| GET /password/status | ✅ | protected: true/false |
| require_chat_access dependency | ✅ | Проверка X-Chat-Access на messages/send/docs |
| ChatPasswordModal.tsx | ✅ | Password input, error display, React state token |

### Фаза 7: Sync

| Компонент | Статус | Детали |
|-----------|--------|--------|
| GET /sync/manifest | ✅ | SHA256 checksum, row_count, last_updated |
| GET /sync/{table_name} | ✅ | Pagination, since/since_id, deleted_ids |
| SyncDeletion модель | ✅ | 3 индекса |
| sync_deletion_service.py | ✅ | after_flush/before_commit hooks, 11 моделей |
| Dexie v2 схема | ✅ | 12 таблиц + syncMeta |
| syncManager.ts | ✅ | Manifest compare, incremental paging, backoff |
| useOfflineTransactions.ts | ✅ | Интеграция с syncManager |
| SyncStatus.tsx | ⚠️ | 3 из 4 состояний (нет жёлтого) |

### Фаза 8: Конфиги

| Компонент | Статус | Детали |
|-----------|--------|--------|
| docker-compose.yml | ✅ | auth_bot сервис, 128MB лимит |
| .env.example | ✅ | Все новые переменные с дефолтами |
| requirements.txt | ✅ | Все зависимости присутствуют |
| package.json | ✅ | Версия 1.2.0 |
| README.md | ✅ | Обновлён разделами по безопасности |

### Фаза 9: Тесты

| Тест | Статус | Покрытие |
|------|--------|----------|
| test_tg_hidden_filter.py | ✅ | Базовый: скрытие + фильтрация |
| test_sync_api.py | ✅ | Manifest + deleted_ids |
| test_otp_scope_access.py | ✅ | Request + verify OTP flow |
| test_chat_password_access.py | ✅ | Set → block → verify → access |
| test_launch_session_gate.py | ✅ | Password → block → token → access |
| test_locked_periods.py | ✅ | Filter + block create |

---

## ЧТО НУЖНО ДОДЕЛАТЬ

### Обязательно (блокеры деплоя):

1. **auth_bot_handler.py** — полная доработка:
   - Подключить OTP-рассылку всем AUTH_ADMIN_IDS при генерации кода
   - Добавить аудит-логирование (AccessAuditLog) во все команды
   - Реализовать `/sessions` и `/kill_session` через Redis
   - Добавить try/except с уведомлением админа об ошибках
   - При изменении настроек — рассылка всем админам

2. **Миграция** — 2 исправления:
   - `chat_passwords.updated_at` → `nullable=False`
   - `app_launch_config.id` → добавить `server_default=sa.text("1")`

### Желательно (до релиза):

3. **LaunchGate.tsx** — shake-анимация при неверном пароле
4. **SyncStatus.tsx** — жёлтое состояние «Отстаёт на N записей»
5. Дополнительные тесты для edge-кейсов скрытия чатов

### Можно после релиза:

6. Расширенные тесты: пагинация с hidden, sync 150k+, lockout brute-force
7. Garbage collection для hidden_bot_chats (удалённые чаты в TG)
8. AppLaunchConfig.created_at — добавить для полного аудит-трейла

---

## БЕЗОПАСНОСТЬ

### Проверено и корректно:
- PBKDF2-SHA256 с 200k итераций ✓
- `secrets.compare_digest()` для timing-safe сравнения ✓
- `secrets.randbelow()` для генерации кодов ✓
- Redis SETEX с жёстким TTL для OTP ✓
- JWT с алгоритмом HS256, configurable secret ✓
- Rate limiting: 100 req/min на IP ✓
- Lockout: 5 попыток → блокировка ✓
- Launch-session в памяти (не localStorage) ✓
- Chat-access в React state (не localStorage) ✓
- X-Internal-API-Key для бот → бэкенд ✓
- AUTH_ADMIN_IDS whitelist в боте ✓

### Пробелы:
- Аудит-логирование в auth_bot_handler не подключено (КРИТ-1)
- Бот не логирует, какой именно админ выполнил команду

---

**Конец аудита.**
