"""Telegram AuthBot command handlers."""
from __future__ import annotations

import asyncio
import json
import os
from contextlib import suppress
from datetime import date, datetime
from html import escape as html_escape
from typing import Any, Dict, List, Optional

from aiogram import Bot, Dispatcher
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.types import (
    BotCommand,
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    MenuButtonWebApp,
    Message,
    WebAppInfo,
)

from database.connection import SessionLocal
from database.models import AccessScope, AppLaunchConfig, ChatPassword, LockedPeriod, MonitoredBotChat, User
from services.access_control_service import hash_password, write_audit_log
from services.auth_bot_service import (
    AUTH_EVENT_CHANNEL,
    clear_pending_otp_requests,
    get_redis,
    list_active_sessions,
    list_pending_otp_requests,
    revoke_active_session,
)
from services.user_service import UserServiceError, create_user, update_user, build_permissions_snapshot
from services.system_settings_service import get_settings_snapshot, is_bot_control_enabled, update_settings


AUTH_BOT_TOKEN = os.getenv("AUTH_BOT_TOKEN", "").strip()
AUTH_ADMIN_IDS = {
    int(value.strip())
    for value in os.getenv("AUTH_ADMIN_IDS", "").split(",")
    if value.strip().isdigit()
}
AUTH_BOT_MINI_APP_URL = os.getenv(
    "AUTH_BOT_MINI_APP_URL",
    "https://64.188.106.221.nip.io/mini-app/",
).strip()
AUTH_INCIDENT_CHAT_ID = int(os.getenv("AUTH_INCIDENT_CHAT_ID", "0") or 0) or None
AUTH_INCIDENT_TOPIC_ID = int(os.getenv("AUTH_INCIDENT_TOPIC_ID", "0") or 0) or None


def _admin_user_id(message: Optional[Message]) -> Optional[int]:
    if not message or not message.from_user:
        return None
    try:
        return int(message.from_user.id)
    except Exception:
        return None


def _callback_user_id(callback: Optional[CallbackQuery]) -> Optional[int]:
    if not callback or not callback.from_user:
        return None
    try:
        return int(callback.from_user.id)
    except Exception:
        return None


def _actor_label(message: Optional[Message]) -> str:
    user_id = _admin_user_id(message)
    if not message or not message.from_user:
        return "unknown-admin"
    username = (message.from_user.username or "").strip()
    if username:
        return f"@{username} ({user_id})"
    return f"id={user_id}"


def _is_admin(message: Message) -> bool:
    user_id = _admin_user_id(message)
    if user_id is None:
        return False
    return user_id in AUTH_ADMIN_IDS


def _audit(
    action: str,
    *,
    success: bool,
    message: Optional[Message] = None,
    details: Optional[Dict[str, Any]] = None,
) -> None:
    db = SessionLocal()
    try:
        user_id = _admin_user_id(message)
        write_audit_log(
            db,
            action=f"authbot_{action}",
            success=success,
            user_id=user_id,
            ip_address=f"tg:{user_id}" if user_id is not None else "tg:unknown",
            details=details or {},
        )
    except Exception:
        pass
    finally:
        db.close()


def _bot_control_enabled() -> bool:
    db = SessionLocal()
    try:
        return bool(is_bot_control_enabled(db))
    except Exception:
        return True
    finally:
        db.close()


async def _ensure_mutation_allowed_message(message: Message, command: str) -> bool:
    if _bot_control_enabled():
        return True
    await _safe_reply(
        message,
        "🔒 Read-only mode включен: изменяющие команды временно недоступны.",
        reply_markup=_kb([("📊 Статус", "menu:status")], _back_button()),
    )
    _audit(
        f"{command}_blocked_readonly",
        success=False,
        message=message,
        details={"reason": "bot_control_disabled"},
    )
    return False


async def _ensure_mutation_allowed_callback(callback: CallbackQuery, action: str) -> bool:
    if _bot_control_enabled():
        return True
    with suppress(Exception):
        await callback.answer("Read-only mode", show_alert=True)
    _audit(
        f"{action}_blocked_readonly",
        success=False,
        details={"reason": "bot_control_disabled", "admin_id": _callback_user_id(callback)},
    )
    return False


def _kb(*rows: list[tuple[str, str]]) -> InlineKeyboardMarkup:
    """
    Build InlineKeyboardMarkup from rows of (text, callback_data) tuples.
    """
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=text, callback_data=data) for text, data in row]
            for row in rows
        ]
    )


def _back_button() -> list[tuple[str, str]]:
    return [("◀️ Меню", "menu:main")]


def _main_menu_text() -> str:
    return "<b>AuthBot</b> — панель управления\n\nВыбери действие:"


def _resolved_mini_app_url() -> str:
    url = (AUTH_BOT_MINI_APP_URL or "").strip()
    if not url:
        return ""
    if not url.startswith("http://") and not url.startswith("https://"):
        url = f"https://{url}"
    return url


def _mini_app_button() -> Optional[InlineKeyboardButton]:
    url = _resolved_mini_app_url()
    if not url:
        return None
    return InlineKeyboardButton(
        text="📱 Mini App",
        web_app=WebAppInfo(url=url),
    )


def _main_menu_keyboard() -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = [
        [InlineKeyboardButton(text="📊 Статус", callback_data="menu:status")],
        [
            InlineKeyboardButton(text="📋 Сессии", callback_data="menu:sessions"),
            InlineKeyboardButton(text="🧭 Скоупы", callback_data="menu:scopes"),
        ],
        [
            InlineKeyboardButton(text="📅 Периоды", callback_data="menu:periods"),
            InlineKeyboardButton(text="💬 Чат-пароли", callback_data="menu:chat_passwords"),
        ],
        [InlineKeyboardButton(text="🔐 Пароль запуска", callback_data="menu:launch_password")],
    ]
    mini_app_btn = _mini_app_button()
    if mini_app_btn is not None:
        rows.append([mini_app_btn])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def _configure_bot_ui(bot: Bot) -> None:
    mini_app_url = _resolved_mini_app_url()
    commands = [
        BotCommand(command="start", description="Открыть панель"),
        BotCommand(command="status", description="Статус системы"),
        BotCommand(command="codes_on", description="Включить все коды"),
        BotCommand(command="codes_off", description="Отключить все коды"),
    ]
    if mini_app_url:
        commands.append(BotCommand(command="miniapp", description="Открыть Mini App"))
    with suppress(Exception):
        await bot.set_my_commands(commands)

    if not mini_app_url:
        return

    menu_button = MenuButtonWebApp(text="Mini App", web_app=WebAppInfo(url=mini_app_url))
    with suppress(Exception):
        await bot.set_chat_menu_button(menu_button=menu_button)
    for admin_id in AUTH_ADMIN_IDS:
        with suppress(Exception):
            await bot.set_chat_menu_button(chat_id=admin_id, menu_button=menu_button)


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


async def _safe_edit_text(
    callback: CallbackQuery,
    text: str,
    *,
    parse_mode: str = "HTML",
    reply_markup: InlineKeyboardMarkup | None = None,
) -> None:
    if not callback.message:
        return
    try:
        await callback.message.edit_text(
            text=text,
            parse_mode=parse_mode,
            reply_markup=reply_markup,
        )
    except TelegramBadRequest as exc:
        # Inline refresh often tries to render the same payload.
        if "message is not modified" in str(exc).lower():
            return
        raise


def _parse_date(value: str) -> Optional[date]:
    value = (value or "").strip()
    if not value:
        return None
    for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%d.%m.%y", "%d/%m/%Y"):
        try:
            return datetime.strptime(value, fmt).date()
        except Exception:
            continue
    return None


def _parse_int_csv(value: str) -> List[int]:
    result: List[int] = []
    for part in (value or "").split(","):
        raw = part.strip()
        if not raw:
            continue
        try:
            result.append(int(raw))
        except Exception:
            continue
    return sorted(set(result))


def _has_confirm_flag(message: Message) -> bool:
    text = (message.text or "").strip()
    return "--yes" in text.split()


