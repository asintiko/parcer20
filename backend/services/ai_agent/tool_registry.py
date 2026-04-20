from __future__ import annotations

from typing import Any, Awaitable, Callable, Dict, Optional

from sqlalchemy.orm import Session

from services.ai_agent.tools.analytics_tools import transaction_analytics
from services.ai_agent.tools.automation_tools import app_mapping, bot_reconciliation, data_verification
from services.ai_agent.tools.cache_tools import (
    duplicate_merge_preview,
    failed_receipt_investigator,
    message_to_transaction_trace,
    monitor_config_inspector,
    monitored_chat_sync_audit,
    receipt_reparse_preview,
    report_publish_tool,
    telegram_cache_search,
)
from services.ai_agent.tools.diagnostics_tools import (
    db_inspector,
    duplicate_detector,
    fix_plan_builder,
    processing_errors_analyzer,
    source_health_check,
)
from services.ai_agent.tools.navigation_tools import table_search_and_navigate
from services.ai_agent.tools.report_tools import report_builder


ToolCallable = Callable[[Session, Dict[str, Any], Optional[dict], Dict[str, Any]], Awaitable[Dict[str, Any]]]


TOOL_DESCRIPTIONS: Dict[str, str] = {
    "transaction_analytics": "Считает суммы расходов, поступлений и оборота за период с учетом текущих прав доступа.",
    "app_mapping": "Запускает AI-анализ неразмеченных транзакций и создает mapping suggestions.",
    "data_verification": "Запускает AI-проверку уже распарсенных транзакций и создает field-level corrections.",
    "bot_reconciliation": "Сравнивает Telegram history из локальной БД с транзакциями и ищет пропуски/ошибки.",
    "table_search_and_navigate": "Находит транзакцию и возвращает navigation target для UI таблицы.",
    "db_inspector": "Дает агрегированный быстрый срез по БД и проблемным очередям.",
    "duplicate_detector": "Возвращает текущие pending duplicate suggestions.",
    "processing_errors_analyzer": "Возвращает recent failed receipt processing tasks.",
    "source_health_check": "Показывает состояние monitored chats и history sync.",
    "monitored_chat_sync_audit": "Проверяет весь доступный период по monitored chats, находит пропущенные чеки, failed parse и stale cursors.",
    "telegram_cache_search": "Ищет сообщения и чеки в серверном Telegram cache.",
    "message_to_transaction_trace": "Строит трассировку: сообщение -> processing task -> transaction -> duplicate path.",
    "failed_receipt_investigator": "Разбирает проблемный чек и объясняет, почему он не попал в таблицу.",
    "duplicate_merge_preview": "Показывает preview кандидатов на merge дублей без изменений данных.",
    "receipt_reparse_preview": "Показывает preview повторного разбора проблемного сообщения без применения изменений.",
    "monitor_config_inspector": "Проверяет настройки мониторинга и состояние синка по monitored chats.",
    "report_publish_tool": "Публикует командный отчет в едином формате с team notifications.",
    "report_builder": "Генерирует личный или командный отчет агента.",
    "fix_plan_builder": "Формирует структурированный план исправлений по быстрым диагностическим метрикам.",
}


TOOLS: Dict[str, ToolCallable] = {
    "transaction_analytics": transaction_analytics,
    "app_mapping": app_mapping,
    "data_verification": data_verification,
    "bot_reconciliation": bot_reconciliation,
    "table_search_and_navigate": table_search_and_navigate,
    "db_inspector": db_inspector,
    "duplicate_detector": duplicate_detector,
    "processing_errors_analyzer": processing_errors_analyzer,
    "source_health_check": source_health_check,
    "monitored_chat_sync_audit": monitored_chat_sync_audit,
    "telegram_cache_search": telegram_cache_search,
    "message_to_transaction_trace": message_to_transaction_trace,
    "failed_receipt_investigator": failed_receipt_investigator,
    "duplicate_merge_preview": duplicate_merge_preview,
    "receipt_reparse_preview": receipt_reparse_preview,
    "monitor_config_inspector": monitor_config_inspector,
    "report_publish_tool": report_publish_tool,
    "report_builder": report_builder,
    "fix_plan_builder": fix_plan_builder,
}


async def execute_tool(
    name: str,
    *,
    db: Session,
    current_user: Dict[str, Any],
    scope: Optional[dict],
    arguments: Optional[Dict[str, Any]] = None,
    progress_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
) -> Dict[str, Any]:
    tool = TOOLS.get(name)
    if not tool:
        return {
            "summary": f"Неизвестный инструмент: {name}",
            "cards": [{"type": "warning", "title": "Tool not found", "body": name}],
        }
    payload = dict(arguments or {})
    if progress_callback is not None:
        payload["_progress_callback"] = progress_callback
    return await tool(db, current_user, scope, payload)
