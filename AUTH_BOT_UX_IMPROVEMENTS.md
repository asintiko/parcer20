# AUTH BOT — UX Нормализация

**Дата:** 2026-02-13
**Файлы:** `backend/services/auth_bot_handler.py`, `backend/services/auth_bot_service.py`
**Фреймворк:** Aiogram 3.4.1

---

## Текущие проблемы

| # | Проблема | Где |
|---|---------|-----|
| 1 | Все 13 команд набираются вручную текстом — нет кнопок | `cmd_start`, все хендлеры |
| 2 | OTP-код приходит plain-text — нельзя тапнуть и скопировать | `_format_event_message` |
| 3 | Подтверждения через `--yes` в конце строки — неудобно, легко забыть | `_has_confirm_flag`, 5 команд |
| 4 | Списки (сессии, периоды, скоупы) — сплошной текст без структуры | `cmd_sessions`, `cmd_list_periods`, `cmd_list_scopes` |
| 5 | Нет главного меню — после `/start` просто стена текста | `cmd_start` |
| 6 | `_broadcast_to_admins` и `_safe_reply` отправляют без `parse_mode` — нет форматирования | все `message.reply()` |

---

## Фаза 1 — Импорты и вспомогательные функции

### 1.1 Добавить импорты Aiogram-клавиатур

**Файл:** `auth_bot_handler.py`, строка 13

Текущее:
```python
from aiogram.types import Message
```

Заменить на:
```python
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
```

### 1.2 Утилита для быстрой сборки inline-клавиатуры

Добавить после строки ~88 (после `_safe_reply`):

```python
def _kb(*rows: list[tuple[str, str]]) -> InlineKeyboardMarkup:
    """
    Собрать InlineKeyboardMarkup из рядов кнопок.
    Каждый ряд — список (text, callback_data).
    """
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=text, callback_data=data) for text, data in row]
            for row in rows
        ]
    )
```

### 1.3 Обновить `_safe_reply` — добавить поддержку parse_mode и reply_markup

Текущее (строка 85-88):
```python
async def _safe_reply(message: Message, text: str) -> None:
    if not _is_admin(message):
        return
    await message.reply(text)
```

Заменить на:
```python
async def _safe_reply(
    message: Message,
    text: str,
    *,
    parse_mode: str = "HTML",
    reply_markup: InlineKeyboardMarkup | None = None,
) -> None:
    if not _is_admin(message):
        return
    await message.reply(text, parse_mode=parse_mode, reply_markup=reply_markup)
```

### 1.4 Обновить `_broadcast_to_admins` — parse_mode + reply_markup

Текущее (строка 91-103):
```python
async def _broadcast_to_admins(
    bot: Bot,
    text: str,
    *,
    exclude_user_id: Optional[int] = None,
) -> None:
```

Заменить на:
```python
async def _broadcast_to_admins(
    bot: Bot,
    text: str,
    *,
    exclude_user_id: Optional[int] = None,
    parse_mode: str = "HTML",
    reply_markup: InlineKeyboardMarkup | None = None,
) -> None:
    for admin_id in AUTH_ADMIN_IDS:
        if exclude_user_id is not None and admin_id == exclude_user_id:
            continue
        try:
            await bot.send_message(
                chat_id=admin_id,
                text=text,
                parse_mode=parse_mode,
                reply_markup=reply_markup,
            )
        except Exception:
            continue
```

---

## Фаза 2 — Главное меню `/start`

### 2.1 Клавиатура главного меню

Заменить тело `cmd_start` (строка 204-226):

```python
async def cmd_start(message: Message) -> None:
    if not _is_admin(message):
        return
    try:
        kb = _kb(
            [("📊 Статус", "menu:status")],
            [("📋 Сессии", "menu:sessions"), ("🧭 Скоупы", "menu:scopes")],
            [("📅 Периоды", "menu:periods"), ("💬 Чат-пароли", "menu:chat_passwords")],
            [("🔐 Пароль запуска", "menu:launch_password")],
        )
        await message.reply(
            "<b>AuthBot</b> — панель управления\n\n"
            "Выбери действие:",
            parse_mode="HTML",
            reply_markup=kb,
        )
        _audit("start", success=True, message=message)
    except Exception as exc:
        await _handle_command_error(message, "start", exc)
```