def _format_event_message(event: str, payload: Dict[str, Any]) -> Optional[str]:
    if event == "scope_code_requested":
        scope_name = html_escape(str(payload.get("scope_name") or payload.get("scope") or "scope"))
        ip_address = html_escape(str(payload.get("ip") or "unknown"))
        code = html_escape(str(payload.get("code") or "------"))
        expires_in = int(payload.get("expires_in") or 120)
        return (
            "🔐 <b>Запрос доступа</b>\n\n"
            f"Скоуп: <b>{scope_name}</b>\n"
            f"IP: <code>{ip_address}</code>\n\n"
            f"Код: <code>{code}</code>\n\n"
            f"⏱ Действует {expires_in} сек"
        )
    if event == "scope_code_invalid":
        ip_address = html_escape(str(payload.get("ip") or "unknown"))
        scope_name = html_escape(str(payload.get("scope_name") or "scope"))
        return (
            "⚠️ <b>Неверный OTP-код</b>\n\n"
            f"IP: <code>{ip_address}</code>\n"
            f"Скоуп: <b>{scope_name}</b>"
        )
    if event == "scope_code_verified":
        ip_address = html_escape(str(payload.get("ip") or "unknown"))
        scope_name = html_escape(str(payload.get("scope_name") or "scope"))
        return (
            "✅ <b>OTP подтвержден</b>\n\n"
            f"IP: <code>{ip_address}</code>\n"
            f"Скоуп: <b>{scope_name}</b>"
        )
    if event == "launch_session_created":
        sid = str(payload.get("session_id") or "").strip()
        short_sid = sid[:16] + "…" if len(sid) > 16 else sid
        ip_address = html_escape(str(payload.get("ip") or "unknown"))
        return (
            "🟢 <b>Создана launch-сессия</b>\n\n"
            f"SID: <code>{html_escape(short_sid or '-')}</code>\n"
            f"IP: <code>{ip_address}</code>"
        )
    if event == "session_revoked":
        sid = str(payload.get("session_id") or "").strip()
        short_sid = sid[:16] + "…" if len(sid) > 16 else sid
        kind = html_escape(str(payload.get("token_kind") or "-"))
        return (
            "🛑 <b>Сессия завершена</b>\n\n"
            f"SID: <code>{html_escape(short_sid or '-')}</code>\n"
            f"Тип: <b>{kind}</b>"
        )
    if event == "receipt_incident":
        title = html_escape(str(payload.get("title") or "Инцидент обработки чеков"))
        summary = html_escape(str(payload.get("summary") or "Требуется проверка"))
        severity = html_escape(str(payload.get("severity") or "medium"))
        chat_id = html_escape(str(payload.get("chat_id") or "-"))
        message_id = html_escape(str(payload.get("message_id") or "-"))
        return (
            f"🚨 <b>{title}</b>\n\n"
            f"{summary}\n\n"
            f"Severity: <b>{severity}</b>\n"
            f"chat_id: <code>{chat_id}</code>\n"
            f"message_id: <code>{message_id}</code>"
        )
    return None


def _event_reply_markup(event: str, payload: Dict[str, Any]) -> InlineKeyboardMarkup | None:
    if event == "launch_session_created":
        sid = str(payload.get("session_id") or "").strip()
        if sid:
            return _kb(
                [("🛑 Завершить эту сессию", f"kill:{sid}")],
                [("📋 Сессии", "menu:sessions")],
            )
    if event == "session_revoked":
        return _kb([("📋 Сессии", "menu:sessions")])
    return None


async def _dispatch_event_notification(bot: Bot, event: str, payload: Dict[str, Any], text: str, reply_markup: InlineKeyboardMarkup | None) -> None:
    if event == "receipt_incident" and AUTH_INCIDENT_CHAT_ID:
        try:
            await bot.send_message(
                chat_id=AUTH_INCIDENT_CHAT_ID,
                message_thread_id=AUTH_INCIDENT_TOPIC_ID,
                text=text,
                parse_mode="HTML",
                reply_markup=reply_markup,
            )
            return
        except Exception:
            pass
    await _broadcast_to_admins(
        bot,
        text,
        parse_mode="HTML",
        reply_markup=reply_markup,
    )


async def _notification_listener(bot: Bot) -> None:
    redis = await get_redis()
    pubsub = redis.pubsub(ignore_subscribe_messages=True)
    await pubsub.subscribe(AUTH_EVENT_CHANNEL)
    _audit("listener_started", success=True, details={"channel": AUTH_EVENT_CHANNEL})
    try:
        while True:
            message = await pubsub.get_message(timeout=1.0)
            if not message:
                await asyncio.sleep(0.1)
                continue
            raw = message.get("data")
            if not raw:
                continue
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8", errors="ignore")
            try:
                envelope = json.loads(raw)
            except Exception:
                continue
            event = str(envelope.get("event") or "").strip()
            payload = envelope.get("payload") if isinstance(envelope.get("payload"), dict) else {}
            notify_text = _format_event_message(event, payload)
            if notify_text:
                await _dispatch_event_notification(
                    bot,
                    event,
                    payload,
                    notify_text,
                    _event_reply_markup(event, payload),
                )
                _audit("event_forwarded", success=True, details={"event": event})
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        _audit("listener_failed", success=False, details={"error": str(exc)[:500]})
    finally:
        with suppress(Exception):
            await pubsub.unsubscribe(AUTH_EVENT_CHANNEL)
        with suppress(Exception):
            await pubsub.aclose()


async def _handle_command_error(message: Message, command: str, exc: Exception) -> None:
    _audit(
        command,
        success=False,
        message=message,
        details={"error": str(exc)[:500]},
    )
    await _safe_reply(message, f"❌ Ошибка команды /{html_escape(command)}. Проверьте параметры и повторите.")
    await _broadcast_to_admins(
        message.bot,
        f"⚠️ AuthBot: ошибка /{html_escape(command)} от {html_escape(_actor_label(message))}\n"
        f"{html_escape(str(exc)[:300])}",
        exclude_user_id=_admin_user_id(message),
    )


async def _cb_status(callback: CallbackQuery) -> None:
    db = SessionLocal()
    try:
        active_scopes = db.query(AccessScope).filter(AccessScope.is_active.is_(True)).count()
        active_locks = db.query(LockedPeriod).filter(LockedPeriod.is_active.is_(True)).count()
        chat_protected = db.query(ChatPassword).count()
        launch_set = db.query(AppLaunchConfig).filter(AppLaunchConfig.id == 1).first() is not None
        settings = get_settings_snapshot(db)
    finally:
        db.close()

    pending_codes = await list_pending_otp_requests(limit=100)
    active_sessions = await list_active_sessions(limit=200)
    bot_control = _bot_control_enabled()

    text = (
        "📊 <b>Состояние системы</b>\n\n"
        f"🧭 Активные скоупы: <b>{active_scopes}</b>\n"
        f"📅 Заблокированные периоды: <b>{active_locks}</b>\n"
        f"💬 Чаты с паролем: <b>{chat_protected}</b>\n"
        f"🔐 Пароль запуска: <b>{'✅' if launch_set else '❌'}</b>\n"
        f"🧩 Scope OTP: <b>{'ON' if settings.get('otp_enabled', True) else 'OFF'}</b>\n"
        f"👤 Login 2FA: <b>{'ON' if settings.get('totp_2fa_enabled', False) else 'OFF'}</b>\n"
        f"🚀 Launch Gate: <b>{'ON' if settings.get('launch_gate_enabled', False) else 'OFF'}</b>\n"
        f"🤖 AuthBot mutate: <b>{'ON' if bot_control else 'READ-ONLY'}</b>\n"
        f"⏳ Ожидающие OTP: <b>{len(pending_codes)}</b>\n"
        f"📋 Активные сессии: <b>{len(active_sessions)}</b>"
    )
    await _safe_edit_text(
        callback,
        text,
        reply_markup=_kb(
            [("🔄 Обновить", "menu:status")],
            _back_button(),
        ),
    )
    _audit(
        "status",
        success=True,
        details={"via": "inline_button", "admin_id": _callback_user_id(callback)},
    )


async def _cb_sessions(callback: CallbackQuery) -> None:
    sessions = await list_active_sessions(limit=20)
    otp_requests = await list_pending_otp_requests(limit=10)

    if not sessions and not otp_requests:
        await _safe_edit_text(
            callback,
            "📋 <b>Сессии</b>\n\nАктивных сессий и OTP-запросов нет.",
            reply_markup=_kb([("🔄 Обновить", "menu:sessions")], _back_button()),
        )
        _audit(
            "sessions",
            success=True,
            details={"sessions": 0, "pending_otp": 0, "via": "inline_button", "admin_id": _callback_user_id(callback)},
        )
        return

    lines = ["📋 <b>Активные сессии</b>\n"]
    buttons: list[list[tuple[str, str]]] = []

    for i, row in enumerate(sessions[:10], 1):
        sid = str(row.get("session_id") or "?")
        short_sid = sid[:12] + "…" if len(sid) > 12 else sid
        kind = html_escape(str(row.get("token_kind") or "?"))
        ip = html_escape(str(row.get("ip_address") or "-"))
        created = html_escape(str(row.get("created_at") or "-").replace("T", " ")[:16])
        expires = html_escape(str(row.get("expires_at") or "-").replace("T", " ")[:16])
        lines.append(
            f"{i}. <code>{html_escape(short_sid)}</code>\n"
            f"   {kind} | {ip}\n"
            f"   🕐 {created} → {expires}"
        )
        buttons.append([(f"🛑 Kill #{i} ({short_sid})", f"kill:{sid}")])

    if otp_requests:
        lines.append("\n⏳ <b>Ожидающие OTP:</b>")
        for otp in otp_requests[:5]:
            ctx = otp.get("context") if isinstance(otp.get("context"), dict) else {}
            scope_name = html_escape(str(ctx.get("scope_name") or ctx.get("scope_id") or "-"))
            lines.append(
                f"• {html_escape(str(otp.get('purpose') or '-'))} | scope={scope_name} | "
                f"ttl={int(otp.get('expires_in') or 0)}s"
            )

    if sessions:
        buttons.append([("🛑 Kill All", "kill_all:confirm")])

    buttons.append([("🔄 Обновить", "menu:sessions")])
    buttons.append(_back_button())

    await _safe_edit_text(
        callback,
        "\n".join(lines),
        reply_markup=_kb(*buttons),
    )
    _audit(
        "sessions",
        success=True,
        details={
            "sessions": len(sessions),
            "pending_otp": len(otp_requests),
            "via": "inline_button",
            "admin_id": _callback_user_id(callback),
        },
    )


