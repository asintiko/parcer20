"""Pydantic argument schemas + descriptions for v5 AI-agent tools.

Imported from `tool_schemas.py` after the legacy schema bundle is built — this
keeps existing v4 schemas untouched while letting the orchestrator register the
new tool surface in a single place.
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Dict, List, Literal, Optional, Type

from pydantic import BaseModel, Field, model_validator


# --------------------------------------------------------------------------- #
# UI-action tools
# --------------------------------------------------------------------------- #
class ApplyFiltersWithCursorArgs(BaseModel):
    date_from: Optional[date] = None
    date_to: Optional[date] = None
    operator: Optional[str] = Field(default=None, max_length=200)
    application: Optional[str] = Field(default=None, max_length=200)
    currency: Optional[Literal["UZS", "USD", "EUR", "RUB"]] = None
    transaction_type: Optional[Literal["DEBIT", "CREDIT", "CONVERSION", "REVERSAL"]] = None
    card_last_4: Optional[str] = Field(default=None, pattern=r"^\d{4}$")
    min_amount: Optional[Decimal] = None
    max_amount: Optional[Decimal] = None
    search: Optional[str] = Field(default=None, max_length=200)
    is_p2p: Optional[bool] = None
    source_chat_id: Optional[int] = None
    reset: bool = False
    rationale: Optional[str] = Field(default=None, max_length=200)


class MarkTransactionRowsArgs(BaseModel):
    transaction_ids: list[int] = Field(default_factory=list)
    mode: Literal["select", "highlight", "flag", "unflag"] = "highlight"


class ExportTransactionsArgs(BaseModel):
    format: Literal["xlsx", "csv", "json"] = "xlsx"
    date_from: Optional[date] = None
    date_to: Optional[date] = None
    operator: Optional[str] = None
    application: Optional[str] = None
    currency: Optional[Literal["UZS", "USD", "EUR", "RUB"]] = None
    source_chat_id: Optional[int] = None


class ClearFiltersArgs(BaseModel):
    pass


class ScrollToTransactionArgs(BaseModel):
    transaction_id: int = Field(ge=1)
    highlight_seconds: int = Field(default=4, ge=1, le=30)


class OpenTransactionDetailsArgs(BaseModel):
    transaction_id: int = Field(ge=1)


class SwitchViewArgs(BaseModel):
    view: Literal[
        "transactions",
        "monitored_chats",
        "operators",
        "audit",
        "reports",
        "settings",
    ]


class ShowChatOnlyMessageArgs(BaseModel):
    text: str = Field(max_length=4000)
    summary: Optional[str] = Field(default=None, max_length=200)


# --------------------------------------------------------------------------- #
# Calculation tools
# --------------------------------------------------------------------------- #
PeriodPreset = Literal[
    "today",
    "yesterday",
    "last_7_days",
    "last_30_days",
    "this_week",
    "last_week",
    "this_month",
    "last_month",
]


class _PeriodBase(BaseModel):
    preset: Optional[PeriodPreset] = None
    date_from: Optional[datetime] = None
    date_to: Optional[datetime] = None
    operator: Optional[str] = None
    currency: Optional[Literal["UZS", "USD", "EUR", "RUB"]] = None
    application: Optional[str] = None
    source_chat_id: Optional[int] = None
    transaction_type: Optional[
        Literal["DEBIT", "CREDIT", "CONVERSION", "REVERSAL"]
    ] = None


class PeriodSummaryArgs(_PeriodBase):
    pass


class _PeriodSlim(BaseModel):
    preset: Optional[PeriodPreset] = None
    date_from: Optional[datetime] = None
    date_to: Optional[datetime] = None


class ComparePeriodsArgs(_PeriodBase):
    a: Optional[_PeriodSlim] = None
    b: Optional[_PeriodSlim] = None


class TopOperatorsArgs(_PeriodBase):
    direction: Literal["spent", "received", "turnover"] = "spent"
    limit: int = Field(default=10, ge=1, le=50)


class GroupByDimensionArgs(_PeriodBase):
    dimension: Literal[
        "day", "week", "month", "operator", "application", "currency", "card"
    ] = "day"


# --------------------------------------------------------------------------- #
# Audit tools
# --------------------------------------------------------------------------- #
class FindDuplicateTransactionsArgs(BaseModel):
    date_from: Optional[datetime] = None
    date_to: Optional[datetime] = None
    min_group_size: int = Field(default=2, ge=2, le=10)
    limit: int = Field(default=20, ge=1, le=100)


class FindOrphanTransactionsArgs(BaseModel):
    date_from: Optional[datetime] = None
    date_to: Optional[datetime] = None
    limit: int = Field(default=100, ge=1, le=1000)


class VerifyReceiptParseArgs(BaseModel):
    transaction_id: int = Field(
        ..., description="ID транзакции, у которой нужно сверить распознанные поля с исходным текстом чека."
    )


class ChatVsDbReconcileArgs(BaseModel):
    chat_id: int
    date_from: Optional[datetime] = None
    date_to: Optional[datetime] = None


class WeeklyHealthCheckArgs(BaseModel):
    date_from: Optional[datetime] = None
    date_to: Optional[datetime] = None


class WeeklyReportAutofixArgs(BaseModel):
    date_from: Optional[datetime] = None
    date_to: Optional[datetime] = None


# --------------------------------------------------------------------------- #
# Automation tools (analyze + auto-apply + rollback)
# --------------------------------------------------------------------------- #
class AppMappingArgs(BaseModel):
    limit: int = Field(default=100, ge=1, le=200, description="Сколько операций взять в анализ.")
    currency: Optional[Literal["UZS", "USD", "EUR", "RUB"]] = Field(
        default=None, description="Ограничить анализ одной валютой."
    )
    only_unmapped: bool = Field(default=True, description="Только операции без приложения.")
    min_confidence: float = Field(
        default=0.85, ge=0.0, le=1.0,
        description="Порог авто-применения: предложения с уверенностью >= порога применяются сразу.",
    )


class DataVerificationArgs(BaseModel):
    limit: int = Field(default=50, ge=1, le=200, description="Сколько транзакций проверить.")
    date_from: Optional[datetime] = None
    date_to: Optional[datetime] = None
    min_confidence: float = Field(
        default=0.85, ge=0.0, le=1.0,
        description="Порог авто-применения уверенных исправлений.",
    )


class BotReconciliationArgs(BaseModel):
    period_days: int = Field(default=7, ge=1, le=180, description="Период сверки в днях, если не заданы date_from/date_to.")
    date_from: Optional[datetime] = None
    date_to: Optional[datetime] = None
    chat_ids: Optional[List[int]] = Field(default=None, description="Конкретные monitored chat id; пусто — все доступные.")
    source: Literal["local", "tdlib"] = "local"
    auto_parse: bool = Field(default=False, description="Сразу поставить пропущенные/ошибочные на повторный разбор.")


class ApplyMappingSuggestionsArgs(BaseModel):
    task_id: Optional[str] = Field(default=None, description="Задача сопоставления; пусто — все pending предложения.")
    min_confidence: float = Field(default=0.85, ge=0.0, le=1.0)
    ids: Optional[List[str]] = Field(default=None, description="Конкретные suggestion id (игнорируют порог).")


class ApplyVerificationSuggestionsArgs(BaseModel):
    task_id: Optional[str] = Field(default=None, description="Задача проверки; пусто — все pending исправления.")
    min_confidence: float = Field(default=0.85, ge=0.0, le=1.0)
    ids: Optional[List[str]] = Field(default=None, description="Конкретные suggestion id (игнорируют порог).")


class AutoParseReconciliationArgs(BaseModel):
    task_id: str = Field(..., description="ID завершённой задачи сверки.")
    category: Optional[Literal["MISSING_IN_DB", "FAILED_PARSE"]] = Field(
        default=None, description="Что разбирать; пусто — обе категории."
    )


class RollbackAutomationArgs(BaseModel):
    task_id: Optional[str] = Field(default=None, description="Откатить только изменения этой задачи; пусто — все агентские.")
    scope: Literal["all", "mapping", "verification"] = Field(
        default="all", description="Область отката: всё / только маппинг / только верификация.",
    )


# --------------------------------------------------------------------------- #
# Public registries
# --------------------------------------------------------------------------- #
class CreateRoutineArgs(BaseModel):
    name: str = Field(..., max_length=200, description="Короткое название рутины")
    cron: str = Field(
        default="0 12 * * 1",
        max_length=120,
        description="5-полевой cron 'мин час день месяц день_недели' в Asia/Tashkent. Пн=1..Вс=0/7.",
    )
    kind: Literal["reconcile", "summary", "custom"] = Field(
        default="reconcile",
        description="reconcile=сверка БД с сообщениями, summary=сводка за период, custom=прочее",
    )
    task_prompt: str = Field(..., max_length=4000, description="Текст задачи, что должен делать агент")


class ListRoutinesArgs(BaseModel):
    pass


class AutoDescribeOperatorsArgs(BaseModel):
    limit: int = Field(
        default=20, ge=1, le=50,
        description="Сколько операторов описать за один проход (кап 50).",
    )
    only_missing: bool = Field(
        default=True,
        description="True — описывать только операторов без описания; False — переописать все.",
    )


class SetOperatorDescriptionArgs(BaseModel):
    operator_raw: str = Field(..., max_length=500, description="Оператор, как в транзакции, напр. 'Korzinka Market'.")
    text: str = Field(..., max_length=120, description="Короткое описание (5-8 слов), напр. 'Сеть продуктовых супермаркетов'.")


class ListOperatorDescriptionsArgs(BaseModel):
    limit: int = Field(default=50, ge=1, le=200, description="Сколько описаний показать (кап 200).")


class RollbackOperatorDescriptionsArgs(BaseModel):
    operators: Optional[List[str]] = Field(
        default=None,
        description="Список операторов для отката. Пусто + all_agent → удалить все агентские.",
    )
    all_agent: bool = Field(
        default=False,
        description="True — удалить ВСЕ описания, добавленные агентом.",
    )


ARGS_MODELS_V5: Dict[str, Type[BaseModel]] = {
    # automation
    "app_mapping": AppMappingArgs,
    "data_verification": DataVerificationArgs,
    "bot_reconciliation": BotReconciliationArgs,
    "apply_mapping_suggestions": ApplyMappingSuggestionsArgs,
    "apply_verification_suggestions": ApplyVerificationSuggestionsArgs,
    "auto_parse_reconciliation": AutoParseReconciliationArgs,
    "rollback_automation": RollbackAutomationArgs,
    # ui_action
    "apply_filters_with_cursor": ApplyFiltersWithCursorArgs,
    "mark_transaction_rows": MarkTransactionRowsArgs,
    "export_transactions": ExportTransactionsArgs,
    "clear_filters_with_cursor": ClearFiltersArgs,
    "scroll_to_transaction": ScrollToTransactionArgs,
    "open_transaction_details": OpenTransactionDetailsArgs,
    "switch_view_with_cursor": SwitchViewArgs,
    "show_chat_only_message": ShowChatOnlyMessageArgs,
    # calc
    "period_summary": PeriodSummaryArgs,
    "compare_periods": ComparePeriodsArgs,
    "top_operators": TopOperatorsArgs,
    "group_by_dimension": GroupByDimensionArgs,
    # audit
    "find_duplicate_transactions": FindDuplicateTransactionsArgs,
    "find_orphan_transactions": FindOrphanTransactionsArgs,
    "verify_receipt_parse": VerifyReceiptParseArgs,
    "chat_vs_db_reconcile": ChatVsDbReconcileArgs,
    "weekly_health_check": WeeklyHealthCheckArgs,
    "weekly_report_autofix": WeeklyReportAutofixArgs,
    # routines
    "create_routine": CreateRoutineArgs,
    "list_routines": ListRoutinesArgs,
    # descriptions
    "auto_describe_operators": AutoDescribeOperatorsArgs,
    "set_operator_description": SetOperatorDescriptionArgs,
    "list_operator_descriptions": ListOperatorDescriptionsArgs,
    "rollback_operator_descriptions": RollbackOperatorDescriptionsArgs,
}


TOOL_DESCRIPTIONS_V5: Dict[str, str] = {
    # automation
    "app_mapping": (
        "AI-сопоставление неразмеченных операций с приложениями. Прогресс идёт живыми шагами "
        "в чат, по завершении уверенные предложения (>= min_confidence, по умолчанию 0.85) "
        "применяются автоматически, слабые показываются списком. Параметры: limit, currency, "
        "only_unmapped, min_confidence. Используй на 'сопоставь приложения / размечай операторов'."
    ),
    "data_verification": (
        "AI-проверка распарсенных транзакций на ошибки полей (сумма, дата, оператор и т.д.). "
        "Уверенные исправления применяет сразу, слабые — на проверку. Параметры: limit, "
        "date_from, date_to, min_confidence. Используй на 'проверь данные / найди ошибки в полях'."
    ),
    "bot_reconciliation": (
        "Сверяет Telegram-историю из локальной БД с транзакциями: совпадения, пропуски, ошибки "
        "разбора. Результат сводкой в чат. Параметры: period_days или date_from/date_to, chat_ids, "
        "source, auto_parse. Используй на 'сверь чеки / что не попало в базу'."
    ),
    "apply_mapping_suggestions": (
        "Применяет уверенные mapping-предложения (порог min_confidence). task_id — конкретная задача "
        "или пусто (все pending). ids — точечный список. Прежнее значение сохраняется для отката."
    ),
    "apply_verification_suggestions": (
        "Применяет уверенные field-level исправления (порог min_confidence). task_id/ids опциональны. "
        "Хранит old-значение для отката."
    ),
    "auto_parse_reconciliation": (
        "Ставит пропущенные/ошибочные сообщения завершённой сверки (MISSING_IN_DB/FAILED_PARSE) на "
        "повторный разбор. Нужен task_id завершённой сверки."
    ),
    "rollback_automation": (
        "Откатывает применённые агентом изменения. scope=all|mapping|verification; task_id опционален. "
        "Маппинг → прежнее значение, верификация → old. Где old не сохранён — честно сообщает, что "
        "откатить нельзя. Используй на 'откати / верни как было'."
    ),
    # ui_action
    "apply_filters_with_cursor": (
        "Применяет фильтры к таблице транзакций и инициирует анимацию агентского "
        "курсора (закрывает чат после показа). Используй когда пользователь просит "
        "'покажи / отфильтруй' и нужно физически наводить курсор на поля."
    ),
    "mark_transaction_rows": (
        "Отмечает / выделяет / флажит ряд строк в таблице. Курсор анимируется по "
        "каждой строке. Использовать когда пользователь говорит 'отметь', 'выдели', "
        "'пометь как ...'."
    ),
    "export_transactions": (
        "Запускает экспорт транзакций (xlsx/csv/json) с заданными фильтрами. "
        "Курсор кликает по кнопке экспорта."
    ),
    "clear_filters_with_cursor": (
        "Сбрасывает все фильтры таблицы. Курсор показывает действие."
    ),
    "scroll_to_transaction": (
        "Перематывает таблицу к конкретной транзакции по id и подсвечивает её."
    ),
    "open_transaction_details": (
        "Открывает деталь по transaction_id. Курсор кликает по строке."
    ),
    "switch_view_with_cursor": (
        "Переходит на другой раздел приложения (transactions / monitored_chats / "
        "operators / audit / reports / settings)."
    ),
    "show_chat_only_message": (
        "Чисто текстовый ответ в чат, без UI-действия и без закрытия чата. "
        "Используй когда пользователю просто нужна информация и никаких действий."
    ),
    # calc
    "period_summary": (
        "Сводка по транзакциям за период (preset или date_from/date_to): расход, "
        "приход, нет, количество, разбивка по валютам."
    ),
    "compare_periods": (
        "Сравнивает 2 периода (a и b) и показывает дельту в % и абсолютном значении."
    ),
    "top_operators": (
        "Топ-N операторов за период по расходу/приходу/обороту."
    ),
    "group_by_dimension": (
        "Группировка транзакций по day / week / month / operator / application / "
        "currency / card."
    ),
    # audit
    "find_duplicate_transactions": (
        "Находит группы возможных дубликатов транзакций по (amount, transaction_date, "
        "card_last_4)."
    ),
    "find_orphan_transactions": (
        "Находит транзакции без оператора или без application mapping."
    ),
    "verify_receipt_parse": (
        "Сверяет распознанные поля одной транзакции с исходным текстом чека. "
        "Берёт сохранённый текст (raw_message или сообщение из кэша), повторно "
        "разбирает его regex-каскадом (без AI/OCR) и сравнивает amount, дату, "
        "оператора, application, карту и тип. Используй когда просят 'проверь что "
        "транзакцию N разобрали верно / вдруг что не так с чеком N'. Только чтение."
    ),
    "chat_vs_db_reconcile": (
        "Сверяет один monitored chat с БД: cached vs receipt_processing_tasks vs "
        "transactions. Возвращает список проблем."
    ),
    "weekly_health_check": (
        "Полный health-check за неделю: всем активным monitored chats, дубликаты, "
        "orphan rows, failed/stuck задач. Возвращает агрегированный отчёт."
    ),
    "weekly_report_autofix": (
        "Готовит preview авто-исправления (merge duplicates + reparse orphans) с "
        "confirmation_payload. Применяется по подтверждению пользователя."
    ),
    "create_routine": (
        "Создаёт плановую рутину (повторяющуюся задачу). Извлеки из фразы пользователя: "
        "name (название), cron (расписание: 'мин час день месяц день_недели', "
        "Asia/Tashkent, пн=1), kind (reconcile=сверка / summary=сводка / custom), "
        "task_prompt (текст задачи). Пример: 'каждый понедельник в 12 делай сверку всех "
        "транзакций' → name='Еженедельная сверка', cron='0 12 * * 1', kind='reconcile'."
    ),
    "list_routines": "Показывает список настроенных рутин.",
    # descriptions
    "auto_describe_operators": (
        "Просматривает операторов транзакций, по каждому ищет в интернете, что это за "
        "продавец/сервис, и АВТОМАТИЧЕСКИ (без подтверждения) вписывает короткое описание "
        "в 5-8 слов. По умолчанию берёт только операторов без описания. Используй на фразы "
        "'добавь описания операциям / найди что за продавцы / опиши операторов'. Параметры: "
        "limit (по умолчанию 20, максимум 50), only_missing (по умолчанию true). "
        "Пример: 'опиши 30 операторов' → limit=30."
    ),
    "set_operator_description": (
        "Вписывает описание одному оператору напрямую (operator_raw + text), без подтверждения. "
        "Пример: operator_raw='Korzinka Market', text='Сеть продуктовых супермаркетов'."
    ),
    "list_operator_descriptions": (
        "Показывает сохранённые описания операторов (оператор → текст + источник manual/agent). "
        "Параметр limit (по умолчанию 50, максимум 200)."
    ),
    "rollback_operator_descriptions": (
        "Откатывает описания, добавленные агентом. all_agent=true (или пустой список) — удалить "
        "все агентские; operators=[...] — удалить только перечисленных. Manual-описания не трогает. "
        "Пример: 'удали все описания что ты добавил' → all_agent=true."
    ),
}
