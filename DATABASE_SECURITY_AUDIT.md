# АУДИТ: База данных, локальное хранение, защита от слива

**Дата:** 2026-02-13
**Область:** Серверная БД (PostgreSQL), локальное хранилище (Dexie/IndexedDB), sync API, экспорт, токены

---

## Сводка

| Уровень | Количество |
|---------|-----------|
| CRITICAL | 3 |
| HIGH | 6 |
| MEDIUM | 7 |
| LOW | 3 |
| **ИТОГО** | **19** |

---

## CRITICAL

### DB-КРИТ-01 · IndexedDB не шифруется — все данные в открытом виде

**Файл:** `frontend/src/storage/db.ts`
**Проблема:** Все 12 таблиц (включая `transactions` с `raw_message`, `chatPasswords`, `accessScopes`, `accessAuditLog`) хранятся в IndexedDB без шифрования. Любой процесс на машине, расширение браузера или физический доступ к диску позволяет прочитать ВСЕ финансовые данные.

В Electron-приложении IndexedDB хранится на диске в `~/.config/tbsparcer/IndexedDB/` (Linux) или `~/Library/Application Support/tbsparcer/` (macOS) в формате LevelDB — plaintext.

**Вектор атаки:**
1. Вредоносное расширение Chrome/Electron → читает IndexedDB через JS
2. Физический доступ → копирование файлов LevelDB
3. Малварь на машине → читает файлы напрямую

**Исправление:**
```bash
npm install dexie-encrypted  # или использовать crypto-js + кастомный Dexie middleware
```
Шифровать sensitive-поля (`raw_message`, `amount`, `balance_after`, `operator_raw`, `card_last_4`, `receiver_name`, `receiver_card`) ключом, полученным из launch-пароля или session key.

---

### DB-КРИТ-02 · Данные НЕ очищаются при logout

**Файл:** `frontend/src/contexts/AuthContext.tsx`, строки 59-69
**Проблема:** При logout удаляется ТОЛЬКО `auth_token` из localStorage:
```typescript
localStorage.removeItem('auth_token');
```
Все 12 таблиц в IndexedDB (тысячи транзакций, суммы, операторы, даты) **остаются на диске**. Нет вызова `db.delete()`, `db.transactions.clear()` или аналогов. Нигде в проекте нет кода очистки Dexie — подтверждено grep-ом.

**Исправление:** В `logout()` добавить:
```typescript
import { db } from '../storage/db';

const logout = async () => {
    try { await authApi.logout(); } catch {}
    // Очистка ВСЕХ локальных данных
    await db.delete();
    localStorage.clear();
    setIsAuthenticated(false);
    setUser(null);
};
```

---

### DB-КРИТ-03 · Sync endpoint позволяет выкачать ВСЮ базу без ограничений

**Файл:** `backend/api/routes/sync.py`, строки 250-304
**Проблема:** Endpoint `GET /api/sync/{table_name}` с `limit=20000` позволяет за несколько запросов скачать все данные из любой таблицы. Rate limit — 100 req/min. Расчёт:
- 50 000 транзакций / 20 000 per page = 3 запроса = ~3 секунды
- Все 12 таблиц = ~15-20 запросов = 12 секунд

Единственная защита — `scope` фильтр, который **применяется ТОЛЬКО к таблице `transactions`**. Все остальные 11 таблиц отдаются БЕЗ фильтрации:
```python
if model is Transaction:
    query = _scope_filter_transactions(query, scope)  # только для transactions!
```

**Вектор атаки:** Пользователь с ограниченным scope (например, только 2025 год) может выкачать ВСЕ записи из: `accessScopes`, `accessAuditLog`, `chatPasswords`, `operatorMappings`, `operatorReferences`, `monitoredBotChats`, `hiddenBotChats`, `parsingLogs`, `hourlyReports`, `lockedPeriods`, `receiptProcessingTasks`.

**Исправление:**
1. Sync rate limit: отдельный лимит на sync — например, 10 req/min
2. Per-table access control: `chatPasswords` и `accessAuditLog` НЕ должны синхронизироваться на клиент
3. Убрать `accessAuditLog` из `TABLE_MODELS` — аудит-логи не нужны на клиенте
4. Убрать `chatPasswords` из `TABLE_MODELS` — или синхронизировать только `chat_id` + `locked_until`

