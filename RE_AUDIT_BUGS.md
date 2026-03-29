# RE-AUDIT: Баги и проблемы после внесённых правок

**Дата:** 2026-02-13
**Файлы:** `automation.py`, `auth_service.py`, `auth_bot_service.py`, `dependencies.py`, `main.py`
**Статус предыдущего аудита:** Большинство CRITICAL и HIGH из `SECURITY_STABILITY_AUDIT.md` исправлены

---

## Общая оценка исправлений

Основные проблемы из предыдущего аудита закрыты корректно:
- ✅ CORS больше не wildcard `"*"` — используются конкретные origins
- ✅ `JWT_SECRET` без fallback, валидация при импорте
- ✅ `AUTH_REQUIRED` флаг для контроля аутентификации
- ✅ `secrets.compare_digest()` для сравнения ключей
- ✅ Redis-пулы с `close_redis_pool()` + graceful shutdown в `main.py`
- ✅ Scope-гарды на всех endpoint-ах automation
- ✅ Аудит-логирование действий
- ✅ Background task safety wrapper `_run_background_task()`
- ✅ Retry с backoff для AI-вызовов
- ✅ Пагинация (`limit`/`offset`) на suggestions
- ✅ `operator_cache` для дедупликации AI-вызовов
- ✅ `_applications_cache` с TTL
- ✅ `_cleanup_stale_auth_sessions()` + лимит активных сессий
- ✅ OTP-код больше не отдаётся в `list_pending_otp_requests`
- ✅ Rate limiter теперь пробует Redis, fallback на memory

---

## Найденные баги и проблемы

### BUG-01 · HIGH · `Decimal(value)` без валидации → unhandled 500

**Файл:** `automation.py`, строки 978-983, 1046-1051
**Проблема:** В `apply_verification_suggestion` (единичное применение) значение `sug.suggested_value` напрямую парсится через `Decimal(value)` и `datetime.fromisoformat(value)`. Если AI вернул невалидную строку (например `"пятнадцать тысяч"` вместо `"15000"`), это вызовет `InvalidOperation` / `ValueError` — необработанный 500.

В batch-версии (`batch_apply_verification_suggestions`) ошибка ловится `except Exception`, но в единичном `apply_verification_suggestion` — нет.

**Исправление:**
```python
# В apply_verification_suggestion, после строки 977:
try:
    if field == "amount":
        tx.amount = Decimal(value)
    elif field == "balance_after":
        tx.balance_after = Decimal(value) if value else None
    elif field == "transaction_date":
        tx.transaction_date = datetime.fromisoformat(value)
    elif field in ("currency", "operator_raw", "card_last_4", "transaction_type",
                   "receiver_name", "receiver_card"):
        setattr(tx, field, value)
except (ValueError, ArithmeticError, TypeError) as exc:
    raise HTTPException(status_code=422, detail=f"Invalid value for {field}: {exc}")
```

---

### BUG-02 · HIGH · OTP TTL сбрасывается при каждой неудачной попытке

**Файл:** `auth_bot_service.py`, строка 367
**Проблема:** `verify_code()` после каждой неудачной попытки вызывает:
```python
await redis.setex(key, AUTH_CODE_TTL_SECONDS, record.to_json())
```
Это **перезаписывает TTL** с нуля (120 секунд). Атакующий может держать OTP живым бесконечно, отправляя неверный код каждые ~100 секунд. Три попытки × бесконечное продление = brute-force вектор.

**Исправление:** Использовать оставшийся TTL вместо полного:
```python
remaining_ttl = await redis.ttl(key)
if remaining_ttl and remaining_ttl > 0:
    await redis.setex(key, remaining_ttl, record.to_json())
else:
    await redis.delete(key)
```

---

### BUG-03 · MEDIUM · `is_new_application` всегда `False`

**Файл:** `automation.py`, строка 477
**Проблема:** В `get_suggestions()` поле `is_new_application` захардкожено:
```python
is_new_application=False,
```
AI возвращает `is_new` в `AISuggestion`, но это значение **нигде не сохраняется** в `AutomationSuggestion` (нет колонки в модели). Информация о том, что приложение новое, теряется после AI-анализа.

