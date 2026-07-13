from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional
from uuid import UUID

from sqlalchemy.orm import Session

from database.models import (
    AccessAuditLog,
    AutomationSuggestion,
    Transaction,
    VerificationSuggestion,
)

logger = logging.getLogger(__name__)

# Audit-log markers the agent writes on apply so a later rollback can find and
# revert exactly the rows it touched (and only those — manual applies via the
# Automation page use different action strings and are never reverted here).
AGENT_MAPPING_APPLY_ACTION = "agent_apply_mapping_suggestion"
AGENT_VERIFICATION_APPLY_ACTION = "agent_apply_verification_suggestion"


def _coerce_uuid(value: Any) -> Optional[UUID]:
    try:
        return UUID(str(value))
    except (ValueError, TypeError):
        return None


def apply_mapping_suggestions(
    db: Session,
    *,
    task_id: Optional[str],
    scope: Optional[dict],
    current_user: Optional[dict],
    min_confidence: float = 0.85,
    suggestion_ids: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Apply confident mapping suggestions, recording prior values for rollback.

    Reuses the same field writes as the Automation page (application_mapped +
    is_p2p) and the same scope/period-lock guard. Suggestions below
    `min_confidence` are skipped and reported back as `pending_low`.
    Returns counts plus a compact list of applied/skipped items for the chat.
    """
    from api.routes.automation import _tx_edit_denial_reason

    tid = _coerce_uuid(task_id) if task_id is not None else None
    q = db.query(AutomationSuggestion).filter(AutomationSuggestion.status == "pending")
    if tid is not None:
        q = q.filter(AutomationSuggestion.task_id == tid)
    if suggestion_ids:
        wanted = [u for u in (_coerce_uuid(s) for s in suggestion_ids) if u is not None]
        if not wanted:
            return {"applied": 0, "skipped": 0, "low_confidence": 0, "items": [], "low_items": []}
        q = q.filter(AutomationSuggestion.id.in_(wanted))

    rows = q.order_by(AutomationSuggestion.confidence.desc()).all()

    applied = 0
    skipped = 0
    low = 0
    applied_items: List[Dict[str, Any]] = []
    low_items: List[Dict[str, Any]] = []

    for sug in rows:
        conf = float(sug.confidence or 0.0)
        if conf < float(min_confidence):
            low += 1
            tx = db.query(Transaction).filter(Transaction.id == sug.transaction_id).first()
            low_items.append({
                "оператор": (tx.operator_raw if tx else None),
                "приложение": sug.suggested_application,
                "уверенность": round(conf, 2),
            })
            continue
        try:
            with db.begin_nested():
                tx = db.query(Transaction).filter(Transaction.id == sug.transaction_id).first()
                if not tx:
                    skipped += 1
                    continue
                denial = _tx_edit_denial_reason(tx, scope, db)
                if denial:
                    skipped += 1
                    continue

                prev_application = tx.application_mapped
                prev_is_p2p = bool(tx.is_p2p)
                tx.application_mapped = sug.suggested_application
                tx.is_p2p = sug.is_p2p
                sug.status = "approved"
                db.add(AccessAuditLog(
                    action=AGENT_MAPPING_APPLY_ACTION,
                    success=True,
                    user_id=(current_user.get("user_id") or current_user.get("id")) if current_user else None,
                    details_json=json.dumps({
                        "suggestion_id": str(sug.id),
                        "task_id": str(sug.task_id),
                        "transaction_id": int(sug.transaction_id),
                        "prev_application_mapped": prev_application,
                        "prev_is_p2p": prev_is_p2p,
                        "new_application_mapped": sug.suggested_application,
                    }, ensure_ascii=False),
                ))
                db.flush()
            applied += 1
            applied_items.append({
                "оператор": tx.operator_raw,
                "приложение": sug.suggested_application,
                "уверенность": round(conf, 2),
            })
        except Exception:  # noqa: BLE001
            logger.warning("agent mapping apply failed for suggestion %s", sug.id, exc_info=True)
            skipped += 1

    db.commit()
    return {
        "applied": applied,
        "skipped": skipped,
        "low_confidence": low,
        "items": applied_items[:10],
        "low_items": low_items[:10],
    }


def apply_verification_suggestions(
    db: Session,
    *,
    task_id: Optional[str],
    scope: Optional[dict],
    current_user: Optional[dict],
    min_confidence: float = 0.85,
    suggestion_ids: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Apply confident field-level corrections; record old values for rollback.

    `VerificationSuggestion.current_value` already holds the pre-correction value,
    so rollback is precise. Anything below `min_confidence` is left pending.
    """
    from api.routes.automation import _apply_verification_field, _tx_edit_denial_reason, FIELD_LABELS_RU

    tid = _coerce_uuid(task_id) if task_id is not None else None
    q = db.query(VerificationSuggestion).filter(VerificationSuggestion.status == "pending")
    if tid is not None:
        q = q.filter(VerificationSuggestion.task_id == tid)
    if suggestion_ids:
        wanted = [u for u in (_coerce_uuid(s) for s in suggestion_ids) if u is not None]
        if not wanted:
            return {"applied": 0, "skipped": 0, "low_confidence": 0, "items": [], "low_items": []}
        q = q.filter(VerificationSuggestion.id.in_(wanted))

    rows = q.order_by(VerificationSuggestion.confidence.desc()).all()

    applied = 0
    skipped = 0
    low = 0
    applied_items: List[Dict[str, Any]] = []
    low_items: List[Dict[str, Any]] = []

    for sug in rows:
        conf = float(sug.confidence or 0.0)
        label = FIELD_LABELS_RU.get(sug.field_name, sug.field_name)
        if conf < float(min_confidence):
            low += 1
            low_items.append({
                "поле": label,
                "было": sug.current_value,
                "станет": sug.suggested_value,
                "уверенность": round(conf, 2),
            })
            continue
        try:
            with db.begin_nested():
                tx = db.query(Transaction).filter(Transaction.id == sug.transaction_id).first()
                if not tx:
                    skipped += 1
                    continue
                denial = _tx_edit_denial_reason(tx, scope, db)
                if denial:
                    skipped += 1
                    continue
                _apply_verification_field(tx, sug.field_name, sug.suggested_value)
                sug.status = "approved"
                db.add(AccessAuditLog(
                    action=AGENT_VERIFICATION_APPLY_ACTION,
                    success=True,
                    user_id=(current_user.get("user_id") or current_user.get("id")) if current_user else None,
                    details_json=json.dumps({
                        "suggestion_id": str(sug.id),
                        "task_id": str(sug.task_id),
                        "transaction_id": int(sug.transaction_id),
                        "field_name": sug.field_name,
                        "old_value": sug.current_value,
                        "new_value": sug.suggested_value,
                    }, ensure_ascii=False),
                ))
                db.flush()
            applied += 1
            applied_items.append({
                "поле": label,
                "было": sug.current_value,
                "стало": sug.suggested_value,
                "уверенность": round(conf, 2),
            })
        except Exception:  # noqa: BLE001
            logger.warning("agent verification apply failed for suggestion %s", sug.id, exc_info=True)
            skipped += 1

    db.commit()
    return {
        "applied": applied,
        "skipped": skipped,
        "low_confidence": low,
        "items": applied_items[:10],
        "low_items": low_items[:10],
    }


def rollback_automation(
    db: Session,
    *,
    task_id: Optional[str] = None,
    scope_kind: str = "all",
    current_user: Optional[dict] = None,
) -> Dict[str, Any]:
    """Revert agent-applied mapping/verification changes using audit markers.

    scope_kind: 'all' | 'mapping' | 'verification'. When `task_id` is given only
    markers for that task are reverted. Mapping reverts application_mapped/is_p2p
    to the stored prior value; verification reverts the field to old_value (or
    reports it can't when the suggestion never captured an old value).
    """
    actions: List[str] = []
    if scope_kind in ("all", "mapping"):
        actions.append(AGENT_MAPPING_APPLY_ACTION)
    if scope_kind in ("all", "verification"):
        actions.append(AGENT_VERIFICATION_APPLY_ACTION)
    if not actions:
        return {"reverted": 0, "skipped": 0, "unrevertable": 0, "notes": ["Неизвестная область отката."]}

    rows = (
        db.query(AccessAuditLog)
        .filter(AccessAuditLog.action.in_(actions), AccessAuditLog.success.is_(True))
        .order_by(AccessAuditLog.created_at.desc())
        .all()
    )

    reverted = 0
    skipped = 0
    unrevertable = 0
    notes: List[str] = []
    seen_keys: set[tuple] = set()

    for log in rows:
        try:
            details = json.loads(log.details_json) if log.details_json else {}
        except Exception:
            continue
        if task_id is not None and str(details.get("task_id")) != str(task_id):
            continue

        tx_id = details.get("transaction_id")
        if tx_id is None:
            continue
        tx = db.query(Transaction).filter(Transaction.id == int(tx_id)).first()
        if not tx:
            skipped += 1
            continue

        if log.action == AGENT_MAPPING_APPLY_ACTION:
            # Only the latest marker per transaction carries the true prior value.
            key = ("mapping", int(tx_id))
            if key in seen_keys:
                continue
            seen_keys.add(key)
            tx.application_mapped = details.get("prev_application_mapped")
            tx.is_p2p = bool(details.get("prev_is_p2p"))
            sug_id = _coerce_uuid(details.get("suggestion_id"))
            if sug_id is not None:
                sug = db.get(AutomationSuggestion, sug_id)
                if sug is not None:
                    sug.status = "pending"
            log.success = False
            reverted += 1
        else:  # verification
            key = ("verification", int(tx_id), details.get("field_name"))
            if key in seen_keys:
                continue
            seen_keys.add(key)
            old_value = details.get("old_value")
            if old_value is None:
                unrevertable += 1
                continue
            try:
                from api.routes.automation import _apply_verification_field

                _apply_verification_field(tx, details.get("field_name"), old_value)
            except Exception:  # noqa: BLE001
                unrevertable += 1
                continue
            sug_id = _coerce_uuid(details.get("suggestion_id"))
            if sug_id is not None:
                sug = db.get(VerificationSuggestion, sug_id)
                if sug is not None:
                    sug.status = "pending"
            log.success = False
            reverted += 1

    db.commit()
    if unrevertable:
        notes.append(
            f"{unrevertable} верификационных правок откатить нельзя — не сохранено прежнее значение."
        )
    return {"reverted": reverted, "skipped": skipped, "unrevertable": unrevertable, "notes": notes}
