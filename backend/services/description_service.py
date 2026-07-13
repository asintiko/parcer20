"""Merchant description service.

Descriptions are bound to a *normalized operator key* (not to a single transaction).
A description is resolved at read time, so any transaction whose ``operator_raw``
normalizes to a keyed operator gets the description retroactively.

A single ``Description`` row can back many operator keys (shared entity): editing
its text updates every linked operator at once.

Process-wide TTL cache mirrors ``parsers/operator_mapper.py`` to avoid a SELECT per
transaction during list serialization.
"""
import os
import threading
import time
from typing import Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from database.models import Description, OperatorDescriptionLink
from parsers.operator_mapper import OperatorMapper


_CACHE_TTL_SECONDS = float(os.getenv("DESCRIPTION_CACHE_TTL", "120"))
_cache_lock = threading.Lock()
# operator_key -> (description_id, text)
_cache_data: Dict[str, Tuple[int, str]] = {}
_cache_loaded_at: float = 0.0


def normalize_key(operator_raw: Optional[str]) -> str:
    """Normalize a raw operator string into the lookup key (uppercase / collapsed)."""
    if not operator_raw:
        return ""
    return OperatorMapper.normalize_operator(operator_raw)


def _load_cache(db: Session) -> Dict[str, Tuple[int, str]]:
    rows = (
        db.query(
            OperatorDescriptionLink.operator_key,
            OperatorDescriptionLink.description_id,
            Description.text,
        )
        .join(Description, Description.id == OperatorDescriptionLink.description_id)
        .all()
    )
    return {
        key: (int(desc_id), text)
        for key, desc_id, text in rows
        if key
    }


def _get_cached(db: Session, force: bool = False) -> Dict[str, Tuple[int, str]]:
    global _cache_data, _cache_loaded_at
    now = time.time()
    with _cache_lock:
        if force or not _cache_loaded_at or (now - _cache_loaded_at) > _CACHE_TTL_SECONDS:
            try:
                _cache_data = _load_cache(db)
                _cache_loaded_at = now
            except Exception:  # noqa: BLE001
                # Keep stale cache rather than failing the request.
                pass
        return _cache_data


def invalidate_descriptions_cache() -> None:
    """Force next caller to reload from DB (call after any description CRUD)."""
    global _cache_data, _cache_loaded_at
    with _cache_lock:
        _cache_data = {}
        _cache_loaded_at = 0.0


def resolve(db: Session, operator_raw: Optional[str]) -> Optional[str]:
    """Return the description text for a single operator, or None."""
    key = normalize_key(operator_raw)
    if not key:
        return None
    entry = _get_cached(db).get(key)
    return entry[1] if entry else None


def resolve_batch(
    db: Session, operator_raws: List[Optional[str]]
) -> Dict[Optional[str], Optional[str]]:
    """Resolve many operators in one cache pass (no N+1 during list serialization).

    Returns a mapping keyed by the *original* operator_raw string -> text|None.
    """
    cache = _get_cached(db)
    result: Dict[Optional[str], Optional[str]] = {}
    for raw in operator_raws:
        if raw in result:
            continue
        key = normalize_key(raw)
        entry = cache.get(key) if key else None
        result[raw] = entry[1] if entry else None
    return result


def _delete_orphan_description(db: Session, description_id: int) -> None:
    remaining = (
        db.query(OperatorDescriptionLink.id)
        .filter(OperatorDescriptionLink.description_id == description_id)
        .first()
    )
    if remaining is None:
        desc = db.query(Description).filter(Description.id == description_id).first()
        if desc is not None:
            db.delete(desc)


