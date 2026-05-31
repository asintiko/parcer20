from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional

from decimal import Decimal

from sqlalchemy import and_, desc, or_
from sqlalchemy.orm import Session

from database.models import Transaction


def _target_sort_value(target: Transaction, sort_by: str):
    if sort_by in {"transaction_date", "date_time", "time", "day", "operation_number"}:
        return target.transaction_date
    if sort_by == "amount":
        return abs(Decimal(str(target.amount or 0)))
    if sort_by == "balance_after":
        return abs(Decimal(str(target.balance_after or 0)))
    return getattr(target, sort_by, None)


def _coerce_decimal(value: Any) -> Optional[Decimal]:
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value))
    except Exception:
        return None


def _coerce_datetime(value: Any) -> Optional[datetime]:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value.replace(tzinfo=None) if value.tzinfo else value
    raw = str(value).strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        return parsed.replace(tzinfo=None) if parsed.tzinfo else parsed
    except Exception:
        pass
    for fmt in ("%Y-%m-%d", "%d.%m.%Y"):
        try:
            return datetime.strptime(raw, fmt)
        except Exception:
            continue
    return None


def locate_transaction(
    db: Session,
    *,
    current_user: Dict[str, Any],
    scope: Optional[Dict[str, Any]],
    transaction_id: Optional[int] = None,
    search: Optional[str] = None,
    sort_by: str = "transaction_date",
    sort_dir: str = "desc",
    page_size: int = 100,
    filters: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    from api.routes.transactions import _build_filtered_transactions_query, _resolve_transactions_sort_column

    f = filters or {}
    fsearch = search if search is not None else (str(f.get("search")).strip() if f.get("search") else None)
    suggested_filters: Dict[str, Any] = {}
    if fsearch:
        suggested_filters["search"] = fsearch

    date_from_v = _coerce_datetime(f.get("date_from"))
    date_to_v = _coerce_datetime(f.get("date_to"))
    if date_from_v:
        suggested_filters["dateFrom"] = date_from_v.isoformat()
    if date_to_v:
        suggested_filters["dateTo"] = date_to_v.isoformat()

    apps = [str(x).strip() for x in (f.get("apps") or []) if str(x).strip()] or None
    operators = [str(x).strip() for x in (f.get("operators") or []) if str(x).strip()] or None
    if apps:
        suggested_filters["apps"] = apps
    if operators:
        suggested_filters["operators"] = operators

    amount_min = _coerce_decimal(f.get("amount_min"))
    amount_max = _coerce_decimal(f.get("amount_max"))
    if amount_min is not None:
        suggested_filters["amount_min"] = str(amount_min)
    if amount_max is not None:
        suggested_filters["amount_max"] = str(amount_max)

    currency = (str(f.get("currency") or "").strip().upper() or None)
    if currency:
        suggested_filters["currency"] = currency

    transaction_types = [str(x).strip().upper() for x in (f.get("transaction_types") or []) if str(x).strip()] or None
    if transaction_types:
        suggested_filters["transaction_types"] = transaction_types

    source_channel = (str(f.get("source_channel") or "").strip().upper() or None)
    if source_channel and source_channel in {"TELEGRAM", "SMS", "MANUAL", "ALL"}:
        suggested_filters["source_channel"] = source_channel
    else:
        source_channel = None

    raw_source_ids = f.get("source_chat_ids") or []
    source_chat_ids: list = []
    for v in raw_source_ids:
        try:
            source_chat_ids.append(int(v))
        except Exception:
            continue
    if source_chat_ids:
        suggested_filters["source_chat_ids"] = source_chat_ids

    parsing_method = (str(f.get("parsing_method") or "").strip() or None)
    if parsing_method:
        suggested_filters["parsing_method"] = parsing_method

    confidence_min = f.get("confidence_min")
    confidence_max = f.get("confidence_max")
    try:
        confidence_min = float(confidence_min) if confidence_min not in (None, "") else None
    except Exception:
        confidence_min = None
    try:
        confidence_max = float(confidence_max) if confidence_max not in (None, "") else None
    except Exception:
        confidence_max = None
    if confidence_min is not None:
        suggested_filters["confidence_min"] = confidence_min
    if confidence_max is not None:
        suggested_filters["confidence_max"] = confidence_max

    card_id = (str(f.get("card_id") or "").strip() or None)
    if card_id:
        suggested_filters["card_id"] = card_id

    days_of_week_raw = f.get("days_of_week") or []
    days_of_week: list = []
    for v in days_of_week_raw:
        try:
            d = int(v)
            if 0 <= d <= 6:
                days_of_week.append(d)
        except Exception:
            continue
    if days_of_week:
        suggested_filters["days_of_week"] = days_of_week

    query, _locked_notice = _build_filtered_transactions_query(
        db,
        current_user=current_user,
        scope=scope,
        date_from=date_from_v,
        date_to=date_to_v,
        operator=None,
        operators=operators,
        app=None,
        apps=apps,
        amount_min=amount_min,
        amount_max=amount_max,
        parsing_method=parsing_method,
        confidence_min=confidence_min,
        confidence_max=confidence_max,
        search=fsearch,
        source_type=None,
        source_channel=source_channel,
        source_chat_ids=[str(x) for x in source_chat_ids] if source_chat_ids else None,
        transaction_type=None,
        transaction_types=transaction_types,
        currency=currency,
        card=card_id,
        days_of_week=days_of_week or None,
    )
    if query is None:
        return {
            "exists": False,
            "route": "/",
            "row_id": None,
            "column_id": None,
            "focus_mode": "filter",
            "suggested_filters": suggested_filters,
            "sort_hint": {"sort_by": sort_by, "sort_dir": sort_dir},
            "page_hint": 1,
        }

    if transaction_id is not None:
        target = query.filter(Transaction.id == int(transaction_id)).first()
    else:
        target = query.order_by(desc(Transaction.transaction_date), desc(Transaction.id)).first()

    if not target:
        return {
            "exists": False,
            "route": "/",
            "row_id": None,
            "column_id": None,
            "focus_mode": "filter",
            "suggested_filters": suggested_filters,
            "sort_hint": {"sort_by": sort_by, "sort_dir": sort_dir},
            "page_hint": 1,
        }

    sort_column = _resolve_transactions_sort_column(sort_by)
    descending = str(sort_dir).lower() == "desc"
    target_sort = _target_sort_value(target, sort_by)
    if target_sort is None:
        page_hint = 1
    else:
        if descending:
            before_count = query.filter(
                or_(
                    sort_column > target_sort,
                    and_(sort_column == target_sort, Transaction.id > int(target.id)),
                )
            ).count()
        else:
            before_count = query.filter(
                or_(
                    sort_column < target_sort,
                    and_(sort_column == target_sort, Transaction.id < int(target.id)),
                )
            ).count()

        page_hint = max(1, int(before_count // max(1, int(page_size))) + 1)
    return {
        "exists": True,
        "route": "/",
        "row_id": int(target.id),
        "column_id": "amount",
        "focus_mode": "row",
        "suggested_filters": suggested_filters,
        "sort_hint": {"sort_by": sort_by, "sort_dir": sort_dir},
        "page_hint": page_hint,
    }
