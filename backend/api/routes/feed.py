"""Static-key transaction feed for external spreadsheet clients (Excel Power Query).

Exposes the full transaction set as JSON to a client authenticated by a single
shared key (EXPORT_FEED_KEY), passed either via the X-Feed-Key header or a
`key` query parameter. Unlike /api/transactions/export this endpoint has no JWT,
RBAC, or scope enforcement: it is a full owner-level feed meant to back a
prepared .xlsx workbook that auto-refreshes on the customer's machine.

The path prefix /api/feed/ is exempted from SystemAccess and LaunchSession
middleware (see api/main.py), mirroring the /api/sms/ ingest pattern.
"""
from __future__ import annotations

import os
import secrets
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from fastapi.responses import JSONResponse
from sqlalchemy import asc
from sqlalchemy.orm import Session

from database.connection import get_db_session
from database.models import Transaction
from api.routes.transactions import (
    EXPORT_COLUMN_HEADERS,
    _build_export_row_values,
    _load_source_meta_map,
)

router = APIRouter(prefix="/api/feed", tags=["feed"])

FEED_COLUMNS: List[str] = [
    "operation_number",
    "date_time",
    "transaction_date",
    "time",
    "day",
    "operator_raw",
    "application_mapped",
    "receiver_name",
    "receiver_card",
    "amount",
    "balance_after",
    "card_last_4",
    "is_p2p",
    "transaction_type",
    "currency",
    "source_type",
]


def _feed_key() -> str:
    return os.getenv("EXPORT_FEED_KEY", "").strip()


async def require_feed_key(
    x_feed_key: Optional[str] = Header(None, alias="X-Feed-Key"),
    key: Optional[str] = Query(None, description="Feed access key (alternative to X-Feed-Key header)"),
) -> None:
    configured = _feed_key()
    if not configured:
        raise HTTPException(status_code=503, detail="Feed key is not configured")
    provided = (x_feed_key or key or "").strip()
    if not provided or not secrets.compare_digest(provided, configured):
        raise HTTPException(status_code=403, detail="Invalid feed key")


@router.get("/transactions", dependencies=[Depends(require_feed_key)])
async def feed_transactions(db: Session = Depends(get_db_session)) -> JSONResponse:
    """Return every transaction as a flat JSON array, oldest first.

    Column ids match the xlsx export; Russian header labels are exposed under
    `columns` so a spreadsheet can render localized headers if desired.
    """
    source_meta_map = _load_source_meta_map(db)
    rows: List[Dict[str, Any]] = []
    query = db.query(Transaction).order_by(asc(Transaction.transaction_date), asc(Transaction.id)).yield_per(1000)
    for index, tx in enumerate(query, start=1):
        values = _build_export_row_values(index, 0, False, tx, source_meta_map)
        rows.append({col: values.get(col, "") for col in FEED_COLUMNS})

    payload = {
        "columns": {col: EXPORT_COLUMN_HEADERS[col] for col in FEED_COLUMNS},
        "count": len(rows),
        "rows": rows,
    }
    return JSONResponse(content=payload)