**Исправление:** Добавить колонку `is_new_application = Column(Boolean, default=False)` в модель `AutomationSuggestion` + миграция. В `process_transactions_batch` сохранять `is_new_application=ai_result.is_new`. В `get_suggestions` читать из `sug.is_new_application`.

---

### BUG-04 · MEDIUM · Нет лимита на `suggestion_ids` в batch-операциях

**Файл:** `automation.py`, строки 554, 1023
**Проблема:** `batch_apply_suggestions(suggestion_ids: List[UUID])` и `batch_apply_verification_suggestions(suggestion_ids: List[UUID])` принимают неограниченный список UUID. Запрос с 10 000 ID-шников вызовет длительную блокировку БД и таймауты.

**Исправление:**
```python
class BatchApplyRequest(BaseModel):
    suggestion_ids: List[UUID] = Field(..., max_length=500)

# Или проверка в начале:
if len(suggestion_ids) > 500:
    raise HTTPException(status_code=400, detail="Too many suggestions (max 500)")
```

---

### BUG-05 · MEDIUM · Detached ORM objects используются между сессиями

**Файл:** `automation.py`, строки 276-298 и 752-775
**Проблема:** В `process_transactions_batch` и `process_verification_batch`:
```python
with SessionLocal() as db:
    txs = db.query(Transaction).filter(...).all()
# ← сессия закрыта, txs отсоединены

with SessionLocal() as write_db:
    for tx in txs:    # ← используем detached объекты
        tx.operator_raw  # работает (column уже загружен)
```
Сейчас это работает, потому что `.all()` грузит все колонки. Но это **хрупкий паттерн**: если добавить `deferred()` колонки, relationship, или `lazy="select"` — получим `DetachedInstanceError` в рантайме без видимых причин.

**Исправление:** Извлекать нужные данные в обычные dict/dataclass-ы ДО закрытия первой сессии:
```python
with SessionLocal() as db:
    txs_raw = db.query(Transaction).filter(...).all()
    tx_data = [
        {
            "id": t.id, "operator_raw": t.operator_raw,
            "transaction_type": t.transaction_type,
            "amount": t.amount, "transaction_date": t.transaction_date,
            "raw_message": t.raw_message, "currency": t.currency,
            # ... и т.д.
        }
        for t in txs_raw
    ]
```

---

### BUG-06 · MEDIUM · Rate limiter memory leak (старые IP) — не полностью исправлен

**Файл:** `main.py`, строки 55-68
**Проблема:** `_check_memory_limit` — fallback при недоступном Redis. Когда IP перестаёт слать запросы, его записи **никогда не удаляются** из `self.requests`. За день-два под нагрузкой `self.requests` разрастётся на тысячи ключей.

Строка 59-61 удаляет ключ только если отфильтрованный список пуст:
```python
if not filtered:
    self.requests.pop(client_ip, None)
```
Это помогает только для IP, который перестал слать запросы >60 секунд назад. Но если IP шлёт хотя бы 1 запрос в минуту — ключ живёт вечно.

**Исправление:** Периодическая чистка (например, каждые 100 вызовов):
```python
self._cleanup_counter = getattr(self, "_cleanup_counter", 0) + 1
if self._cleanup_counter % 100 == 0:
    cutoff = current_time - 120  # 2 минуты
    stale = [ip for ip, times in self.requests.items() if not times or max(times) < cutoff]
    for ip in stale:
        self.requests.pop(ip, None)
```

---

### BUG-07 · MEDIUM · `_write_system_access_audit` создаёт собственную DB-сессию

**Файл:** `main.py`, строки 120-135
**Проблема:** Внутри middleware `SystemAccessMiddleware` вызывается `_write_system_access_audit`, который делает `db = SessionLocal()` → `write_audit_log(db, ...)` → `db.close()`. Это корректно, но `write_audit_log` внутри вызывает `db.commit()`. Если commit упадёт, вызывается `db.rollback()`, а в `finally` — `db.close()`.

Проблема в том, что каждый запрос к API создаёт **дополнительную** DB-сессию только для аудит-лога, даже когда `system_access_enforced()` активен и токен валиден (строки 193-198). Это +1 connection на каждый запрос.

