# SESSION LIFECYCLE — Реальная работа сессий

**Дата:** 2026-02-13
**Цель:** Пароль → сессия → бот видит сессию → kill → приложение блокируется

---

## Что уже работает

| Компонент | Что есть | Где |
|-----------|---------|-----|
| Пароль запуска | Ввод, хеширование, lockout после 5 попыток | `security.py` строки 807-874 |
| JWT-токен сессии | `create_launch_session_token()`, sid + ip + exp | `auth_bot_service.py` строки 376-386 |
| Регистрация сессии | `register_active_session()` → Redis hash + sorted set | `auth_bot_service.py` строки 181-216 |
| Middleware валидация | `LaunchSessionMiddleware` проверяет `X-Launch-Session` на каждом запросе | `main.py` строки 207-253 |
| Проверка отзыва | `_is_session_revoked()` → Redis key `auth:sessions:revoked:{sid}` | `auth_bot_service.py` строки 154-162 |
| Отзыв сессии | `revoke_active_session()` → ставит revoked-флаг в Redis | `auth_bot_service.py` строки 253-270 |
| Бот: Kill через кнопки | `_cb_kill_execute` → `revoke_active_session()` | `auth_bot_handler.py` |
| LaunchGate UI | Форма ввода пароля, lockout-таймер | `LaunchGate.tsx` |
| Токен в памяти | `launchSessionToken` отправляется в `X-Launch-Session` header | `api.ts` строки 111, 233 |

---

## Что НЕ работает (разрывы цепочки)

### Разрыв 1: Фронтенд не обрабатывает `launch_expired`

**Проблема:** Middleware возвращает `403 { "error": "launch_expired" }` когда сессия отозвана. Но interceptor в `api.ts` (строка 242-258) обрабатывает только:
- `401` → сбрасывает auth token
- `403` со scope → сбрасывает scope token

**Launch session 403 — игнорируется.** Приложение продолжает показывать интерфейс, просто все API-вызовы начинают фейлиться.

### Разрыв 2: Нет возврата на LaunchGate

**Проблема:** `launchUnlocked` в `App.tsx` (строка 184) — это `useState(false)` без обратного сброса. Даже если frontend обнаружит что сессия отозвана, нет механизма вернуть `launchUnlocked = false`.

### Разрыв 3: Нет real-time push

**Проблема:** Приложение узнаёт об отзыве только при следующем API-запросе. Если пользователь ничего не делает — приложение остаётся "открытым" бесконечно.

### Разрыв 4: Бот не показывает детали сессии

**Проблема:** В списке сессий показывается session_id, kind, IP. Но нет привязки к конкретному действию (кто ввёл пароль, когда). Нет кнопки "Kill All".

---

## Фаза 1 — Фронтенд: обработка `launch_expired`

### 1.1 Добавить глобальный callback для сброса LaunchGate

**Файл:** `frontend/src/services/api.ts`

Добавить после строки 111 (после `let launchSessionToken`):

```typescript
/** Callback для принудительной блокировки приложения при отзыве сессии */
let onLaunchSessionRevoked: (() => void) | null = null;

export const setOnLaunchSessionRevoked = (callback: (() => void) | null) => {
    onLaunchSessionRevoked = callback;
};
```

### 1.2 Обновить response interceptor — ловить `launch_expired`

**Файл:** `frontend/src/services/api.ts`, строки 242-258

Текущий interceptor обрабатывает 401 и 403-scope. Добавить обработку 403-launch:

```typescript
apiClient.interceptors.response.use(
    (response) => response,
    (error) => {
        if (error.response?.status === 401) {
            setAuthToken(null);
        }
        if (error.response?.status === 403) {
            const detail = error.response?.data?.detail;
            // --- НОВОЕ: отзыв launch-сессии ---
            const errorCode = typeof detail === 'object' ? detail?.error :
                              typeof detail === 'string' ? detail : null;
            if (errorCode === 'launch_expired' || errorCode === 'launch_required') {
                setLaunchSessionToken(null);
                if (onLaunchSessionRevoked) {
                    onLaunchSessionRevoked();
                }
            }
            // --- scope обработка (оставить как есть) ---
            if (typeof detail === 'string' && detail.toLowerCase().includes('scope')) {
                sessionStorage.removeItem(SCOPE_TOKEN_KEY);
                localStorage.removeItem(SCOPE_TOKEN_KEY);
            }
        }
        return Promise.reject(error);
    }
);
```

### 1.3 Подключить callback в App.tsx

**Файл:** `frontend/src/App.tsx`

Импортировать:
```typescript
import { setOnLaunchSessionRevoked } from './services/api';
```

