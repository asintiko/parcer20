# Фиксы безопасности клиента — 5 пунктов

---

## 1. Папка с чеками (2025/2026) остаётся открытой навсегда

### Проблема
Scope token (`access_scope_token`) сохраняется в `localStorage` и **не очищается** при:
- Смене года в дропдауне
- Уходе на другую страницу (Автоматизация, Логи, Справочник)
- Закрытии/сворачивании окна
- Перезапуске Electron

Ток scope token кэшируется ещё и в `access_scope_token_cache` (строка 92 api.ts) с TTL 1 час. Даже после logout scope token остаётся.

### Где код

**`TransactionsPage.tsx`**, строки 321-354 — при загрузке пробует восстановить кэшированный scope. Нигде нет cleanup-а.

**`api.ts`**, строка 91-93:
```typescript
const SCOPE_TOKEN_KEY = 'access_scope_token';
const SCOPE_TOKEN_CACHE_KEY = 'access_scope_token_cache';
```

**`api.ts`**, строка 1198-1201 — `securityApi.clearScopeToken()` уже существует, но нигде не вызывается при навигации.

### Что делать

**Файл: `TransactionsPage.tsx`**

После строки `securityApi.pruneScopeTokenCache();` (строка 322) добавить два useEffect:

```typescript
// 1) При смене года — сбросить scope
const prevYearRef = useRef<number | null>(selectedYear);
useEffect(() => {
    if (prevYearRef.current !== null && prevYearRef.current !== selectedYear && scopesEnabled) {
        securityApi.clearScopeToken();
        securityStatusQuery.refetch();
    }
    prevYearRef.current = selectedYear;
}, [selectedYear, scopesEnabled]);

// 2) При уходе со страницы (unmount) — сбросить scope
useEffect(() => {
    return () => {
        if (scopesEnabled) {
            securityApi.clearScopeToken();
        }
    };
}, [scopesEnabled]);
```

Не забудь добавить `useRef` в импорт (в строке 5 уже есть `useRef`).

**Файл: `api.ts`** — опционально, для закрытия окна:

Заменить хранение scope в `localStorage` на `sessionStorage` — тогда при закрытии Electron scope автоматически пропадёт:

```typescript
// Строки 1011, 1148, 1170 — заменить:
localStorage.setItem(SCOPE_TOKEN_KEY, entry.token);
// на:
sessionStorage.setItem(SCOPE_TOKEN_KEY, entry.token);

// Строка 150 — заменить:
const scopeToken = localStorage.getItem(SCOPE_TOKEN_KEY);
// на:
const scopeToken = sessionStorage.getItem(SCOPE_TOKEN_KEY);

// И аналогично все localStorage.removeItem(SCOPE_TOKEN_KEY)
// заменить на sessionStorage.removeItem(SCOPE_TOKEN_KEY)
```

Проверить все места: строки 150, 174, 1011, 1148, 1170, 1199.

---

## 2. Свободный доступ к вкладке Telegram Bots без OTP

### Проблема
В `App.tsx` (строка 160-166) `/userbot` обёрнут в `<ScopeGuard action="sources">`:
```tsx
<ScopeGuard action="sources">
    <UserbotPage />
</ScopeGuard>
```

ScopeGuard проверяет `allow_sources` в текущем scope. Но:
1. Scope token из пункта 1 **не очищается** — если ранее был получен scope с `allow_sources=true`, он остаётся
2. Когда пользователь уходит с `/userbot` и возвращается — ScopeGuard видит старый scope token и пускает без OTP

### Где код

**`ScopeGuard.tsx`**, строка 30-35:
```typescript
const hasAccess = useMemo(() => {
    if (!statusQuery.data?.scopes_enabled) return true;  // если scopes отключены — пускаем всех
    const scope = statusQuery.data?.current_scope;
    if (!scope) return false;
    return action === 'sources' ? Boolean(scope.allow_sources) : Boolean(scope.allow_transactions);
}, [statusQuery.data, action]);
```

### Что делать

**Файл: `ScopeGuard.tsx`**

Добавить cleanup при unmount — сброс scope token:

```typescript
// После строки 72 (закрывающая скобка verifyCodeMutation), добавить:

// При уходе с защищённой страницы — сбросить scope
useEffect(() => {
    return () => {
        securityApi.clearScopeToken();
        queryClient.invalidateQueries({ queryKey: ['security-status'] });
    };
}, [queryClient]);
```

Добавить импорт `securityApi`:
```typescript
import { securityApi } from '../services/api';
```

Теперь при КАЖДОМ уходе с `/userbot` (или любой другой ScopeGuard-защищённой страницы) scope сбрасывается, и при возвращении — снова OTP.

---

## 3. Правая кнопка → "Установить пин" — ничего не происходит

### Проблема
В контекстном меню чата кнопка "Установить пароль" (строка 1597 `UserbotPage.tsx`) вызывает `handleSetChatPassword`, который использует `window.prompt()`:

```typescript
const handleSetChatPassword = (chat: TelegramChat) => {
    const password = window.prompt(`Установить пароль для чата "${chat.title}"`, '');
    if (!password || !password.trim()) return;
    setChatPasswordMutation.mutate({ chatId: chat.chat_id, password: password.trim() });
};
```