---

## HIGH

### DB-ВЫС-01 · `accessAuditLog` синхронизируется на клиент

**Файл:** `sync.py`, строка 50: `"accessAuditLog": AccessAuditLog`
**Проблема:** Аудит-логи содержат: IP-адреса, действия пользователей, ID scope, пути запросов, детали ошибок. Это операционные данные безопасности, которые НЕ должны быть на клиенте.

**Данные в каждой записи:**
- `action` (scope_missing, system_token_invalid, scope_forbidden_transactions...)
- `ip_address`
- `details_json` (path, error messages, scope names)
- `user_id`

**Исправление:** Убрать `"accessAuditLog": AccessAuditLog` из `TABLE_MODELS` в `sync.py`.

---

### DB-ВЫС-02 · `chatPasswords` утекает метаданные замков

**Файл:** `sync.py`, строка 51: `"chatPasswords": ChatPassword`
**Проблема:** Хотя `password_hash`, `salt`, `hash_method` фильтруются через `SENSITIVE_COLUMNS`, синхронизируются:
- `chat_id` — какие чаты защищены паролем
- `failed_attempts` — сколько попыток было сделано
- `locked_until` — когда истекает блокировка

Атакующий видит: "чат 12345678 заблокирован до 14:30, 3 неудачных попытки". Это информация, полезная для тайминг-атаки.

**Исправление:** Убрать `chatPasswords` из `TABLE_MODELS`, или создать отдельный serialize, который отдаёт только `{chat_id, is_locked: bool}`.

---

### DB-ВЫС-03 · Excel-экспорт обходит scope на клиенте

**Файл:** `frontend/src/services/excelExport.ts`, строки 151-174
**Проблема:** Экспорт берёт данные из параметра `rows` (который приходит из Dexie — локальный кэш). Locked periods фильтруются (строки 154-174), но **scope НЕ проверяется вообще**. Если пользователь с ограниченным scope ранее закэшировал данные за другой период, экспорт выгрузит их в Excel.

**Цепочка:**
1. Пользователь логинится с полным scope → sync загружает ВСЕ транзакции в IndexedDB
2. Админ меняет scope пользователя на "только 2025"
3. Пользователь экспортирует → IndexedDB содержит данные за все годы → Excel получает всё

**Исправление:**
1. При смене scope (получении нового scope_token) очищать локальный кэш: `db.transactions.clear()` + re-sync
2. В `excelExport.ts` фильтровать rows по текущему scope token

---

### DB-ВЫС-04 · DATABASE_URL с дефолтными credentials

**Файл:** `backend/database/connection.py`, строка 14
```python
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://uzbek_parser:password@localhost:5432/receipt_parser_db")
```
**Проблема:** Если `.env` файл отсутствует или `DATABASE_URL` не задан, используется пароль `password`. В production это может привести к подключению к БД с дефолтными credentials.

**Исправление:**
```python
DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise EnvironmentError("DATABASE_URL environment variable is required")
```

---

### DB-ВЫС-05 · `api_base_url_override` — redirect-атака через localStorage

**Файл:** `frontend/src/services/api.ts`, строки 19-28
**Проблема:** API base URL можно перенаправить, записав в localStorage ключ `api_base_url_override`:
```typescript
const raw = window.localStorage.getItem('api_base_url_override') || '';
```
Если XSS или вредоносное расширение запишет `api_base_url_override = "https://evil.com"`, ВСЕ API-запросы (включая auth-токены в headers) уйдут на сервер атакующего.

**Исправление:** Убрать `api_base_url_override` в production. Или валидировать, что override URL — это `localhost` / `127.0.0.1`:
```typescript
const isLocalUrl = (url: string) => {
    try {
        const u = new URL(url);
        return ['localhost', '127.0.0.1'].includes(u.hostname);
    } catch { return false; }
};
```

---

### DB-ВЫС-06 · `deleted_ids` в sync не учитывают scope

