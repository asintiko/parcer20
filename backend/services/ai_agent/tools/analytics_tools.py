from __future__ import annotations

import os
import re
from datetime import date, datetime, time, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional, Tuple

import pytz
from sqlalchemy import desc, func
from sqlalchemy.orm import Session

from database.models import Transaction


MONTH_MAP = {
    "январ": 1,
    "феврал": 2,
    "март": 3,
    "апрел": 4,
    "ма": 5,
    "июн": 6,
    "июл": 7,
    "август": 8,
    "сентябр": 9,
    "октябр": 10,
    "ноябр": 11,
    "декабр": 12,
}

DIRECTION_LABELS = {
    "spent": "Расходы",
    "received": "Поступления",
    "turnover": "Оборот",
}


def _now_local_naive() -> datetime:
    tz_name = os.getenv("TIMEZONE", "Asia/Tashkent")
    try:
        now = datetime.now(pytz.timezone(tz_name))
    except Exception:
        now = datetime.utcnow()
    return now.replace(tzinfo=None)


def _parse_datetime_value(value: Any) -> Optional[datetime]:
    if isinstance(value, datetime):
        return value.replace(tzinfo=None) if value.tzinfo else value
    if isinstance(value, date):
        return datetime.combine(value, time.min)
    raw = str(value or "").strip()
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


def _extract_month(month_text: str) -> Optional[int]:
    normalized = month_text.strip().lower().replace("ё", "е")
    for stem, month in MONTH_MAP.items():
        if normalized.startswith(stem):
            return month
    return None


def _safe_period_day(year: int, month: int, day: int) -> Optional[datetime]:
    try:
        return datetime(year, month, day)
    except ValueError:
        return None


def _extract_date_range_from_text(text: str) -> Tuple[Optional[datetime], Optional[datetime], Optional[str]]:
    lowered = (text or "").lower().replace("ё", "е")
    now = _now_local_naive()

    if "с начала месяца" in lowered:
        start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        return start, now, f"с {start.strftime('%d.%m.%Y')} по {now.strftime('%d.%m.%Y')}"

    if "вчера" in lowered and "с " not in lowered:
        yesterday = (now - timedelta(days=1)).date()
        start = datetime.combine(yesterday, time.min)
        end = datetime.combine(yesterday, time.max)
        return start, end, f"за {start.strftime('%d.%m.%Y')}"

    if "сегодня" in lowered and "с " not in lowered:
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        return start, now, f"за {start.strftime('%d.%m.%Y')}"

    range_match = re.search(
        r"с\s+(\d{1,2})(?:[-\s]?(?:го|й))?\s+([а-я]+)(?:\s+(\d{4}))?(?:\s+г(?:ода|\.)?)?(?:\s+по\s+(?:сей\s+день|сегодня|сегодняшний\s+день|сейчас|текущий\s+момент|сегодняшнюю\s+дату)|\s+по\s+(\d{1,2})(?:[-\s]?(?:го|й))?\s+([а-я]+)(?:\s+(\d{4}))?)?",
        lowered,
    )
    if range_match:
        start_day = int(range_match.group(1))
        start_month = _extract_month(range_match.group(2) or "")
        start_year = int(range_match.group(3)) if range_match.group(3) else now.year
        if start_month:
            start = _safe_period_day(start_year, start_month, start_day)
            if start and not range_match.group(3) and start > now:
                start = _safe_period_day(start_year - 1, start_month, start_day)
            if start:
                if range_match.group(4) and range_match.group(5):
                    end_day = int(range_match.group(4))
                    end_month = _extract_month(range_match.group(5) or "")
                    end_year = int(range_match.group(6)) if range_match.group(6) else start.year
                    if end_month:
                        end = _safe_period_day(end_year, end_month, end_day)
                        if end:
                            end = end.replace(hour=23, minute=59, second=59, microsecond=999999)
                            return start, end, f"с {start.strftime('%d.%m.%Y')} по {end.strftime('%d.%m.%Y')}"
                return start, now, f"с {start.strftime('%d.%m.%Y')} по {now.strftime('%d.%m.%Y')}"

    month_match = re.search(r"(?:за|с)\s+([а-я]+)(?:\s+(\d{4}))?(?:\s+по\s+сей\s+день)?$", lowered)
    if month_match:
        month = _extract_month(month_match.group(1) or "")
        if month:
            year = int(month_match.group(2)) if month_match.group(2) else now.year
            start = datetime(year, month, 1)
            if not month_match.group(2) and start > now:
                start = datetime(year - 1, month, 1)
            if "по сей день" in lowered and start.year == now.year and start.month == now.month:
                return start, now, f"с {start.strftime('%d.%m.%Y')} по {now.strftime('%d.%m.%Y')}"
            if start.year == now.year and start.month == now.month:
                end = now
            else:
                if month == 12:
                    next_month = datetime(start.year + 1, 1, 1)
                else:
                    next_month = datetime(start.year, month + 1, 1)
                end = next_month - timedelta(microseconds=1)
            return start, end, f"за {start.strftime('%m.%Y')}"

    return None, None, None


