from __future__ import annotations

from typing import Any, Awaitable, Callable, Dict, Optional

from sqlalchemy.orm import Session

from config.ai_models import AI_AGENT_MUTATION_TOOLS_ENABLED
from services.ai_agent.tools.analytics_tools import transaction_analytics
from services.ai_agent.tools.automation_tools import (
    app_mapping,
    apply_mapping_suggestions_tool,
    apply_verification_suggestions_tool,
    auto_parse_reconciliation_tool,
    bot_reconciliation,
    data_verification,
    rollback_automation_tool,
)
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
from services.ai_agent.tools.filter_tools import apply_table_filters
from services.ai_agent.tools.mutation_tools import (
    bulk_update_transactions,
    create_transaction,
    update_transaction,
)
from services.ai_agent.tools.navigation_tools import table_search_and_navigate
from services.ai_agent.tools.report_tools import report_builder


ToolCallable = Callable[[Session, Dict[str, Any], Optional[dict], Dict[str, Any]], Awaitable[Dict[str, Any]]]


TOOL_DESCRIPTIONS: Dict[str, str] = {
    "transaction_analytics": "Считает суммы расходов, поступлений и оборота за период с учетом текущих прав доступа.",
    "app_mapping": "AI-сопоставление неразмеченных операций с приложениями. Результат и автоприменённые уверенные предложения отдаёт прямо в чат (без перехода в раздел). Параметры: limit, currency, only_unmapped, min_confidence.",
    "data_verification": "AI-проверка распарсенных транзакций на ошибки полей. Уверенные исправления применяет автоматически и отчитывается в чат. Параметры: limit, date_from, date_to, min_confidence.",
    "bot_reconciliation": "Сверяет Telegram-историю из локальной БД с транзакциями, ищет пропуски/ошибки, отдаёт сводку в чат. Параметры: period_days или date_from/date_to, chat_ids, source, auto_parse.",
    "apply_mapping_suggestions": "Применяет уверенные mapping-предложения задачи (порог min_confidence). Можно указать конкретные ids. Записывает прежнее значение для отката.",
    "apply_verification_suggestions": "Применяет уверенные field-level исправления задачи (порог min_confidence). Можно указать ids. Хранит old-значение для отката.",
    "auto_parse_reconciliation": "Ставит на повторный разбор пропущенные/ошибочные сообщения из завершённой сверки (MISSING_IN_DB/FAILED_PARSE).",
    "rollback_automation": "Откатывает применённые агентом изменения: маппинг → в прежнее значение, верификацию → в old. Параметры: task_id (опц.), scope=all|mapping|verification.",
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
    "apply_table_filters": "Применяет набор фильтров к таблице транзакций (без обращения к БД).",
    "create_transaction": "Готовит preview создания новой транзакции — применяется после подтверждения.",
    "update_transaction": "Готовит preview редактирования полей транзакции — применяется после подтверждения.",
    "bulk_update_transactions": "Готовит preview массового редактирования набора транзакций.",
}


TOOLS: Dict[str, ToolCallable] = {
    "transaction_analytics": transaction_analytics,
    "app_mapping": app_mapping,
    "data_verification": data_verification,
    "bot_reconciliation": bot_reconciliation,
    "apply_mapping_suggestions": apply_mapping_suggestions_tool,
    "apply_verification_suggestions": apply_verification_suggestions_tool,
    "auto_parse_reconciliation": auto_parse_reconciliation_tool,
    "rollback_automation": rollback_automation_tool,
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
    "apply_table_filters": apply_table_filters,
}

if AI_AGENT_MUTATION_TOOLS_ENABLED:
    TOOLS["create_transaction"] = create_transaction
    TOOLS["update_transaction"] = update_transaction
    TOOLS["bulk_update_transactions"] = bulk_update_transactions


