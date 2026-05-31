"""Weekly health-check publisher for the AI agent.

Each Sunday (or on demand) the agent runs `weekly_health_check`, formats the
result as a Telegram message and posts it into the receipt log channel.

If `has_issues=True`, the message includes an inline button:
    🔧 Исправить → tg://callback_data:autofix_<report_id>

The auth-bot dispatcher receives the callback, schedules the corresponding
`weekly_report_autofix` action through the standard agent confirm flow.

Configuration (env):
    AUTH_BOT_TOKEN              - re-used from auth bot
    RECEIPT_LOG_CHAT_ID         - target channel id (re-uses receipt logger channel by default)
    WEEKLY_PUBLISH_CHAT_ID      - override target if you want a separate channel
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import httpx
from sqlalchemy.orm import Session

from database.connection import get_db
from services.ai_agent.tools.audit_tools import weekly_health_check

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
def _esc(value: Any) -> str:
    if value is None:
        return ""
    text = str(value)
    return (
        text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    )


def _format_int(value: Any) -> str:
    try:
        return f"{int(value):,}".replace(",", " ")
    except Exception:  # noqa: BLE001
        return str(value)


# --------------------------------------------------------------------------- #
@dataclass
class WeeklyPublishConfig:
    bot_token: str = ""
    chat_id: Optional[int] = None
    topic_id: Optional[int] = None

    @classmethod
    def from_env(cls) -> "WeeklyPublishConfig":
        chat = os.getenv("WEEKLY_PUBLISH_CHAT_ID") or os.getenv("RECEIPT_LOG_CHAT_ID")
        topic = os.getenv("WEEKLY_PUBLISH_TOPIC_ID") or os.getenv("RECEIPT_LOG_TOPIC_ID")
        return cls(
            bot_token=(os.getenv("AUTH_BOT_TOKEN") or "").strip(),
            chat_id=int(chat) if chat else None,
            topic_id=int(topic) if topic else None,
        )

    @property
    def configured(self) -> bool:
        return bool(self.bot_token and self.chat_id)


# --------------------------------------------------------------------------- #
def _build_message(health: Dict[str, Any]) -> str:
    data = health.get("data") or {}
    period = data.get("period") or [None, None]
    totals = data.get("totals") or {}
    chats = data.get("chats") or []
    has_issues = bool(data.get("has_issues"))

    period_label = "—"
    try:
        if period[0] and period[1]:
            start = datetime.fromisoformat(period[0])
            end = datetime.fromisoformat(period[1])
            period_label = f"{start.strftime('%d.%m')} — {end.strftime('%d.%m.%Y')}"
    except Exception:  # noqa: BLE001
        pass

    icon = "✅" if not has_issues else "⚠️"
    title = "Недельный отчёт"

    lines = [
        f"{icon} <b>{_esc(title)}</b> · {_esc(period_label)}",
        "",
        f"📊 Транзакций: <b>{_format_int(totals.get('transactions', 0))}</b>",
        f"📥 Чатов проверено: <b>{_format_int(len(chats))}</b>",
    ]

    failed = int(totals.get("failed", 0))
    stuck = int(totals.get("stuck", 0))
    dups = int(totals.get("duplicate_groups", 0))
    orphan = int(totals.get("orphan_rows", 0))

    if has_issues:
        lines.append("")
        lines.append("<b>Найденные проблемы:</b>")
        if failed:
            lines.append(f"  ❌ Ошибок обработки: <b>{failed}</b>")
        if stuck:
            lines.append(f"  ⏳ Зависших задач: <b>{stuck}</b>")
        if dups:
            lines.append(f"  ♻️ Групп дубликатов: <b>{dups}</b>")
        if orphan:
            lines.append(f"  🏷 Без маппинга: <b>{orphan}</b>")

        # Top 3 problem chats
        problem_chats = [
            c for c in chats
            if (
                ((c.get("data") or {}).get("tasks") or {}).get("failed", 0)
                or ((c.get("data") or {}).get("issues") or [])
            )
        ][:3]
        if problem_chats:
            lines.append("")
            lines.append("<b>Топ проблемных чатов:</b>")
            for c in problem_chats:
                title = _esc(c.get("chat_title") or c.get("chat_id"))
                tasks = (c.get("data") or {}).get("tasks") or {}
                lines.append(
                    f"  · {title} — failed {tasks.get('failed', 0)}, "
                    f"stuck {tasks.get('processing', 0)}"
                )
    else:
        lines.append("")
        lines.append("Всё чисто. Дубликатов и ошибок не найдено.")

    return "\n".join(lines)


def _build_reply_markup(report_id: str, has_issues: bool) -> Optional[Dict[str, Any]]:
    if not has_issues:
        return None
    return {
        "inline_keyboard": [
            [
                {
                    "text": "🔧 Исправить",
                    "callback_data": f"autofix:{report_id}",
                }
            ]
        ]
    }


# --------------------------------------------------------------------------- #
async def publish_weekly_report(
    *,
    current_user: Optional[Dict[str, Any]] = None,
    scope: Optional[Dict[str, Any]] = None,
    arguments: Optional[Dict[str, Any]] = None,
    config: Optional[WeeklyPublishConfig] = None,
) -> Dict[str, Any]:
    """Run health check, format, and post to the configured Telegram channel.

    Returns a small status dict; never raises (failures are logged).
    """
    cfg = config or WeeklyPublishConfig.from_env()
    if not cfg.configured:
        logger.warning("Weekly report not published: token/chat_id missing")
        return {"published": False, "reason": "not_configured"}

    args = arguments or {}
    with get_db() as db:
        health = await weekly_health_check(
            db=db,
            current_user=current_user or {},
            scope=scope,
            arguments=args,
        )
    data = health.get("data") or {}
    has_issues = bool(data.get("has_issues"))

    text = _build_message(health)
    report_id = f"weekly-{int(datetime.utcnow().timestamp())}"
    payload: Dict[str, Any] = {
        "chat_id": cfg.chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    if cfg.topic_id:
        payload["message_thread_id"] = cfg.topic_id
    reply_markup = _build_reply_markup(report_id, has_issues)
    if reply_markup:
        payload["reply_markup"] = reply_markup

    url = f"https://api.telegram.org/bot{cfg.bot_token}/sendMessage"
    sent = False
    response_meta: Dict[str, Any] = {}
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.post(url, json=payload)
            response_meta = {"status": r.status_code, "body": r.text[:300]}
            if r.status_code < 400:
                sent = True
            else:
                logger.warning("Weekly publish failed: %s %s", r.status_code, r.text[:300])
    except Exception as exc:  # noqa: BLE001
        logger.exception("Weekly publish raised: %s", exc)
        response_meta = {"error": str(exc)[:300]}

    return {
        "published": sent,
        "report_id": report_id,
        "has_issues": has_issues,
        "telegram": response_meta,
        "totals": data.get("totals") or {},
    }