def set_for_operator(
    db: Session,
    operator_raw: Optional[str],
    text: Optional[str],
    source: str = "manual",
    user_id: Optional[int] = None,
) -> Optional[Description]:
    """Upsert the description for one operator key.

    - empty/None text -> remove the link (and orphaned Description) for this operator.
    - link exists      -> update the linked Description's text (shared-entity edit).
    - no link          -> create a Description + link.
    """
    key = normalize_key(operator_raw)
    if not key:
        return None

    clean_text = text.strip() if isinstance(text, str) else text
    link = (
        db.query(OperatorDescriptionLink)
        .filter(OperatorDescriptionLink.operator_key == key)
        .first()
    )

    if not clean_text:
        if link is not None:
            description_id = int(link.description_id)
            db.delete(link)
            db.flush()
            _delete_orphan_description(db, description_id)
            db.commit()
            invalidate_descriptions_cache()
        return None

    if link is not None:
        desc = db.query(Description).filter(Description.id == link.description_id).first()
        if desc is None:
            desc = Description(text=clean_text, created_by_user_id=user_id)
            db.add(desc)
            db.flush()
            link.description_id = desc.id
        else:
            desc.text = clean_text
        db.commit()
        db.refresh(desc)
        invalidate_descriptions_cache()
        return desc

    desc = Description(text=clean_text, created_by_user_id=user_id)
    db.add(desc)
    db.flush()
    link = OperatorDescriptionLink(
        operator_key=key,
        description_id=desc.id,
        source=source or "manual",
        created_by_user_id=user_id,
    )
    db.add(link)
    db.commit()
    db.refresh(desc)
    invalidate_descriptions_cache()
    return desc


def remove_for_operators(
    db: Session,
    operator_raws: List[Optional[str]],
    only_source: Optional[str] = None,
) -> int:
    """Remove links for the given operators (optionally only those with ``only_source``).

    Cleans orphaned Descriptions. Returns the number of links removed.
    """
    keys = {normalize_key(raw) for raw in operator_raws}
    keys.discard("")
    if not keys:
        return 0

    query = db.query(OperatorDescriptionLink).filter(
        OperatorDescriptionLink.operator_key.in_(keys)
    )
    if only_source is not None:
        query = query.filter(OperatorDescriptionLink.source == only_source)

    links = query.all()
    if not links:
        return 0

    description_ids = {int(link.description_id) for link in links}
    removed = 0
    for link in links:
        db.delete(link)
        removed += 1
    db.flush()
    for description_id in description_ids:
        _delete_orphan_description(db, description_id)
    db.commit()
    invalidate_descriptions_cache()
    return removed


def link_operators(
    db: Session,
    description_id: int,
    operator_raws: List[Optional[str]],
    source: str = "manual",
    user_id: Optional[int] = None,
) -> List[OperatorDescriptionLink]:
    """Point the given operators at ``description_id`` (re-pointing existing links)."""
    desc = db.query(Description).filter(Description.id == description_id).first()
    if desc is None:
        return []

    orphan_candidates: set[int] = set()
    result: List[OperatorDescriptionLink] = []
    for raw in operator_raws:
        key = normalize_key(raw)
        if not key:
            continue
        link = (
            db.query(OperatorDescriptionLink)
            .filter(OperatorDescriptionLink.operator_key == key)
            .first()
        )
        if link is not None:
            if int(link.description_id) != int(description_id):
                orphan_candidates.add(int(link.description_id))
            link.description_id = description_id
            link.source = source or link.source
        else:
            link = OperatorDescriptionLink(
                operator_key=key,
                description_id=description_id,
                source=source or "manual",
                created_by_user_id=user_id,
            )
            db.add(link)
        result.append(link)

    db.flush()
    for candidate in orphan_candidates:
        if candidate != int(description_id):
            _delete_orphan_description(db, candidate)
    db.commit()
    invalidate_descriptions_cache()
    return result


def unlink_operators(
    db: Session,
    description_id: int,
    operator_raws: List[Optional[str]],
) -> int:
    """Remove the given operators from ``description_id``. Returns links removed."""
    keys = {normalize_key(raw) for raw in operator_raws}
    keys.discard("")
    if not keys:
        return 0

    links = (
        db.query(OperatorDescriptionLink)
        .filter(
            OperatorDescriptionLink.description_id == description_id,
            OperatorDescriptionLink.operator_key.in_(keys),
        )
        .all()
    )
    if not links:
        return 0

    removed = 0
    for link in links:
        db.delete(link)
        removed += 1
    db.flush()
    _delete_orphan_description(db, int(description_id))
    db.commit()
    invalidate_descriptions_cache()
    return removed
