from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from services.automation import (
    start_mapping_analysis,
    start_reconciliation_analysis,
    start_verification_analysis,
)


ToolResult = Dict[str, Any]


async def app_mapping(db: Session, current_user: Dict[str, Any], scope: Optional[dict], args: Dict[str, Any]) -> ToolResult:
    started = await start_mapping_analysis(
        db,
        current_user=current_user,
        scope=scope,
        limit=int(args.get("limit") or 100),
        only_unmapped=bool(args.get("only_unmapped", True)),
        currency_filter=args.get("currency_filter"),
    )
    return {
        "summary": f"Запущен mapping-анализ: {started['count']} транзакций",
        "assistant_message": f"Запустил сопоставление приложений. В обработке: {started['count']} транзакций.",
        "cards": [{"type": "result", "title": "Сопоставление приложений", "body": f"В обработку отправлено: {started['count']} транзакций.", "payload": started, "details": started}],
        "run_reference": started,
    }


async def data_verification(db: Session, current_user: Dict[str, Any], scope: Optional[dict], args: Dict[str, Any]) -> ToolResult:
    started = await start_verification_analysis(
        db,
        current_user=current_user,
        scope=scope,
        limit=int(args.get("limit") or 50),
        date_from=datetime.fromisoformat(args["date_from"]) if args.get("date_from") else None,
        date_to=datetime.fromisoformat(args["date_to"]) if args.get("date_to") else None,
    )
    return {
        "summary": f"Запущена verification-задача: {started['count']} транзакций",
        "assistant_message": f"Запустил проверку данных. В обработке: {started['count']} транзакций.",
        "cards": [{"type": "result", "title": "Проверка данных", "body": f"В обработку отправлено: {started['count']} транзакций.", "payload": started, "details": started}],
        "run_reference": started,
    }


async def bot_reconciliation(db: Session, current_user: Dict[str, Any], scope: Optional[dict], args: Dict[str, Any]) -> ToolResult:
    period_end = datetime.fromisoformat(args["period_end"]) if args.get("period_end") else datetime.utcnow()
    period_start = datetime.fromisoformat(args["period_start"]) if args.get("period_start") else (period_end - timedelta(days=7))
    started = await start_reconciliation_analysis(
        db,
        current_user=current_user,
        period_start=period_start,
        period_end=period_end,
        bot_chat_ids=args.get("bot_chat_ids"),
        auto_parse=bool(args.get("auto_parse", False)),
        source=str(args.get("source") or "local"),
    )
    return {
        "summary": f"Запущена reconciliation-задача: {started['count']} источников",
        "assistant_message": f"Запустил сверку чеков. Проверяемых источников: {started['count']}.",
        "cards": [{"type": "result", "title": "Сверка чеков", "body": f"Проверяемых источников: {started['count']}.", "payload": started, "details": started}],
        "run_reference": started,
    }