**`window.prompt()` не работает в Electron.** Electron по умолчанию блокирует `window.prompt()` (возвращает `null`), поэтому функция сразу выходит на `if (!password) return`.

### Где код

**`UserbotPage.tsx`**, строки 441-451:
- `handleSetChatPassword` → `window.prompt()` → молча возвращает null
- `handleRemoveChatPassword` → `window.prompt()` → молча возвращает null

### Что делать

Заменить `window.prompt()` на модальное окно. У тебя уже есть `ChatPasswordModal` (`components/ChatPasswordModal.tsx`), но он используется только для **ввода пароля при доступе к чату**. Нужно:

**Вариант A (быстрый):** Переиспользовать существующий state для установки пароля:

```typescript
// Заменить handleSetChatPassword (строки 441-445):
const handleSetChatPassword = (chat: TelegramChat) => {
    setPasswordModalChat(chat);
    setPasswordModalOpen(true);
    // Нужно добавить mode='set' для ChatPasswordModal, чтобы отличать
    // "ввести пароль для доступа" от "установить новый пароль"
};
```

**Вариант B (правильный):** Добавить новый стейт и мини-модалку:

```typescript
// Добавить стейты:
const [setPwdModalOpen, setSetPwdModalOpen] = useState(false);
const [setPwdModalChat, setSetPwdModalChat] = useState<TelegramChat | null>(null);
const [newChatPassword, setNewChatPassword] = useState('');

// handleSetChatPassword:
const handleSetChatPassword = (chat: TelegramChat) => {
    setSetPwdModalChat(chat);
    setNewChatPassword('');
    setSetPwdModalOpen(true);
};

// handleRemoveChatPassword:
const handleRemoveChatPassword = (chat: TelegramChat) => {
    // Аналогично — модалка с вводом текущего пароля для снятия
    setPasswordModalChat(chat);
    setPasswordModalOpen(true);
};
```

И в JSX перед закрывающим `</div>` добавить модалку:

```tsx
{setPwdModalOpen && setPwdModalChat && (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
        <div className="bg-surface border border-border rounded-lg p-6 w-[400px] space-y-4">
            <h3 className="text-lg font-semibold">
                Установить пароль для «{setPwdModalChat.title}»
            </h3>
            <input
                type="password"
                value={newChatPassword}
                onChange={(e) => setNewChatPassword(e.target.value)}
                placeholder="Введите пароль"
                className="w-full px-3 py-2 border border-border rounded-md bg-input-bg"
                autoFocus
                onKeyDown={(e) => {
                    if (e.key === 'Enter' && newChatPassword.trim()) {
                        setChatPasswordMutation.mutate({
                            chatId: setPwdModalChat.chat_id,
                            password: newChatPassword.trim(),
                        });
                        setSetPwdModalOpen(false);
                    }
                }}
            />
            <div className="flex gap-2 justify-end">
                <button
                    onClick={() => setSetPwdModalOpen(false)}
                    className="px-4 py-2 text-sm rounded-md border border-border hover:bg-surface-2"
                >
                    Отмена
                </button>
                <button
                    onClick={() => {
                        if (!newChatPassword.trim()) return;
                        setChatPasswordMutation.mutate({
                            chatId: setPwdModalChat.chat_id,
                            password: newChatPassword.trim(),
                        });
                        setSetPwdModalOpen(false);
                    }}
                    disabled={!newChatPassword.trim() || setChatPasswordMutation.isPending}
                    className="px-4 py-2 text-sm rounded-md bg-primary text-white hover:bg-primary/90 disabled:opacity-50"
                >
                    Установить
                </button>
            </div>
        </div>
    </div>
)}
```

Аналогично для `handleRemoveChatPassword` — модалка с полем "Введите текущий пароль для снятия".

---

## 4. Нет экспорта за период — только "Текущий вид" и "Все транзакции"

### Проблема
В `TransactionTable.tsx` экспорт-меню (строки 1405-1421) содержит только 2 кнопки:
- "Экспорт текущего вида" → `exportCurrentView()`
- "Экспорт всех транзакций" → `exportAll()`

Нет опции "За период" (date range export).

### Где код

**`TransactionTable.tsx`**, строки 1405-1422 — dropdown меню экспорта.

**`TransactionTable.tsx`**, строки 1293-1323 — функции `exportCurrentView` и `exportAll`.

**Пропсы компонента** (строки 58-59):
```typescript
exportViewRows?: Transaction[];
exportAllRows?: Transaction[];
```

### Что делать

**Файл: `TransactionTable.tsx`**

1) Добавить стейты для периода экспорта (после строки ~197):
```typescript
const [exportPeriodOpen, setExportPeriodOpen] = useState(false);
const [exportDateFrom, setExportDateFrom] = useState('');
const [exportDateTo, setExportDateTo] = useState('');
```

