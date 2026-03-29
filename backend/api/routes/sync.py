"""Incremental sync API for desktop local mirror."""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import time
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple, Type
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import and_, func, or_
from sqlalchemy.orm import Session

from api.dependencies import (
    get_effective_folder_scope_for_user,
    merge_scope_payloads,
    require_tab_access,
    require_transactions_scope,
)
from database.connection import get_db_session
from database.models import (
    AccessScope,
    HiddenBotChat,
    HourlyReport,
    LockedPeriod,
    MonitoredBotChat,
    OperatorMapping,
    OperatorReference,
    ParsingLog,
    ReceiptProcessingTask,
    SyncDeletion,
    Transaction,
)
from services.access_control_service import get_scope_window
from services.auth_bot_service import get_redis
from services.period_lock_service import period_lock_service

router = APIRouter(prefix="/api/sync", tags=["sync"])
logger = logging.getLogger(__name__)

SYNC_MANIFEST_CACHE_TTL = int(os.getenv("SYNC_MANIFEST_CACHE_TTL", "300"))
SYNC_MANIFEST_LOCAL_CACHE_TTL = int(os.getenv("SYNC_MANIFEST_LOCAL_CACHE_TTL", "30"))
# Full desktop sync cycle pulls manifest + multiple tables/pages, so
# conservative limits can self-throttle normal bootstrap sync (429).
SYNC_RATE_LIMIT_PER_MIN = int(os.getenv("SYNC_RATE_LIMIT_PER_MIN", "600"))
SYNC_DELETED_IDS_LIMIT = int(os.getenv("SYNC_DELETED_IDS_LIMIT", "10000"))
SYNC_DELETION_RETENTION_DAYS = int(os.getenv("SYNC_DELETION_RETENTION_DAYS", "30"))
SYNC_DELETION_CLEANUP_INTERVAL_SEC = int(os.getenv("SYNC_DELETION_CLEANUP_INTERVAL_SEC", "3600"))
_last_sync_deletion_cleanup_ts = 0.0
_sync_cleanup_lock = asyncio.Lock()
_manifest_local_cache: Dict[str, tuple[float, Dict[str, Any]]] = {}
EMPTY_CHECKSUM = "sha256:" + hashlib.sha256(b"").hexdigest()


TABLE_MODELS: Dict[str, Type] = {
    "transactions": Transaction,
    "operatorMappings": OperatorMapping,
    "operatorReferences": OperatorReference,
    "monitoredBotChats": MonitoredBotChat,
    "hiddenBotChats": HiddenBotChat,
    "parsingLogs": ParsingLog,
    "hourlyReports": HourlyReport,
    "accessScopes": AccessScope,
    "receiptProcessingTasks": ReceiptProcessingTask,
    "lockedPeriods": LockedPeriod,
}

SENSITIVE_COLUMNS = {"password_hash", "salt", "hash_method", "raw_message"}
TRANSACTION_ONLY_SYNC_TABLES = {
    "transactions",
    "operatorMappings",
    "operatorReferences",
    "lockedPeriods",
}


def _dt_to_iso(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, (bytes, bytearray, memoryview)):
        return bytes(value).hex()
    return value


def _to_naive_utc(value: Optional[datetime]) -> Optional[datetime]:
    if value is None:
        return None
    if value.tzinfo is not None:
        return value.astimezone(timezone.utc).replace(tzinfo=None)
    return value


