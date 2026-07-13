"""Calculation / aggregation tools for the AI agent.

These tools read transactions from the DB and compute metrics suitable for an
in-chat answer. Unlike `transaction_analytics`, these are tuned for natural-
language Q&A: "за последние 7 дней", "сколько потратил на Uzum в марте",
"сравни февраль с январём", "топ-5 операторов по обороту".
"""
from __future__ import annotations

import logging
from collections import defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple

from sqlalchemy import and_, func
from sqlalchemy.orm import Session

from database.models import Transaction

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
def _ok(summary: str, **kw: Any) -> Dict[str, Any]:
    out: Dict[str, Any] = {"summary": summary}
    out.update(kw)
    return out


def _parse_dt(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time())
    s = str(value).strip().replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        try:
            return datetime.strptime(s, "%Y-%m-%d")
        except Exception:  # noqa: BLE001
            return None


def _resolve_period(args: Dict[str, Any]) -> Tuple[datetime, datetime, str]:
    """Resolve period from preset or explicit dates.

    Returns (start, end, label).
    """
    preset = (args.get("preset") or "").strip().lower()
    now = datetime.utcnow()
    today_start = datetime(now.year, now.month, now.day)
    if preset == "today":
        return today_start, now, "сегодня"
    if preset == "yesterday":
        end = today_start
        start = end - timedelta(days=1)
        return start, end, "вчера"
    if preset == "last_7_days":
        return now - timedelta(days=7), now, "последние 7 дней"
    if preset == "last_30_days":
        return now - timedelta(days=30), now, "последние 30 дней"
    if preset == "this_week":
        weekday = now.weekday()  # mon=0
        start = today_start - timedelta(days=weekday)
        return start, now, "эта неделя"
    if preset == "last_week":
        weekday = now.weekday()
        end = today_start - timedelta(days=weekday)
        start = end - timedelta(days=7)
        return start, end, "прошлая неделя"
    if preset == "this_month":
        start = datetime(now.year, now.month, 1)
        return start, now, f"{now.strftime('%Y-%m')}"
    if preset == "last_month":
        first_of_this = datetime(now.year, now.month, 1)
        end = first_of_this
        prev = first_of_this - timedelta(days=1)
        start = datetime(prev.year, prev.month, 1)
        return start, end, f"{prev.strftime('%Y-%m')}"
    # Explicit dates
    start = _parse_dt(args.get("date_from")) or (now - timedelta(days=7))
    end = _parse_dt(args.get("date_to")) or now
    if end < start:
        start, end = end, start
    label = f"{start.strftime('%d.%m.%Y')} — {end.strftime('%d.%m.%Y')}"
    return start, end, label


def _scope_chat_ids(scope: Optional[dict]) -> Optional[List[int]]:
    if not scope or not isinstance(scope, dict):
        return None
    if "allowed_chat_ids" not in scope:
        return None
    chats = scope.get("allowed_chat_ids") or []
    try:
        return [int(c) for c in chats]
    except Exception:  # noqa: BLE001
        return None


def _filtered_query(
    db: Session,
    *,
    start: datetime,
    end: datetime,
    args: Dict[str, Any],
    scope: Optional[dict],
):
    q = db.query(Transaction).filter(
        Transaction.transaction_date >= start,
        Transaction.transaction_date < end,
    )
    if args.get("operator"):
        q = q.filter(func.lower(Transaction.operator_raw) == str(args["operator"]).lower())
    if args.get("currency"):
        q = q.filter(Transaction.currency == str(args["currency"]).upper())
    if args.get("application"):
        q = q.filter(Transaction.application_mapped == args["application"])
    if args.get("source_chat_id") is not None:
        q = q.filter(Transaction.source_chat_id == int(args["source_chat_id"]))
    if args.get("transaction_type"):
        q = q.filter(Transaction.transaction_type == str(args["transaction_type"]).upper())
    chat_ids = _scope_chat_ids(scope)
    if chat_ids is not None:
        q = q.filter(Transaction.source_chat_id.in_(chat_ids))
    return q


def _fmt_amount(value: Any, currency: str = "UZS") -> str:
    if value is None:
        return "—"
    try:
        d = Decimal(str(value))
    except Exception:  # noqa: BLE001
        return str(value)
    sign = "−" if d < 0 else ""
    grouped = "{:,}".format(int(abs(d))).replace(",", " ")
    return f"{sign}{grouped} {currency}".strip()


