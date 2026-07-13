from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, Iterable, Optional, Sequence

from sqlalchemy.orm import Session

from database.models import AccessScope, LockedPeriod, Transaction, User
from services.period_lock_service import period_lock_service
from services.user_service import build_permissions_snapshot


class AgentAuthorizationError(ValueError):
    """A current database policy rejected an agent action."""


def _normalize_ints(values: Any) -> tuple[int, ...]:
    if not isinstance(values, (list, tuple, set)):
        return ()
    normalized: set[int] = set()
    for value in values:
        try:
            normalized.add(int(value))
        except (TypeError, ValueError):
            continue
    return tuple(sorted(normalized))


def _parse_datetime(value: Any) -> Optional[datetime]:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value.replace(tzinfo=None) if value.tzinfo else value
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return parsed.replace(tzinfo=None) if parsed.tzinfo else parsed


def _scope_windows(db: Session, folder_ids: Sequence[int]) -> tuple[Dict[str, Any], ...]:
    if not folder_ids:
        return ()
    rows = (
        db.query(AccessScope)
        .filter(AccessScope.id.in_(folder_ids), AccessScope.is_active.is_(True))
        .all()
    )
    by_id: Dict[int, Dict[str, Any]] = {}
    for row in rows:
        try:
            import json

            years = _normalize_ints(json.loads(row.years_json or "[]"))
        except Exception:
            years = ()
        by_id[int(row.id)] = {
            "id": int(row.id),
            "years": years,
            "date_from": row.period_start,
            "date_to": row.period_end,
            "allow_transactions": bool(row.allow_transactions),
            "allow_sources": bool(row.allow_sources),
        }

    # Some deployments keep access scopes in the root-access configuration.
    # They are part of the same current policy and must not be skipped here.
    try:
        from services.access_control_service import config_scope_to_public_dict
        from services.root_access_config_service import get_config_scopes

        for raw in get_config_scopes(active_only=True):
            public = config_scope_to_public_dict(raw)
            try:
                scope_id = int(public.get("id"))
            except (TypeError, ValueError):
                continue
            if scope_id in by_id:
                continue
            by_id[scope_id] = {
                "id": scope_id,
                "years": _normalize_ints(public.get("years")),
                "date_from": _parse_datetime(public.get("period_start")),
                "date_to": _parse_datetime(public.get("period_end")),
                "allow_transactions": bool(public.get("allow_transactions", True)),
                "allow_sources": bool(public.get("allow_sources", False)),
            }
    except Exception:
        # A missing optional root-access file cannot widen access. Database
        # scopes remain authoritative and an unknown configured scope is denied.
        pass

    return tuple(by_id[scope_id] for scope_id in folder_ids if scope_id in by_id)