### 2.2 Вспомогательная: кнопка «Назад в меню»

```python
def _back_button() -> list[tuple[str, str]]:
    return [("◀️ Меню", "menu:main")]
```

---

## Фаза 3 — Callback-роутер

### 3.1 Зарегистрировать callback_query handler

В функции `start_auth_bot()` (строка 657+), ПОСЛЕ всех `dp.message.register(...)`, добавить:

```python
dp.callback_query.register(_handle_callback)
```

### 3.2 Главный диспетчер callback-ов

Добавить новую функцию (после `cmd_kill_session`, перед `start_auth_bot`):

```python
async def _handle_callback(callback: CallbackQuery) -> None:
    """Единый роутер для всех inline-кнопок."""
    if not callback.from_user or callback.from_user.id not in AUTH_ADMIN_IDS:
        await callback.answer("⛔ Нет доступа", show_alert=True)
        return

    data = callback.data or ""
    await callback.answer()  # убрать часики

    # --- Меню ---
    if data == "menu:main":
        kb = _kb(
            [("📊 Статус", "menu:status")],
            [("📋 Сессии", "menu:sessions"), ("🧭 Скоупы", "menu:scopes")],
            [("📅 Периоды", "menu:periods"), ("💬 Чат-пароли", "menu:chat_passwords")],
            [("🔐 Пароль запуска", "menu:launch_password")],
        )
        await callback.message.edit_text(
            "<b>AuthBot</b> — панель управления\n\nВыбери действие:",
            parse_mode="HTML",
            reply_markup=kb,
        )
        return

    if data == "menu:status":
        await _cb_status(callback)
        return

    if data == "menu:sessions":
        await _cb_sessions(callback)
        return

    if data == "menu:scopes":
        await _cb_scopes(callback)
        return

    if data == "menu:periods":
        await _cb_periods(callback)
        return

    if data == "menu:chat_passwords":
        await _cb_chat_passwords(callback)
        return

    if data == "menu:launch_password":
        await callback.message.edit_text(
            "🔐 <b>Пароль запуска</b>\n\n"
            "Для установки отправь команду:\n"
            "<code>/set_launch_password ваш_пароль</code>",
            parse_mode="HTML",
            reply_markup=_kb(_back_button()),
        )
        return

    # --- Действия с сессиями ---
    if data.startswith("kill:"):
        session_id = data[5:]
        await _cb_kill_confirm(callback, session_id)
        return

    if data.startswith("kill_yes:"):
        session_id = data[9:]
        await _cb_kill_execute(callback, session_id)
        return

    # --- Действия со скоупами ---
    if data.startswith("toggle:"):
        scope_id = data[7:]
        await _cb_toggle_scope(callback, scope_id)
        return

    # --- Действия с периодами ---
    if data.startswith("unlock:"):
        lock_id = data[7:]
        await _cb_unlock_confirm(callback, lock_id)
        return

    if data.startswith("unlock_yes:"):
        lock_id = data[11:]
        await _cb_unlock_execute(callback, lock_id)
        return

    # --- Отмена ---
    if data == "cancel":
        await callback.message.edit_text("❌ Отменено.", parse_mode="HTML")
        return
```

---

## Фаза 4 — Callback-хендлеры для каждого раздела

### 4.1 Статус

```python
async def _cb_status(callback: CallbackQuery) -> None:
    db = SessionLocal()
    try:
        active_scopes = db.query(AccessScope).filter(AccessScope.is_active.is_(True)).count()
        active_locks = db.query(LockedPeriod).filter(LockedPeriod.is_active.is_(True)).count()
        chat_protected = db.query(ChatPassword).count()
        launch_set = db.query(AppLaunchConfig).filter(AppLaunchConfig.id == 1).first() is not None
    finally:
        db.close()

    pending_codes = await list_pending_otp_requests(limit=100)
    active_sessions = await list_active_sessions(limit=200)

    text = (
        "📊 <b>Состояние системы</b>\n\n"
        f"🧭 Активные скоупы: <b>{active_scopes}</b>\n"
        f"📅 Заблокированные периоды: <b>{active_locks}</b>\n"
        f"💬 Чаты с паролем: <b>{chat_protected}</b>\n"
        f"🔐 Пароль запуска: <b>{'✅' if launch_set else '❌'}</b>\n"
        f"⏳ Ожидающие OTP: <b>{len(pending_codes)}</b>\n"
        f"📋 Активные сессии: <b>{len(active_sessions)}</b>"
    )
    await callback.message.edit_text(
        text,
        parse_mode="HTML",
        reply_markup=_kb(
            [("🔄 Обновить", "menu:status")],
            _back_button(),
        ),
    )
    _audit("status", success=True, details={"via": "inline_button"})
```

