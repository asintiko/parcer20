from __future__ import annotations

from datetime import date, datetime, time
from typing import Any, Dict, Optional
from uuid import UUID

from sqlalchemy.orm import Session

from services.ai_agent.report_service import generate_report


def _parse_period_value(value: Any, *, end: bool = False) -> Optional[datetime]:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value.replace(tzinfo=None) if value.tzinfo else value
    if isinstance(value, date):
        return datetime.combine(value, time.max if end else time.min)
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
            parsed = datetime.strptime(raw, fmt)
            return parsed.replace(hour=23, minute=59, second=59, microsecond=999999) if end else parsed
        except Exception:
            continue
    return None


async def report_builder(db: Session, current_user: Dict[str, Any], scope: Optional[dict], args: Dict[str, Any]) -> Dict[str, Any]:
    period_start = _parse_period_value(args.get("period_start"))
    period_end = _parse_period_value(args.get("period_end"), end=True)
    group_by = str(args.get("group_by") or "").strip().lower() or None
    if group_by not in {None, "day", "week", "month", "application", "source"}:
        group_by = None

    report = generate_report(
        db,
        created_by_user_id=int(current_user.get("id") or current_user.get("user_id") or 0),
        thread_id=UUID(str(args["thread_id"])) if args.get("thread_id") else None,
        scope="team" if bool(args.get("team")) else "personal",
        period_start=period_start,
        period_end=period_end,
        group_by=group_by,
        publish_team_notification=bool(args.get("team")),
    )
    return {
        "summary": "Отчет сформирован",
        "cards": [{"type": "report", "title": report.get("title") or "Отчет агента", "payload": report}],
        "report_id": report.get("id"),
    }