# --------------------------------------------------------------------------- #
async def period_summary(db: Session, current_user: Dict[str, Any], scope: Optional[dict], arguments: Dict[str, Any]) -> Dict[str, Any]:
    start, end, label = _resolve_period(arguments)
    q = _filtered_query(db, start=start, end=end, args=arguments, scope=scope)

    by_currency: Dict[str, Dict[str, Decimal]] = defaultdict(
        lambda: {"spent": Decimal(0), "received": Decimal(0), "count": Decimal(0)}
    )
    total_count = 0
    for amount, currency in q.with_entities(Transaction.amount, Transaction.currency):
        if amount is None:
            continue
        cur = (currency or "UZS").upper()
        if amount < 0:
            by_currency[cur]["spent"] += -amount
        else:
            by_currency[cur]["received"] += amount
        by_currency[cur]["count"] += 1
        total_count += 1

    breakdown = []
    for cur, parts in by_currency.items():
        breakdown.append(
            {
                "currency": cur,
                "spent": str(parts["spent"]),
                "received": str(parts["received"]),
                "net": str(parts["received"] - parts["spent"]),
                "count": int(parts["count"]),
            }
        )

    msg_lines = [f"<b>Период:</b> {label}", f"<b>Транзакций:</b> {total_count}"]
    for row in breakdown:
        msg_lines.append(
            f"  · {row['currency']}: расход {_fmt_amount(row['spent'], row['currency'])}, "
            f"приход {_fmt_amount(row['received'], row['currency'])}, "
            f"net {_fmt_amount(row['net'], row['currency'])}"
        )

    return _ok(
        f"Сводка за {label}: {total_count} транзакций",
        assistant_message="\n".join(msg_lines),
        cards=[
            {
                "type": "analytics",
                "title": f"Сводка · {label}",
                "body": {
                    "period": {"start": start.isoformat(), "end": end.isoformat(), "label": label},
                    "count": total_count,
                    "breakdown": breakdown,
                },
            }
        ],
        data={
            "period": {"start": start.isoformat(), "end": end.isoformat(), "label": label},
            "count": total_count,
            "breakdown": breakdown,
        },
    )


async def compare_periods(db: Session, current_user: Dict[str, Any], scope: Optional[dict], arguments: Dict[str, Any]) -> Dict[str, Any]:
    a_args = {**arguments, **(arguments.get("a") or {})}
    b_args = {**arguments, **(arguments.get("b") or {})}
    a_start, a_end, a_label = _resolve_period(a_args)
    b_start, b_end, b_label = _resolve_period(b_args)

    def aggregate(start: datetime, end: datetime) -> Dict[str, Decimal]:
        q = _filtered_query(db, start=start, end=end, args=arguments, scope=scope)
        spent = Decimal(0)
        received = Decimal(0)
        count = 0
        for amount in q.with_entities(Transaction.amount):
            (a,) = amount
            if a is None:
                continue
            if a < 0:
                spent += -a
            else:
                received += a
            count += 1
        return {"spent": spent, "received": received, "count": Decimal(count)}

    a = aggregate(a_start, a_end)
    b = aggregate(b_start, b_end)

    def delta(x: Decimal, y: Decimal) -> Tuple[str, str]:
        if y == 0:
            return ("∞" if x else "0%"), str(x - y)
        pct = ((x - y) / y) * 100
        return f"{pct:+.1f}%", str(x - y)

    spent_pct, spent_abs = delta(a["spent"], b["spent"])
    recv_pct, recv_abs = delta(a["received"], b["received"])

    return _ok(
        f"Сравнение: {a_label} vs {b_label}",
        assistant_message=(
            f"<b>{a_label}</b>: расход {_fmt_amount(a['spent'])}, "
            f"приход {_fmt_amount(a['received'])} ({int(a['count'])} тр.)\n"
            f"<b>{b_label}</b>: расход {_fmt_amount(b['spent'])}, "
            f"приход {_fmt_amount(b['received'])} ({int(b['count'])} тр.)\n"
            f"<b>Δ расход:</b> {spent_pct} ({_fmt_amount(spent_abs)})\n"
            f"<b>Δ приход:</b> {recv_pct} ({_fmt_amount(recv_abs)})"
        ),
        data={
            "a": {"label": a_label, "spent": str(a["spent"]), "received": str(a["received"]), "count": int(a["count"])},
            "b": {"label": b_label, "spent": str(b["spent"]), "received": str(b["received"]), "count": int(b["count"])},
            "delta": {
                "spent_pct": spent_pct,
                "spent_abs": spent_abs,
                "received_pct": recv_pct,
                "received_abs": recv_abs,
            },
        },
    )


