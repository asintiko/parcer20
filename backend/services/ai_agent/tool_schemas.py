"""Single source of truth for AI agent tool schemas.

Defines Pydantic argument models for each tool, plus the JSON Schema list
that is shipped to DeepSeek via OpenAI-compatible `tools=[...]`.

Design notes
------------
* Every tool has a Pydantic model in ARGS_MODELS — used to validate the
  arguments coming back from the LLM before dispatch.
* TOOL_SCHEMAS exposes the same set of tools to the LLM in OpenAI's
  `function`-style envelope. We flatten any `$ref/$defs` produced by
  pydantic so DeepSeek does not need recursive schema support.
* Mutation tools (create/update/bulk) are gated by
  AI_AGENT_MUTATION_TOOLS_ENABLED; they are excluded from TOOL_SCHEMAS
  when the flag is off.
* AgentSuggestedFilters / AgentLocateResult are the wire contract between
  backend tools and the frontend TransactionsPage navigation handler.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Dict, List, Literal, Optional, Type

from pydantic import BaseModel, Field, model_validator

from config.ai_models import AI_AGENT_MUTATION_TOOLS_ENABLED


# ─── Common contract models ──────────────────────────────────────────────────

FocusMode = Literal["row", "filter", "none"]
TransactionType = Literal["DEBIT", "CREDIT", "CONVERSION", "REVERSAL"]
SourceChannel = Literal["TELEGRAM", "SMS", "MANUAL", "ALL"]
Direction = Literal["spent", "received", "turnover", "any"]
ReportGroupBy = Literal["day", "week", "month", "application", "source"]
AnalyticsGroupBy = Literal[
    "day", "week", "month", "application", "source", "currency"
]


class AgentSuggestedFilters(BaseModel):
    """Filter payload that flows from agent tools to the table UI.

    Field names mirror the existing TransactionsPage FilterState where
    practical (camelCase for date bounds, snake_case for the rest, matching
    backend `/api/transactions/` query params).
    """

    search: Optional[str] = None
    dateFrom: Optional[str] = Field(default=None, description="ISO date or datetime")
    dateTo: Optional[str] = Field(default=None, description="ISO date or datetime")
    apps: Optional[List[str]] = None
    operators: Optional[List[str]] = None
    source_channel: Optional[SourceChannel] = None
    source_chat_ids: Optional[List[int]] = None
    transaction_types: Optional[List[TransactionType]] = None
    currency: Optional[str] = None
    amount_min: Optional[str] = Field(
        default=None, description="Inclusive lower bound, decimal as string"
    )
    amount_max: Optional[str] = Field(
        default=None, description="Inclusive upper bound, decimal as string"
    )
    parsing_method: Optional[str] = None
    confidence_min: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    confidence_max: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    card_id: Optional[str] = Field(
        default=None, description="Last 4 digits of card"
    )
    days_of_week: Optional[List[int]] = Field(
        default=None, description="Day-of-week ints, 0=Sunday..6=Saturday"
    )
    reset: bool = Field(
        default=False,
        description="If true the UI clears all filters before applying these.",
    )


class AgentLocateResult(BaseModel):
    exists: bool
    route: str = "/"
    row_id: Optional[int] = None
    row_ids: Optional[List[int]] = None
    column_id: Optional[str] = None
    focus_mode: FocusMode = "filter"
    suggested_filters: AgentSuggestedFilters = Field(
        default_factory=AgentSuggestedFilters
    )
    sort_hint: Optional[Dict[str, str]] = None
    page_hint: Optional[int] = None
    cursor_hint: Optional[str] = None
    highlight_seconds: int = 4


# ─── Tool argument models ────────────────────────────────────────────────────


class ApplyFiltersArgs(BaseModel):
    """Arguments for `apply_table_filters` (and reused by other tools)."""

    date_from: Optional[date] = None
    date_to: Optional[date] = None
    operators: Optional[List[str]] = None
    apps: Optional[List[str]] = None
    amount_min: Optional[Decimal] = None
    amount_max: Optional[Decimal] = None
    currency: Optional[str] = None
    transaction_types: Optional[List[TransactionType]] = None
    source_channel: Optional[SourceChannel] = None
    source_chat_ids: Optional[List[int]] = None
    parsing_method: Optional[str] = None
    confidence_min: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    confidence_max: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    card_id: Optional[str] = None
    days_of_week: Optional[List[int]] = None
    search: Optional[str] = None
    reset: bool = False


class TransactionAnalyticsArgs(BaseModel):
    query_text: Optional[str] = Field(
        default=None,
        description="Original user phrasing — used as a date-parsing fallback.",
    )
    direction: Direction = "any"
    currency: Optional[Literal["UZS", "USD", "EUR", "RUB"]] = None
    date_from: Optional[datetime] = None
    date_to: Optional[datetime] = None
    application: Optional[str] = None
    apps: Optional[List[str]] = None
    operators: Optional[List[str]] = None
    source_channel: Optional[SourceChannel] = None
    source_chat_ids: Optional[List[int]] = None
    amount_min: Optional[Decimal] = None
    amount_max: Optional[Decimal] = None
    search: Optional[str] = None
    group_by: AnalyticsGroupBy = "currency"


class ReportBuilderArgs(BaseModel):
    period_start: Optional[datetime] = None
    period_end: Optional[datetime] = None
    team: bool = False
    thread_id: Optional[str] = None
    group_by: ReportGroupBy = "week"


class TableSearchArgs(BaseModel):
    transaction_id: Optional[int] = Field(default=None, ge=1)
    search: Optional[str] = None
    sort_by: str = "transaction_date"
    sort_dir: Literal["asc", "desc"] = "desc"
    page_size: int = Field(default=100, ge=1, le=500)
    filters: Optional[ApplyFiltersArgs] = None


class DiagnosticsArgs(BaseModel):
    query_text: Optional[str] = None


class AutomationArgs(BaseModel):
    query_text: Optional[str] = None


class DuplicateMergePreviewArgs(BaseModel):
    suggestion_ids: Optional[List[str]] = None
    limit: int = Field(default=5, ge=1, le=50)


class ReceiptReparsePreviewArgs(BaseModel):
    chat_id: Optional[int] = None
    message_id: Optional[int] = None
    query_text: Optional[str] = None


class MonitorConfigInspectorArgs(BaseModel):
    pass


class TelegramCacheSearchArgs(BaseModel):
    query_text: Optional[str] = None
    chat_id: Optional[int] = None
    limit: int = Field(default=20, ge=1, le=100)


class MessageTraceArgs(BaseModel):
    chat_id: Optional[int] = None
    message_id: Optional[int] = None
    transaction_id: Optional[int] = None
    query_text: Optional[str] = None


class FailedReceiptInvestigatorArgs(BaseModel):
    chat_id: Optional[int] = None
    message_id: Optional[int] = None
    task_id: Optional[str] = None
    query_text: Optional[str] = None


class ReportPublishArgs(BaseModel):
    report_id: Optional[str] = None


class MonitoredChatSyncAuditArgs(BaseModel):
    query_text: Optional[str] = None
    date_from: Optional[datetime] = None
    date_to: Optional[datetime] = None


class FixPlanBuilderArgs(BaseModel):
    query_text: Optional[str] = None


# ─── Mutation tools ──────────────────────────────────────────────────────────


class CreateTransactionArgs(BaseModel):
    transaction_datetime: datetime = Field(
        ..., description="ISO datetime of the transaction"
    )
    operator: str = Field(..., min_length=1, max_length=255)
    amount: Decimal = Field(..., ge=0)
    card_last4: str = Field(..., pattern=r"^\d{4}$")
    transaction_type: TransactionType
    currency: Literal["UZS", "USD"]
    app: Optional[str] = Field(default=None, max_length=100)
    balance: Optional[Decimal] = None
    is_p2p: Optional[bool] = False
    receiver_name: Optional[str] = Field(default=None, max_length=255)
    receiver_card: Optional[str] = Field(default=None, pattern=r"^\d{4,32}$")
    raw_text: Optional[str] = None


class UpdateTransactionPatch(BaseModel):
    """Whitelist of fields the agent is allowed to patch."""

    transaction_date: Optional[datetime] = None
    operator_raw: Optional[str] = Field(default=None, max_length=255)
    application_mapped: Optional[str] = Field(default=None, max_length=100)
    amount: Optional[Decimal] = Field(default=None, ge=0)
    balance_after: Optional[Decimal] = None
    card_last_4: Optional[str] = Field(default=None, pattern=r"^\d{4}$")
    receiver_name: Optional[str] = Field(default=None, max_length=255)
    receiver_card: Optional[str] = Field(default=None, pattern=r"^\d{4,32}$")
    transaction_type: Optional[TransactionType] = None
    currency: Optional[Literal["UZS", "USD"]] = None
    is_p2p: Optional[bool] = None

    @model_validator(mode="after")
    def _at_least_one_field(self) -> "UpdateTransactionPatch":
        if not self.model_dump(exclude_unset=True, exclude_none=True):
            raise ValueError("patch_must_contain_at_least_one_field")
        return self


class UpdateTransactionArgs(BaseModel):
    transaction_id: int = Field(..., ge=1)
    patch: UpdateTransactionPatch


class BulkUpdateTransactionsArgs(BaseModel):
    transaction_ids: List[int] = Field(..., min_length=1, max_length=200)
    patch: UpdateTransactionPatch


# ─── Tool descriptions (shown to the LLM) ────────────────────────────────────

TOOL_DESCRIPTIONS_NATIVE: Dict[str, str] = {
    "transaction_analytics": (
        "Считает суммы расходов, поступлений, оборота за период с учетом фильтров. "
        "Используй для вопросов 'сколько потратил/получил/всего за …'."
    ),
    "report_builder": (
        "Генерирует структурированный отчет за period_start..period_end с группировкой. "
        "Используй когда пользователь явно просит 'отчет', 'сводку', 'weekly report'."
    ),
    "apply_table_filters": (
        "Просит UI применить набор фильтров к таблице транзакций. "
        "Используй когда пользователь говорит 'покажи транзакции X / отфильтруй Y'. "
        "К БД не обращается, только формирует navigation_target с фильтрами."
    ),
    "table_search_and_navigate": (
        "Ищет конкретную транзакцию по id или поиску, возвращает navigation target. "
        "Можно дополнительно передать filters."
    ),
    "create_transaction": (
        "Готовит preview создания новой транзакции. Возвращает confirmation_payload — "
        "реальное создание происходит после подтверждения пользователем."
    ),
    "update_transaction": (
        "Готовит preview редактирования полей одной транзакции. Возвращает "
        "confirmation_payload с diff. Изменения применяются после подтверждения."
    ),
    "bulk_update_transactions": (
        "Готовит preview массового редактирования набора транзакций одним и тем же "
        "патчем. Применяется только после подтверждения."
    ),
    "app_mapping": "Запускает AI-анализ неразмеченных транзакций и создает mapping suggestions.",
    "data_verification": "Запускает AI-проверку распарсенных транзакций.",
    "bot_reconciliation": "Сверяет Telegram history с транзакциями и ищет пропуски.",
    "db_inspector": "Дает быстрый агрегированный срез по БД и проблемным очередям.",
    "duplicate_detector": "Возвращает текущие pending duplicate suggestions.",
    "processing_errors_analyzer": "Возвращает recent failed receipt processing tasks.",
    "source_health_check": "Показывает состояние monitored chats и history sync.",
    "monitored_chat_sync_audit": (
        "Полный аудит monitored chats: пропущенные чеки, failed parse, stale cursors."
    ),
    "telegram_cache_search": "Ищет сообщения и чеки в серверном Telegram cache.",
    "message_to_transaction_trace": (
        "Строит трассировку сообщение → processing task → transaction → duplicate."
    ),
    "failed_receipt_investigator": (
        "Объясняет почему конкретный чек не попал в таблицу."
    ),
    "duplicate_merge_preview": "Preview merge кандидатов на дубликаты, без изменений.",
    "receipt_reparse_preview": "Preview повторного разбора сообщения, без изменений.",
    "monitor_config_inspector": "Проверяет настройки мониторинга и состояние синка.",
    "report_publish_tool": "Публикует командный отчет.",
    "fix_plan_builder": "Формирует план исправлений по диагностическим метрикам.",
}


# ─── Pydantic args registry ──────────────────────────────────────────────────

ARGS_MODELS_ALL: Dict[str, Type[BaseModel]] = {
    "transaction_analytics": TransactionAnalyticsArgs,
    "report_builder": ReportBuilderArgs,
    "apply_table_filters": ApplyFiltersArgs,
    "table_search_and_navigate": TableSearchArgs,
    "create_transaction": CreateTransactionArgs,
    "update_transaction": UpdateTransactionArgs,
    "bulk_update_transactions": BulkUpdateTransactionsArgs,
    "app_mapping": AutomationArgs,
    "data_verification": AutomationArgs,
    "bot_reconciliation": AutomationArgs,
    "db_inspector": DiagnosticsArgs,
    "duplicate_detector": DiagnosticsArgs,
    "processing_errors_analyzer": DiagnosticsArgs,
    "source_health_check": DiagnosticsArgs,
    "monitored_chat_sync_audit": MonitoredChatSyncAuditArgs,
    "telegram_cache_search": TelegramCacheSearchArgs,
    "message_to_transaction_trace": MessageTraceArgs,
    "failed_receipt_investigator": FailedReceiptInvestigatorArgs,
    "duplicate_merge_preview": DuplicateMergePreviewArgs,
    "receipt_reparse_preview": ReceiptReparsePreviewArgs,
    "monitor_config_inspector": MonitorConfigInspectorArgs,
    "report_publish_tool": ReportPublishArgs,
    "fix_plan_builder": FixPlanBuilderArgs,
}

_MUTATION_TOOLS = {
    "create_transaction",
    "update_transaction",
    "bulk_update_transactions",
}


def _active_tool_names() -> List[str]:
    names = list(ARGS_MODELS_ALL.keys())
    if not AI_AGENT_MUTATION_TOOLS_ENABLED:
        names = [n for n in names if n not in _MUTATION_TOOLS]
    return names


ARGS_MODELS: Dict[str, Type[BaseModel]] = {
    name: ARGS_MODELS_ALL[name] for name in _active_tool_names()
}


# ─── JSON Schema flattening ──────────────────────────────────────────────────


def _resolve_refs(node: Any, defs: Dict[str, Any]) -> Any:
    """Inline `$ref` → defs[X], collapse single-item allOf, drop $defs."""
    if isinstance(node, dict):
        if "$ref" in node and isinstance(node["$ref"], str):
            ref = node["$ref"]
            if ref.startswith("#/$defs/"):
                key = ref.split("/")[-1]
                target = defs.get(key)
                if target is not None:
                    merged = {k: v for k, v in node.items() if k != "$ref"}
                    resolved = _resolve_refs(target, defs)
                    if isinstance(resolved, dict):
                        for k, v in resolved.items():
                            merged.setdefault(k, v)
                        return merged
                    return resolved
        if "allOf" in node and isinstance(node["allOf"], list) and len(node["allOf"]) == 1:
            single = _resolve_refs(node["allOf"][0], defs)
            rest = {k: v for k, v in node.items() if k != "allOf"}
            if isinstance(single, dict):
                merged = {**single, **rest}
                return _resolve_refs(merged, defs)
        return {
            k: _resolve_refs(v, defs)
            for k, v in node.items()
            if k != "$defs"
        }
    if isinstance(node, list):
        return [_resolve_refs(item, defs) for item in node]
    return node


def build_json_schema(model: Type[BaseModel]) -> Dict[str, Any]:
    schema = model.model_json_schema(mode="validation")
    defs = schema.get("$defs", {}) if isinstance(schema, dict) else {}
    flattened = _resolve_refs(schema, defs)
    if isinstance(flattened, dict):
        flattened.pop("$defs", None)
        flattened.pop("title", None)
    return flattened or {"type": "object", "properties": {}}


def build_tool_schemas() -> List[Dict[str, Any]]:
    """Return OpenAI-compatible tool schema list for the active toolset."""
    schemas: List[Dict[str, Any]] = []
    for name, model in ARGS_MODELS.items():
        description = TOOL_DESCRIPTIONS_NATIVE.get(name) or name
        parameters = build_json_schema(model)
        schemas.append(
            {
                "type": "function",
                "function": {
                    "name": name,
                    "description": description,
                    "parameters": parameters,
                },
            }
        )
    return schemas


TOOL_SCHEMAS: List[Dict[str, Any]] = build_tool_schemas()


# --------------------------------------------------------------------------- #
# v5 extensions: ui_action / calc / audit tools.
# Imported lazily so a missing v5 module never breaks legacy code.
# --------------------------------------------------------------------------- #
try:
    from services.ai_agent.tool_schemas_v5 import (
        ARGS_MODELS_V5,
        TOOL_DESCRIPTIONS_V5,
    )

    for _name, _model in ARGS_MODELS_V5.items():
        ARGS_MODELS_ALL[_name] = _model
        ARGS_MODELS[_name] = _model
        TOOL_DESCRIPTIONS_NATIVE[_name] = TOOL_DESCRIPTIONS_V5[_name]
    TOOL_SCHEMAS = build_tool_schemas()
except Exception as _exc:  # noqa: BLE001
    import logging as _logging

    _logging.getLogger(__name__).warning(
        "v5 tool schemas not loaded: %s", _exc
    )



__all__ = [
    "AgentSuggestedFilters",
    "AgentLocateResult",
    "ApplyFiltersArgs",
    "TransactionAnalyticsArgs",
    "ReportBuilderArgs",
    "TableSearchArgs",
    "CreateTransactionArgs",
    "UpdateTransactionArgs",
    "UpdateTransactionPatch",
    "BulkUpdateTransactionsArgs",
    "DiagnosticsArgs",
    "AutomationArgs",
    "MonitoredChatSyncAuditArgs",
    "DuplicateMergePreviewArgs",
    "ReceiptReparsePreviewArgs",
    "MonitorConfigInspectorArgs",
    "TelegramCacheSearchArgs",
    "MessageTraceArgs",
    "FailedReceiptInvestigatorArgs",
    "ReportPublishArgs",
    "FixPlanBuilderArgs",
    "ARGS_MODELS",
    "ARGS_MODELS_ALL",
    "TOOL_DESCRIPTIONS_NATIVE",
    "TOOL_SCHEMAS",
    "build_tool_schemas",
    "build_json_schema",
]