2) Добавить функцию `exportByPeriod` (после `exportAll`, строка ~1323):
```typescript
const exportByPeriod = useCallback(() => {
    if (!exportDateFrom || !exportDateTo) {
        alert('Укажите период (дата начала и дата конца).');
        return;
    }
    const from = new Date(exportDateFrom);
    const to = new Date(exportDateTo);
    to.setHours(23, 59, 59, 999);

    const allRows = exportAllRows || exportViewRows || table.getPrePaginationRowModel().rows.map(r => r.original);
    const filtered = allRows.filter((tx) => {
        const txDate = tx.transaction_date ? new Date(tx.transaction_date) : null;
        if (!txDate || Number.isNaN(txDate.getTime())) return false;
        return txDate >= from && txDate <= to;
    });

    if (!filtered.length) {
        alert('Нет транзакций за выбранный период.');
        return;
    }

    exportTransactionsToExcel({
        rows: filtered,
        columns: buildExportColumns(),
        columnStyles: columnStyles as any,
        cellStyles: cellStyles as any,
        fileName: `transactions_${exportDateFrom}_${exportDateTo}.xlsx`,
        includeAlternating: true,
    });
    setExportPeriodOpen(false);
    setExportMenuOpen(false);
}, [exportDateFrom, exportDateTo, exportAllRows, exportViewRows, table, columnStyles, cellStyles, buildExportColumns]);
```

3) В JSX dropdown меню (строка ~1408), после кнопки "Экспорт всех транзакций" добавить:
```tsx
<div className="border-t border-border my-1" />
<button
    onClick={() => setExportPeriodOpen((prev) => !prev)}
    className="w-full text-left px-3 py-2 text-sm hover:bg-surface-2"
>
    Экспорт за период
</button>
{exportPeriodOpen && (
    <div className="px-3 py-2 space-y-2">
        <input
            type="date"
            value={exportDateFrom}
            onChange={(e) => setExportDateFrom(e.target.value)}
            className="w-full px-2 py-1 text-sm border border-border rounded bg-input-bg"
        />
        <input
            type="date"
            value={exportDateTo}
            onChange={(e) => setExportDateTo(e.target.value)}
            className="w-full px-2 py-1 text-sm border border-border rounded bg-input-bg"
        />
        <button
            onClick={exportByPeriod}
            disabled={!exportDateFrom || !exportDateTo}
            className="w-full px-2 py-1.5 text-sm rounded bg-primary text-white hover:bg-primary/90 disabled:opacity-50"
        >
            Скачать
        </button>
    </div>
)}
```

---

## 5. Убрать кнопку "Где пароли?" и "+ Новая папка"

### Проблема
В toolbar панели папок (`TransactionsPage.tsx`, строки 633-656) есть:
- Кнопка `+ Новая папка` (строки 633-648)
- Кнопка `Где пароли?` (строки 649-656)

Обе нужно убрать.

### Где код

**`TransactionsPage.tsx`**, строки 612-656 — блок `<div className="mb-3 p-3 bg-surface ...">`:

```tsx
<div className="mb-3 p-3 bg-surface border border-border rounded-lg flex items-center gap-2 flex-wrap">
    <span>Папка (год):</span>
    <select ...> ... </select>
    {selectedYear !== null && (<span>Открыта папка: {selectedYear}</span>)}

    {/* УДАЛИТЬ: кнопка "+ Новая папка" — строки 633-648 */}
    <button onClick={() => { ... }} className="ml-auto ...">
        + Новая папка
    </button>

    {/* УДАЛИТЬ: кнопка "Где пароли?" — строки 649-656 */}
    <button onClick={() => { ... }} className="...">
        Где пароли?
    </button>
</div>
```

### Что делать

**Файл: `TransactionsPage.tsx`**

Удалить строки 633-656 (обе кнопки).

После удаления блок должен выглядеть так:
```tsx
<div className="mb-3 p-3 bg-surface border border-border rounded-lg flex items-center gap-2 flex-wrap">
    <span className="text-sm text-foreground-secondary">Папка (год):</span>
    <select
        value={selectedYear === null ? '' : String(selectedYear)}
        onChange={(e) => {
            const value = e.target.value;
            setSelectedYear(value ? parseInt(value, 10) : null);
        }}
        className="min-w-[180px] px-3 py-1.5 text-sm rounded-md border border-border bg-input-bg text-input-text"
    >
        {availableYears.map((year) => (
            <option key={year} value={year}>
                {year}
            </option>
        ))}
    </select>
    {selectedYear !== null && (
        <span className="text-xs text-foreground-muted ml-1">
            Открыта папка: {selectedYear}
        </span>
    )}
</div>
```

Также удалить весь блок `createYearOpen` (строки 659-706) — форму создания папки, если кнопка убрана, форма не нужна.

И можно удалить неиспользуемые стейты:
```typescript
// Строки 65-69 — больше не нужны:
const [createYearOpen, setCreateYearOpen] = useState(false);
const [newYearValue, setNewYearValue] = useState<string>(...);
const [newYearPassword, setNewYearPassword] = useState('');
const [newYearName, setNewYearName] = useState('');
const [newYearAllowSources, setNewYearAllowSources] = useState(false);
```

И мутацию `createYearScopeMutation` (строки 158-196) — тоже удалить.
