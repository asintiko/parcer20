# FIX: raw_message не отображается в деталях транзакции

**Дата:** 2026-02-13

---

## Причина

Цепочка данных:

```
sync.py → _serialize_row() → SENSITIVE_COLUMNS пропускает raw_message
  → /api/sync/transactions возвращает rows БЕЗ raw_message
  → syncManager загружает в Dexie (IndexedDB) — raw_message = undefined
  → useOfflineTransactions() → db.transactions.toArray() → Transaction без raw_message
  → TransactionTable.tsx → detailRow.raw_message → undefined → '—'
```

**Строка-виновник:** `backend/api/routes/sync.py`, строка 64:
```python
SENSITIVE_COLUMNS = {"password_hash", "salt", "hash_method", "raw_message"}
```

Это было добавлено в аудите (DB-СРД-02) чтобы не гонять сырые тексты чеков в IndexedDB.

---

## Решение: lazy-загрузка raw_message при открытии деталей

Не убирать `raw_message` из SENSITIVE_COLUMNS (это правильная защита). Вместо этого — подгружать raw_message по отдельному запросу, когда пользователь открывает детальный drawer.

### Шаг 1. Backend — новый лёгкий endpoint

**Файл:** `backend/api/routes/transactions.py`

Добавить endpoint (после `get_transaction`):

```python
@router.get("/{transaction_id}/raw")
async def get_transaction_raw_message(
    transaction_id: int,
    db: Session = Depends(get_db_session),
    current_user: dict = Depends(get_current_user),
    scope: Optional[Dict[str, Any]] = Depends(get_scope_context),
) -> Dict[str, Any]:
    """Return only the raw_message for a transaction."""
    query = db.query(Transaction).filter(Transaction.id == transaction_id)
    query = _apply_scope_to_query(query, scope)
    row = query.first()
    if not row:
        raise HTTPException(status_code=404, detail="Transaction not found")
    return {
        "id": row.id,
        "raw_message": getattr(row, "raw_message", None) or getattr(row, "raw_text", None),
    }
```

**Примечание:** Нужно проверить что `get_scope_context` и `_apply_scope_to_query` уже используются в файле. Если dependency называется по-другому — скопировать из существующего `get_transaction`.

**Альтернатива:** Можно вообще не делать отдельный endpoint, а использовать уже имеющийся `GET /api/transactions/{id}` — он возвращает `TransactionResponse` с `raw_message`. Это проще.

---

### Шаг 2. Frontend — api.ts (если нужен отдельный endpoint)

**Файл:** `frontend/src/services/api.ts`

В `transactionsApi` добавить:

```typescript
getRawMessage: async (id: number): Promise<{ id: number; raw_message: string | null }> => {
    const response = await apiClient.get<{ id: number; raw_message: string | null }>(
        `/api/transactions/${id}/raw`
    );
    return response.data;
},
```

**Или (если используем существующий endpoint):** ничего добавлять не нужно — `transactionsApi.getTransaction(id)` уже есть (строка 502).

---

### Шаг 3. Frontend — TransactionTable.tsx (lazy-load raw_message)

**Файл:** `frontend/src/components/TransactionTable.tsx`

#### 3.1 Добавить state для raw_message и loading

Рядом с `const [detailRow, setDetailRow] = useState<Transaction | null>(null);` (строка 314):

```typescript
const [detailRawMessage, setDetailRawMessage] = useState<string | null>(null);
const [detailRawLoading, setDetailRawLoading] = useState(false);
```

#### 3.2 Добавить импорт

Вверху файла, в импортах из `../services/api`:

```typescript
import { transactionsApi } from '../services/api';
```

(Проверить — возможно уже импортирован.)

#### 3.3 Подгружать raw_message при открытии детали

Добавить `useEffect` после определения состояния:

```typescript
useEffect(() => {
    if (!detailRow) {
        setDetailRawMessage(null);
        return;
    }
    // Если raw_message уже есть в данных (пришёл из API, не из sync) — использовать
    if (detailRow.raw_message) {
        setDetailRawMessage(detailRow.raw_message);
        return;
    }
    // Иначе подгрузить с сервера
    let cancelled = false;
    setDetailRawLoading(true);
    transactionsApi.getTransaction(detailRow.id)
        .then((full) => {
            if (!cancelled) {
                setDetailRawMessage(full.raw_message || null);
            }
        })
        .catch(() => {
            if (!cancelled) {
                setDetailRawMessage(null);
            }
        })
        .finally(() => {
            if (!cancelled) setDetailRawLoading(false);
        });
    return () => { cancelled = true; };
}, [detailRow]);
```

#### 3.4 Обновить отображение в drawer

Строка 1977-1980, текущее:
```tsx
<div className="text-sm font-medium text-foreground">Исходный текст</div>
<div className="border border-border rounded-md bg-surface-2 p-3 text-sm text-foreground max-h-[300px] overflow-auto whitespace-pre-wrap">
    {detailRow.raw_message || '—'}
</div>
```

Заменить на:
```tsx
<div className="text-sm font-medium text-foreground">Исходный текст</div>
<div className="border border-border rounded-md bg-surface-2 p-3 text-sm text-foreground max-h-[300px] overflow-auto whitespace-pre-wrap">
    {detailRawLoading
        ? <span className="text-foreground-secondary animate-pulse">Загрузка…</span>
        : (detailRawMessage || '—')
    }
</div>
```

---

## Сводка

| Файл | Что |
|------|-----|
| `TransactionTable.tsx` | Добавить `detailRawMessage` state + useEffect для lazy-load + обновить отображение |
| `api.ts` | (опционально) Если делать отдельный endpoint — добавить `getRawMessage` |
| `transactions.py` | (опционально) Endpoint `GET /{id}/raw` |

**Минимальный вариант (рекомендуемый):** Только TransactionTable.tsx — использовать существующий `transactionsApi.getTransaction(id)` для подгрузки полной транзакции с `raw_message`.

`SENSITIVE_COLUMNS` в sync.py **не трогать** — raw_message правильно исключён из IndexedDB.