def _serialize_row(row: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {}
    for column in row.__table__.columns:  # type: ignore[attr-defined]
        if column.name in SENSITIVE_COLUMNS:
            continue
        payload[column.name] = _dt_to_iso(getattr(row, column.name))
    return payload


def _resolve_id_column(model: Type) -> str:
    for name in ("id", "chat_id"):
        if hasattr(model, name):
            return name
    raise ValueError(f"Model {model.__name__} has no supported id column")


def _resolve_updated_column(model: Type) -> Optional[str]:
    for name in ("updated_at", "created_at", "hidden_at", "locked_at"):
        if hasattr(model, name):
            return name
    return None


def _scope_filter_transactions(query, scope: Optional[Dict[str, Any]]):
    if not scope:
        return query
    scope_from, scope_to, scope_years = get_scope_window(scope)
    if scope_from:
        query = query.filter(Transaction.transaction_date >= scope_from)
    if scope_to:
        query = query.filter(Transaction.transaction_date <= scope_to)
    if scope_years:
        query = query.filter(func.extract("year", Transaction.transaction_date).in_(scope_years))
    return query


def _effective_scope(
    db: Session,
    scope: Optional[Dict[str, Any]],
    current_user: Optional[dict],
) -> Optional[Dict[str, Any]]:
    user_scope = get_effective_folder_scope_for_user(current_user, db)
    return merge_scope_payloads(scope, user_scope)


def _forbidden_ranges_for_user(current_user: Optional[dict]) -> List[tuple[date, date]]:
    if not current_user:
        return []
    if str(current_user.get("role") or "").lower() == "admin":
        return []
    raw = current_user.get("forbidden_periods")
    if not isinstance(raw, list):
        return []
    ranges: List[tuple[date, date]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        try:
            d_from = datetime.fromisoformat(str(item.get("from"))).date()
            d_to = datetime.fromisoformat(str(item.get("to"))).date()
        except Exception:
            continue
        if d_from > d_to:
            d_from, d_to = d_to, d_from
        ranges.append((d_from, d_to))
    return ranges


def _apply_forbidden_ranges(query, ranges: List[tuple[date, date]]):
    if not ranges:
        return query
    blocked = []
    for date_from, date_to in ranges:
        blocked.append(
            and_(
                func.date(Transaction.transaction_date) >= date_from,
                func.date(Transaction.transaction_date) <= date_to,
            )
        )
    if blocked:
        query = query.filter(~or_(*blocked))
    return query


def _table_allowed_for_scope(table_name: str, scope: Optional[Dict[str, Any]]) -> bool:
    if not scope:
        return True
    # Internal service scope always has full access.
    if int(scope.get("scope_id") or 0) == 0:
        return True
    if bool(scope.get("allow_sources")):
        return True
    return table_name in TRANSACTION_ONLY_SYNC_TABLES


def _locked_period_filter_transactions(query, db: Session):
    locks = period_lock_service.get_active_locks(db)
    if not locks:
        return query
    blocked = []
    for lock in locks:
        blocked.append(
            and_(
                func.date(Transaction.transaction_date) >= lock.date_from,
                func.date(Transaction.transaction_date) <= lock.date_to,
            )
        )
    if blocked:
        query = query.filter(~or_(*blocked))
    return query


def _rows_checksum(rows: List[Any], id_column: str, updated_column: Optional[str]) -> str:
    digest = hashlib.sha256()
    for row in rows:
        row_id = getattr(row, id_column, None)
        updated_val = getattr(row, updated_column, None) if updated_column else None
        serialized_row = json.dumps(_serialize_row(row), sort_keys=True, ensure_ascii=False)
        digest.update(f"{row_id}:{updated_val}:{serialized_row}".encode("utf-8"))
    return "sha256:" + digest.hexdigest()


def _table_manifest(
    db: Session,
    table_name: str,
    model: Type,
    scope: Optional[Dict[str, Any]],
    forbidden_ranges: Optional[List[tuple[date, date]]] = None,
) -> Dict[str, Any]:
    if not _table_allowed_for_scope(table_name, scope):
        return {
            "row_count": 0,
            "last_updated": None,
            "checksum": EMPTY_CHECKSUM,
        }

    id_column = _resolve_id_column(model)
    updated_column = _resolve_updated_column(model)

    query = db.query(model)
    if model is Transaction:
        query = _scope_filter_transactions(query, scope)
        query = _apply_forbidden_ranges(query, forbidden_ranges or [])
        query = _locked_period_filter_transactions(query, db)
    total = query.count()

    if updated_column:
        last_updated = query.with_entities(func.max(getattr(model, updated_column))).scalar()
    else:
        last_updated = None

    order_col = getattr(model, id_column)
    sample_rows = query.order_by(order_col.desc()).limit(100).all()
    checksum = _rows_checksum(sample_rows, id_column=id_column, updated_column=updated_column)
    return {
        "row_count": int(total),
        "last_updated": last_updated.isoformat() if isinstance(last_updated, datetime) else None,
        "checksum": checksum,
    }


def _manifest_cache_key(scope: Optional[Dict[str, Any]]) -> str:
    scope_from, scope_to, scope_years = get_scope_window(scope)
    raw_key = json.dumps(
        {
            "scope_id": int(scope.get("scope_id") or 0) if scope else None,
            "allow_transactions": bool(scope.get("allow_transactions", True)) if scope else None,
            "allow_sources": bool(scope.get("allow_sources", False)) if scope else None,
            "from": scope_from.isoformat() if scope_from else None,
            "to": scope_to.isoformat() if scope_to else None,
            "years": sorted(scope_years or []),
        },
        sort_keys=True,
        ensure_ascii=False,
    )
    digest = hashlib.sha256(raw_key.encode("utf-8")).hexdigest()[:20]
    return f"sync:manifest:{digest}"


def _get_manifest_from_local_cache(cache_key: str) -> Optional[Dict[str, Any]]:
    item = _manifest_local_cache.get(cache_key)
    if not item:
        return None
    expires_at, payload = item
    if expires_at <= time.time():
        _manifest_local_cache.pop(cache_key, None)
        return None
    return payload


def _put_manifest_to_local_cache(cache_key: str, payload: Dict[str, Any]) -> None:
    ttl = max(1, int(SYNC_MANIFEST_LOCAL_CACHE_TTL))
    _manifest_local_cache[cache_key] = (time.time() + ttl, payload)


async def _cleanup_old_sync_deletions(db: Session) -> None:
    global _last_sync_deletion_cleanup_ts
    async with _sync_cleanup_lock:
        retention_days = max(1, int(SYNC_DELETION_RETENTION_DAYS))
        interval_sec = max(60, int(SYNC_DELETION_CLEANUP_INTERVAL_SEC))
        now_ts = time.time()
        if (now_ts - _last_sync_deletion_cleanup_ts) < interval_sec:
            return

        cutoff = datetime.utcnow() - timedelta(days=retention_days)
        total_deleted = 0
        batch_size = 10_000
        try:
            while True:
                stale_ids = (
                    db.query(SyncDeletion.id)
                    .filter(SyncDeletion.deleted_at < cutoff)
                    .order_by(SyncDeletion.id.asc())
                    .limit(batch_size)
                    .all()
                )
                ids = [int(row[0]) for row in stale_ids if row and row[0] is not None]
                if not ids:
                    break
                deleted_rows = (
                    db.query(SyncDeletion)
                    .filter(SyncDeletion.id.in_(ids))
                    .delete(synchronize_session=False)
                )
                db.commit()
                total_deleted += int(deleted_rows or 0)
                if len(ids) < batch_size:
                    break
            _last_sync_deletion_cleanup_ts = now_ts
            if total_deleted:
                logger.info(
                    "sync_deletions cleanup removed %s rows older than %s days",
                    total_deleted,
                    retention_days,
                )
        except Exception:
            db.rollback()
            logger.warning("sync_deletions cleanup failed", exc_info=True)


async def _enforce_sync_rate_limit(request: Request, current_user: Optional[dict]) -> None:
    actor = None
    if current_user:
        actor = current_user.get("user_id")
    if not actor:
        actor = request.client.host if request.client and request.client.host else "unknown"

    minute_slot = int(datetime.utcnow().timestamp() // 60)
    key = f"sync:rate:{actor}:{minute_slot}"
    try:
        redis = await get_redis()
        count = await redis.incr(key)
        if count == 1:
            await redis.expire(key, 65)
        if int(count) > max(1, int(SYNC_RATE_LIMIT_PER_MIN)):
            raise HTTPException(status_code=429, detail="Sync rate limit exceeded")
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning("sync rate limiter unavailable; fail-closed", exc_info=True)
        raise HTTPException(status_code=503, detail="Sync temporarily unavailable")


@router.get("/manifest")
async def sync_manifest(
    request: Request,
    client_last_sync: Optional[datetime] = Query(
        None,
        description="Client's last successful sync timestamp (ISO). Used to request full resync after long gaps.",
    ),
    db: Session = Depends(get_db_session),
    current_user: dict = Depends(require_tab_access("dashboard")),
    scope: Optional[Dict[str, Any]] = Depends(require_transactions_scope),
) -> Dict[str, Any]:
    effective_scope = _effective_scope(db, scope, current_user)
    forbidden_ranges = _forbidden_ranges_for_user(current_user)
    await _enforce_sync_rate_limit(request, current_user)
    await _cleanup_old_sync_deletions(db)
    retention_days = max(1, int(SYNC_DELETION_RETENTION_DAYS))
    now_utc = datetime.utcnow()
    normalized_client_last_sync = _to_naive_utc(client_last_sync)
    if normalized_client_last_sync is not None and (now_utc - normalized_client_last_sync) > timedelta(days=retention_days):
        return {
            "tables": {},
            "server_time": now_utc.isoformat() + "Z",
            "full_resync_required": True,
            "reason": "client_out_of_retention_window",
            "retention_days": retention_days,
        }
    cache_key = _manifest_cache_key(effective_scope)
    local_cached = _get_manifest_from_local_cache(cache_key)
    if local_cached:
        return local_cached
    redis = None
    try:
        redis = await get_redis()
        cached = await redis.get(cache_key)
        if cached:
            payload = json.loads(cached)
            _put_manifest_to_local_cache(cache_key, payload)
            return payload
    except Exception:
        logger.debug("sync manifest redis cache unavailable", exc_info=True)
        redis = None

    tables: Dict[str, Any] = {}
    for table_name, model in TABLE_MODELS.items():
        tables[table_name] = _table_manifest(
            db=db,
            table_name=table_name,
            model=model,
            scope=effective_scope,
            forbidden_ranges=forbidden_ranges,
        )
    response_payload = {
        "tables": tables,
        "server_time": datetime.utcnow().isoformat() + "Z",
    }
    _put_manifest_to_local_cache(cache_key, response_payload)
    if redis:
        try:
            await redis.setex(
                cache_key,
                max(1, int(SYNC_MANIFEST_CACHE_TTL)),
                json.dumps(response_payload, ensure_ascii=False),
            )
        except Exception:
            logger.debug("sync manifest redis cache set failed", exc_info=True)
    return response_payload


def _load_deleted_ids(
    db: Session,
    table_name: str,
    *,
    since: Optional[datetime],
    limit: int = SYNC_DELETED_IDS_LIMIT,
) -> List[int]:
    query = db.query(SyncDeletion.record_id).filter(SyncDeletion.table_name == table_name)
    if since:
        query = query.filter(SyncDeletion.deleted_at >= since)
    rows = query.order_by(SyncDeletion.id.desc()).limit(limit).all()
    return sorted({int(row[0]) for row in rows if row and row[0] is not None})


def _blocked_ranges(db: Session) -> List[Dict[str, str]]:
    locks = period_lock_service.get_active_locks(db)
    ranges: List[Dict[str, str]] = []
    for lock in locks:
        ranges.append(
            {
                "from": lock.date_from.isoformat(),
                "to": lock.date_to.isoformat(),
            }
        )
    return ranges


@router.get("/{table_name}")
async def sync_table(
    table_name: str,
    request: Request,
    since: Optional[datetime] = Query(None),
    since_id: Optional[int] = Query(None, ge=0),
    cursor_updated_at: Optional[datetime] = Query(None, description="Cursor updated_at for cursor-mode sync"),
    cursor_id: Optional[int] = Query(None, ge=0, description="Cursor id for cursor-mode sync"),
    limit: int = Query(5000, ge=1, le=20000),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db_session),
    current_user: dict = Depends(require_tab_access("dashboard")),
    scope: Optional[Dict[str, Any]] = Depends(require_transactions_scope),
) -> Dict[str, Any]:
    effective_scope = _effective_scope(db, scope, current_user)
    forbidden_ranges = _forbidden_ranges_for_user(current_user)
    await _enforce_sync_rate_limit(request, current_user)
    await _cleanup_old_sync_deletions(db)
    model = TABLE_MODELS.get(table_name)
    if not model:
        raise HTTPException(status_code=404, detail="Unknown table_name")
    if not _table_allowed_for_scope(table_name, effective_scope):
        return {
            "table": table_name,
            "rows": [],
            "total_count": 0,
            "has_more": False,
            "server_checksum": EMPTY_CHECKSUM,
            "server_time": datetime.utcnow().isoformat() + "Z",
            "deleted_ids": [],
            "blocked_ranges": [],
            "next_cursor": None,
        }

    id_column_name = _resolve_id_column(model)
    updated_column_name = _resolve_updated_column(model)
    id_column = getattr(model, id_column_name)

    base_query = db.query(model)
    if model is Transaction:
        base_query = _scope_filter_transactions(base_query, effective_scope)
        base_query = _apply_forbidden_ranges(base_query, forbidden_ranges)
        base_query = _locked_period_filter_transactions(base_query, db)

    query = base_query

    if since and updated_column_name:
        query = query.filter(getattr(model, updated_column_name) >= since)
    if since_id:
        query = query.filter(id_column > since_id)
    cursor_mode = bool(cursor_updated_at is not None or cursor_id is not None)
    next_cursor: Optional[Dict[str, Any]] = None

    if cursor_mode:
        if updated_column_name and cursor_updated_at is not None:
            updated_col = getattr(model, updated_column_name)
            if cursor_id is None:
                query = query.filter(updated_col > cursor_updated_at)
            else:
                query = query.filter(
                    or_(
                        updated_col > cursor_updated_at,
                        and_(updated_col == cursor_updated_at, id_column > int(cursor_id)),
                    )
                )
            rows = (
                query.order_by(updated_col.asc(), id_column.asc())
                .limit(limit + 1)
                .all()
            )
        else:
            last_id = int(cursor_id or 0)
            query = query.filter(id_column > last_id)
            rows = query.order_by(id_column.asc()).limit(limit + 1).all()

        has_more = len(rows) > limit
        if has_more:
            rows = rows[:limit]
        total_count = len(rows)
        if rows:
            last = rows[-1]
            cursor_payload: Dict[str, Any] = {"id": int(getattr(last, id_column_name))}
            if updated_column_name:
                updated_val = getattr(last, updated_column_name, None)
                cursor_payload["updated_at"] = (
                    updated_val.isoformat() if isinstance(updated_val, datetime) else None
                )
            next_cursor = cursor_payload if has_more else None
    else:
        total_count = query.count()
        rows = query.order_by(id_column.asc()).offset(offset).limit(limit).all()
        has_more = (offset + len(rows)) < total_count

    checksum_rows = base_query.order_by(id_column.desc()).limit(100).all()
    server_checksum = _rows_checksum(checksum_rows, id_column=id_column_name, updated_column=updated_column_name)

    deleted_ids = _load_deleted_ids(db, table_name=table_name, since=since)
    if model is Transaction and effective_scope:
        # Avoid leaking existence/deletion of out-of-scope transactions.
        deleted_ids = []

    return {
        "table": table_name,
        "rows": [_serialize_row(row) for row in rows],
        "total_count": total_count,
        "has_more": has_more,
        "server_checksum": server_checksum,
        "server_time": datetime.utcnow().isoformat() + "Z",
        "deleted_ids": deleted_ids,
        "blocked_ranges": _blocked_ranges(db) if (model is Transaction and offset == 0 and not cursor_mode) else [],
        "next_cursor": next_cursor,
    }