В компоненте `App`, после `const [launchUnlocked, setLaunchUnlocked] = useState(false);`:

```typescript
useEffect(() => {
    setOnLaunchSessionRevoked(() => {
        setLaunchUnlocked(false);
    });
    return () => setOnLaunchSessionRevoked(null);
}, []);
```

### Результат Фазы 1

Цепочка: Admin жмёт "Kill" в боте → `revoke_active_session()` → Redis ставит revoked-флаг → следующий API-запрос приложения → middleware возвращает 403 `launch_expired` → interceptor ловит → `onLaunchSessionRevoked()` → `setLaunchUnlocked(false)` → приложение показывает LaunchGate → **пользователь заблокирован**.

---

## Фаза 2 — Heartbeat: регулярная проверка валидности сессии

### Зачем

Без heartbeat приложение узнает об отзыве только при следующем действии пользователя. Если пользователь просто смотрит на экран — приложение остаётся открытым.

### 2.1 Новый endpoint на бэкенде

**Файл:** `backend/api/routes/security.py`

Добавить эндпоинт (после `get_launch_status`):

```python
@router.get("/app/launch-heartbeat")
async def launch_heartbeat(
    request: Request,
    x_launch_session: Optional[str] = Header(None, alias="X-Launch-Session"),
    _system: Optional[Dict[str, Any]] = Depends(get_system_access_context),
) -> Dict[str, Any]:
    """Lightweight session validity check."""
    if not x_launch_session:
        raise HTTPException(status_code=403, detail={"error": "launch_required"})
    payload = verify_launch_session_token(x_launch_session)
    if not payload:
        raise HTTPException(status_code=403, detail={"error": "launch_expired"})
    exp = payload.get("exp")
    return {
        "valid": True,
        "session_id": payload.get("sid"),
        "expires_at": datetime.utcfromtimestamp(exp).isoformat() + "Z" if exp else None,
    }
```

Добавить в `LaunchSessionMiddleware.EXEMPT_PATHS`:
```python
"/api/security/app/launch-heartbeat",
```

**Важно:** Heartbeat должен быть в EXEMPT_PATHS middleware, потому что он сам проверяет токен и возвращает правильную ошибку. Middleware для exempt-путей не проверяет — а нам нужна именно проверка внутри endpoint.

Либо НЕ добавлять в exempt и позволить middleware сделать проверку — тогда endpoint просто не будет вызван при отзыве. Middleware уже вернёт 403 `launch_expired`. **Этот вариант проще** — endpoint тогда вообще не нужен, фронтенд просто пингует любой API-путь.

### 2.2 Выбор: отдельный endpoint vs heartbeat через существующий

**Рекомендация:** Использовать существующий `/api/security/status` как heartbeat. Он уже вызывается фронтендом, лёгкий, и middleware уже его проверяет.

### 2.3 Heartbeat-интервал на фронтенде

**Файл:** `frontend/src/App.tsx`

Добавить в `App` компонент, после useEffect с `setOnLaunchSessionRevoked`:

```typescript
useEffect(() => {
    if (!launchUnlocked) return;

    const HEARTBEAT_INTERVAL_MS = 30_000; // 30 сек
    let timer: ReturnType<typeof setInterval>;

    const heartbeat = async () => {
        try {
            await securityApi.getStatus(); // любой API-вызов
        } catch {
            // interceptor сам обработает 403 launch_expired
        }
    };

    timer = setInterval(heartbeat, HEARTBEAT_INTERVAL_MS);
    return () => clearInterval(timer);
}, [launchUnlocked]);
```

### Результат Фазы 2

Каждые 30 секунд фронтенд пингует бэкенд. Если сессия отозвана — middleware вернёт 403 → interceptor сработает → приложение заблокируется.

**Максимальная задержка блокировки:** 30 секунд.

---

## Фаза 3 — Бот: улучшение отображения сессий

### 3.1 Расширить данные в `register_active_session`

**Файл:** `backend/services/auth_bot_service.py`, функция `register_active_session` (строка 181)

В `mapping` хеша Redis добавить поле `description`:

```python
await redis_client.hset(
    _session_key(session_id),
    mapping={
        "session_id": session_id,
        "token_kind": token_kind,
        "subject": subject or "",
        "user_id": str(user_id) if user_id is not None else "",
        "ip_address": ip_address or "",
        "created_at": now.isoformat(),
        "expires_at": expires_at.isoformat(),
        "exp_ts": str(int(expires_at.timestamp())),
        "description": subject or token_kind,   # <-- НОВОЕ
    },
)
```

