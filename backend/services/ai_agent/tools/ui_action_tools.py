"""UI-action tools for the AI agent.

These tools do not change DB state — they emit a structured `ui_action` payload
that the frontend renders as an animated cursor performing a real UI gesture
(filter apply, row mark, scroll, export, drawer-close, …).

Each tool returns the canonical agent result shape with one extra contract:

    {
      ...,
      "ui_action": {
        "kind": "<verb>",
        "target": {...},        # selectors / ids / coords for the cursor
        "params": {...},        # tool-specific data
        "animate_cursor": True,
        "close_chat": True|False,
        "duration_ms": 1500,    # how long the cursor stays
      }
    }

The frontend listens for `ui_action` on every assistant message and runs a
canned animation. Backend never assumes any specific selector — it just gives
intent (`{kind: "apply_filters", params: {...}}`) and lets the frontend pick
DOM targets from its own registry.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any, Awaitable, Callable, Dict, List, Optional

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


def _ok(
    summary: str,
    *,
    ui_action: Dict[str, Any],
    assistant_message: Optional[str] = None,
    cards: Optional[List[Dict[str, Any]]] = None,
    data: Optional[Dict[str, Any]] = None,
    navigation_targets: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    out: Dict[str, Any] = {
        "summary": summary,
        "ui_action": ui_action,
    }
    if assistant_message:
        out["assistant_message"] = assistant_message
    if cards is not None:
        out["cards"] = cards
    if data is not None:
        out["data"] = data
    if navigation_targets is not None:
        out["navigation_targets"] = navigation_targets
    return out


def _normalise_date(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    s = str(value).strip()
    return s or None


# --------------------------------------------------------------------------- #
# Tools
# --------------------------------------------------------------------------- #
async def apply_filters_with_cursor(
    db: Session,
    current_user: Dict[str, Any],
    scope: Optional[dict],
    arguments: Dict[str, Any],
) -> Dict[str, Any]:
    """Apply filters to the transactions table; agent cursor mimics the action.

    Differs from the existing `apply_table_filters` tool by:
    1. always emitting `ui_action.kind = "apply_filters"` with explicit params,
    2. requesting the frontend to close the chat drawer after the animation.
    """
    filters = {
        "dateFrom": _normalise_date(arguments.get("date_from")),
        "dateTo": _normalise_date(arguments.get("date_to")),
        "operator": arguments.get("operator"),
        "application": arguments.get("application"),
        "currency": arguments.get("currency"),
        "transaction_type": arguments.get("transaction_type"),
        "card_last_4": arguments.get("card_last_4"),
        "min_amount": _coerce_decimal(arguments.get("min_amount")),
        "max_amount": _coerce_decimal(arguments.get("max_amount")),
        "search": arguments.get("search"),
        "is_p2p": arguments.get("is_p2p"),
        "source_chat_id": arguments.get("source_chat_id"),
    }
    filters_clean = {k: v for k, v in filters.items() if v is not None}

    summary = arguments.get("rationale") or "Применяю фильтры"
    return _ok(
        summary,
        assistant_message=(
            "Применяю фильтры — курсор сейчас покажет, какие поля заполнены."
        ),
        ui_action={
            "kind": "apply_filters",
            "target": {"area": "transactions_table"},
            "params": {"filters": filters_clean, "reset": bool(arguments.get("reset"))},
            "animate_cursor": True,
            "close_chat": True,
            "duration_ms": 1800,
        },
        data={"filters": filters_clean},
    )


async def mark_transaction_rows(db: Session, current_user: Dict[str, Any], scope: Optional[dict], arguments: Dict[str, Any]) -> Dict[str, Any]:
    """Mark / select / highlight specific transaction rows in the table.

    Args: transaction_ids: list[int], mode: "select"|"highlight"|"flag"|"unflag"
    """
    ids = arguments.get("transaction_ids") or []
    mode = (arguments.get("mode") or "highlight").strip().lower()
    if mode not in {"select", "highlight", "flag", "unflag"}:
        mode = "highlight"

    return _ok(
        f"Отмечаю {len(ids)} строк (режим: {mode})",
        assistant_message=f"Отметил {len(ids)} строк, курсор показал каждую.",
        ui_action={
            "kind": "mark_rows",
            "target": {"area": "transactions_table"},
            "params": {"transaction_ids": list(ids), "mode": mode},
            "animate_cursor": True,
            "close_chat": False,
            "duration_ms": 800 + 250 * min(len(ids), 8),
        },
        data={"count": len(ids), "ids": list(ids), "mode": mode},
    )


async def export_transactions(db: Session, current_user: Dict[str, Any], scope: Optional[dict], arguments: Dict[str, Any]) -> Dict[str, Any]:
    """Trigger an export of currently visible / specified transactions.

    Backend does not produce a file here — frontend hits its own export endpoint
    with the assembled filters. This tool is a facade for the cursor animation.
    """
    fmt = (arguments.get("format") or "xlsx").strip().lower()
    if fmt not in {"xlsx", "csv", "json"}:
        fmt = "xlsx"
    filters = {
        "dateFrom": _normalise_date(arguments.get("date_from")),
        "dateTo": _normalise_date(arguments.get("date_to")),
        "operator": arguments.get("operator"),
        "application": arguments.get("application"),
        "currency": arguments.get("currency"),
        "source_chat_id": arguments.get("source_chat_id"),
    }
    filters_clean = {k: v for k, v in filters.items() if v is not None}

    return _ok(
        f"Экспорт {fmt.upper()}",
        assistant_message=f"Запускаю экспорт — формат {fmt.upper()}.",
        ui_action={
            "kind": "export",
            "target": {"button": "export_transactions"},
            "params": {"format": fmt, "filters": filters_clean},
            "animate_cursor": True,
            "close_chat": True,
            "duration_ms": 1500,
        },
        data={"format": fmt, "filters": filters_clean},
    )


async def clear_filters_with_cursor(db: Session, current_user: Dict[str, Any], scope: Optional[dict], arguments: Dict[str, Any]) -> Dict[str, Any]:
    return _ok(
        "Сбрасываю все фильтры",
        assistant_message="Сбрасываю фильтры — курсор покажет.",
        ui_action={
            "kind": "clear_filters",
            "target": {"area": "transactions_table"},
            "params": {},
            "animate_cursor": True,
            "close_chat": True,
            "duration_ms": 900,
        },
    )


async def scroll_to_transaction(db: Session, current_user: Dict[str, Any], scope: Optional[dict], arguments: Dict[str, Any]) -> Dict[str, Any]:
    """Scroll the table to a specific transaction id (or row index)."""
    transaction_id = arguments.get("transaction_id")
    if not transaction_id:
        return _ok(
            "Не указан id",
            assistant_message="Нужен transaction_id для скролла.",
            ui_action={
                "kind": "noop",
                "target": {},
                "params": {},
                "animate_cursor": False,
                "close_chat": False,
                "duration_ms": 0,
            },
        )
    return _ok(
        f"Перематываю к транзакции #{transaction_id}",
        assistant_message=f"Курсор подведёт к строке #{transaction_id}.",
        ui_action={
            "kind": "scroll_to_row",
            "target": {"transaction_id": int(transaction_id)},
            "params": {"highlight_seconds": int(arguments.get("highlight_seconds") or 4)},
            "animate_cursor": True,
            "close_chat": True,
            "duration_ms": 1300,
        },
        data={"transaction_id": int(transaction_id)},
    )


async def open_transaction_details(db: Session, current_user: Dict[str, Any], scope: Optional[dict], arguments: Dict[str, Any]) -> Dict[str, Any]:
    transaction_id = int(arguments.get("transaction_id") or 0)
    if transaction_id <= 0:
        return _ok(
            "Не указан id",
            ui_action={
                "kind": "noop",
                "target": {},
                "params": {},
                "animate_cursor": False,
                "close_chat": False,
                "duration_ms": 0,
            },
        )
    return _ok(
        f"Открываю детали #{transaction_id}",
        assistant_message=f"Курсор кликнет по строке #{transaction_id}, чтобы открыть детали.",
        ui_action={
            "kind": "open_details",
            "target": {"transaction_id": transaction_id},
            "params": {},
            "animate_cursor": True,
            "close_chat": True,
            "duration_ms": 1100,
        },
    )


async def switch_view_with_cursor(db: Session, current_user: Dict[str, Any], scope: Optional[dict], arguments: Dict[str, Any]) -> Dict[str, Any]:
    view = (arguments.get("view") or "").strip().lower()
    allowed = {"transactions", "monitored_chats", "operators", "audit", "reports", "settings"}
    if view not in allowed:
        view = "transactions"
    return _ok(
        f"Перехожу в раздел {view}",
        assistant_message=f"Курсор переключит на раздел «{view}».",
        ui_action={
            "kind": "navigate_view",
            "target": {"view": view},
            "params": {},
            "animate_cursor": True,
            "close_chat": True,
            "duration_ms": 1200,
        },
    )


async def show_chat_only_message(db: Session, current_user: Dict[str, Any], scope: Optional[dict], arguments: Dict[str, Any]) -> Dict[str, Any]:
    """Pure conversational reply — no cursor, no UI action.

    Used when the model wants to keep the chat open without doing anything.
    """
    return _ok(
        arguments.get("summary") or "Ответ",
        assistant_message=arguments.get("text") or "",
        ui_action={
            "kind": "noop",
            "target": {},
            "params": {},
            "animate_cursor": False,
            "close_chat": False,
            "duration_ms": 0,
        },
    )


# --------------------------------------------------------------------------- #
def _coerce_decimal(value: Any) -> Optional[str]:
    if value in (None, "", "null"):
        return None
    try:
        return str(Decimal(str(value)))
    except Exception:  # noqa: BLE001
        return None