### 4.2 Сессии — список с кнопками Kill

```python
async def _cb_sessions(callback: CallbackQuery) -> None:
    sessions = await list_active_sessions(limit=20)
    otp_requests = await list_pending_otp_requests(limit=10)

    if not sessions and not otp_requests:
        await callback.message.edit_text(
            "📋 <b>Сессии</b>\n\nАктивных сессий и OTP-запросов нет.",
            parse_mode="HTML",
            reply_markup=_kb([("🔄 Обновить", "menu:sessions")], _back_button()),
        )
        return

    lines = ["📋 <b>Активные сессии</b>\n"]
    buttons: list[list[tuple[str, str]]] = []

    for i, s in enumerate(sessions[:10], 1):
        sid = s.get("session_id") or "?"
        short_sid = sid[:12] + "…" if len(sid) > 12 else sid
        kind = s.get("token_kind") or "?"
        ip = s.get("ip_address") or "-"
        lines.append(f"{i}. <code>{short_sid}</code> | {kind} | {ip}")
        # Кнопка kill для каждой сессии
        buttons.append([
            (f"🛑 Kill #{i} ({short_sid})", f"kill:{sid}")
        ])

    if otp_requests:
        lines.append("\n⏳ <b>Ожидающие OTP:</b>")
        for otp in otp_requests[:5]:
            ctx = otp.get("context") if isinstance(otp.get("context"), dict) else {}
            scope_name = ctx.get("scope_name") or ctx.get("scope_id") or "-"
            lines.append(f"  • {otp.get('purpose')} | scope={scope_name} | ttl={otp.get('expires_in')}s")

    buttons.append([("🔄 Обновить", "menu:sessions")])
    buttons.append(_back_button())

    await callback.message.edit_text(
        "\n".join(lines),
        parse_mode="HTML",
        reply_markup=_kb(*buttons),
    )
```

### 4.3 Kill Session — подтверждение через кнопки (замена --yes)

```python
async def _cb_kill_confirm(callback: CallbackQuery, session_id: str) -> None:
    short = session_id[:16] + "…" if len(session_id) > 16 else session_id
    await callback.message.edit_text(
        f"⚠️ Завершить сессию <code>{short}</code>?",
        parse_mode="HTML",
        reply_markup=_kb(
            [("✅ Да, завершить", f"kill_yes:{session_id}"), ("❌ Отмена", "menu:sessions")],
        ),
    )


async def _cb_kill_execute(callback: CallbackQuery, session_id: str) -> None:
    ok, _data = await revoke_active_session(session_id)
    if not ok:
        await callback.message.edit_text(
            "Сессия не найдена или уже завершена.",
            parse_mode="HTML",
            reply_markup=_kb(_back_button()),
        )
        return

    short = session_id[:16] + "…" if len(session_id) > 16 else session_id
    await callback.message.edit_text(
        f"✅ Сессия <code>{short}</code> завершена.",
        parse_mode="HTML",
        reply_markup=_kb([("📋 К сессиям", "menu:sessions")], _back_button()),
    )
    _audit(
        "kill_session",
        success=True,
        details={"session_id": session_id, "via": "inline_button", "admin_id": callback.from_user.id},
    )
    await _broadcast_to_admins(
        callback.bot,
        f"🛑 Сессия <code>{short}</code> завершена админом (tg:{callback.from_user.id})",
        exclude_user_id=callback.from_user.id,
        parse_mode="HTML",
    )
```

### 4.4 Скоупы — список с кнопками Toggle

