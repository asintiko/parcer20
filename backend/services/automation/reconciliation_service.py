from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
from uuid import uuid4

from sqlalchemy.orm import Session

from database.models import AutomationTask, MonitoredBotChat, TgHistoryCursor


async def start_reconciliation_analysis(
    db: Session,
    *,
    current_user: Dict[str, Any],
    period_start: datetime,
    period_end: datetime,
    bot_chat_ids: Optional[List[int]] = None,
    auto_parse: bool = False,
    source: str = "local",
) -> Dict[str, Any]:
    from api.routes.reconciliation import _process_reconciliation, _run_background_task

    chat_ids = [int(chat_id) for chat_id in (bot_chat_ids or []) if chat_id is not None]
    if not chat_ids:
        rows = (
            db.query(MonitoredBotChat.chat_id)
            .filter(MonitoredBotChat.enabled.is_(True))
            .all()
        )
        chat_ids = [int(row[0]) for row in rows]

    sync_warnings: List[Dict[str, Any]] = []
    for cid in chat_ids:
        cursor = db.get(TgHistoryCursor, cid)
        if not cursor:
            sync_warnings.append({
                "chat_id": cid,
                "warning": "not_synced",
                "message": f"Chat {cid} has not been synced yet",
            })
        elif cursor.status not in ("completed", "loading"):
            sync_warnings.append({
                "chat_id": cid,
                "warning": "sync_incomplete",
                "message": f"Chat {cid} sync status: {cursor.status}",
            })

    if source == "tdlib":
        sync_warnings.append({
            "chat_id": 0,
            "warning": "source_fallback",
            "message": "source=tdlib requested; using local synced history for this run",
        })

    task = AutomationTask(id=uuid4(), task_type="reconciliation", status="processing")
    db.add(task)
    db.commit()

    asyncio.create_task(
        _run_background_task(
            task.id,
            "reconciliation",
            _process_reconciliation(
                task_id=task.id,
                chat_ids=chat_ids,
                period_start=period_start,
                period_end=period_end,
                auto_parse=auto_parse,
                sync_warnings=sync_warnings,
            ),
        )
    )
    return {
        "task_id": str(task.id),
        "status": "started",
        "count": len(chat_ids),
        "sync_warnings": sync_warnings,
    }