**Исправление:** Логировать `system_token_ok` только в dependency (`get_system_access_context`), не дублировать в middleware. Или использовать request.state для передачи данных в dependency, который уже имеет DB-сессию.

---

### BUG-08 · LOW · `analyze_with_ai` — implicit `None` return

**Файл:** `automation.py`, строка 240-265
**Проблема:** Цикл `for attempt in range(retry_count + 1)` имеет `return` внутри `try` и внутри последнего `except`. Но если `retry_count = 0` и `attempt >= retry_count`, fallback `return` выполняется корректно. Однако если `AUTOMATION_AI_RETRY_COUNT` будет задан как отрицательное число, `max(0, ...)` делает его 0, и цикл `range(1)` выполнится ровно раз. Это безопасно.

Но: если `range(retry_count + 1)` окажется пустым (impossible из-за `max(0, ...)`), функция вернёт `None` неявно. Mypy/type checker это не поймает, потому что return type `AISuggestion`, а `None` не указан.

**Не блокирующий баг**, но стоит добавить финальный `return` после цикла как safety net:
```python
# После цикла for:
return AISuggestion(application="Unknown", confidence=0.0, is_new=True, is_p2p=False, reasoning="No attempts made")
```

---

### BUG-09 · LOW · `search_web_for_operator` использует `print()` вместо `logger`

**Файл:** `automation.py`, строка 205
**Проблема:** `print(f"Web search error: {e}")` — в файле уже есть `logger = logging.getLogger(__name__)`, но web search и AI errors до сих пор пишутся через `print()`. Это не попадёт в structured logging.

Строки: 205, 256, 329, 738, 812.

**Исправление:** Заменить все `print(...)` на `logger.warning(...)` или `logger.error(...)`.

---

### BUG-10 · LOW · `_assert_tx_edit_allowed` вызывает `is_date_locked` внутри `begin_nested()`

**Файл:** `automation.py`, строки 576, 1042
**Проблема:** Внутри `with db.begin_nested():` вызывается `_assert_tx_edit_allowed(tx, scope, db)`, который внутри делает `period_lock_service.is_date_locked(tx_day, db)` — это SELECT-запрос. Если `_assert_tx_edit_allowed` бросит `HTTPException`, savepoint откатится. `HTTPException` наследует от `Exception`, поэтому ловится внешним `except Exception as e`.

Ошибка будет иметь вид `{"error": "403: Transaction date is locked"}` в списке errors — **HTTP status код попадает в текст ошибки**. Лучше возвращать чистое сообщение.

**Исправление:** Вместо `HTTPException` в batch-контексте использовать обычный `ValueError`:
```python
# В batch-функциях вызывать отдельную проверку:
def _check_tx_edit_allowed(tx, scope, db) -> Optional[str]:
    """Returns error message or None."""
    ...
    return "Transaction date is locked"  # или None если ок
```

---

### BUG-11 · LOW · Двойная обработка ошибок в background tasks

**Файл:** `automation.py`
**Проблема:** `_run_background_task` (строки 149-164) оборачивает корутину и при ошибке маркирует task как `failed`. Но `process_transactions_batch` (строки 355-361) и `process_verification_batch` (строки 834-840) уже содержат свой `try/except` с тем же `status="failed"`.

Если внутренний handler отработает — `_run_background_task` не увидит исключения. Если внутренний handler сам упадёт — `_run_background_task` поймает и попробует записать "failed" снова. Потенциально **два `SessionLocal()`** откроются для записи одной ошибки.

**Не критично** — это defense-in-depth. Но стоит добавить `logger.debug` в `_run_background_task`, чтобы было видно, когда outer handler срабатывает.

---

## Статус предыдущих находок из SECURITY_STABILITY_AUDIT.md