```python
async def _cb_scopes(callback: CallbackQuery) -> None:
    db = SessionLocal()
    try:
        rows = db.query(AccessScope).order_by(AccessScope.id.asc()).all()
        scope_data = [
            {"id": r.id, "name": r.name, "is_active": r.is_active, "auth_method": r.auth_method}
            for r in rows
        ]
    finally:
        db.close()

    if not scope_data:
        await callback.message.edit_text(
            "🧭 <b>Скоупы</b>\n\nВ БД нет скоупов.",
            parse_mode="HTML",
            reply_markup=_kb(_back_button()),
        )
        return

    lines = ["🧭 <b>Скоупы</b>\n"]
    buttons: list[list[tuple[str, str]]] = []
    for s in scope_data[:20]:
        status = "🟢" if s["is_active"] else "🔴"
        lines.append(f"{status} #{s['id']} <b>{s['name']}</b> | auth={s['auth_method']}")
        toggle_label = f"{'🔴 OFF' if s['is_active'] else '🟢 ON'} #{s['id']}"
        buttons.append([(toggle_label, f"toggle:{s['id']}")])

    buttons.append([("🔄 Обновить", "menu:scopes")])
    buttons.append(_back_button())

    await callback.message.edit_text(
        "\n".join(lines),
        parse_mode="HTML",
        reply_markup=_kb(*buttons),
    )


async def _cb_toggle_scope(callback: CallbackQuery, scope_id_str: str) -> None:
    if not scope_id_str.isdigit():
        return
    scope_id = int(scope_id_str)

    db = SessionLocal()
    try:
        row = db.get(AccessScope, scope_id)
        if row is None:
            await callback.message.edit_text(
                "Скоуп не найден.",
                parse_mode="HTML",
                reply_markup=_kb(_back_button()),
            )
            return
        row.is_active = not bool(row.is_active)
        new_state = bool(row.is_active)
        db.commit()
    finally:
        db.close()

    status = "🟢 Включен" if new_state else "🔴 Выключен"
    await callback.message.edit_text(
        f"Скоуп <b>#{scope_id}</b> → {status}",
        parse_mode="HTML",
        reply_markup=_kb([("🧭 К скоупам", "menu:scopes")], _back_button()),
    )
    _audit("toggle_scope", success=True, details={
        "scope_id": scope_id, "is_active": new_state, "via": "inline_button",
    })
    await _broadcast_to_admins(
        callback.bot,
        f"🧭 Скоуп #{scope_id} → {status} (admin tg:{callback.from_user.id})",
        exclude_user_id=callback.from_user.id,
        parse_mode="HTML",
    )
```

### 4.5 Периоды — список с кнопками Unlock

```python
async def _cb_periods(callback: CallbackQuery) -> None:
    db = SessionLocal()
    try:
        rows: List[LockedPeriod] = (
            db.query(LockedPeriod)
            .order_by(LockedPeriod.is_active.desc(), LockedPeriod.id.desc())
            .limit(30)
            .all()
        )
        period_data = [
            {
                "id": r.id,
                "date_from": r.date_from.isoformat() if r.date_from else "?",
                "date_to": r.date_to.isoformat() if r.date_to else "?",
                "is_active": r.is_active,
                "reason": r.reason or "",
            }
            for r in rows
        ]
    finally:
        db.close()

    if not period_data:
        await callback.message.edit_text(
            "📅 <b>Периоды</b>\n\nЗаблокированных периодов нет.",
            parse_mode="HTML",
            reply_markup=_kb(
                [("➕ Заблокировать", "menu:lock_period_help")],
                _back_button(),
            ),
        )
        return

    lines = ["📅 <b>Заблокированные периоды</b>\n"]
    buttons: list[list[tuple[str, str]]] = []
    for p in period_data[:15]:
        status = "🟢 ACTIVE" if p["is_active"] else "⚪ OFF"
        reason = f' — {p["reason"]}' if p["reason"] else ""
        lines.append(f"#{p['id']} {p['date_from']}..{p['date_to']} {status}{reason}")
        if p["is_active"]:
            buttons.append([(f"🔓 Снять #{p['id']}", f"unlock:{p['id']}")])

    buttons.append([("➕ Заблокировать", "menu:lock_period_help")])
    buttons.append([("🔄 Обновить", "menu:periods")])
    buttons.append(_back_button())

    await callback.message.edit_text(
        "\n".join(lines),
        parse_mode="HTML",
        reply_markup=_kb(*buttons),
    )


async def _cb_unlock_confirm(callback: CallbackQuery, lock_id_str: str) -> None:
    await callback.message.edit_text(
        f"⚠️ Снять блокировку периода <b>#{lock_id_str}</b>?",
        parse_mode="HTML",
        reply_markup=_kb(
            [("✅ Да, снять", f"unlock_yes:{lock_id_str}"), ("❌ Отмена", "menu:periods")],
        ),
    )


async def _cb_unlock_execute(callback: CallbackQuery, lock_id_str: str) -> None:
    if not lock_id_str.isdigit():
        return
    lock_id = int(lock_id_str)

    db = SessionLocal()
    try:
        row = db.get(LockedPeriod, lock_id)
        if row is None:
            await callback.message.edit_text(
                "Блокировка не найдена.",
                parse_mode="HTML",
                reply_markup=_kb(_back_button()),
            )
            return
        row.is_active = False
        db.commit()
    finally:
        db.close()

    await callback.message.edit_text(
        f"✅ Блокировка <b>#{lock_id}</b> снята.",
        parse_mode="HTML",
        reply_markup=_kb([("📅 К периодам", "menu:periods")], _back_button()),
    )
    _audit("unlock_period", success=True, details={"lock_id": lock_id, "via": "inline_button"})
    await _broadcast_to_admins(
        callback.bot,
        f"📅 Блокировка #{lock_id} снята (admin tg:{callback.from_user.id})",
        exclude_user_id=callback.from_user.id,
        parse_mode="HTML",
    )
```

