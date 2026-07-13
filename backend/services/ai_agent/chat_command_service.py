"""Agent chat commands: reusable saved prompt templates for the chat palette.

A command is a saved prompt template an operator can fire from the chat input.
Backend owns CRUD + storage + default seeds; the frontend renders the palette
and sends the stored `prompt_template` (with optional `requested_tool`) to the
agent when a command is picked.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4

from sqlalchemy import or_
from sqlalchemy.orm import Session

from database.models import AgentChatCommand

logger = logging.getLogger(__name__)

VALID_SCOPES = {"team", "personal"}


def _normalize_scope(scope: Optional[str]) -> str:
    s = (scope or "team").strip().lower()
    return s if s in VALID_SCOPES else "team"


def serialize_command(c: AgentChatCommand) -> Dict[str, Any]:
    return {
        "id": str(c.id),
        "title": c.title,
        "icon": c.icon,
        "prompt_template": c.prompt_template,
        "requested_tool": c.requested_tool,
        "scope": c.scope,
        "created_by_user_id": c.created_by_user_id,
        "sort_order": int(c.sort_order) if c.sort_order is not None else 0,
        "enabled": bool(c.enabled),
        "created_at": c.created_at.isoformat() if c.created_at else None,
        "updated_at": c.updated_at.isoformat() if c.updated_at else None,
    }


def list_commands(db: Session, *, user_id: Optional[int] = None) -> List[Dict[str, Any]]:
    """Team commands + the requesting user's own personal commands, ordered."""
    query = db.query(AgentChatCommand)
    if user_id is not None:
        query = query.filter(
            or_(
                AgentChatCommand.scope == "team",
                AgentChatCommand.created_by_user_id == int(user_id),
            )
        )
    else:
        query = query.filter(AgentChatCommand.scope == "team")
    rows = query.order_by(
        AgentChatCommand.sort_order.asc(),
        AgentChatCommand.created_at.asc(),
    ).all()
    return [serialize_command(r) for r in rows]


def get_command(db: Session, command_id: UUID) -> Optional[AgentChatCommand]:
    return db.get(AgentChatCommand, command_id)


def create_command(
    db: Session,
    *,
    title: str,
    prompt_template: str,
    icon: Optional[str] = None,
    requested_tool: Optional[str] = None,
    scope: str = "team",
    sort_order: int = 0,
    enabled: bool = True,
    created_by_user_id: Optional[int] = None,
) -> AgentChatCommand:
    if not (title or "").strip():
        raise ValueError("title is required")
    if not (prompt_template or "").strip():
        raise ValueError("prompt_template is required")
    row = AgentChatCommand(
        id=uuid4(),
        title=title.strip()[:120],
        icon=(icon.strip()[:40] if icon and icon.strip() else None),
        prompt_template=prompt_template.strip(),
        requested_tool=(requested_tool.strip()[:80] if requested_tool and requested_tool.strip() else None),
        scope=_normalize_scope(scope),
        sort_order=int(sort_order or 0),
        enabled=bool(enabled),
        created_by_user_id=created_by_user_id,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def update_command(db: Session, command: AgentChatCommand, **fields: Any) -> AgentChatCommand:
    if "title" in fields and fields["title"] is not None:
        command.title = str(fields["title"]).strip()[:120]
    if "prompt_template" in fields and fields["prompt_template"] is not None:
        command.prompt_template = str(fields["prompt_template"]).strip()
    if "icon" in fields:
        icon = fields["icon"]
        command.icon = str(icon).strip()[:40] if icon and str(icon).strip() else None
    if "requested_tool" in fields:
        tool = fields["requested_tool"]
        command.requested_tool = str(tool).strip()[:80] if tool and str(tool).strip() else None
    if "scope" in fields and fields["scope"] is not None:
        command.scope = _normalize_scope(str(fields["scope"]))
    if "sort_order" in fields and fields["sort_order"] is not None:
        command.sort_order = int(fields["sort_order"])
    if "enabled" in fields and fields["enabled"] is not None:
        command.enabled = bool(fields["enabled"])
    db.commit()
    db.refresh(command)
    return command


def delete_command(db: Session, command: AgentChatCommand) -> None:
    db.delete(command)
    db.commit()


# Default commands seeded on first boot (scope=team, enabled).
_DEFAULT_COMMANDS = (
    {
        "title": "Подсчёт затрат",
        "icon": "wallet",
        "prompt_template": "Посчитай суммарные затраты за период. Уточни у меня период, если он не задан.",
        "requested_tool": None,
        "sort_order": 0,
    },
    {
        "title": "Сводка за период",
        "icon": "bar-chart-3",
        "prompt_template": "Собери сводку операций за период с разбивкой по приложениям и источникам.",
        "requested_tool": None,
        "sort_order": 1,
    },
    {
        "title": "Сверка чеков",
        "icon": "refresh-cw",
        "prompt_template": "Сверь локально скачанные Telegram-чеки с базой и покажи расхождения и точность парсинга.",
        "requested_tool": "bot_reconciliation",
        "sort_order": 2,
    },
)


def ensure_builtin_commands(db: Session) -> int:
    """Seed the default command palette if the table is empty. Returns count created."""
    if db.query(AgentChatCommand.id).first() is not None:
        return 0
    created = 0
    for spec in _DEFAULT_COMMANDS:
        create_command(
            db,
            title=spec["title"],
            prompt_template=spec["prompt_template"],
            icon=spec["icon"],
            requested_tool=spec["requested_tool"],
            scope="team",
            sort_order=spec["sort_order"],
            enabled=True,
            created_by_user_id=None,
        )
        created += 1
    logger.info("Seeded %s builtin agent chat command(s)", created)
    return created