**Файл:** `sync.py`, строки 207-218, 287-293
**Проблема:** `_load_deleted_ids()` возвращает ID удалённых записей БЕЗ scope-фильтрации. Пользователь с ограниченным scope получает информацию о ВСЕХ удалённых транзакциях, включая те, которые вне его scope. Это раскрывает факт существования и удаления записей.

**Исправление:** Не отдавать deleted_ids для записей вне scope. Или использовать `SyncDeletion` только для записей, которые пользователь ранее мог видеть.

---

## MEDIUM

### DB-СРД-01 · Токены в localStorage уязвимы для XSS

**Файл:** `frontend/src/services/api.ts`, `contexts/AuthContext.tsx`
**Проблема:** Три критичных токена хранятся в localStorage:
- `auth_token` (JWT)
- `system_access_token`
- `access_scope_token`

localStorage доступен из любого JS на том же origin. XSS (даже stored в raw_message, если когда-нибудь рендерится как HTML) = кража всех токенов.

**Исправление (для desktop Electron):**
- Использовать `electron-store` с encryption
- Или передавать токены через `safeStorage` API Electron
- В web-режиме: httpOnly cookies (если есть серверный рендеринг)

---

### DB-СРД-02 · `raw_message` отдаётся в каждом ответе API

**Файл:** `backend/api/routes/transactions.py`, строка 336
```python
raw_message=raw_message
```
**Проблема:** `raw_message` — полный текст SMS/Telegram чека. Может содержать:
- Полные номера карт (до маскировки парсером)
- ФИО получателей
- Адреса и телефоны
- Внутренние коды банка

Он отдаётся в КАЖДОМ GET-запросе (`get_transactions`, `get_transaction`, update-ответах) И через sync endpoint.

**Исправление:**
- Не включать `raw_message` в стандартный list response — только по отдельному запросу `GET /api/transactions/{id}/raw`
- В sync endpoint добавить `raw_message` в `SENSITIVE_COLUMNS` (или отдавать только хэш для верификации)

---

### DB-СРД-03 · `_blocked_transaction_ids` загружает ID в память

**Файл:** `sync.py`, строки 221-234
**Проблема:** `_blocked_transaction_ids` выбирает до 50,000 (по умолчанию) transaction IDs в один список Python. При большой базе это:
1. Долгий SQL-запрос
2. Большой JSON в ответе (50K int ID = ~300KB)
3. Memory pressure на сервере

**Исправление:** Вместо списка ID отправлять `blocked_ranges` (которые уже есть в ответе) — клиент сам удалит записи из IndexedDB по диапазону дат.

---

### DB-СРД-04 · `get_db_session()` не делает auto-commit

**Файл:** `backend/database/connection.py`, строки 49-62
**Проблема:** `get_db_session()` — FastAPI dependency — не вызывает `db.commit()`:
```python
def get_db_session() -> Session:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
```
Каждый route обязан вызывать `db.commit()` вручную. Если забыть — данные не сохранятся, но ошибки не будет. Сейчас все routes делают commit, но это хрупкий паттерн.

**Сравнение с `get_db()`** — контекстный менеджер делает auto-commit:
```python
def get_db():
    db = SessionLocal()
    try:
        yield db
        db.commit()  # ← есть
    except:
        db.rollback()
        raise
```

**Исправление:** Добавить commit/rollback в `get_db_session`:
```python
def get_db_session() -> Session:
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
```

---

### DB-СРД-05 · `SyncDeletion` не ограничена по размеру

**Файл:** `sync.py`, `_load_deleted_ids()`, limit=50000
**Проблема:** `SyncDeletion` таблица растёт бесконечно. При каждом удалении добавляется запись, но нет cleanup-а старых записей. Через год — миллионы записей.

**Исправление:** Cron-задача для удаления записей старше N дней:
```sql
DELETE FROM sync_deletions WHERE deleted_at < NOW() - INTERVAL '30 days';
```

---

### DB-СРД-06 · Frontend sync загружает ВСЮ базу при первом запуске

**Файл:** `frontend/src/hooks/useOfflineTransactions.ts`, строки 131-138
```typescript
if (items.length === 0) {
    await syncFromServer(false);  // full sync
}
```
**Проблема:** При первом запуске (пустой IndexedDB) загружается ВЕСЬ датасет — все транзакции, все таблицы. Нет progressive loading. На базе 100K транзакций это ~50MB+ данных.

