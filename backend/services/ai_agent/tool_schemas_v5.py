"""Pydantic argument schemas + descriptions for v5 AI-agent tools.

Imported from `tool_schemas.py` after the legacy schema bundle is built — this
keeps existing v4 schemas untouched while letting the orchestrator register the
new tool surface in a single place.
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Dict, Literal, Optional, Type

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


ARGS_MODELS_V5: Dict[str, Type[BaseModel]] = {
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
    "chat_vs_db_reconcile": ChatVsDbReconcileArgs,
    "weekly_health_check": WeeklyHealthCheckArgs,
    "weekly_report_autofix": WeeklyReportAutofixArgs,
    # routines
    "create_routine": CreateRoutineArgs,
    "list_routines": ListRoutinesArgs,
}


TOOL_DESCRIPTIONS_V5: Dict[str, str] = {
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
}
