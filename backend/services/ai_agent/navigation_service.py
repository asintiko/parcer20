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
) -> Dict[str, Any]:
    from api.routes.transactions import _build_filtered_transactions_query, _resolve_transactions_sort_column

    query, _locked_notice = _build_filtered_transactions_query(
        db,
        current_user=current_user,
        scope=scope,
        date_from=None,
        date_to=None,
        operator=None,
        operators=None,
        app=None,
        apps=None,
        amount_min=None,
        amount_max=None,
        parsing_method=None,
        confidence_min=None,
        confidence_max=None,
        search=search,
        source_type=None,
        source_channel=None,
        source_chat_ids=None,
        transaction_type=None,
        transaction_types=None,
        currency=None,
        card=None,
        days_of_week=None,
    )
    if query is None:
        return {
            "exists": False,
            "route": "/",
            "row_id": None,
            "column_id": None,
            "focus_mode": "none",
            "suggested_filters": {},
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
            "focus_mode": "none",
            "suggested_filters": {"search": search} if search else {},
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
        "suggested_filters": {"search": search} if search else {},
        "sort_hint": {"sort_by": sort_by, "sort_dir": sort_dir},
        "page_hint": page_hint,
    }
