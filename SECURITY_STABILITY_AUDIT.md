# АУДИТ БЕЗОПАСНОСТИ, СТАБИЛЬНОСТИ И ОПТИМИЗАЦИИ

**Проект:** TBSparcer (Parcer 2.0)
**Дата:** 2026-02-13
**Аудитор:** Бин
**Статус:** Первичный аудит

---

## ОГЛАВЛЕНИЕ

1. [Безопасность (15 проблем)](#1-безопасность)
2. [Стабильность (12 проблем)](#2-стабильность)
3. [Оптимизация (10 проблем)](#3-оптимизация)
4. [Порядок исправления](#4-порядок-исправления)

---

## 1. БЕЗОПАСНОСТЬ

### КРИТИЧЕСКИЕ

---

#### SEC-КРИТ-01: CORS wildcard `"*"` разрешает любой origin

**Файл:** `backend/api/main.py`, строка 244
**Описание:**
В списке `allowed_origins` присутствует `"*"`, совмещённый с `allow_credentials=True`. Starlette CORS middleware при наличии `"*"` в списке origins с `allow_credentials=True` фактически рефлектит любой Origin, возвращая его в `Access-Control-Allow-Origin`. Это позволяет любому сайту делать credentialed-запросы к API.

**Текущий код:**
```python
allowed_origins = [
    FRONTEND_URL,
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:3000",
    "file://",      # electron
    "*",            # ← ПРОБЛЕМА
]
```

**Как исправить:**
```python
allowed_origins = [
    FRONTEND_URL,
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:3000",
    "app://.",              # Electron packaged
]
# Добавляем file:// только если это Electron
if os.getenv("ELECTRON_MODE"):
    allowed_origins.append("file://")
```

**Риск:** Злоумышленник может создать страницу, которая будет делать запросы к API от имени пользователя (CSRF через CORS).

---

#### SEC-КРИТ-02: JWT_SECRET по умолчанию = `"local-dev-scope-secret"`

**Файлы:**
- `backend/services/access_control_service.py`, строка 25
- `backend/services/auth_bot_service.py`, строка 24

**Описание:**
Оба сервиса имеют fallback значение для JWT_SECRET:
```python
JWT_SECRET = os.getenv("JWT_SECRET", "local-dev-scope-secret")
```

В отличие от `auth_service.py`, который корректно выбрасывает `EnvironmentError` при отсутствии переменной, эти два сервиса тихо используют предсказуемый ключ.

**Как исправить:**
```python
JWT_SECRET = os.getenv("JWT_SECRET")
if not JWT_SECRET:
    raise EnvironmentError("JWT_SECRET environment variable is required")
```

**Риск:** Если .env файл не загружен/повреждён, система работает с предсказуемым ключом — любой может генерировать валидные scope-токены.

---

#### SEC-КРИТ-03: Sync endpoint отдаёт хеши паролей

**Файл:** `backend/api/routes/sync.py`, строки 36–49
**Описание:**
`TABLE_MODELS` включает `chatPasswords` и `accessScopes`. Функция `_serialize_row` (строка 62–66) сериализует ВСЕ колонки модели, включая `password_hash` и `salt`. При запросе `GET /api/sync/chatPasswords` или `GET /api/sync/accessScopes` клиент получает полные хеши и соли паролей.

**Текущий код:**
```python
TABLE_MODELS: Dict[str, Type] = {
    ...
    "chatPasswords": ChatPassword,    # ← содержит password_hash, salt
    "accessScopes": AccessScope,       # ← содержит password_hash, salt
    ...
}

def _serialize_row(row: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {}
    for column in row.__table__.columns:
        payload[column.name] = _dt_to_iso(getattr(row, column.name))  # ← ВСЕ колонки
    return payload
```

**Как исправить:**
```python
SENSITIVE_COLUMNS = {"password_hash", "salt", "hash_method"}

def _serialize_row(row: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {}
    for column in row.__table__.columns:
        if column.name in SENSITIVE_COLUMNS:
            continue
        payload[column.name] = _dt_to_iso(getattr(row, column.name))
    return payload
```

**Риск:** Офлайн-атака на пароли — хеши PBKDF2-SHA256 можно брутфорсить на GPU.

---

#### SEC-КРИТ-04: API доступен без авторизации (fallback user)

**Файл:** `backend/api/dependencies.py`, строки 57–59
**Описание:**
`get_current_user()` при отсутствии Bearer-токена возвращает фиктивного пользователя:
```python
if not credentials:
    return {"user_id": 1, "phone": "local", "exp": None}
```

Все endpoint-ы, использующие `Depends(get_current_user)`, доступны без авторизации. Защита обеспечивается только middleware-слоями (LaunchSession, SystemAccess, Scope), но если они отключены — полностью открытый API.

**Как исправить:**
```python
# Вариант A: требовать токен всегда
async def get_current_user(credentials=Depends(security)) -> dict:
    if not credentials:
        raise HTTPException(status_code=401, detail="Authentication required")
    user = verify_jwt_token(credentials.credentials)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid token")
    return user

# Вариант B: управляемый флаг
AUTH_REQUIRED = os.getenv("AUTH_REQUIRED", "true").lower() in ("true", "1", "yes")
```

**Риск:** Полный доступ к CRUD транзакций, automation, reference без аутентификации.

---

### ВЫСОКИЕ

---

#### SEC-ВЫС-01: Порт бэкенда 8000 открыт на 0.0.0.0

**Файл:** `docker-compose.yml`, строка 64
**Описание:**
```yaml
ports:
  - "8000:8000"  # ← биндится на 0.0.0.0
```

В отличие от Postgres (127.0.0.1:9990) и Redis (127.0.0.1:9991), бэкенд API доступен на всех интерфейсах.

**Как исправить:**
```yaml
ports:
  - "127.0.0.1:8000:8000"
```

---

#### SEC-ВЫС-02: `--reload` в docker-compose для бэкенда

**Файл:** `docker-compose.yml`, строка 65
**Описание:**
```yaml
command: uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload
```

`--reload` предназначен для разработки:
- Включает file-watcher на весь `./backend` volume
- Перезагружает приложение при любом изменении файла
- Увеличивает потребление CPU и памяти
- При ошибке в файле — бэкенд падает

**Как исправить:**
```yaml
command: uvicorn api.main:app --host 0.0.0.0 --port 8000 --workers 2
```

---

#### SEC-ВЫС-03: Auth сессии в памяти без очистки

**Файл:** `backend/services/auth_service.py`, строки 39–40
**Описание:**
```python
auth_clients: Dict[str, TelegramClient] = {}
auth_sessions: Dict[str, dict] = {}
```

QR-авторизация создаёт TelegramClient и хранит его в глобальном dict. Проблемы:
- Не очищаются автоматически
- Растут бесконечно
- Каждый TelegramClient держит сетевое соединение
- При рестарте — все теряются

**Как исправить:**
- Добавить TTL-based cleanup (asyncio.create_task с периодической проверкой)
- Ограничить максимальное количество одновременных сессий
- Перенести в Redis с TTL

---

#### SEC-ВЫС-04: Automation endpoints без scope guard

**Файл:** `backend/api/routes/automation.py`
**Описание:**
Все endpoint-ы `/api/automation/*` используют только `Depends(get_current_user)`, но НЕ `require_transactions_scope`. Пользователь с scope, ограниченным по годам/датам, может:
- Запустить анализ ВСЕХ транзакций
- Применить suggestion к транзакциям вне своего scope

**Как исправить:**
Добавить `scope: Optional[Dict] = Depends(require_transactions_scope)` во все endpoint-ы automation и фильтровать транзакции по scope.

---

#### SEC-ВЫС-05: apply_verification_suggestion обходит scope/lock

**Файл:** `backend/api/routes/automation.py`, строки 789–816
**Описание:**
`apply_verification_suggestion` и `batch_apply_verification_suggestions` напрямую модифицируют транзакции (`setattr(tx, field, value)`) без проверки:
- `is_datetime_allowed(scope, tx.transaction_date)`
- `period_lock_service.is_date_locked()`

**Как исправить:**
Добавить scope-проверку и lock-проверку перед каждой модификацией (аналогично `update_transaction`).

---

### СРЕДНИЕ

---

#### SEC-СРД-01: LIKE wildcard injection

**Файл:** `backend/api/routes/transactions.py`, строки 878, 882, 898
**Описание:**
```python
query = query.filter(Transaction.operator_raw.ilike(f"%{operator}%"))
query = query.filter(Transaction.raw_message.ilike(f"%{search}%"))
```

Пользователь может передать `%` или `_` как часть строки поиска, манипулируя результатами.

**Как исправить:**
```python
def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")

query = query.filter(Transaction.operator_raw.ilike(f"%{_escape_like(operator)}%", escape="\\"))
```

---

#### SEC-СРД-02: Rate limiter не разделяется между workers

**Файл:** `backend/api/main.py`, строки 28–55
**Описание:**
`RateLimitMiddleware` хранит данные в `defaultdict(list)` — в памяти процесса. При запуске нескольких uvicorn workers каждый имеет свой лимитер, фактически увеличивая лимит в N раз.

**Как исправить:**
Перенести rate limiting в Redis:
```python
# Используй redis INCR + EXPIRE
async def check_rate(ip: str) -> bool:
    key = f"rate:{ip}"
    count = await redis.incr(key)
    if count == 1:
        await redis.expire(key, 60)
    return count <= MAX_REQUESTS
```

---

#### SEC-СРД-03: Ошибки утекают внутренние детали

**Файл:** `backend/api/routes/transactions.py`, строки 804, 1013, 1121
**Описание:**
```python
raise HTTPException(status_code=500, detail=f"Bulk update failed: {str(e)}")
raise HTTPException(status_code=500, detail=f"Create failed: {str(e)}")
raise HTTPException(status_code=500, detail=f"Update failed: {str(e)}")
```

`str(e)` может содержать: имена таблиц, имена колонок, SQL-фрагменты, пути файлов.

**Как исправить:**
```python
import logging
logger = logging.getLogger(__name__)

except Exception as e:
    logger.exception("Bulk update failed")
    raise HTTPException(status_code=500, detail="Internal server error")
```

---

#### SEC-СРД-04: OTP-код отдаётся в list_pending_otp_requests

**Файл:** `backend/services/auth_bot_service.py`, строка 274
**Описание:**
```python
rows.append({
    ...
    "code": record.code,    # ← актуальный OTP-код
})
```

Endpoint, вызывающий эту функцию, отдаёт одноразовые коды в открытом виде. Если этот endpoint доступен не только auth-боту, OTP-коды утекают.

**Как исправить:**
Убрать `"code"` из ответа или ограничить доступ к endpoint-у только internal API key.

---

#### SEC-СРД-05: Сравнение internal API key не timing-safe

**Файлы:** `backend/api/main.py`, строка 121; `backend/api/dependencies.py`, строка 97
**Описание:**
```python
if internal_api_key and internal_header and internal_header == internal_api_key:
```

Python `==` для строк — не constant-time операция.

**Как исправить:**
```python
import secrets
if internal_api_key and internal_header and secrets.compare_digest(internal_header, internal_api_key):
```

---

### НИЗКИЕ

---

#### SEC-НИЗ-01: JWT живёт 720 часов (30 дней)

**Файл:** `backend/services/auth_service.py`, строка 22
**Описание:**
`JWT_EXPIRATION_HOURS = int(os.getenv("JWT_EXPIRATION_HOURS", "720"))` — украденный токен действует месяц.

**Рекомендация:** Уменьшить до 24–72 часов + добавить refresh-токен.

---

#### SEC-НИЗ-02: Нет audit log для automation операций

**Файл:** `backend/api/routes/automation.py`
**Описание:**
`apply_suggestion`, `reject_suggestion`, `batch_apply`, apply/reject verification — ни один из них не пишет запись в `AccessAuditLog`.

**Рекомендация:** Добавить `write_audit_log(db, action="automation_apply_suggestion", ...)`.

---

## 2. СТАБИЛЬНОСТЬ

### ВЫСОКИЕ

---

#### СТАБ-ВЫС-01: asyncio.create_task без обработки ошибок

**Файлы:**
- `backend/api/routes/automation.py`, строка 298
- `backend/api/routes/automation.py`, строка 729
- `backend/api/main.py`, строка 279

**Описание:**
```python
asyncio.create_task(process_transactions_batch(task_id, [...]))
asyncio.create_task(process_verification_batch(task_id, [...]))
asyncio.create_task(monitor_service.start())
```

Если task упадёт с исключением, asyncio выведет предупреждение в stderr, но:
- Нет механизма retry
- Нет уведомления
- Task-ID зависнет в status="processing" навсегда

**Как исправить:**
```python
async def _safe_task(coro, name: str):
    try:
        await coro
    except Exception as e:
        logger.exception(f"Background task '{name}' crashed: {e}")
        # Можно добавить fallback-логику: обновить task status = "failed"

asyncio.create_task(_safe_task(
    process_transactions_batch(task_id, ids),
    name=f"automation-{task_id}"
))
```

---

#### СТАБ-ВЫС-02: Избыточные DB-сессии в background tasks

**Файл:** `backend/api/routes/automation.py`, строки 174–255, 588–689
**Описание:**
Каждая итерация цикла создаёт новые `with SessionLocal() as db:` блоки:
```python
for tx in txs:
    # ... AI call ...
    with SessionLocal() as db:   # сессия 1: insert suggestion
        db.add(AutomationSuggestion(...))
        db.commit()
    with SessionLocal() as db:   # сессия 2: update progress
        update_task(db, ...)
```

При 100 транзакциях = 200+ сессий (создаётся/закрывается каждый раз).

**Как исправить:**
Использовать одну сессию на весь batch:
```python
with SessionLocal() as db:
    for tx in txs:
        # ... AI call ...
        db.add(AutomationSuggestion(...))
        update_task(db, ...)
        db.commit()  # коммит после каждой итерации для прогресса
```

---

#### СТАБ-ВЫС-03: Redis-подключение создаётся каждый раз

**Файлы:**
- `backend/services/auth_bot_service.py`, строка 72: `return await aioredis.from_url(REDIS_URL)`
- `backend/services/auth_service.py`, строка 45: `return await aioredis.from_url(REDIS_URL)`

**Описание:**
Каждый вызов `get_redis()` открывает новое TCP-соединение. При высокой нагрузке:
- Исчерпание file descriptors
- Задержки на TCP handshake

**Как исправить:**
```python
_redis_pool: Optional[aioredis.Redis] = None

async def get_redis() -> aioredis.Redis:
    global _redis_pool
    if _redis_pool is None:
        _redis_pool = await aioredis.from_url(
            REDIS_URL,
            decode_responses=True,
            max_connections=20,
        )
    return _redis_pool
```

---

### СРЕДНИЕ

---

#### СТАБ-СРД-01: Rate limiter memory leak

**Файл:** `backend/api/main.py`, строки 35, 42–44
**Описание:**
```python
self.requests: dict = defaultdict(list)
# ...
self.requests[client_ip] = [req_time for req_time in self.requests[client_ip] if req_time > minute_ago]
```

Старые timestamps очищаются, но ключи (IP-адреса) остаются навсегда. За месяц работы — тысячи пустых списков.

**Как исправить:**
```python
if not self.requests[client_ip]:
    del self.requests[client_ip]
```

---

#### СТАБ-СРД-02: Middleware создают свои DB-сессии

**Файлы:**
- `backend/api/main.py`, строки 88–103 (`SystemAccessMiddleware`)
- `backend/api/main.py`, строки 196–210 (`LaunchSessionMiddleware`)

**Описание:**
Обе middleware создают `SessionLocal()` вне жизненного цикла запроса FastAPI. Если middleware выбросит исключение между `SessionLocal()` и `db.close()`, сессия может утечь.

**Как исправить:**
Обернуть в context manager:
```python
from database.connection import get_db

with get_db() as db:
    launch_cfg = db.get(AppLaunchConfig, 1)
```

---

#### СТАБ-СРД-03: Нет graceful shutdown

**Файл:** `backend/api/main.py`, строки 283–284
**Описание:**
Shutdown-часть lifespan:
```python
yield
print("👋 Shutting down API...")
```

Не закрывается:
- TDLib manager
- Redis connections pool
- Auto-monitor service
- Не дожидается завершения background asyncio tasks

**Как исправить:**
```python
yield
print("Shutting down...")
await monitor_service.stop()
await manager.close()
# Close global Redis pool if created
if _redis_pool:
    await _redis_pool.close()
```

---

#### СТАБ-СРД-04: Celery worker без Docker healthcheck

**Файл:** `docker-compose.yml`, строки 124–139
**Описание:**
У postgres, redis, frontend есть healthcheck. У celery_worker — нет. Если worker зависнет (deadlock, memory), Docker его не перезапустит.

**Как исправить:**
```yaml
celery_worker:
  ...
  healthcheck:
    test: ["CMD-SHELL", "celery -A workers.celery_worker inspect ping --timeout 5"]
    interval: 30s
    timeout: 10s
    retries: 3
```

---

#### СТАБ-СРД-05: get_db_session не коммитит

**Файл:** `backend/database/connection.py`, строки 49–62
**Описание:**
```python
def get_db_session() -> Session:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
```

В отличие от `get_db()` (context manager, строки 30–46), `get_db_session()` не вызывает `db.commit()`. Каждый route должен явно коммитить. Если забудете — данные не запишутся, без ошибки.

**Как исправить:**
Для FastAPI dependency это нормальный паттерн (commit делается в route). Но можно добавить warning-log если session имеет dirty state при close.

---

#### СТАБ-СРД-06: Ревокация сессий fail-open

**Файл:** `backend/services/auth_bot_service.py`, строки 130–138
**Описание:**
```python
def _is_session_revoked(session_id):
    try:
        ...
    except Exception:
        return False  # ← fail-open
```

Если Redis недоступен, отозванные сессии считаются валидными.

**Как исправить:**
Для одиночного пользователя — допустимо (downtime Redis = кратковременный risk). Для multi-tenant — fail-closed.

---

### НИЗКИЕ

---

#### СТАБ-НИЗ-01: batch_apply коммитит на каждой итерации

**Файлы:**
- `backend/api/routes/automation.py`, строки 436–437
- `backend/api/routes/automation.py`, строка 865

**Описание:**
```python
for sug_id in suggestion_ids:
    ...
    db.commit()  # ← каждый раз
```

При 100 suggestions = 100 коммитов вместо одного.

**Как исправить:** Коммитить один раз после цикла.

---

#### СТАБ-НИЗ-02: Нет retry для AI-вызовов в automation

**Файл:** `backend/api/routes/automation.py`, строка 200
**Описание:**
Если OpenAI API вернёт 429 (rate limit) или 500 — транзакция будет просто пропущена.

**Рекомендация:** Добавить tenacity с exponential backoff (max 2 retry).

---

## 3. ОПТИМИЗАЦИЯ

### ВЫСОКИЕ

---

#### ОПТ-ВЫС-01: sync manifest — 24+ запросов на каждый poll

**Файл:** `backend/api/routes/sync.py`, строки 147–160
**Описание:**
```python
for table_name, model in TABLE_MODELS.items():  # 12 таблиц
    tables[table_name] = _table_manifest(...)
    # → COUNT + MAX(updated_at) = 2 запроса на таблицу
```

12 таблиц × 2 запроса = 24 запроса при каждом GET /api/sync/manifest. Фронт опрашивает каждые 30 секунд.

**Как исправить:**
1. Кешировать manifest на 10 секунд в Redis
2. Инвалидировать при изменениях (через SQLAlchemy event listener)

```python
MANIFEST_CACHE_KEY = "sync:manifest"
MANIFEST_TTL = 10  # seconds

async def sync_manifest(...):
    cached = await redis.get(MANIFEST_CACHE_KEY)
    if cached:
        return json.loads(cached)
    result = _compute_manifest(db, scope)
    await redis.setex(MANIFEST_CACHE_KEY, MANIFEST_TTL, json.dumps(result))
    return result
```

---

#### ОПТ-ВЫС-02: _blocked_transaction_ids загружает все ID в память

**Файл:** `backend/api/routes/sync.py`, строки 177–190
**Описание:**
```python
def _blocked_transaction_ids(db: Session) -> List[int]:
    rows = db.query(Transaction.id).filter(or_(*conditions)).all()
    return [int(row[0]) for row in rows]
```

Если заблокирован период в 6 месяцев с 100K транзакциями — все 100K ID загружаются в память и включаются в JSON-ответ.

**Как исправить:**
Вместо отправки всех заблокированных ID, отправлять заблокированные диапазоны дат:
```python
"blocked_ranges": [
    {"from": "2025-01-01", "to": "2025-06-30"}
]
```

Клиент сам отфильтрует.

---

#### ОПТ-ВЫС-03: duplicate-events — N+1 scope-проверка

**Файл:** `backend/api/routes/transactions.py`, строки 457–468
**Описание:**
```python
for tx_id, tx_date in tx_rows:
    if is_datetime_allowed(scope, tx_date) and \
       not period_lock_service.is_date_locked(tx_date.date(), db):
        allowed_tx_ids.add(int(tx_id))
```

`period_lock_service.is_date_locked()` делает запрос к БД для каждого tx_id. При 200 записях = 200 запросов.

**Как исправить:**
Загрузить locked periods один раз:
```python
locks = period_lock_service.get_active_locks(db)
for tx_id, tx_date in tx_rows:
    if is_datetime_allowed(scope, tx_date) and \
       not any(l.date_from <= tx_date.date() <= l.date_to for l in locks):
        allowed_tx_ids.add(int(tx_id))
```

---

### СРЕДНИЕ

---

#### ОПТ-СРД-01: Нет пагинации в suggestions endpoints

**Файл:** `backend/api/routes/automation.py`, строки 320–359, 754–785
**Описание:**
`get_suggestions` и `get_verification_suggestions` загружают ВСЕ записи. При тысяче suggestions — большой JSON-ответ.

**Как исправить:**
Добавить `limit` + `offset` параметры (аналогично transactions).

---

#### ОПТ-СРД-02: Один AI-вызов на транзакцию

**Файл:** `backend/api/routes/automation.py`, строка 200
**Описание:**
Для каждой транзакции:
1. Web search via DuckDuckGo (~1-5 сек)
2. OpenAI API call (~0.5-2 сек)

100 транзакций = ~5-10 минут.

**Как исправить:**
- Группировать уникальные операторы (многие транзакции имеют одинаковый operator_raw)
- Batched web search
- Кешировать результаты по operator_raw

```python
unique_operators = {tx.operator_raw for tx in txs}
# Один AI-вызов для 5-10 операторов одновременно
```

---

#### ОПТ-СРД-03: Redis подключение при каждой проверке токена

**Файл:** `backend/services/auth_service.py`, строки 258–277
**Описание:**
```python
async def verify_user_token(token: str):
    redis = await get_redis()
    stored_token = await redis.get(f"auth_token:{user_id}")
    await redis.close()  # ← каждый раз
```

Создание и закрытие TCP-соединения на каждый API-запрос.

**Как исправить:** Использовать connection pool (см. СТАБ-ВЫС-03).

---

#### ОПТ-СРД-04: sync table — двойной запрос для checksum

**Файл:** `backend/api/routes/sync.py`, строки 224, 227
**Описание:**
```python
rows = query.order_by(id_column.asc()).offset(offset).limit(limit).all()  # основной запрос
# ...
checksum_rows = query.order_by(id_column.desc()).limit(100).all()  # ещё один запрос
```

Два запроса на один и тот же фильтрованный набор.

**Как исправить:**
Вычислять checksum из уже загруженных rows (если limit >= 100) или кешировать checksum при записи.

---

### НИЗКИЕ

---

#### ОПТ-НИЗ-01: Нет составного индекса (fingerprint, transaction_date)

**Файл:** `backend/database/models.py`
**Описание:**
При дедупликации часто проверяется `fingerprint` + `transaction_date`. Отдельный индекс по fingerprint есть, но составной ускорит поиск.

**Как исправить:**
```python
Index('idx_transactions_fp_date', 'fingerprint', 'transaction_date'),
```

---

#### ОПТ-НИЗ-02: get_existing_applications без кеширования

**Файл:** `backend/api/routes/automation.py`, строки 77–83
**Описание:**
```python
def get_existing_applications(db: Session) -> List[str]:
    apps = db.query(OperatorReference.application_name).distinct().filter(...).all()
    return [a[0] for a in apps if a[0]]
```

Вызывается при каждом запуске automation — каждый раз запрос к БД.

**Рекомендация:** Кешировать на 5 минут.

---

#### ОПТ-НИЗ-03: Полный sync для non-transaction таблиц

**Файл:** `backend/api/routes/sync.py`
**Описание:**
Для таблиц без поля `updated_at` (например, `HiddenBotChat` с `hidden_at`) delta-sync работает неоптимально.

**Рекомендация:** Добавить `updated_at` ко всем синхронизируемым таблицам.

---

## 4. ПОРЯДОК ИСПРАВЛЕНИЯ

### Фаза 1: Критическая безопасность (1-2 дня)
1. **SEC-КРИТ-01** — Удалить `"*"` из CORS origins
2. **SEC-КРИТ-02** — Убрать fallback JWT_SECRET
3. **SEC-КРИТ-03** — Фильтровать sensitive columns в sync
4. **SEC-КРИТ-04** — Решить стратегию аутентификации

### Фаза 2: Высокая безопасность (1 день)
5. **SEC-ВЫС-01** — Ограничить порт 8000 на 127.0.0.1
6. **SEC-ВЫС-02** — Убрать --reload
7. **SEC-ВЫС-04** — Добавить scope guard в automation
8. **SEC-ВЫС-05** — Scope/lock проверка при apply suggestions

### Фаза 3: Стабильность (1-2 дня)
9. **СТАБ-ВЫС-01** — Обернуть create_task в safe wrapper
10. **СТАБ-ВЫС-02** — Оптимизировать DB-сессии в background tasks
11. **СТАБ-ВЫС-03** — Redis connection pool
12. **СТАБ-СРД-03** — Graceful shutdown
13. **СТАБ-СРД-04** — Celery healthcheck

### Фаза 4: Оптимизация (1-2 дня)
14. **ОПТ-ВЫС-01** — Кешировать sync manifest
15. **ОПТ-ВЫС-02** — Заменить blocked IDs на date ranges
16. **ОПТ-ВЫС-03** — Убрать N+1 в duplicate-events
17. **ОПТ-СРД-02** — Группировать AI-вызовы по оператору

### Фаза 5: Остальное (по мере возможности)
18. Остальные СРЕДНИЕ и НИЗКИЕ по приоритету

---

## ИТОГО

| Категория | Критические | Высокие | Средние | Низкие | Всего |
|-----------|:-----------:|:-------:|:-------:|:------:|:-----:|
| Безопасность | 4 | 5 | 5 | 2 | **16** |
| Стабильность | 0 | 3 | 6 | 2 | **11** |
| Оптимизация | 0 | 3 | 4 | 3 | **10** |
| **ИТОГО** | **4** | **11** | **15** | **7** | **37** |