def _normalize_direction(direction: Optional[str], query_text: str) -> str:
    raw = str(direction or "").strip().lower()
    if raw in {"spent", "received", "turnover"}:
        return raw

    lowered = (query_text or "").lower().replace("ё", "е")
    if any(token in lowered for token in ["получ", "поступ", "зачис", "пришло"]):
        return "received"
    if any(token in lowered for token in ["оборот", "всего прошло", "движение"]):
        return "turnover"
    return "spent"


def _format_amount(value: Decimal) -> str:
    quantized = value.quantize(Decimal("0.01"))
    raw = f"{quantized:,.2f}"
    return raw.replace(",", " ").replace(".", ",")


def _serialize_decimal(value: Any) -> Decimal:
    try:
        return Decimal(str(value or "0"))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal("0")


def _human_period_label(start: Optional[datetime], end: Optional[datetime], extracted: Optional[str]) -> str:
    if extracted:
        return extracted
    if start and end:
        return f"с {start.strftime('%d.%m.%Y')} по {end.strftime('%d.%m.%Y')}"
    if start:
        return f"с {start.strftime('%d.%m.%Y')}"
    if end:
        return f"по {end.strftime('%d.%m.%Y')}"
    return "за выбранный период"


def _build_transactions_navigation_target(
    *,
    start: Optional[datetime],
    end: Optional[datetime],
    direction: str,
    currency: Optional[str],
    search: Optional[str],
    source_chat_ids: Optional[List[str]],
    application: Optional[str],
) -> Dict[str, Any]:
    suggested_filters: Dict[str, Any] = {}
    if start:
        suggested_filters["dateFrom"] = start.isoformat()
    if end:
        suggested_filters["dateTo"] = end.isoformat()
    if currency:
        suggested_filters["currency"] = currency
    if search:
        suggested_filters["search"] = search
    if application:
        suggested_filters["apps"] = [application]
    parsed_source_ids: List[int] = []
    for value in source_chat_ids or []:
        try:
            parsed_source_ids.append(int(value))
        except Exception:
            continue
    if parsed_source_ids:
        suggested_filters["source_chat_ids"] = parsed_source_ids
        suggested_filters["source_channel"] = "TELEGRAM"
    if direction == "spent":
        suggested_filters["transaction_types"] = ["DEBIT"]
    elif direction == "received":
        suggested_filters["transaction_types"] = ["CREDIT"]

    return {
        "exists": True,
        "route": "/",
        "row_id": None,
        "column_id": "amount",
        "focus_mode": "filter",
        "suggested_filters": suggested_filters,
        "sort_hint": {"sort_by": "transaction_date", "sort_dir": "desc"},
        "page_hint": 1,
        "cursor_hint": None,
    }


