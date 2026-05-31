from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session


def _coerce_iso(value: Any) -> Optional[str]:
    if value in (None, ""):
        return None
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return str(value)


async def apply_table_filters(
    db: Session,
    current_user: Dict[str, Any],
    scope: Optional[dict],
    args: Dict[str, Any],
) -> Dict[str, Any]:
    """Build a navigation target carrying the requested filter set.

    The tool does not touch the database — it only translates the validated
    Pydantic args into the wire contract consumed by TransactionsPage.
    """

    suggested: Dict[str, Any] = {}

    if args.get("reset"):
        suggested["reset"] = True

    if args.get("date_from"):
        suggested["dateFrom"] = _coerce_iso(args.get("date_from"))
    if args.get("date_to"):
        suggested["dateTo"] = _coerce_iso(args.get("date_to"))

    if args.get("search"):
        suggested["search"] = str(args["search"]).strip()

    apps = [str(x).strip() for x in (args.get("apps") or []) if str(x).strip()]
    if apps:
        suggested["apps"] = apps

    operators = [str(x).strip() for x in (args.get("operators") or []) if str(x).strip()]
    if operators:
        suggested["operators"] = operators

    amount_min = args.get("amount_min")
    amount_max = args.get("amount_max")
    if amount_min not in (None, ""):
        try:
            suggested["amount_min"] = str(Decimal(str(amount_min)))
        except Exception:
            pass
    if amount_max not in (None, ""):
        try:
            suggested["amount_max"] = str(Decimal(str(amount_max)))
        except Exception:
            pass

    currency = (str(args.get("currency") or "").strip().upper() or None)
    if currency:
        suggested["currency"] = currency

    transaction_types = [str(x).strip().upper() for x in (args.get("transaction_types") or []) if str(x).strip()]
    if transaction_types:
        suggested["transaction_types"] = transaction_types

    source_channel = (str(args.get("source_channel") or "").strip().upper() or None)
    if source_channel in {"TELEGRAM", "SMS", "MANUAL", "ALL"}:
        suggested["source_channel"] = source_channel

    source_chat_ids = []
    for v in args.get("source_chat_ids") or []:
        try:
            source_chat_ids.append(int(v))
        except Exception:
            continue
    if source_chat_ids:
        suggested["source_chat_ids"] = source_chat_ids

    parsing_method = (str(args.get("parsing_method") or "").strip() or None)
    if parsing_method:
        suggested["parsing_method"] = parsing_method

    confidence_min = args.get("confidence_min")
    confidence_max = args.get("confidence_max")
    try:
        if confidence_min not in (None, ""):
            suggested["confidence_min"] = float(confidence_min)
    except Exception:
        pass
    try:
        if confidence_max not in (None, ""):
            suggested["confidence_max"] = float(confidence_max)
    except Exception:
        pass

    card_id = (str(args.get("card_id") or "").strip() or None)
    if card_id:
        suggested["card_id"] = card_id

    days_of_week = []
    for v in args.get("days_of_week") or []:
        try:
            d = int(v)
            if 0 <= d <= 6:
                days_of_week.append(d)
        except Exception:
            continue
    if days_of_week:
        suggested["days_of_week"] = days_of_week

    description_parts = []
    if suggested.get("reset"):
        description_parts.append("очищаю фильтры")
    if suggested.get("dateFrom") or suggested.get("dateTo"):
        description_parts.append(
            f"период {suggested.get('dateFrom') or '…'} → {suggested.get('dateTo') or '…'}"
        )
    if suggested.get("apps"):
        description_parts.append("приложения: " + ", ".join(suggested["apps"]))
    if suggested.get("operators"):
        description_parts.append("операторы: " + ", ".join(suggested["operators"]))
    if suggested.get("transaction_types"):
        description_parts.append("типы: " + ", ".join(suggested["transaction_types"]))
    if suggested.get("currency"):
        description_parts.append(f"валюта {suggested['currency']}")
    if suggested.get("amount_min") or suggested.get("amount_max"):
        description_parts.append(
            f"сумма {suggested.get('amount_min') or '0'} … {suggested.get('amount_max') or '∞'}"
        )
    if suggested.get("search"):
        description_parts.append(f"поиск '{suggested['search']}'")

    summary = "Применяю фильтры: " + "; ".join(description_parts) if description_parts else "Применяю фильтры таблицы."

    target = {
        "exists": True,
        "route": "/",
        "row_id": None,
        "column_id": None,
        "focus_mode": "filter",
        "suggested_filters": suggested,
        "sort_hint": {"sort_by": "transaction_date", "sort_dir": "desc"},
        "page_hint": 1,
    }

    return {
        "summary": summary,
        "assistant_message": summary,
        "cards": [
            {
                "type": "navigation",
                "title": "Фильтры таблицы",
                "body": summary,
                "payload": target,
            }
        ],
        "navigation_targets": [target],
    }