**Исправление:** Initial sync с лимитом (последние N месяцев), остальное — по запросу.

---

### DB-СРД-07 · Scope token не ревалидируется при sync

**Файл:** `frontend/src/services/syncManager.ts`
**Проблема:** SyncManager вызывает `syncApi.getManifest()` и затем `syncApi.getTable()` для каждой таблицы. Scope token отправляется через interceptor. Но между началом sync-цикла и его завершением scope может быть отозван/изменён. Данные уже загруженные в IndexedDB остаются, даже если scope больше не действителен.

**Исправление:** После завершения sync цикла перепроверять scope token. При смене scope — очищать IndexedDB и re-sync.

---

## LOW

### DB-НИЗ-01 · Frontend port 5173 не на localhost

**Файл:** `docker-compose.yml`, строка 152
```yaml
ports:
  - "5173:80"  # ← доступен на всех интерфейсах
```
PostgreSQL, Redis, Backend — все на `127.0.0.1`. Frontend — на `0.0.0.0`.

**Исправление:** `"127.0.0.1:5173:80"`

---

### DB-НИЗ-02 · `./backend:/app` монтирует весь исходный код

**Файл:** `docker-compose.yml`, строки 58, 81, 101, 118
**Проблема:** Весь `./backend` монтируется в контейнеры. Если контейнер скомпрометирован, атакующий получает полный исходный код. В production это не нужно — достаточно COPY в Dockerfile.

**Исправление:** Убрать volume mount в production, использовать multi-stage Dockerfile с COPY.

---

### DB-НИЗ-03 · Sync checksum слабый — не обнаруживает перестановки

**Файл:** `sync.py`, строки 122-128
```python
def _rows_checksum(rows, id_column, updated_column):
    digest = hashlib.sha256()
    for row in rows:
        digest.update(f"{row_id}:{updated_val}".encode("utf-8"))
    return "sha256:" + digest.hexdigest()
```
**Проблема:** SHA256 хэш чувствителен к порядку строк (rows уже отсортированы, ок), но основан только на `id` и `updated_at`. Если данные изменились, но `updated_at` не обновился (например, прямой SQL UPDATE без trigger) — checksum не изменится, sync не произойдёт.

**Не критично** — `updated_at` имеет `onupdate=func.now()` на ORM-уровне.

---

## Приоритеты исправлений

### Фаза 1 — Немедленно (утечка данных):
1. **DB-КРИТ-02**: Очистка IndexedDB при logout
2. **DB-КРИТ-03**: Ограничить sync — убрать `accessAuditLog`, `chatPasswords` из TABLE_MODELS
3. **DB-ВЫС-01**: Убрать `accessAuditLog` из sync
4. **DB-ВЫС-02**: Убрать `chatPasswords` из sync (или минимальный payload)
5. **DB-ВЫС-04**: Убрать дефолтный DATABASE_URL

### Фаза 2 — Скоро (защита от слива):
6. **DB-КРИТ-01**: Шифрование IndexedDB (хотя бы sensitive полей)
7. **DB-ВЫС-03**: Scope-фильтрация при Excel-экспорте + очистка при смене scope
8. **DB-ВЫС-05**: Убрать или валидировать `api_base_url_override`
9. **DB-ВЫС-06**: Scope-фильтрация `deleted_ids`
10. **DB-СРД-01**: Токены в secure storage (Electron safeStorage)
11. **DB-СРД-02**: Не отдавать `raw_message` в list-ответах

### Фаза 3 — Плановые:
12. **DB-СРД-03**: `blocked_ranges` вместо `blocked_ids`
13. **DB-СРД-04**: Auto-commit в `get_db_session()`
14. **DB-СРД-05**: Cleanup `SyncDeletion`
15. **DB-СРД-06**: Progressive initial sync
16. **DB-СРД-07**: Ревалидация scope при sync
17. **DB-НИЗ-01**: Frontend port → localhost
18. **DB-НИЗ-02**: Убрать volume mount в prod
19. **DB-НИЗ-03**: Усилить checksum (опционально)