### 4.6 Чат-пароли — список

```python
async def _cb_chat_passwords(callback: CallbackQuery) -> None:
    db = SessionLocal()
    try:
        rows = db.query(ChatPassword).order_by(ChatPassword.chat_id.asc()).limit(50).all()
        titles = {
            int(r.chat_id): (r.chat_title or "").strip()
            for r in db.query(MonitoredBotChat).all()
        }
        cp_data = [
            {
                "chat_id": r.chat_id,
                "title": titles.get(int(r.chat_id)) or "чат",
                "failed": r.failed_attempts,
                "locked_until": r.locked_until.isoformat() if r.locked_until else None,
            }
            for r in rows
        ]
    finally:
        db.close()

    if not cp_data:
        await callback.message.edit_text(
            "💬 <b>Чат-пароли</b>\n\nЗащищенных чатов нет.",
            parse_mode="HTML",
            reply_markup=_kb(_back_button()),
        )
        return

    lines = ["💬 <b>Защищенные чаты</b>\n"]
    for c in cp_data:
        lock_info = f" | 🔒 до {c['locked_until']}" if c["locked_until"] else ""
        lines.append(f"• <b>{c['title']}</b> (<code>{c['chat_id']}</code>) | fails={c['failed']}{lock_info}")

    lines.append("\nУправление:")
    lines.append("<code>/set_chat_password chat_id пароль</code>")
    lines.append("<code>/remove_chat_password chat_id</code>")

    await callback.message.edit_text(
        "\n".join(lines),
        parse_mode="HTML",
        reply_markup=_kb([("🔄 Обновить", "menu:chat_passwords")], _back_button()),
    )
```

### 4.7 Подсказка для lock_period (callback `menu:lock_period_help`)

В `_handle_callback` добавить ещё один блок:

```python
if data == "menu:lock_period_help":
    await callback.message.edit_text(
        "📅 <b>Блокировка периода</b>\n\n"
        "Отправь команду:\n"
        "<code>/lock_period 2026-01-01 2026-01-31 причина</code>\n\n"
        "Форматы дат: YYYY-MM-DD, DD.MM.YYYY",
        parse_mode="HTML",
        reply_markup=_kb(_back_button()),
    )
    return
```

---

## Фаза 5 — OTP-уведомления: копируемый код

### 5.1 Переписать `_format_event_message`

Текущее (строка 123-147) возвращает plain-text.
Заменить на HTML-версию с `<code>` тегами:

```python
def _format_event_message(event: str, payload: Dict[str, Any]) -> Optional[str]:
    if event == "scope_code_requested":
        scope_name = payload.get("scope_name") or payload.get("scope") or "scope"
        ip_address = payload.get("ip") or "unknown"
        code = payload.get("code") or "------"
        expires_in = int(payload.get("expires_in") or 120)
        return (
            f'🔐 <b>Запрос доступа</b>\n\n'
            f'Скоуп: <b>{scope_name}</b>\n'
            f'IP: <code>{ip_address}</code>\n\n'
            f'Код: <code>{code}</code>\n\n'
            f'⏱ Действует {expires_in} сек'
        )
    if event == "scope_code_invalid":
        return (
            f'⚠️ <b>Неверный OTP-код</b>\n\n'
            f'IP: <code>{payload.get("ip") or "unknown"}</code>\n'
            f'Скоуп: <b>{payload.get("scope_name") or "scope"}</b>'
        )
    if event == "scope_code_verified":
        return (
            f'✅ <b>OTP подтвержден</b>\n\n'
            f'IP: <code>{payload.get("ip") or "unknown"}</code>\n'
            f'Скоуп: <b>{payload.get("scope_name") or "scope"}</b>'
        )
    return None
```

### 5.2 Обновить `_notification_listener` — передать parse_mode

Строка 173-174, текущее:
```python
if notify_text:
    await _broadcast_to_admins(bot, notify_text)
```

Заменить на:
```python
if notify_text:
    await _broadcast_to_admins(bot, notify_text, parse_mode="HTML")
```

### Результат

Когда придёт OTP-код, пользователь увидит:

```
🔐 Запрос доступа

Скоуп: finance_read
IP: 192.168.1.45

Код: 847293

⏱ Действует 120 сек
```

Где `847293` и IP будут в моноширинном блоке — **тап = копирование** в Telegram.

---

## Фаза 6 — Текстовые команды: обновить форматирование

Текстовые команды `/lock_period`, `/set_launch_password`, `/set_chat_password`, `/remove_chat_password` оставить для ручного ввода (их нельзя полностью перевести на кнопки — нужен текстовый аргумент).

Но обновить ответы: добавить `parse_mode="HTML"` и inline-кнопку «Назад».

### 6.1 Пример: `cmd_lock_period` — форматирование ответа

Строка 345, текущее:
```python
await message.reply(f"Период заблокирован: id={lock_id}, {d_from} — {d_to}")
```

Заменить на:
```python
await message.reply(
    f"✅ Период заблокирован\n\n"
    f"ID: <b>#{lock_id}</b>\n"
    f"Даты: <b>{d_from}</b> — <b>{d_to}</b>",
    parse_mode="HTML",
    reply_markup=_kb([("📅 Периоды", "menu:periods")], _back_button()),
)
```

### 6.2 Аналогично обновить все ответы текстовых команд

| Команда | Строка | Что менять |
|---------|--------|-----------|
| `cmd_set_launch_password` | 301 | Добавить `parse_mode="HTML"`, кнопку «Меню» |
| `cmd_unlock_period` | 387 | `parse_mode="HTML"`, кнопку «📅 Периоды» |
| `cmd_set_chat_password` | 515 | `parse_mode="HTML"`, кнопку «💬 Чат-пароли» |
| `cmd_remove_chat_password` | 551 | `parse_mode="HTML"`, кнопку «💬 Чат-пароли» |
| `cmd_toggle_scope` | 475 | `parse_mode="HTML"`, кнопку «🧭 Скоупы» |
| `cmd_kill_session` | 646 | `parse_mode="HTML"`, кнопку «📋 Сессии» |

Паттерн одинаковый — добавить `parse_mode="HTML"` и `reply_markup=_kb(...)` в `message.reply()`.

---

## Фаза 7 — Удалить `_has_confirm_flag` и `--yes` логику

### 7.1 Команды с `--yes` подтверждением

Сейчас 5 команд требуют `--yes`:
- `cmd_set_launch_password` (строка 271)
- `cmd_unlock_period` (строка 371)
- `cmd_remove_chat_password` (строка 535)
- `cmd_kill_session` (строка 636)

### 7.2 Стратегия

Для команд которые теперь дублируются кнопками (kill_session, unlock_period) — `--yes` можно убрать, т.к. подтверждение идёт через inline-кнопки.