async def transaction_analytics(db: Session, current_user: Dict[str, Any], scope: Optional[dict], args: Dict[str, Any]) -> Dict[str, Any]:
    from api.routes.transactions import _build_filtered_transactions_query, _load_source_meta_map

    query_text = str(args.get("query_text") or args.get("text") or "").strip()
    direction = _normalize_direction(args.get("direction"), query_text)

    date_from = _parse_datetime_value(args.get("date_from"))
    date_to = _parse_datetime_value(args.get("date_to"))
    extracted_label: Optional[str] = None
    if date_from is None and date_to is None:
        date_from, date_to, extracted_label = _extract_date_range_from_text(query_text)

    currency = str(args.get("currency") or "").strip().upper() or None
    if currency not in {None, "UZS", "USD"}:
        currency = None

    application = str(args.get("application") or "").strip() or None
    search = str(args.get("search") or "").strip() or None

    source_chat_ids_arg = args.get("source_chat_ids")
    if isinstance(source_chat_ids_arg, list):
        source_chat_ids = [str(item).strip() for item in source_chat_ids_arg if str(item).strip()]
    elif args.get("source_chat_id") not in (None, ""):
        source_chat_ids = [str(args.get("source_chat_id"))]
    else:
        source_chat_ids = None

    transaction_type = None
    if direction == "spent":
        transaction_type = "DEBIT"
    elif direction == "received":
        transaction_type = "CREDIT"

    query, locked_notice = _build_filtered_transactions_query(
        db,
        current_user=current_user,
        scope=scope,
        date_from=date_from,
        date_to=date_to,
        operator=None,
        operators=None,
        app=application,
        apps=None,
        amount_min=None,
        amount_max=None,
        parsing_method=None,
        confidence_min=None,
        confidence_max=None,
        search=search,
        source_type=None,
        source_channel=None,
        source_chat_ids=source_chat_ids,
        transaction_type=transaction_type,
        transaction_types=None,
        currency=currency,
        card=None,
        days_of_week=None,
    )

    period_label = _human_period_label(date_from, date_to, extracted_label)
    direction_label = DIRECTION_LABELS.get(direction, "Сумма")

    if query is None:
        message = locked_notice or f"За период {period_label} нет доступных операций для расчета."
        return {
            "summary": message,
            "assistant_message": message,
            "cards": [
                {
                    "type": "warning",
                    "title": "Данные недоступны",
                    "body": message,
                    "details": {"locked_notice": locked_notice, "period": period_label},
                }
            ],
        }

    base_query = query.order_by(None)

    totals_rows = (
        base_query.with_entities(
            Transaction.currency,
            func.count(Transaction.id),
            func.coalesce(func.sum(func.abs(Transaction.amount)), 0),
        )
        .group_by(Transaction.currency)
        .order_by(Transaction.currency.asc())
        .all()
    )

    total_operations = sum(int(row[1] or 0) for row in totals_rows)
    totals = [
        {
            "currency": str(row[0] or "UZS"),
            "count": int(row[1] or 0),
            "total": _format_amount(_serialize_decimal(row[2])),
        }
        for row in totals_rows
    ]

    if not totals:
        message = f"{direction_label} {period_label}: подходящих операций не найдено."
        return {
            "summary": message,
            "assistant_message": message,
            "cards": [
                {
                    "type": "warning",
                    "title": "Операции не найдены",
                    "body": message,
                    "details": {
                        "period": period_label,
                        "direction": direction,
                    },
                }
            ],
        }

    top_app_rows = (
        base_query.with_entities(
            func.coalesce(Transaction.application_mapped, "Без приложения"),
            func.count(Transaction.id),
            func.coalesce(func.sum(func.abs(Transaction.amount)), 0),
        )
        .group_by(func.coalesce(Transaction.application_mapped, "Без приложения"))
        .order_by(desc(func.coalesce(func.sum(func.abs(Transaction.amount)), 0)))
        .limit(3)
        .all()
    )
    top_applications = [
        {
            "name": str(row[0] or "Без приложения"),
            "count": int(row[1] or 0),
            "total": _format_amount(_serialize_decimal(row[2])),
        }
        for row in top_app_rows
    ]

    top_source_rows = (
        base_query.filter(Transaction.source_chat_id.isnot(None))
        .with_entities(
            Transaction.source_chat_id,
            func.count(Transaction.id),
            func.coalesce(func.sum(func.abs(Transaction.amount)), 0),
        )
        .group_by(Transaction.source_chat_id)
        .order_by(desc(func.coalesce(func.sum(func.abs(Transaction.amount)), 0)))
        .limit(3)
        .all()
    )
    source_meta = _load_source_meta_map(db, [int(row[0]) for row in top_source_rows if row[0] is not None])
    top_sources = [
        {
            "chat_id": int(row[0]),
            "title": (source_meta.get(int(row[0])) or {}).get("title") or f"Telegram {int(row[0])}",
            "count": int(row[1] or 0),
            "total": _format_amount(_serialize_decimal(row[2])),
        }
        for row in top_source_rows
        if row[0] is not None
    ]

    totals_text = "; ".join(f"{item['currency']} {item['total']}" for item in totals)
    message = f"{direction_label} {period_label} составили: {totals_text}."
    if total_operations:
        message += f" Операций: {total_operations}."

    return {
        "summary": message,
        "assistant_message": message,
        "cards": [
            {
                "type": "analytics",
                "title": direction_label,
                "body": message,
                "payload": {
                    "direction": direction,
                    "period_label": period_label,
                    "total_operations": total_operations,
                    "totals": totals,
                    "top_applications": top_applications,
                    "top_sources": top_sources,
                },
                "details": {
                    "date_from": date_from.isoformat() if date_from else None,
                    "date_to": date_to.isoformat() if date_to else None,
                    "currency": currency,
                    "application": application,
                    "search": search,
                    "source_chat_ids": source_chat_ids,
                    "locked_notice": locked_notice,
                },
            }
        ],
        "navigation_targets": [
            _build_transactions_navigation_target(
                start=date_from,
                end=date_to,
                direction=direction,
                currency=currency,
                search=search,
                source_chat_ids=source_chat_ids,
                application=application,
            )
        ],
    }