async def _cb_kill_confirm(callback: CallbackQuery, session_id: str) -> None:
    short = session_id[:16] + "…" if len(session_id) > 16 else session_id
    await _safe_edit_text(
        callback,
        f"⚠️ Завершить сессию <code>{html_escape(short)}</code>?",
        reply_markup=_kb(
            [("✅ Да, завершить", f"kill_yes:{session_id}"), ("❌ Отмена", "menu:sessions")],
        ),
    )


async def _cb_kill_execute(callback: CallbackQuery, session_id: str) -> None:
    ok, _data = await revoke_active_session(session_id)
    if not ok:
        await _safe_edit_text(
            callback,
            "Сессия не найдена или уже завершена.",
            reply_markup=_kb(_back_button()),
        )
        return

    short = session_id[:16] + "…" if len(session_id) > 16 else session_id
    await _safe_edit_text(
        callback,
        f"✅ Сессия <code>{html_escape(short)}</code> завершена.",
        reply_markup=_kb([("📋 К сессиям", "menu:sessions")], _back_button()),
    )
    _audit(
        "kill_session",
        success=True,
        details={
            "session_id": session_id,
            "via": "inline_button",
            "admin_id": _callback_user_id(callback),
        },
    )
    await _broadcast_to_admins(
        callback.bot,
        (
            f"🛑 Сессия <code>{html_escape(short)}</code> завершена "
            f"админом (tg:{_callback_user_id(callback)})"
        ),
        exclude_user_id=_callback_user_id(callback),
        parse_mode="HTML",
    )


async def _cb_kill_all_confirm(callback: CallbackQuery) -> None:
    await _safe_edit_text(
        callback,
        "⚠️ Завершить все активные сессии?",
        reply_markup=_kb(
            [("✅ Да, завершить все", "kill_all:yes"), ("❌ Отмена", "menu:sessions")],
        ),
    )


async def _cb_kill_all_execute(callback: CallbackQuery) -> None:
    sessions = await list_active_sessions(limit=500)
    if not sessions:
        await _safe_edit_text(
            callback,
            "Активных сессий нет.",
            reply_markup=_kb([("📋 К сессиям", "menu:sessions")], _back_button()),
        )
        return

    revoked = 0
    for row in sessions:
        sid = str(row.get("session_id") or "").strip()
        if not sid:
            continue
        ok, _ = await revoke_active_session(sid, suppress_event=True)
        if ok:
            revoked += 1

    await _safe_edit_text(
        callback,
        f"✅ Завершено сессий: <b>{revoked}</b>.",
        reply_markup=_kb([("📋 К сессиям", "menu:sessions")], _back_button()),
    )
    _audit(
        "kill_all_sessions",
        success=True,
        details={
            "revoked": revoked,
            "via": "inline_button",
            "admin_id": _callback_user_id(callback),
        },
    )
    await _broadcast_to_admins(
        callback.bot,
        f"🛑 Завершены все сессии (count={revoked}) админом tg:{_callback_user_id(callback)}",
        exclude_user_id=_callback_user_id(callback),
        parse_mode="HTML",
    )