@dataclass(frozen=True)
class AgentAuthorization:
    user_id: int
    role: str
    permissions_version: int
    user: Dict[str, Any]
    allowed_sources: Optional[frozenset[int]]
    folder_windows: tuple[Dict[str, Any], ...]

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"

    def require_admin(self, action: str) -> None:
        if not self.is_admin:
            raise AgentAuthorizationError(f"admin_required:{action}")

    def require_dashboard(self) -> None:
        if self.is_admin:
            return
        tabs = {
            "dashboard" if str(item).strip().lower() == "transactions" else str(item).strip().lower()
            for item in (self.user.get("allowed_tabs") or [])
        }
        if "dashboard" not in tabs:
            raise AgentAuthorizationError("tab_forbidden:dashboard")

    def authorize_chat(self, chat_id: Any) -> int:
        try:
            normalized = int(chat_id)
        except (TypeError, ValueError) as exc:
            raise AgentAuthorizationError("invalid_source_chat") from exc
        if self.allowed_sources is not None and normalized not in self.allowed_sources:
            raise AgentAuthorizationError(f"source_forbidden:{normalized}")
        return normalized

    def authorize_date(self, db: Session, value: Any) -> datetime:
        parsed = _parse_datetime(value)
        if parsed is None:
            raise AgentAuthorizationError("invalid_transaction_date")

        if not self.is_admin:
            if not any(_window_allows_date(window, parsed) for window in self.folder_windows):
                raise AgentAuthorizationError(f"folder_period_forbidden:{parsed.date().isoformat()}")
            for period in self.user.get("forbidden_periods") or []:
                if not isinstance(period, dict):
                    continue
                start = _parse_datetime(period.get("from"))
                end = _parse_datetime(period.get("to"))
                if start and end:
                    low, high = sorted((start.date(), end.date()))
                    if low <= parsed.date() <= high:
                        raise AgentAuthorizationError(f"period_forbidden:{parsed.date().isoformat()}")

        if period_lock_service.is_date_locked(parsed.date(), db, user_id=self.user_id):
            raise AgentAuthorizationError(f"period_locked:{parsed.date().isoformat()}")
        return parsed

    def authorize_range(self, db: Session, date_from: Any, date_to: Any) -> tuple[datetime, datetime]:
        start = _parse_datetime(date_from)
        end = _parse_datetime(date_to)
        if start is None or end is None:
            raise AgentAuthorizationError("explicit_period_required")
        if end < start:
            start, end = end, start

        if not self.is_admin:
            if not any(
                _window_allows_date(window, start) and _window_allows_date(window, end)
                for window in self.folder_windows
            ):
                raise AgentAuthorizationError("folder_period_forbidden:range")
            for period in self.user.get("forbidden_periods") or []:
                if not isinstance(period, dict):
                    continue
                blocked_from = _parse_datetime(period.get("from"))
                blocked_to = _parse_datetime(period.get("to"))
                if blocked_from and blocked_to:
                    low, high = sorted((blocked_from.date(), blocked_to.date()))
                    if low <= end.date() and high >= start.date():
                        raise AgentAuthorizationError("period_forbidden:range")

        locks = (
            db.query(LockedPeriod)
            .filter(
                LockedPeriod.is_active.is_(True),
                LockedPeriod.date_from <= end.date(),
                LockedPeriod.date_to >= start.date(),
            )
            .all()
        )
        for lock in locks:
            try:
                excluded = {int(item) for item in (lock.excluded_user_ids or [])}
            except (TypeError, ValueError):
                excluded = set()
            if self.user_id not in excluded:
                raise AgentAuthorizationError("period_locked:range")
        return start, end

    def authorize_transaction(
        self,
        db: Session,
        transaction: Transaction,
        *,
        proposed_date: Any = None,
    ) -> None:
        self.require_dashboard()
        if transaction.source_chat_id is None:
            if not self.is_admin:
                raise AgentAuthorizationError("source_forbidden:null")
        else:
            self.authorize_chat(transaction.source_chat_id)
        self.authorize_date(db, transaction.transaction_date)
        if proposed_date is not None:
            self.authorize_date(db, proposed_date)

    def tool_scope(self) -> Optional[Dict[str, Any]]:
        if self.is_admin:
            return None
        starts = [window["date_from"] for window in self.folder_windows if window.get("date_from")]
        ends = [window["date_to"] for window in self.folder_windows if window.get("date_to")]
        years = sorted(
            {
                int(year)
                for window in self.folder_windows
                for year in (window.get("years") or ())
            }
        )
        return {
            "scope_id": -2,
            "scope_name": "current-user-policy",
            "years": years,
            "date_from": min(starts).isoformat() if starts else None,
            "date_to": max(ends).isoformat() if ends else None,
            "allow_transactions": bool(self.folder_windows),
            "allow_sources": bool(self.allowed_sources),
            # An empty list is an explicit deny-all value. Callers must not
            # collapse it to None/no filter.
            "allowed_chat_ids": sorted(self.allowed_sources or ()),
        }


def _window_allows_date(window: Dict[str, Any], value: datetime) -> bool:
    if not window.get("allow_transactions", True):
        return False
    years = set(window.get("years") or ())
    if years and value.year not in years:
        return False
    date_from = _parse_datetime(window.get("date_from"))
    date_to = _parse_datetime(window.get("date_to"))
    if date_from and value < date_from:
        return False
    if date_to and value > date_to:
        return False
    return True


def current_agent_authorization(db: Session, user_id: Any) -> AgentAuthorization:
    try:
        normalized_id = int(user_id)
    except (TypeError, ValueError) as exc:
        raise AgentAuthorizationError("invalid_actor") from exc
    if normalized_id <= 0:
        raise AgentAuthorizationError("invalid_actor")

    db.expire_all()
    row = db.get(User, normalized_id)
    if row is None or not row.is_active:
        raise AgentAuthorizationError("inactive_or_missing_actor")
    user = build_permissions_snapshot(row)
    role = str(user.get("role") or "operator").lower()
    allowed_sources = None if role == "admin" else frozenset(_normalize_ints(user.get("allowed_sources")))
    folder_windows = () if role == "admin" else _scope_windows(db, _normalize_ints(user.get("allowed_folders")))
    return AgentAuthorization(
        user_id=normalized_id,
        role=role,
        permissions_version=int(row.permissions_version or 1),
        user=user,
        allowed_sources=allowed_sources,
        folder_windows=folder_windows,
    )


def actor_id(current_user: Dict[str, Any]) -> int:
    try:
        value = int(current_user.get("id") or current_user.get("user_id") or 0)
    except (TypeError, ValueError) as exc:
        raise AgentAuthorizationError("invalid_actor") from exc
    if value <= 0:
        raise AgentAuthorizationError("invalid_actor")
    return value


def require_same_source_set(auth: AgentAuthorization, chat_ids: Iterable[Any]) -> tuple[int, ...]:
    normalized = tuple(sorted({auth.authorize_chat(value) for value in chat_ids}))
    if not normalized:
        raise AgentAuthorizationError("empty_source_scope")
    return normalized