# --------------------------------------------------------------------------- #
# v5 extensions: ui_action / calc / audit tools.
# Loaded lazily so a missing module never breaks legacy registry.
# --------------------------------------------------------------------------- #
try:
    from services.ai_agent.tools.ui_action_tools import (
        apply_filters_with_cursor,
        clear_filters_with_cursor,
        export_transactions,
        mark_transaction_rows,
        open_transaction_details,
        scroll_to_transaction,
        show_chat_only_message,
        switch_view_with_cursor,
    )
    from services.ai_agent.tools.calc_tools import (
        compare_periods,
        group_by_dimension,
        period_summary,
        top_operators,
    )
    from services.ai_agent.tools.audit_tools import (
        chat_vs_db_reconcile,
        find_duplicate_transactions,
        find_orphan_transactions,
        verify_receipt_parse,
        weekly_health_check,
        weekly_report_autofix,
    )
    from services.ai_agent.tools.routine_tools import (
        create_routine_tool,
        list_routines_tool,
    )
    from services.ai_agent.tools.description_tools import (
        auto_describe_operators,
        list_operator_descriptions,
        rollback_operator_descriptions,
        set_operator_description,
    )

    TOOLS.update(
        {
            "apply_filters_with_cursor": apply_filters_with_cursor,
            "mark_transaction_rows": mark_transaction_rows,
            "export_transactions": export_transactions,
            "clear_filters_with_cursor": clear_filters_with_cursor,
            "scroll_to_transaction": scroll_to_transaction,
            "open_transaction_details": open_transaction_details,
            "switch_view_with_cursor": switch_view_with_cursor,
            "show_chat_only_message": show_chat_only_message,
            "period_summary": period_summary,
            "compare_periods": compare_periods,
            "top_operators": top_operators,
            "group_by_dimension": group_by_dimension,
            "find_duplicate_transactions": find_duplicate_transactions,
            "find_orphan_transactions": find_orphan_transactions,
            "verify_receipt_parse": verify_receipt_parse,
            "chat_vs_db_reconcile": chat_vs_db_reconcile,
            "weekly_health_check": weekly_health_check,
            "weekly_report_autofix": weekly_report_autofix,
            "create_routine": create_routine_tool,
            "list_routines": list_routines_tool,
            "auto_describe_operators": auto_describe_operators,
            "set_operator_description": set_operator_description,
            "list_operator_descriptions": list_operator_descriptions,
            "rollback_operator_descriptions": rollback_operator_descriptions,
        }
    )
    TOOL_DESCRIPTIONS.update(
        {
            "apply_filters_with_cursor": "Применить фильтры (анимация курсора)",
            "mark_transaction_rows": "Отметить строки",
            "export_transactions": "Экспорт",
            "clear_filters_with_cursor": "Сбросить фильтры",
            "scroll_to_transaction": "Промотать к транзакции",
            "open_transaction_details": "Открыть детали",
            "switch_view_with_cursor": "Перейти в раздел",
            "show_chat_only_message": "Только текстовый ответ",
            "period_summary": "Сводка за период",
            "compare_periods": "Сравнить два периода",
            "top_operators": "Топ операторов",
            "group_by_dimension": "Группировка",
            "find_duplicate_transactions": "Найти дубликаты",
            "find_orphan_transactions": "Без маппинга",
            "verify_receipt_parse": "Сверить распознавание чека",
            "chat_vs_db_reconcile": "Сверка чата с БД",
            "weekly_health_check": "Недельный health-check",
            "weekly_report_autofix": "Авто-исправление",
            "create_routine": "Создать рутину (плановую задачу): извлеки название, расписание (cron 'мин час день месяц день_недели' в Asia/Tashkent), тип (reconcile=сверка/summary=сводка/custom) и текст задачи из фразы пользователя. Пример: 'каждый понедельник в 12 делай сверку' → cron '0 12 * * 1', kind 'reconcile'.",
            "list_routines": "Показать список настроенных рутин.",
            "auto_describe_operators": "Просмотреть операторов транзакций, найти каждого в интернете и автоматически вписать короткое описание (5-8 слов). Запись без подтверждения. Используй на фразы 'добавь описания операторам / найди что за продавцы / опиши операции'.",
            "set_operator_description": "Вписать описание конкретному оператору напрямую (operator_raw + text). Запись без подтверждения.",
            "list_operator_descriptions": "Показать сохранённые описания операторов (оператор → текст + источник).",
            "rollback_operator_descriptions": "Откатить агентские описания: все (all_agent=true или пусто) либо по списку operators. Удаляет только source=agent.",
        }
    )
except Exception as _exc:  # noqa: BLE001
    import logging as _logging

    _logging.getLogger(__name__).warning("v5 tools not registered: %s", _exc)


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