Но текстовые команды тоже должны работать (для backward compatibility и для скриптов). Поэтому **оставить `--yes` для текстовых команд**, но добавить подсказку:

```python
if not _has_confirm_flag(message):
    await message.reply(
        "⚠️ Подтверди действие: повтори с <code>--yes</code>\n\n"
        "Или используй кнопки в /start",
        parse_mode="HTML",
    )
    return
```

---

## Фаза 8 — Startup-уведомление с кнопкой

### 8.1 Обновить стартовое сообщение

В `start_auth_bot()`, строка 682:

Текущее:
```python
await _broadcast_to_admins(bot, "✅ AuthBot запущен и готов к работе")
```

Заменить на:
```python
await _broadcast_to_admins(
    bot,
    "✅ <b>AuthBot запущен</b> и готов к работе",
    parse_mode="HTML",
    reply_markup=_kb([("📊 Открыть панель", "menu:main")]),
)
```

---

## Сводка изменений

| Что | Файл | Строки |
|-----|------|--------|
| Добавить импорты `CallbackQuery`, `InlineKeyboardButton`, `InlineKeyboardMarkup` | `auth_bot_handler.py` | 13 |
| Добавить `_kb()` и `_back_button()` | `auth_bot_handler.py` | новые ~90 |
| Обновить `_safe_reply` — `parse_mode` + `reply_markup` | `auth_bot_handler.py` | 85-88 |
| Обновить `_broadcast_to_admins` — `parse_mode` + `reply_markup` | `auth_bot_handler.py` | 91-103 |
| Переписать `cmd_start` — главное меню с кнопками | `auth_bot_handler.py` | 204-226 |
| Переписать `_format_event_message` — HTML + `<code>` для OTP | `auth_bot_handler.py` | 123-147 |
| Обновить `_notification_listener` — передать `parse_mode` | `auth_bot_handler.py` | 173-174 |
| Добавить `_handle_callback` — единый callback-роутер | `auth_bot_handler.py` | новая |
| Добавить 10+ callback-хендлеров (`_cb_status`, `_cb_sessions`, и т.д.) | `auth_bot_handler.py` | новые |
| Зарегистрировать `dp.callback_query.register(_handle_callback)` | `auth_bot_handler.py` | ~679 |
| Обновить стартовое уведомление — кнопка «Открыть панель» | `auth_bot_handler.py` | 682 |
| Обновить ответы всех текстовых команд — `parse_mode="HTML"` | `auth_bot_handler.py` | все reply() |

### В `auth_bot_service.py` — изменения НЕ нужны

Сервисный слой (`OTPManager`, `list_active_sessions`, `revoke_active_session`) уже полностью готов. Все изменения только в handler-файле.

---

## Порядок реализации

1. Фаза 1 — импорты + утилиты `_kb`, `_back_button`, обновить `_safe_reply` / `_broadcast_to_admins`
2. Фаза 5 — OTP-форматирование (самое заметное улучшение, можно сразу протестить)
3. Фаза 2 — главное меню `/start`
4. Фаза 3 — callback-роутер `_handle_callback`
5. Фаза 4 — callback-хендлеры по разделам (sessions → scopes → periods → chat_passwords)
6. Фаза 6 — HTML-форматирование текстовых команд
7. Фаза 7 — обновить подсказки `--yes`
8. Фаза 8 — стартовое уведомление с кнопкой

---

## Важные заметки

1. **`callback_data` ограничен 64 байтами** — session_id (hex 32 символа) + prefix `kill:` = 37 байт, укладывается.

2. **`edit_text` может выбросить `MessageNotModified`** — обернуть в try/except:
```python
from aiogram.exceptions import TelegramBadRequest
# в каждом edit_text:
try:
    await callback.message.edit_text(...)
except TelegramBadRequest:
    pass  # сообщение не изменилось
```

3. **HTML parse_mode** — экранировать `<`, `>`, `&` в пользовательских данных:
```python
from html import escape as html_escape
# использовать html_escape(user_input) в f-строках
```

4. **Длина сообщения Telegram** — макс. 4096 символов. Для длинных списков сессий/скоупов — ограничить `[:10]` или `[:15]` и показать кнопку «Ещё».
