"""Deletion tracking for incremental sync endpoints."""
from __future__ import annotations

from typing import Dict, Optional, Type

from sqlalchemy import event, insert
from sqlalchemy.orm import Session

from database.models import (
    AccessScope,
    ChatPassword,
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


TRACKED_MODELS: Dict[Type, str] = {
    Transaction: "transactions",
    OperatorMapping: "operatorMappings",
    OperatorReference: "operatorReferences",
    MonitoredBotChat: "monitoredBotChats",
    HiddenBotChat: "hiddenBotChats",
    ParsingLog: "parsingLogs",
    HourlyReport: "hourlyReports",
    AccessScope: "accessScopes",
    ReceiptProcessingTask: "receiptProcessingTasks",
    ChatPassword: "chatPasswords",
    LockedPeriod: "lockedPeriods",
}


def _extract_record_id(obj: object) -> Optional[int]:
    record_id = getattr(obj, "id", None)
    if record_id is None:
        record_id = getattr(obj, "chat_id", None)
    if record_id is None:
        return None
    try:
        return int(record_id)
    except Exception:
        return None


def _collect_sync_deletions(session: Session, *_args) -> None:
    pending = session.info.setdefault("sync_deletions_pending", [])
    for obj in list(session.deleted):
        table_name = TRACKED_MODELS.get(type(obj))
        if not table_name:
            continue
        record_id = _extract_record_id(obj)
        if record_id is None:
            continue
        pending.append((table_name, record_id))


def _persist_sync_deletions(session: Session, *_args) -> None:
    pending = session.info.pop("sync_deletions_pending", None) or []
    if not pending:
        return

    # Deduplicate within transaction.
    unique = {(table_name, record_id) for table_name, record_id in pending}
    rows = [{"table_name": table_name, "record_id": record_id} for table_name, record_id in unique]
    if rows:
        session.execute(insert(SyncDeletion), rows)


def register_sync_deletion_listeners() -> None:
    """Register SQLAlchemy Session hooks once."""
    if getattr(register_sync_deletion_listeners, "_registered", False):
        return
    # before_commit is executed prior to flush; collect deleted entities there,
    # then persist records after SQL delete statements have executed.
    event.listen(Session, "before_commit", _collect_sync_deletions)
    event.listen(Session, "after_flush_postexec", _persist_sync_deletions)
    setattr(register_sync_deletion_listeners, "_registered", True)