| ID | Статус | Комментарий |
|---|---|---|
| SEC-КРИТ-01 (CORS `*`) | ✅ Исправлен | Конкретные origins, фильтрация `*` |
| SEC-КРИТ-02 (JWT fallback) | ✅ Исправлен | `raise EnvironmentError` |
| SEC-КРИТ-03 (Sync хэши) | ❓ Не проверял | Нужен повторный просмотр `sync.py` |
| SEC-КРИТ-04 (Auth bypass) | ✅ Исправлен | `AUTH_REQUIRED` flag |
| SEC-ВЫС-01 (0.0.0.0) | ❓ Не проверял | docker-compose |
| SEC-ВЫС-02 (--reload prod) | ❓ Не проверял | docker-compose |
| SEC-ВЫС-03 (QR session leak) | ✅ Исправлен | Cleanup + max sessions |
| SEC-ВЫС-04 (No scope automation) | ✅ Исправлен | `require_transactions_scope` |
| SEC-ВЫС-05 (No lock check) | ✅ Исправлен | `_assert_tx_edit_allowed` |
| SEC-СРД-01 (LIKE injection) | ❓ Не проверял | `transactions.py` |
| SEC-СРД-02 (Rate limit memory) | ⚠️ Частично | Redis primary, memory fallback с утечкой |
| SEC-СРД-03 (Error leak) | ⚠️ Частично | `ErrorHandlingMiddleware` скрывает, но `print()` в automation |
| SEC-СРД-04 (OTP code leak) | ✅ Исправлен | Код убран из ответа |
| SEC-СРД-05 (Timing attack) | ✅ Исправлен | `secrets.compare_digest` |
| SEC-НИЗ-01 (JWT 720h) | ✅ Исправлен | 72 часа |
| SEC-НИЗ-02 (No audit log) | ✅ Исправлен | `_audit_automation_action` |
| СТАБ-ВЫС-01 (BG task crash) | ✅ Исправлен | `_run_background_task` wrapper |
| СТАБ-ВЫС-02 (Session per tx) | ✅ Исправлен | Single `with SessionLocal()` |
| СТАБ-ВЫС-03 (Redis per call) | ✅ Исправлен | Pooled Redis |
| СТАБ-СРД-01 (Rate limit leak) | ⚠️ Частично | Redis primary, memory fallback всё ещё без чистки |
| СТАБ-СРД-02/03 (Middleware DB) | ⚠️ Осталось | `_write_system_access_audit` создаёт свою сессию |
| СТАБ-СРД-04 (Celery healthcheck) | ❓ Не проверял | |
| СТАБ-НИЗ-01 (Batch commit) | ✅ Исправлен | `begin_nested` + single commit |
| СТАБ-НИЗ-02 (AI retry) | ✅ Исправлен | Retry + exponential backoff |
| ОПТ-ВЫС-01 (Sync 24+ queries) | ❓ Не проверял | |
| ОПТ-ВЫС-02 (Blocked IDs memory) | ❓ Не проверял | |
| ОПТ-ВЫС-03 (N+1 duplicates) | ❓ Не проверял | |
| ОПТ-СРД-01 (No pagination) | ✅ Исправлен | `limit`/`offset` |
| ОПТ-СРД-02 (No dedup AI) | ✅ Исправлен | `operator_cache` |
| ОПТ-СРД-03 (Redis per verify) | ✅ Исправлен | Pooled |
| ОПТ-НИЗ-01 (No index sug) | ❓ Не проверял | |
| ОПТ-НИЗ-02 (Apps cache) | ✅ Исправлен | TTL cache |
| ОПТ-НИЗ-03 (Starlette middleware) | ❓ Не проверял | |

---

## Приоритет исправлений

**Фаза 1 — Сейчас (баги, ломающие функционал):**
1. BUG-01: try/except на Decimal/datetime парсинг
2. BUG-02: OTP TTL — использовать remaining TTL

**Фаза 2 — Скоро (потеря данных, DoS):**
3. BUG-03: Добавить `is_new_application` в модель
4. BUG-04: Лимит на batch suggestion_ids
5. BUG-05: Extrakt данные в dict вместо detached ORM

**Фаза 3 — Плановые улучшения:**
6. BUG-06: Rate limiter memory cleanup
7. BUG-07: Middleware audit → dependency
8. BUG-09: print → logger
9. BUG-10: HTTPException → ValueError в batch
10. BUG-08: Safety return после цикла
11. BUG-11: Debug log в outer handler