### 3.2 Обновить `_cb_sessions` — показывать время жизни

В `auth_bot_handler.py`, в функции `_cb_sessions`, обновить формат строки сессии:

Текущее:
```python
lines.append(f"{i}. <code>{html_escape(short_sid)}</code> | {kind} | {ip}")
```

Заменить на:
```python
created = html_escape(str(row.get("created_at") or "-"))[:16]
exp = html_escape(str(row.get("expires_at") or "-"))[:16]
lines.append(
    f"{i}. <code>{html_escape(short_sid)}</code>\n"
    f"   {kind} | {ip}\n"
    f"   🕐 {created} → {exp}"
)
```

### 3.3 Добавить кнопку "Kill All" (экстренная блокировка)

В `_cb_sessions`, перед кнопкой «🔄 Обновить»:

```python
if sessions:
    buttons.append([("🛑 Kill All", "kill_all:confirm")])
```

В `_handle_callback`, добавить обработчики:

```python
if data == "kill_all:confirm":
    sessions = await list_active_sessions(limit=50)
    count = len(sessions)
    await _safe_edit_text(
        callback,
        f"⚠️ Завершить <b>ВСЕ {count}</b> активные сессии?",
        reply_markup=_kb(
            [("✅ Да, Kill All", "kill_all:execute"), ("❌ Отмена", "menu:sessions")],
        ),
    )
    return

if data == "kill_all:execute":
    sessions = await list_active_sessions(limit=100)
    killed = 0
    for s in sessions:
        sid = s.get("session_id")
        if sid:
            ok, _ = await revoke_active_session(sid)
            if ok:
                killed += 1
    await _safe_edit_text(
        callback,
        f"✅ Завершено сессий: <b>{killed}</b>",
        reply_markup=_kb([("📋 К сессиям", "menu:sessions")], _back_button()),
    )
    _audit(
        "kill_all_sessions",
        success=True,
        details={"killed": killed, "via": "inline_button", "admin_id": _callback_user_id(callback)},
    )
    await _broadcast_to_admins(
        callback.bot,
        f"🛑 Все сессии ({killed} шт.) завершены (admin tg:{_callback_user_id(callback)})",
        exclude_user_id=_callback_user_id(callback),
        parse_mode="HTML",
    )
    return
```

---

## Фаза 4 — Уведомление в боте при создании сессии

### 4.1 Publish событие при verify-launch

**Файл:** `backend/api/routes/security.py`, функция `verify_launch_password`, после `register_active_session()`:

```python
# После строки с register_active_session (строка ~855):
await publish_auth_event(
    "launch_session_created",
    {
        "session_id": decoded.get("sid"),
        "ip": _request_ip(request),
        "expires_at": datetime.utcfromtimestamp(exp).isoformat() + "Z" if exp else None,
    },
)
```

### 4.2 Обработать событие в `_format_event_message`

**Файл:** `auth_bot_handler.py`, функция `_format_event_message`, добавить новый блок:

```python
if event == "launch_session_created":
    ip_address = html_escape(str(payload.get("ip") or "unknown"))
    sid = html_escape(str(payload.get("session_id") or "?")[:16])
    expires_at = html_escape(str(payload.get("expires_at") or "-")[:19])
    return (
        "🚀 <b>Новая сессия запуска</b>\n\n"
        f"IP: <code>{ip_address}</code>\n"
        f"SID: <code>{sid}</code>\n"
        f"Истекает: {expires_at}"
    )
```

### 4.3 Добавить inline-кнопку Kill прямо в уведомлении

В `_notification_listener`, обновить блок отправки:

```python
if notify_text:
    reply_markup = None
    # Для новых сессий — кнопка Kill прямо в уведомлении
    if event == "launch_session_created":
        sid = str(payload.get("session_id") or "")
        if sid:
            reply_markup = _kb([(f"🛑 Kill", f"kill:{sid}")])
    await _broadcast_to_admins(
        bot, notify_text, parse_mode="HTML", reply_markup=reply_markup,
    )
```

### Результат Фазы 4

Когда пользователь вводит пароль запуска:
1. Админ получает уведомление "🚀 Новая сессия запуска" с IP
2. Прямо под уведомлением — кнопка 🛑 Kill
3. Админ нажимает Kill → подтверждение → сессия отозвана → приложение пользователя блокируется

---

## Фаза 5 — Событие session_revoked → уведомление в боте

### 5.1 Publish событие при revoke

**Файл:** `backend/services/auth_bot_service.py`, функция `revoke_active_session`, перед `return True, data`:

