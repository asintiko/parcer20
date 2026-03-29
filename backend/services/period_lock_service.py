"""Services for blocking date ranges."""
from __future__ import annotations

from datetime import date, timedelta
from typing import List, Tuple

from sqlalchemy import and_
from sqlalchemy.orm import Session

from database.models import LockedPeriod


class PeriodLockService:
    def get_active_locks(self, db: Session) -> List[LockedPeriod]:
        return (
            db.query(LockedPeriod)
            .filter(LockedPeriod.is_active.is_(True))
            .order_by(LockedPeriod.date_from.asc(), LockedPeriod.id.asc())
            .all()
        )

    def is_date_locked(self, value: date, db: Session) -> bool:
        return (
            db.query(LockedPeriod.id)
            .filter(
                LockedPeriod.is_active.is_(True),
                LockedPeriod.date_from <= value,
                LockedPeriod.date_to >= value,
            )
            .first()
            is not None
        )

    def filter_locked_range(self, start: date, end: date, db: Session) -> List[Tuple[date, date]]:
        if start > end:
            start, end = end, start

        locks = (
            db.query(LockedPeriod)
            .filter(
                LockedPeriod.is_active.is_(True),
                and_(LockedPeriod.date_from <= end, LockedPeriod.date_to >= start),
            )
            .order_by(LockedPeriod.date_from.asc(), LockedPeriod.date_to.asc())
            .all()
        )
        if not locks:
            return [(start, end)]

        allowed: List[Tuple[date, date]] = []
        cursor = start
        for lock in locks:
            if lock.date_from > cursor:
                allowed.append((cursor, lock.date_from - timedelta(days=1)))
            if lock.date_to >= cursor:
                cursor = lock.date_to + timedelta(days=1)
            if cursor > end:
                break

        if cursor <= end:
            allowed.append((cursor, end))
        return [(a, b) for a, b in allowed if a <= b]

    def lock_period(self, date_from: date, date_to: date, tg_id: int, reason: str | None, db: Session) -> LockedPeriod:
        if date_from > date_to:
            date_from, date_to = date_to, date_from
        row = LockedPeriod(
            date_from=date_from,
            date_to=date_to,
            reason=reason,
            locked_by_tg_id=tg_id,
            is_active=True,
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return row

    def unlock_period(self, lock_id: int, db: Session) -> bool:
        row = db.get(LockedPeriod, lock_id)
        if row is None:
            return False
        row.is_active = False
        db.commit()
        return True


period_lock_service = PeriodLockService()
