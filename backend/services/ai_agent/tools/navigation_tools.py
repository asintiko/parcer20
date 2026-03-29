from __future__ import annotations

from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from services.ai_agent.navigation_service import locate_transaction


async def table_search_and_navigate(db: Session, current_user: Dict[str, Any], scope: Optional[dict], args: Dict[str, Any]) -> Dict[str, Any]:
    target = locate_transaction(
        db,
        current_user=current_user,
        scope=scope,
        transaction_id=args.get("transaction_id"),
        search=args.get("search"),
        sort_by=str(args.get("sort_by") or "transaction_date"),
        sort_dir=str(args.get("sort_dir") or "desc"),
        page_size=int(args.get("page_size") or 100),
    )
    return {
        "summary": "Точка навигации подготовлена" if target.get("exists") else "Запись не найдена",
        "cards": [{"type": "navigation", "title": "Навигация к транзакции", "payload": target}],
        "navigation_targets": [target] if target.get("exists") else [],
    }