```python
# Перед return True, data (строка 270):
try:
    channel_msg = json.dumps({
        "event": "session_revoked",
        "payload": {
            "session_id": sid,
            "token_kind": data.get("token_kind", ""),
            "ip_address": data.get("ip_address", ""),
        },
        "ts": datetime.utcnow().isoformat(),
    }, ensure_ascii=False)
    await redis_client.publish(AUTH_EVENT_CHANNEL, channel_msg)
except Exception:
    pass
```

### 5.2 Обработать в `_format_event_message`

```python
if event == "session_revoked":
    sid = html_escape(str(payload.get("session_id") or "?")[:16])
    ip_address = html_escape(str(payload.get("ip_address") or "-"))
    kind = html_escape(str(payload.get("token_kind") or "-"))
    return (
        "🛑 <b>Сессия завершена</b>\n\n"
        f"SID: <code>{sid}</code>\n"
        f"Тип: {kind}\n"
        f"IP: <code>{ip_address}</code>"
    )
```

---

## Полная цепочка (после всех фаз)

```
1. Пользователь вводит пароль в LaunchGate
   ↓
2. POST /api/security/app/verify-launch
   ↓
3. Backend: create_launch_session_token() + register_active_session()
   ↓
4. Backend: publish "launch_session_created" → Redis pub/sub
   ↓
5. Бот: получает уведомление "🚀 Новая сессия" + кнопка Kill
   ↓
6. Админ нажимает 🛑 Kill → подтверждение → _cb_kill_execute()
   ↓
7. revoke_active_session() → Redis: ставит revoked-флаг
   ↓
8. revoke_active_session() → publish "session_revoked" → бот уведомляет
   ↓
9. Фронтенд (heartbeat каждые 30с ИЛИ любой запрос пользователя):
   → middleware проверяет X-Launch-Session → видит revoked → 403 launch_expired
   ↓
10. Interceptor ловит 403 launch_expired → onLaunchSessionRevoked()
    ↓
11. App.tsx: setLaunchUnlocked(false) → рендерит LaunchGate
    ↓
12. Приложение ЗАБЛОКИРОВАНО. Пользователь видит экран ввода пароля.
```

---

## Сводка изменений по файлам

| Файл | Что менять |
|------|-----------|
| `frontend/src/services/api.ts` | Добавить `onLaunchSessionRevoked` callback; обновить response interceptor для 403 `launch_expired` |
| `frontend/src/App.tsx` | Подключить `setOnLaunchSessionRevoked`; добавить heartbeat useEffect |
| `backend/api/routes/security.py` | Добавить `publish_auth_event("launch_session_created")` после создания сессии |
| `backend/services/auth_bot_service.py` | Добавить `publish("session_revoked")` в `revoke_active_session()`; добавить `description` в session hash |
| `backend/services/auth_bot_handler.py` | Добавить обработку `launch_session_created` и `session_revoked` в `_format_event_message`; добавить Kill кнопку в уведомление; добавить Kill All; обновить формат сессий |
| `backend/api/main.py` | (опционально) `/api/security/app/launch-heartbeat` в EXEMPT_PATHS — **не нужно** если используем существующий endpoint |

### Порядок реализации

1. **Фаза 1** — interceptor + callback → самое критичное, замыкает цепочку
2. **Фаза 2** — heartbeat → убирает задержку обнаружения
3. **Фаза 4** — уведомление о новой сессии → админ видит кто зашёл
4. **Фаза 5** — уведомление об отзыве → полная обратная связь
5. **Фаза 3** — улучшение отображения + Kill All → удобство

---

## Дополнительно: LaunchGate — сообщение об отзыве

Когда пользователя выкидывает на LaunchGate после revoke, он не понимает почему. Добавить prop:

**Файл:** `frontend/src/pages/LaunchGate.tsx`

```typescript
type LaunchGateProps = {
    onUnlocked: () => void;
    revokedMessage?: string | null;  // <-- НОВОЕ
};
```

В `App.tsx`:
```typescript
const [revokedMsg, setRevokedMsg] = useState<string | null>(null);

// В setOnLaunchSessionRevoked:
setOnLaunchSessionRevoked(() => {
    setRevokedMsg('Сессия завершена администратором');
    setLaunchUnlocked(false);
});

// В рендере:
<LaunchGate
    onUnlocked={() => { setLaunchUnlocked(true); setRevokedMsg(null); }}
    revokedMessage={revokedMsg}
/>
```

В `LaunchGate.tsx` — показать сообщение:
```typescript
{revokedMessage && (
    <div style={{ color: '#ef4444', fontWeight: 600, marginBottom: 12, textAlign: 'center' }}>
        🛑 {revokedMessage}
    </div>
)}
```