async def _cb_scopes(callback: CallbackQuery) -> None:
    db = SessionLocal()
    try:
        rows = db.query(AccessScope).order_by(AccessScope.id.asc()).all()
        scopes = [
            {"id": int(row.id), "name": row.name, "is_active": bool(row.is_active), "auth_method": row.auth_method}
            for row in rows
        ]
    finally:
        db.close()

    if not scopes:
        await _safe_edit_text(
            callback,
            "🧭 <b>Скоупы</b>\n\nВ БД нет скоупов.",
            reply_markup=_kb(_back_button()),
        )
        return

    lines = ["🧭 <b>Скоупы</b>\n"]
    buttons: list[list[tuple[str, str]]] = []
    for scope in scopes[:20]:
        status = "🟢" if scope["is_active"] else "🔴"
        name = html_escape(str(scope["name"]))
        auth_method = html_escape(str(scope["auth_method"] or "-"))
        lines.append(f"{status} #{scope['id']} <b>{name}</b> | auth={auth_method}")
        toggle_label = f"{'🔴 OFF' if scope['is_active'] else '🟢 ON'} #{scope['id']}"
        buttons.append([(toggle_label, f"toggle:{scope['id']}")])

    buttons.append([("🔄 Обновить", "menu:scopes")])
    buttons.append(_back_button())

    await _safe_edit_text(
        callback,
        "\n".join(lines),
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
            await _safe_edit_text(
                callback,
                "Скоуп не найден.",
                reply_markup=_kb(_back_button()),
            )
            return
        row.is_active = not bool(row.is_active)
        new_state = bool(row.is_active)
        db.commit()
    finally:
        db.close()

    status = "🟢 Включен" if new_state else "🔴 Выключен"
    await _safe_edit_text(
        callback,
        f"Скоуп <b>#{scope_id}</b> → {status}",
        reply_markup=_kb([("🧭 К скоупам", "menu:scopes")], _back_button()),
    )
    _audit(
        "toggle_scope",
        success=True,
        details={
            "scope_id": scope_id,
            "is_active": new_state,
            "via": "inline_button",
            "admin_id": _callback_user_id(callback),
        },
    )
    await _broadcast_to_admins(
        callback.bot,
        f"🧭 Скоуп #{scope_id} → {status} (admin tg:{_callback_user_id(callback)})",
        exclude_user_id=_callback_user_id(callback),
        parse_mode="HTML",
    )


async def _cb_periods(callback: CallbackQuery) -> None:
    db = SessionLocal()
    try:
        rows: List[LockedPeriod] = (
            db.query(LockedPeriod)
            .order_by(LockedPeriod.is_active.desc(), LockedPeriod.id.desc())
            .limit(30)
            .all()
        )
        periods = [
            {
                "id": int(row.id),
                "date_from": row.date_from.isoformat() if row.date_from else "?",
                "date_to": row.date_to.isoformat() if row.date_to else "?",
                "is_active": bool(row.is_active),
                "reason": row.reason or "",
            }
            for row in rows
        ]
    finally:
        db.close()

    if not periods:
        await _safe_edit_text(
            callback,
            "📅 <b>Периоды</b>\n\nЗаблокированных периодов нет.",
            reply_markup=_kb(
                [("➕ Заблокировать", "menu:lock_period_help")],
                _back_button(),
            ),
        )
        return

    lines = ["📅 <b>Заблокированные периоды</b>\n"]
    buttons: list[list[tuple[str, str]]] = []
    for period in periods[:15]:
        status = "🟢 ACTIVE" if period["is_active"] else "⚪ OFF"
        reason = f" — {html_escape(period['reason'])}" if period["reason"] else ""
        lines.append(f"#{period['id']} {period['date_from']}..{period['date_to']} {status}{reason}")
        if period["is_active"]:
            buttons.append([(f"🔓 Снять #{period['id']}", f"unlock:{period['id']}")])

    buttons.append([("➕ Заблокировать", "menu:lock_period_help")])
    buttons.append([("🔄 Обновить", "menu:periods")])
    buttons.append(_back_button())

    await _safe_edit_text(
        callback,
        "\n".join(lines),
        reply_markup=_kb(*buttons),
    )


async def _cb_unlock_confirm(callback: CallbackQuery, lock_id_str: str) -> None:
    await _safe_edit_text(
        callback,
        f"⚠️ Снять блокировку периода <b>#{html_escape(lock_id_str)}</b>?",
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
            await _safe_edit_text(
                callback,
                "Блокировка не найдена.",
                reply_markup=_kb(_back_button()),
            )
            return
        row.is_active = False
        db.commit()
    finally:
        db.close()

    await _safe_edit_text(
        callback,
        f"✅ Блокировка <b>#{lock_id}</b> снята.",
        reply_markup=_kb([("📅 К периодам", "menu:periods")], _back_button()),
    )
    _audit(
        "unlock_period",
        success=True,
        details={
            "lock_id": lock_id,
            "via": "inline_button",
            "admin_id": _callback_user_id(callback),
        },
    )
    await _broadcast_to_admins(
        callback.bot,
        f"📅 Блокировка #{lock_id} снята (admin tg:{_callback_user_id(callback)})",
        exclude_user_id=_callback_user_id(callback),
        parse_mode="HTML",
    )


async def _cb_chat_passwords(callback: CallbackQuery) -> None:
    db = SessionLocal()
    try:
        rows = db.query(ChatPassword).order_by(ChatPassword.chat_id.asc()).limit(50).all()
        titles = {
            int(row.chat_id): (row.chat_title or "").strip()
            for row in db.query(MonitoredBotChat).all()
        }
        chat_passwords = [
            {
                "chat_id": int(row.chat_id),
                "title": titles.get(int(row.chat_id)) or "чат",
                "failed": int(row.failed_attempts or 0),
                "locked_until": row.locked_until.isoformat() if row.locked_until else None,
            }
            for row in rows
        ]
    finally:
        db.close()

    if not chat_passwords:
        await _safe_edit_text(
            callback,
            "💬 <b>Чат-пароли</b>\n\nЗащищенных чатов нет.",
            reply_markup=_kb(_back_button()),
        )
        return

    lines = ["💬 <b>Защищенные чаты</b>\n"]
    for item in chat_passwords:
        lock_info = f" | 🔒 до {item['locked_until']}" if item["locked_until"] else ""
        lines.append(
            f"• <b>{html_escape(item['title'])}</b> "
            f"(<code>{item['chat_id']}</code>) | fails={item['failed']}{lock_info}"
        )

    lines.append("\nУправление:")
    lines.append("<code>/set_chat_password chat_id пароль</code>")
    lines.append("<code>/remove_chat_password chat_id --yes</code>")

    await _safe_edit_text(
        callback,
        "\n".join(lines),
        reply_markup=_kb([("🔄 Обновить", "menu:chat_passwords")], _back_button()),
    )


async def _handle_callback(callback: CallbackQuery) -> None:
    """Unified inline button router."""
    admin_id = _callback_user_id(callback)
    if admin_id is None or admin_id not in AUTH_ADMIN_IDS:
        await callback.answer("⛔ Нет доступа", show_alert=True)
        return

    data = callback.data or ""
    with suppress(Exception):
        await callback.answer()

    if data == "menu:main":
        await _safe_edit_text(callback, _main_menu_text(), reply_markup=_main_menu_keyboard())
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
        await _safe_edit_text(
            callback,
            "🔐 <b>Пароль запуска</b>\n\n"
            "Для установки отправь команду:\n"
            "<code>/set_launch_password ваш_пароль --yes</code>",
            reply_markup=_kb(_back_button()),
        )
        return

    if data == "menu:lock_period_help":
        await _safe_edit_text(
            callback,
            "📅 <b>Блокировка периода</b>\n\n"
            "Отправь команду:\n"
            "<code>/lock_period 2026-01-01 2026-01-31 причина</code>\n\n"
            "Форматы дат: YYYY-MM-DD, DD.MM.YYYY",
            reply_markup=_kb(_back_button()),
        )
        return

    if data.startswith("kill:"):
        session_id = data[5:]
        await _cb_kill_confirm(callback, session_id)
        return

    if data.startswith("kill_yes:"):
        if not await _ensure_mutation_allowed_callback(callback, "kill_session"):
            return
        session_id = data[9:]
        await _cb_kill_execute(callback, session_id)
        return

    if data == "kill_all:confirm":
        await _cb_kill_all_confirm(callback)
        return

    if data == "kill_all:yes":
        if not await _ensure_mutation_allowed_callback(callback, "kill_all_sessions"):
            return
        await _cb_kill_all_execute(callback)
        return

    if data.startswith("toggle:"):
        if not await _ensure_mutation_allowed_callback(callback, "toggle_scope"):
            return
        scope_id = data[7:]
        await _cb_toggle_scope(callback, scope_id)
        return

    if data.startswith("unlock:"):
        lock_id = data[7:]
        await _cb_unlock_confirm(callback, lock_id)
        return

    if data.startswith("unlock_yes:"):
        if not await _ensure_mutation_allowed_callback(callback, "unlock_period"):
            return
        lock_id = data[11:]
        await _cb_unlock_execute(callback, lock_id)
        return

    if data == "cancel":
        await _safe_edit_text(callback, "❌ Отменено.")
        return


async def cmd_start(message: Message) -> None:
    if not _is_admin(message):
        return
    try:
        await _safe_reply(message, _main_menu_text(), reply_markup=_main_menu_keyboard())
        _audit("start", success=True, message=message)
    except Exception as exc:
        await _handle_command_error(message, "start", exc)


async def cmd_mini_app(message: Message) -> None:
    if not _is_admin(message):
        return
    try:
        url = _resolved_mini_app_url()
        if not url:
            await _safe_reply(
                message,
                "Mini App URL не настроен. Укажи <code>AUTH_BOT_MINI_APP_URL</code> в .env",
            )
            return
        await _safe_reply(
            message,
            f"📱 <b>Mini App</b>\n\n<a href=\"{html_escape(url)}\">Открыть ссылку</a>",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[[InlineKeyboardButton(text="📱 Открыть Mini App", web_app=WebAppInfo(url=url))]]
            ),
        )
        _audit("mini_app_open", success=True, message=message, details={"url": url})
    except Exception as exc:
        await _handle_command_error(message, "miniapp", exc)


async def cmd_status(message: Message) -> None:
    if not _is_admin(message):
        return
    try:
        db = SessionLocal()
        try:
            active_scopes = db.query(AccessScope).filter(AccessScope.is_active.is_(True)).count()
            active_locks = db.query(LockedPeriod).filter(LockedPeriod.is_active.is_(True)).count()
            chat_protected = db.query(ChatPassword).count()
            launch_set = db.query(AppLaunchConfig).filter(AppLaunchConfig.id == 1).first() is not None
            settings = get_settings_snapshot(db)
        finally:
            db.close()

        pending_codes = await list_pending_otp_requests(limit=100)
        active_sessions = await list_active_sessions(limit=200)
        bot_control = _bot_control_enabled()
        await _safe_reply(
            message,
            "📊 <b>Состояние системы</b>\n\n"
            f"🧭 Активные скоупы: <b>{active_scopes}</b>\n"
            f"📅 Заблокированные периоды: <b>{active_locks}</b>\n"
            f"💬 Чаты с паролем: <b>{chat_protected}</b>\n"
            f"🔐 Пароль запуска: <b>{'✅' if launch_set else '❌'}</b>\n"
            f"🧩 Scope OTP: <b>{'ON' if settings.get('otp_enabled', True) else 'OFF'}</b>\n"
            f"👤 Login 2FA: <b>{'ON' if settings.get('totp_2fa_enabled', False) else 'OFF'}</b>\n"
            f"🚀 Launch Gate: <b>{'ON' if settings.get('launch_gate_enabled', False) else 'OFF'}</b>\n"
            f"🤖 AuthBot mutate: <b>{'ON' if bot_control else 'READ-ONLY'}</b>\n"
            f"⏳ Ожидающие OTP: <b>{len(pending_codes)}</b>\n"
            f"📋 Активные сессии: <b>{len(active_sessions)}</b>",
            reply_markup=_kb([("📊 Панель", "menu:status")], _back_button()),
        )
        _audit(
            "status",
            success=True,
            message=message,
            details={"pending_otp": len(pending_codes), "active_sessions": len(active_sessions)},
        )
    except Exception as exc:
        await _handle_command_error(message, "status", exc)


async def cmd_codes_off(message: Message) -> None:
    if not _is_admin(message):
        return
    try:
        if not _has_confirm_flag(message):
            await _safe_reply(
                message,
                "Использование: <code>/codes_off --yes</code>\n"
                "Отключает все кодовые проверки (scope OTP + login 2FA + launch gate) и очищает зависшие OTP.",
                reply_markup=_kb([("📊 Панель", "menu:status")], _back_button()),
            )
            return

        admin_id = _admin_user_id(message)
        db = SessionLocal()
        try:
            update_settings(
                db,
                otp_enabled=False,
                totp_2fa_enabled=False,
                launch_gate_enabled=False,
                updated_by=admin_id,
            )
            force_disabled = int(
                db.query(User)
                .filter(User.force_2fa.is_(True))
                .update({User.force_2fa: False}, synchronize_session=False)
                or 0
            )
            db.commit()
            snapshot = get_settings_snapshot(db, fresh=True)
        finally:
            db.close()

        cleared = await clear_pending_otp_requests(clear_rate_limits=True)

        await _safe_reply(
            message,
            "✅ <b>Кодовые проверки отключены.</b>\n\n"
            f"🧩 Scope OTP: <b>{'ON' if snapshot.get('otp_enabled') else 'OFF'}</b>\n"
            f"👤 Login 2FA: <b>{'ON' if snapshot.get('totp_2fa_enabled') else 'OFF'}</b>\n"
            f"🚀 Launch Gate: <b>{'ON' if snapshot.get('launch_gate_enabled') else 'OFF'}</b>\n"
            f"🔓 force_2fa снято у пользователей: <b>{force_disabled}</b>\n"
            f"🧹 OTP очищено: <b>{int(cleared.get('deleted_requests') or 0)}</b>",
            reply_markup=_kb([("📊 Панель", "menu:status")], _back_button()),
        )
        await _broadcast_to_admins(
            message.bot,
            f"🧯 Все кодовые проверки отключены админом {html_escape(_actor_label(message))}",
            exclude_user_id=admin_id,
            parse_mode="HTML",
        )
        _audit(
            "codes_off",
            success=True,
            message=message,
            details={
                "force_2fa_cleared": force_disabled,
                "otp_deleted": int(cleared.get("deleted_requests") or 0),
            },
        )
    except Exception as exc:
        await _handle_command_error(message, "codes_off", exc)


async def cmd_codes_on(message: Message) -> None:
    if not _is_admin(message):
        return
    try:
        if not _has_confirm_flag(message):
            await _safe_reply(
                message,
                "Использование: <code>/codes_on --yes</code>\n"
                "Включает все кодовые проверки (scope OTP + login 2FA + launch gate).",
                reply_markup=_kb([("📊 Панель", "menu:status")], _back_button()),
            )
            return

        admin_id = _admin_user_id(message)
        db = SessionLocal()
        try:
            update_settings(
                db,
                otp_enabled=True,
                totp_2fa_enabled=True,
                launch_gate_enabled=True,
                updated_by=admin_id,
            )
            snapshot = get_settings_snapshot(db, fresh=True)
        finally:
            db.close()

        cleared = await clear_pending_otp_requests(clear_rate_limits=True)

        await _safe_reply(
            message,
            "✅ <b>Кодовые проверки включены.</b>\n\n"
            f"🧩 Scope OTP: <b>{'ON' if snapshot.get('otp_enabled') else 'OFF'}</b>\n"
            f"👤 Login 2FA: <b>{'ON' if snapshot.get('totp_2fa_enabled') else 'OFF'}</b>\n"
            f"🚀 Launch Gate: <b>{'ON' if snapshot.get('launch_gate_enabled') else 'OFF'}</b>\n"
            f"🧹 OTP-кэш очищен: <b>{int(cleared.get('deleted_requests') or 0)}</b>",
            reply_markup=_kb([("📊 Панель", "menu:status")], _back_button()),
        )
        await _broadcast_to_admins(
            message.bot,
            f"🛡️ Все кодовые проверки включены админом {html_escape(_actor_label(message))}",
            exclude_user_id=admin_id,
            parse_mode="HTML",
        )
        _audit(
            "codes_on",
            success=True,
            message=message,
            details={"otp_deleted": int(cleared.get("deleted_requests") or 0)},
        )
    except Exception as exc:
        await _handle_command_error(message, "codes_on", exc)


async def cmd_set_launch_password(message: Message) -> None:
    if not _is_admin(message):
        return
    if not await _ensure_mutation_allowed_message(message, "set_launch_password"):
        return
    try:
        args = (message.text or "").split(maxsplit=1)
        if len(args) < 2 or not args[1].strip():
            await _safe_reply(
                message,
                "Использование: <code>/set_launch_password пароль --yes</code>",
                reply_markup=_kb(_back_button()),
            )
            return
        if not _has_confirm_flag(message):
            await _safe_reply(
                message,
                "⚠️ Подтверди действие: повтори с <code>--yes</code>\n\nИли используй кнопки в /start",
                reply_markup=_kb([("🔐 Раздел запуска", "menu:launch_password")], _back_button()),
            )
            return

        password = args[1].replace("--yes", "").strip()
        if not password:
            await _safe_reply(message, "Пароль пустой.", reply_markup=_kb(_back_button()))
            return
        password_hash, salt = hash_password(password)
        db = SessionLocal()
        try:
            row = db.get(AppLaunchConfig, 1)
            if row is None:
                row = AppLaunchConfig(
                    id=1,
                    password_hash=password_hash,
                    salt=salt,
                    updated_by_tg_id=_admin_user_id(message),
                )
                db.add(row)
            else:
                row.password_hash = password_hash
                row.salt = salt
                row.failed_attempts = 0
                row.locked_until = None
                row.updated_by_tg_id = _admin_user_id(message)
            db.commit()
        finally:
            db.close()

        await _safe_reply(
            message,
            "✅ <b>Пароль запуска обновлен.</b>",
            reply_markup=_kb([("🔐 Раздел запуска", "menu:launch_password")], _back_button()),
        )
        await _broadcast_to_admins(
            message.bot,
            f"🔐 Пароль запуска обновлен админом {html_escape(_actor_label(message))}",
            exclude_user_id=_admin_user_id(message),
            parse_mode="HTML",
        )
        _audit("set_launch_password", success=True, message=message)
    except Exception as exc:
        await _handle_command_error(message, "set_launch_password", exc)


async def cmd_lock_period(message: Message) -> None:
    if not _is_admin(message):
        return
    if not await _ensure_mutation_allowed_message(message, "lock_period"):
        return
    try:
        parts = (message.text or "").split(maxsplit=3)
        if len(parts) < 3:
            await _safe_reply(
                message,
                "Использование: <code>/lock_period YYYY-MM-DD YYYY-MM-DD [reason]</code>",
                reply_markup=_kb([("📅 Периоды", "menu:periods")], _back_button()),
            )
            return
        d_from = _parse_date(parts[1])
        d_to = _parse_date(parts[2])
        if not d_from or not d_to:
            await _safe_reply(
                message,
                "Неверный формат даты. Используйте YYYY-MM-DD.",
                reply_markup=_kb([("📅 Периоды", "menu:periods")], _back_button()),
            )
            return
        reason = parts[3].strip() if len(parts) > 3 else None
        if d_from > d_to:
            d_from, d_to = d_to, d_from

        db = SessionLocal()
        try:
            row = LockedPeriod(
                date_from=d_from,
                date_to=d_to,
                reason=reason,
                locked_by_tg_id=_admin_user_id(message) or 0,
                is_active=True,
            )
            db.add(row)
            db.commit()
            db.refresh(row)
            lock_id = row.id
        finally:
            db.close()

        await _safe_reply(
            message,
            "✅ Период заблокирован\n\n"
            f"ID: <b>#{lock_id}</b>\n"
            f"Даты: <b>{d_from}</b> — <b>{d_to}</b>",
            reply_markup=_kb([("📅 Периоды", "menu:periods")], _back_button()),
        )
        await _broadcast_to_admins(
            message.bot,
            "📅 Период заблокирован админом "
            f"{html_escape(_actor_label(message))}\n"
            f"id={lock_id}, {d_from} — {d_to}",
            exclude_user_id=_admin_user_id(message),
            parse_mode="HTML",
        )
        _audit(
            "lock_period",
            success=True,
            message=message,
            details={"date_from": d_from.isoformat(), "date_to": d_to.isoformat(), "lock_id": lock_id},
        )
    except Exception as exc:
        await _handle_command_error(message, "lock_period", exc)


async def cmd_unlock_period(message: Message) -> None:
    if not _is_admin(message):
        return
    if not await _ensure_mutation_allowed_message(message, "unlock_period"):
        return
    try:
        parts = (message.text or "").split(maxsplit=1)
        raw_arg = parts[1].replace("--yes", "").strip() if len(parts) >= 2 else ""
        if len(parts) < 2 or not raw_arg.isdigit():
            await _safe_reply(
                message,
                "Использование: <code>/unlock_period lock_id --yes</code>",
                reply_markup=_kb([("📅 Периоды", "menu:periods")], _back_button()),
            )
            return
        if not _has_confirm_flag(message):
            await _safe_reply(
                message,
                "⚠️ Подтверди действие: повтори с <code>--yes</code>\n\nИли используй кнопки в /start",
                reply_markup=_kb([("📅 Периоды", "menu:periods")], _back_button()),
            )
            return
        lock_id = int(raw_arg)
        db = SessionLocal()
        try:
            row = db.get(LockedPeriod, lock_id)
            if row is None:
                await _safe_reply(
                    message,
                    "Блокировка не найдена.",
                    reply_markup=_kb([("📅 Периоды", "menu:periods")], _back_button()),
                )
                _audit("unlock_period", success=False, message=message, details={"lock_id": lock_id, "reason": "not_found"})
                return
            row.is_active = False
            db.commit()
        finally:
            db.close()

        await _safe_reply(
            message,
            f"✅ Блокировка <b>#{lock_id}</b> отключена.",
            reply_markup=_kb([("📅 Периоды", "menu:periods")], _back_button()),
        )
        await _broadcast_to_admins(
            message.bot,
            "📅 Блокировка периода снята админом "
            f"{html_escape(_actor_label(message))}\n"
            f"id={lock_id}",
            exclude_user_id=_admin_user_id(message),
            parse_mode="HTML",
        )
        _audit("unlock_period", success=True, message=message, details={"lock_id": lock_id})
    except Exception as exc:
        await _handle_command_error(message, "unlock_period", exc)


async def cmd_list_periods(message: Message) -> None:
    if not _is_admin(message):
        return
    try:
        db = SessionLocal()
        try:
            rows: List[LockedPeriod] = (
                db.query(LockedPeriod)
                .order_by(LockedPeriod.is_active.desc(), LockedPeriod.id.desc())
                .limit(50)
                .all()
            )
        finally:
            db.close()
        if not rows:
            await _safe_reply(
                message,
                "📅 <b>Периоды</b>\n\nЗаблокированных периодов нет.",
                reply_markup=_kb([("📅 Периоды", "menu:periods")], _back_button()),
            )
            _audit("list_periods", success=True, message=message, details={"count": 0})
            return
        lines = ["📅 <b>Периоды</b>\n"]
        for row in rows[:30]:
            reason = f" ({html_escape(row.reason)})" if row.reason else ""
            status = "🟢 ACTIVE" if row.is_active else "⚪ OFF"
            lines.append(f"#{row.id} {row.date_from}..{row.date_to} {status}{reason}")
        await _safe_reply(
            message,
            "\n".join(lines),
            reply_markup=_kb([("📅 Периоды", "menu:periods")], _back_button()),
        )
        _audit("list_periods", success=True, message=message, details={"count": len(rows)})
    except Exception as exc:
        await _handle_command_error(message, "list_periods", exc)


async def cmd_list_scopes(message: Message) -> None:
    if not _is_admin(message):
        return
    try:
        db = SessionLocal()
        try:
            rows = db.query(AccessScope).order_by(AccessScope.id.asc()).all()
        finally:
            db.close()
        if not rows:
            await _safe_reply(
                message,
                "🧭 <b>Скоупы</b>\n\nСкоупов в БД нет.",
                reply_markup=_kb([("🧭 Скоупы", "menu:scopes")], _back_button()),
            )
            _audit("list_scopes", success=True, message=message, details={"count": 0})
            return
        lines = ["🧭 <b>Скоупы</b>\n"]
        for row in rows[:80]:
            status = "🟢" if row.is_active else "🔴"
            lines.append(
                f"{status} #{row.id} <b>{html_escape(row.name)}</b> | "
                f"auth={html_escape(str(row.auth_method or '-'))}"
            )
        await _safe_reply(
            message,
            "\n".join(lines),
            reply_markup=_kb([("🧭 Скоупы", "menu:scopes")], _back_button()),
        )
        _audit("list_scopes", success=True, message=message, details={"count": len(rows)})
    except Exception as exc:
        await _handle_command_error(message, "list_scopes", exc)


async def cmd_toggle_scope(message: Message) -> None:
    if not _is_admin(message):
        return
    if not await _ensure_mutation_allowed_message(message, "toggle_scope"):
        return
    try:
        parts = (message.text or "").split(maxsplit=1)
        if len(parts) < 2 or not parts[1].strip().isdigit():
            await _safe_reply(
                message,
                "Использование: <code>/toggle_scope scope_id</code>",
                reply_markup=_kb([("🧭 Скоупы", "menu:scopes")], _back_button()),
            )
            return
        scope_id = int(parts[1])
        db = SessionLocal()
        try:
            row = db.get(AccessScope, scope_id)
            if row is None:
                await _safe_reply(
                    message,
                    "Скоуп не найден.",
                    reply_markup=_kb([("🧭 Скоупы", "menu:scopes")], _back_button()),
                )
                _audit("toggle_scope", success=False, message=message, details={"scope_id": scope_id, "reason": "not_found"})
                return
            row.is_active = not bool(row.is_active)
            new_state = bool(row.is_active)
            db.commit()
        finally:
            db.close()

        status = "🟢 Включен" if new_state else "🔴 Выключен"
        await _safe_reply(
            message,
            f"Скоуп <b>#{scope_id}</b> → {status}",
            reply_markup=_kb([("🧭 Скоупы", "menu:scopes")], _back_button()),
        )
        await _broadcast_to_admins(
            message.bot,
            f"🧭 Скоуп #{scope_id} переключен админом {html_escape(_actor_label(message))}\nactive={new_state}",
            exclude_user_id=_admin_user_id(message),
            parse_mode="HTML",
        )
        _audit("toggle_scope", success=True, message=message, details={"scope_id": scope_id, "is_active": new_state})
    except Exception as exc:
        await _handle_command_error(message, "toggle_scope", exc)


async def cmd_set_chat_password(message: Message) -> None:
    if not _is_admin(message):
        return
    if not await _ensure_mutation_allowed_message(message, "set_chat_password"):
        return
    try:
        parts = (message.text or "").split(maxsplit=2)
        if len(parts) < 3 or not parts[1].strip().isdigit():
            await _safe_reply(
                message,
                "Использование: <code>/set_chat_password chat_id пароль</code>",
                reply_markup=_kb([("💬 Чат-пароли", "menu:chat_passwords")], _back_button()),
            )
            return
        chat_id = int(parts[1])
        password = parts[2].strip()
        if not password:
            await _safe_reply(message, "Пароль пустой.", reply_markup=_kb(_back_button()))
            return
        password_hash, salt = hash_password(password)
        db = SessionLocal()
        try:
            row = db.get(ChatPassword, chat_id)
            if row is None:
                row = ChatPassword(chat_id=chat_id, password_hash=password_hash, salt=salt)
                db.add(row)
            else:
                row.password_hash = password_hash
                row.salt = salt
                row.failed_attempts = 0
                row.locked_until = None
            db.commit()
        finally:
            db.close()

        await _safe_reply(
            message,
            f"✅ Пароль чата <b>{chat_id}</b> установлен.",
            reply_markup=_kb([("💬 Чат-пароли", "menu:chat_passwords")], _back_button()),
        )
        await _broadcast_to_admins(
            message.bot,
            f"💬 Пароль чата {chat_id} установлен админом {html_escape(_actor_label(message))}",
            exclude_user_id=_admin_user_id(message),
            parse_mode="HTML",
        )
        _audit("set_chat_password", success=True, message=message, details={"chat_id": chat_id})
    except Exception as exc:
        await _handle_command_error(message, "set_chat_password", exc)


async def cmd_remove_chat_password(message: Message) -> None:
    if not _is_admin(message):
        return
    if not await _ensure_mutation_allowed_message(message, "remove_chat_password"):
        return
    try:
        parts = (message.text or "").split(maxsplit=1)
        raw_arg = parts[1].replace("--yes", "").strip() if len(parts) >= 2 else ""
        if len(parts) < 2 or not raw_arg.isdigit():
            await _safe_reply(
                message,
                "Использование: <code>/remove_chat_password chat_id --yes</code>",
                reply_markup=_kb([("💬 Чат-пароли", "menu:chat_passwords")], _back_button()),
            )
            return
        if not _has_confirm_flag(message):
            await _safe_reply(
                message,
                "⚠️ Подтверди действие: повтори с <code>--yes</code>\n\nИли используй кнопки в /start",
                reply_markup=_kb([("💬 Чат-пароли", "menu:chat_passwords")], _back_button()),
            )
            return
        chat_id = int(raw_arg)
        db = SessionLocal()
        try:
            row = db.get(ChatPassword, chat_id)
            if row is None:
                await _safe_reply(
                    message,
                    "Пароль на чат не установлен.",
                    reply_markup=_kb([("💬 Чат-пароли", "menu:chat_passwords")], _back_button()),
                )
                _audit(
                    "remove_chat_password",
                    success=False,
                    message=message,
                    details={"chat_id": chat_id, "reason": "not_found"},
                )
                return
            db.delete(row)
            db.commit()
        finally:
            db.close()

        await _safe_reply(
            message,
            f"✅ Пароль чата <b>{chat_id}</b> снят.",
            reply_markup=_kb([("💬 Чат-пароли", "menu:chat_passwords")], _back_button()),
        )
        await _broadcast_to_admins(
            message.bot,
            f"💬 Пароль чата {chat_id} снят админом {html_escape(_actor_label(message))}",
            exclude_user_id=_admin_user_id(message),
            parse_mode="HTML",
        )
        _audit("remove_chat_password", success=True, message=message, details={"chat_id": chat_id})
    except Exception as exc:
        await _handle_command_error(message, "remove_chat_password", exc)


async def cmd_list_chat_passwords(message: Message) -> None:
    if not _is_admin(message):
        return
    try:
        db = SessionLocal()
        try:
            rows = db.query(ChatPassword).order_by(ChatPassword.chat_id.asc()).limit(200).all()
            titles = {
                int(row.chat_id): (row.chat_title or "").strip()
                for row in db.query(MonitoredBotChat).all()
            }
        finally:
            db.close()
        if not rows:
            await _safe_reply(
                message,
                "💬 <b>Чат-пароли</b>\n\nЗащищенных чатов нет.",
                reply_markup=_kb([("💬 Чат-пароли", "menu:chat_passwords")], _back_button()),
            )
            _audit("list_chat_passwords", success=True, message=message, details={"count": 0})
            return
        lines = ["💬 <b>Чаты с паролем</b>\n"]
        for row in rows[:80]:
            title = html_escape(titles.get(int(row.chat_id)) or "чат")
            locked_until = row.locked_until.isoformat() if row.locked_until else "-"
            lines.append(
                f"• {title} (<code>{row.chat_id}</code>) | attempts={row.failed_attempts} | "
                f"locked_until={html_escape(locked_until)}"
            )
        await _safe_reply(
            message,
            "\n".join(lines),
            reply_markup=_kb([("💬 Чат-пароли", "menu:chat_passwords")], _back_button()),
        )
        _audit("list_chat_passwords", success=True, message=message, details={"count": len(rows)})
    except Exception as exc:
        await _handle_command_error(message, "list_chat_passwords", exc)


async def cmd_sessions(message: Message) -> None:
    if not _is_admin(message):
        return
    try:
        sessions = await list_active_sessions(limit=50)
        otp_requests = await list_pending_otp_requests(limit=20)
        lines: List[str] = ["📋 <b>Сессии</b>\n"]

        if sessions:
            lines.append("Активные сессии:")
            for row in sessions[:15]:
                sid = html_escape(str(row.get("session_id") or "?"))
                kind = html_escape(str(row.get("token_kind") or "?"))
                ip = html_escape(str(row.get("ip_address") or "-"))
                exp = html_escape(str(row.get("expires_at") or "-"))
                lines.append(f"• <code>{sid}</code> | {kind} | {ip} | exp={exp}")
        else:
            lines.append("Активных сессий нет.")

        if otp_requests:
            lines.append("\n⏳ Ожидающие OTP:")
            for row in otp_requests[:10]:
                ctx = row.get("context") if isinstance(row.get("context"), dict) else {}
                scope_name = html_escape(str(ctx.get("scope_name") or ctx.get("scope_id") or "-"))
                lines.append(
                    f"• {html_escape(str(row.get('purpose') or '-'))} | scope={scope_name} | "
                    f"ttl={int(row.get('expires_in') or 0)}s"
                )
        await _safe_reply(
            message,
            "\n".join(lines),
            reply_markup=_kb([("📋 Сессии", "menu:sessions")], _back_button()),
        )
        _audit(
            "sessions",
            success=True,
            message=message,
            details={"sessions": len(sessions), "pending_otp": len(otp_requests)},
        )
    except Exception as exc:
        await _handle_command_error(message, "sessions", exc)


async def cmd_kill_session(message: Message) -> None:
    if not _is_admin(message):
        return
    if not await _ensure_mutation_allowed_message(message, "kill_session"):
        return
    try:
        parts = (message.text or "").split(maxsplit=1)
        if len(parts) < 2 or not parts[1].strip():
            await _safe_reply(
                message,
                "Использование: <code>/kill_session session_id --yes</code>",
                reply_markup=_kb([("📋 Сессии", "menu:sessions")], _back_button()),
            )
            return
        if not _has_confirm_flag(message):
            await _safe_reply(
                message,
                "⚠️ Подтверди действие: повтори с <code>--yes</code>\n\nИли используй кнопки в /start",
                reply_markup=_kb([("📋 Сессии", "menu:sessions")], _back_button()),
            )
            return
        session_id = parts[1].replace("--yes", "").strip()
        ok, _data = await revoke_active_session(session_id)
        if not ok:
            await _safe_reply(
                message,
                "Сессия не найдена или уже завершена.",
                reply_markup=_kb([("📋 Сессии", "menu:sessions")], _back_button()),
            )
            _audit("kill_session", success=False, message=message, details={"session_id": session_id, "reason": "not_found"})
            return

        await _safe_reply(
            message,
            f"✅ Сессия <code>{html_escape(session_id)}</code> завершена.",
            reply_markup=_kb([("📋 Сессии", "menu:sessions")], _back_button()),
        )
        await _broadcast_to_admins(
            message.bot,
            f"🛑 Сессия <code>{html_escape(session_id)}</code> завершена админом {html_escape(_actor_label(message))}",
            exclude_user_id=_admin_user_id(message),
            parse_mode="HTML",
        )
        _audit("kill_session", success=True, message=message, details={"session_id": session_id})
    except Exception as exc:
        await _handle_command_error(message, "kill_session", exc)


async def cmd_kill_all_sessions(message: Message) -> None:
    if not _is_admin(message):
        return
    if not await _ensure_mutation_allowed_message(message, "kill_all_sessions"):
        return
    try:
        if not _has_confirm_flag(message):
            await _safe_reply(
                message,
                "⚠️ Подтверди действие: <code>/kill_all_sessions --yes</code>",
                reply_markup=_kb([("📋 Сессии", "menu:sessions")], _back_button()),
            )
            return

        sessions = await list_active_sessions(limit=500)
        if not sessions:
            await _safe_reply(
                message,
                "Активных сессий нет.",
                reply_markup=_kb([("📋 Сессии", "menu:sessions")], _back_button()),
            )
            return

        revoked = 0
        for row in sessions:
            sid = str(row.get("session_id") or "").strip()
            if not sid:
                continue
            ok, _ = await revoke_active_session(sid, suppress_event=True)
            if ok:
                revoked += 1

        await _safe_reply(
            message,
            f"✅ Завершено сессий: <b>{revoked}</b>.",
            reply_markup=_kb([("📋 Сессии", "menu:sessions")], _back_button()),
        )
        await _broadcast_to_admins(
            message.bot,
            f"🛑 Завершены все сессии (count={revoked}) админом {html_escape(_actor_label(message))}",
            exclude_user_id=_admin_user_id(message),
            parse_mode="HTML",
        )
        _audit("kill_all_sessions", success=True, message=message, details={"revoked": revoked})
    except Exception as exc:
        await _handle_command_error(message, "kill_all_sessions", exc)


async def cmd_users(message: Message) -> None:
    if not _is_admin(message):
        return
    try:
        db = SessionLocal()
        try:
            rows = db.query(User).order_by(User.id.asc()).limit(200).all()
        finally:
            db.close()
        if not rows:
            await _safe_reply(message, "👤 Пользователей нет.")
            return
        lines = ["👤 <b>Пользователи</b>\n"]
        for row in rows:
            snapshot = build_permissions_snapshot(row)
            lines.append(
                f"#{row.id} <b>{html_escape(row.username)}</b> | role={html_escape(snapshot.get('role', '-'))} | "
                f"active={'yes' if row.is_active else 'no'} | tabs={','.join(snapshot.get('allowed_tabs') or [])}"
            )
        await _safe_reply(message, "\n".join(lines))
        _audit("users", success=True, message=message, details={"count": len(rows)})
    except Exception as exc:
        await _handle_command_error(message, "users", exc)


async def cmd_user_add(message: Message) -> None:
    if not _is_admin(message):
        return
    if not await _ensure_mutation_allowed_message(message, "user_add"):
        return
    try:
        parts = (message.text or "").split(maxsplit=4)
        if len(parts) < 3:
            await _safe_reply(message, "Использование: <code>/user_add username password [admin|operator] [display_name]</code>")
            return
        username = parts[1].strip()
        password = parts[2]
        role = parts[3].strip().lower() if len(parts) >= 4 else "operator"
        display_name = parts[4].strip() if len(parts) >= 5 else username

        db = SessionLocal()
        try:
            row = create_user(
                db,
                username=username,
                password=password,
                role=role,
                display_name=display_name,
                allowed_tabs=["dashboard"] if role != "admin" else ["dashboard", "reference", "automation", "userbot", "logs", "admin"],
                allowed_folders=[],
                forbidden_periods=[],
                allowed_sources=[],
                can_toggle_sources=(role == "admin"),
                is_active=True,
            )
        finally:
            db.close()
        await _safe_reply(message, f"✅ Пользователь создан: <b>{html_escape(row.username)}</b> (id={row.id})")
        _audit("user_add", success=True, message=message, details={"user_id": int(row.id), "username": row.username, "role": role})
    except UserServiceError as exc:
        await _safe_reply(message, f"❌ Не удалось создать пользователя: <code>{html_escape(str(exc))}</code>")
    except Exception as exc:
        await _handle_command_error(message, "user_add", exc)


async def cmd_user_disable(message: Message) -> None:
    if not _is_admin(message):
        return
    if not await _ensure_mutation_allowed_message(message, "user_disable"):
        return
    try:
        parts = (message.text or "").split(maxsplit=1)
        if len(parts) < 2 or not parts[1].strip().isdigit():
            await _safe_reply(message, "Использование: <code>/user_disable user_id</code>")
            return
        user_id = int(parts[1].strip())
        db = SessionLocal()
        try:
            row = db.get(User, user_id)
            if not row:
                await _safe_reply(message, "Пользователь не найден.")
                return
            row = update_user(db, row, is_active=False)
        finally:
            db.close()
        await _safe_reply(message, f"✅ Пользователь <b>{html_escape(row.username)}</b> отключен.")
        _audit("user_disable", success=True, message=message, details={"user_id": user_id})
    except Exception as exc:
        await _handle_command_error(message, "user_disable", exc)


async def cmd_user_enable(message: Message) -> None:
    if not _is_admin(message):
        return
    if not await _ensure_mutation_allowed_message(message, "user_enable"):
        return
    try:
        parts = (message.text or "").split(maxsplit=1)
        if len(parts) < 2 or not parts[1].strip().isdigit():
            await _safe_reply(message, "Использование: <code>/user_enable user_id</code>")
            return
        user_id = int(parts[1].strip())
        db = SessionLocal()
        try:
            row = db.get(User, user_id)
            if not row:
                await _safe_reply(message, "Пользователь не найден.")
                return
            row = update_user(db, row, is_active=True)
        finally:
            db.close()
        await _safe_reply(message, f"✅ Пользователь <b>{html_escape(row.username)}</b> активирован.")
        _audit("user_enable", success=True, message=message, details={"user_id": user_id})
    except Exception as exc:
        await _handle_command_error(message, "user_enable", exc)


async def cmd_user_reset_password(message: Message) -> None:
    if not _is_admin(message):
        return
    if not await _ensure_mutation_allowed_message(message, "user_reset_password"):
        return
    try:
        parts = (message.text or "").split(maxsplit=2)
        if len(parts) < 3 or not parts[1].strip().isdigit():
            await _safe_reply(message, "Использование: <code>/user_reset_password user_id new_password</code>")
            return
        user_id = int(parts[1].strip())
        new_password = parts[2]
        db = SessionLocal()
        try:
            row = db.get(User, user_id)
            if not row:
                await _safe_reply(message, "Пользователь не найден.")
                return
            row = update_user(db, row, password=new_password)
        finally:
            db.close()
        await _safe_reply(message, f"✅ Пароль пользователя <b>{html_escape(row.username)}</b> обновлен.")
        _audit("user_reset_password", success=True, message=message, details={"user_id": user_id})
    except Exception as exc:
        await _handle_command_error(message, "user_reset_password", exc)


async def cmd_user_set_tabs(message: Message) -> None:
    if not _is_admin(message):
        return
    if not await _ensure_mutation_allowed_message(message, "user_set_tabs"):
        return
    try:
        parts = (message.text or "").split(maxsplit=2)
        if len(parts) < 3 or not parts[1].strip().isdigit():
            await _safe_reply(message, "Использование: <code>/user_set_tabs user_id dashboard,reference,userbot</code>")
            return
        user_id = int(parts[1].strip())
        tabs = [item.strip().lower() for item in parts[2].split(",") if item.strip()]
        db = SessionLocal()
        try:
            row = db.get(User, user_id)
            if not row:
                await _safe_reply(message, "Пользователь не найден.")
                return
            row = update_user(db, row, allowed_tabs=tabs)
            snapshot = build_permissions_snapshot(row)
        finally:
            db.close()
        await _safe_reply(message, f"✅ tabs для <b>{html_escape(row.username)}</b>: {html_escape(','.join(snapshot.get('allowed_tabs') or []))}")
        _audit("user_set_tabs", success=True, message=message, details={"user_id": user_id, "tabs": tabs})
    except Exception as exc:
        await _handle_command_error(message, "user_set_tabs", exc)


async def cmd_user_set_folders(message: Message) -> None:
    if not _is_admin(message):
        return
    if not await _ensure_mutation_allowed_message(message, "user_set_folders"):
        return
    try:
        parts = (message.text or "").split(maxsplit=2)
        if len(parts) < 3 or not parts[1].strip().isdigit():
            await _safe_reply(message, "Использование: <code>/user_set_folders user_id 1,2,3</code>")
            return
        user_id = int(parts[1].strip())
        folder_ids = _parse_int_csv(parts[2])
        db = SessionLocal()
        try:
            row = db.get(User, user_id)
            if not row:
                await _safe_reply(message, "Пользователь не найден.")
                return
            row = update_user(db, row, allowed_folders=folder_ids)
        finally:
            db.close()
        await _safe_reply(message, f"✅ folders для <b>{html_escape(row.username)}</b>: {','.join(str(x) for x in folder_ids) or '-'}")
        _audit("user_set_folders", success=True, message=message, details={"user_id": user_id, "folders": folder_ids})
    except Exception as exc:
        await _handle_command_error(message, "user_set_folders", exc)


async def cmd_user_set_sources(message: Message) -> None:
    if not _is_admin(message):
        return
    if not await _ensure_mutation_allowed_message(message, "user_set_sources"):
        return
    try:
        parts = (message.text or "").split(maxsplit=2)
        if len(parts) < 3 or not parts[1].strip().isdigit():
            await _safe_reply(message, "Использование: <code>/user_set_sources user_id 12345,-10077</code>")
            return
        user_id = int(parts[1].strip())
        source_ids = _parse_int_csv(parts[2])
        db = SessionLocal()
        try:
            row = db.get(User, user_id)
            if not row:
                await _safe_reply(message, "Пользователь не найден.")
                return
            row = update_user(db, row, allowed_sources=source_ids)
        finally:
            db.close()
        await _safe_reply(message, f"✅ sources для <b>{html_escape(row.username)}</b>: {','.join(str(x) for x in source_ids) or '-'}")
        _audit("user_set_sources", success=True, message=message, details={"user_id": user_id, "sources": source_ids})
    except Exception as exc:
        await _handle_command_error(message, "user_set_sources", exc)


async def start_auth_bot() -> None:
    if not AUTH_BOT_TOKEN:
        raise RuntimeError("AUTH_BOT_TOKEN is not set")
    if not AUTH_ADMIN_IDS:
        raise RuntimeError("AUTH_ADMIN_IDS is empty")

    bot = Bot(AUTH_BOT_TOKEN)
    dp = Dispatcher()
    await _configure_bot_ui(bot)

    dp.message.register(cmd_start, Command(commands=["start"]))
    dp.message.register(cmd_mini_app, Command(commands=["miniapp", "mini_app", "app"]))
    dp.message.register(cmd_status, Command(commands=["status"]))
    dp.message.register(cmd_codes_off, Command(commands=["codes_off", "codes_disable", "security_open"]))
    dp.message.register(cmd_codes_on, Command(commands=["codes_on", "codes_enable", "security_lock"]))
    dp.message.register(cmd_set_launch_password, Command(commands=["set_launch_password"]))
    dp.message.register(cmd_lock_period, Command(commands=["lock_period"]))
    dp.message.register(cmd_unlock_period, Command(commands=["unlock_period"]))
    dp.message.register(cmd_list_periods, Command(commands=["list_periods"]))
    dp.message.register(cmd_list_scopes, Command(commands=["list_scopes"]))
    dp.message.register(cmd_toggle_scope, Command(commands=["toggle_scope"]))
    dp.message.register(cmd_set_chat_password, Command(commands=["set_chat_password"]))
    dp.message.register(cmd_remove_chat_password, Command(commands=["remove_chat_password"]))
    dp.message.register(cmd_list_chat_passwords, Command(commands=["list_chat_passwords"]))
    dp.message.register(cmd_sessions, Command(commands=["sessions"]))
    dp.message.register(cmd_kill_session, Command(commands=["kill_session"]))
    dp.message.register(cmd_kill_all_sessions, Command(commands=["kill_all_sessions"]))
    dp.message.register(cmd_users, Command(commands=["users"]))
    dp.message.register(cmd_user_add, Command(commands=["user_add"]))
    dp.message.register(cmd_user_disable, Command(commands=["user_disable"]))
    dp.message.register(cmd_user_enable, Command(commands=["user_enable"]))
    dp.message.register(cmd_user_reset_password, Command(commands=["user_reset_password"]))
    dp.message.register(cmd_user_set_tabs, Command(commands=["user_set_tabs"]))
    dp.message.register(cmd_user_set_folders, Command(commands=["user_set_folders"]))
    dp.message.register(cmd_user_set_sources, Command(commands=["user_set_sources"]))
    dp.callback_query.register(_handle_callback)

    listener_task = asyncio.create_task(_notification_listener(bot), name="auth-bot-notifications")
    try:
        await _broadcast_to_admins(
            bot,
            "✅ <b>AuthBot запущен</b> и готов к работе",
            parse_mode="HTML",
            reply_markup=_kb([("📊 Открыть панель", "menu:main")]),
        )
        await dp.start_polling(bot)
    finally:
        listener_task.cancel()
        with suppress(asyncio.CancelledError):
            await listener_task
        with suppress(Exception):
            await bot.session.close()


def main() -> None:
    asyncio.run(start_auth_bot())


if __name__ == "__main__":
    main()
