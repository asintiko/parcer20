from __future__ import annotations

from typing import Any, Dict, Optional
from uuid import UUID

from sqlalchemy.orm import Session

from services.ai_agent.report_service import generate_report


async def report_builder(db: Session, current_user: Dict[str, Any], scope: Optional[dict], args: Dict[str, Any]) -> Dict[str, Any]:
    report = generate_report(
        db,
        created_by_user_id=int(current_user.get("id") or current_user.get("user_id") or 0),
        thread_id=UUID(str(args["thread_id"])) if args.get("thread_id") else None,
        scope="team" if bool(args.get("team")) else "personal",
        publish_team_notification=bool(args.get("team")),
    )
    return {
        "summary": "Отчет сформирован",
        "cards": [{"type": "report", "title": report.get("title") or "Отчет агента", "payload": report}],
        "report_id": report.get("id"),
    }