async def top_operators(db: Session, current_user: Dict[str, Any], scope: Optional[dict], arguments: Dict[str, Any]) -> Dict[str, Any]:
    start, end, label = _resolve_period(arguments)
    limit = max(1, min(50, int(arguments.get("limit") or 10)))
    direction = (arguments.get("direction") or "spent").strip().lower()

    q = _filtered_query(db, start=start, end=end, args=arguments, scope=scope)
    rows = q.with_entities(
        Transaction.operator_raw,
        Transaction.amount,
        Transaction.currency,
    ).all()
    agg: Dict[str, Decimal] = defaultdict(lambda: Decimal(0))
    for op, amount, _cur in rows:
        if amount is None:
            continue
        key = op or "Unknown"
        if direction == "spent" and amount < 0:
            agg[key] += -amount
        elif direction == "received" and amount > 0:
            agg[key] += amount
        elif direction == "turnover":
            agg[key] += abs(amount)
    ranking = sorted(agg.items(), key=lambda x: x[1], reverse=True)[:limit]

    msg_lines = [f"<b>Топ-{limit} операторов · {label} · {direction}</b>"]
    for i, (op, value) in enumerate(ranking, 1):
        msg_lines.append(f"  {i}. {op} — {_fmt_amount(value)}")

    return _ok(
        f"Топ {limit} операторов · {direction}",
        assistant_message="\n".join(msg_lines),
        data={
            "period": {"start": start.isoformat(), "end": end.isoformat(), "label": label},
            "direction": direction,
            "ranking": [{"operator": op, "value": str(v)} for op, v in ranking],
        },
    )


async def group_by_dimension(db: Session, current_user: Dict[str, Any], scope: Optional[dict], arguments: Dict[str, Any]) -> Dict[str, Any]:
    """Group transactions by one of: day, week, month, operator, application, currency."""
    start, end, label = _resolve_period(arguments)
    dim = (arguments.get("dimension") or "day").strip().lower()
    if dim not in {"day", "week", "month", "operator", "application", "currency", "card"}:
        dim = "day"

    q = _filtered_query(db, start=start, end=end, args=arguments, scope=scope)
    bucket: Dict[str, Dict[str, Decimal]] = defaultdict(
        lambda: {"spent": Decimal(0), "received": Decimal(0), "count": Decimal(0)}
    )
    for tx in q.all():
        if tx.amount is None or tx.transaction_date is None:
            continue
        if dim == "day":
            key = tx.transaction_date.strftime("%Y-%m-%d")
        elif dim == "week":
            iso = tx.transaction_date.isocalendar()
            key = f"{iso[0]}-W{iso[1]:02d}"
        elif dim == "month":
            key = tx.transaction_date.strftime("%Y-%m")
        elif dim == "operator":
            key = tx.operator_raw or "Unknown"
        elif dim == "application":
            key = tx.application_mapped or "Unknown"
        elif dim == "card":
            key = tx.card_last_4 or "—"
        else:
            key = tx.currency or "UZS"
        if tx.amount < 0:
            bucket[key]["spent"] += -tx.amount
        else:
            bucket[key]["received"] += tx.amount
        bucket[key]["count"] += 1

    rows = sorted(
        bucket.items(),
        key=lambda kv: (kv[1]["spent"] + kv[1]["received"]),
        reverse=True,
    )
    table = [
        {
            "key": k,
            "spent": str(v["spent"]),
            "received": str(v["received"]),
            "count": int(v["count"]),
        }
        for k, v in rows
    ]

    return _ok(
        f"Группировка по {dim} · {label}",
        assistant_message=(
            f"Группировка по {dim} за {label}: {len(table)} групп. "
            f"Топ: {', '.join(r['key'] for r in table[:5])}"
        ),
        data={
            "period": {"start": start.isoformat(), "end": end.isoformat(), "label": label},
            "dimension": dim,
            "rows": table,
        },
    )
