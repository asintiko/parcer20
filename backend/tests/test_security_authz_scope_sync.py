from datetime import datetime, timedelta

from database.models import AccessScope, Transaction
from api import dependencies
from api.routes import sync


def _scope_row(db_session) -> AccessScope:
    row = AccessScope(
        name="finance-2026",
        password_hash="hash",
        salt="salt",
        years_json="[2026]",
        period_start=datetime(2026, 1, 1),
        period_end=datetime(2026, 12, 31, 23, 59, 59),
        allow_transactions=True,
        allow_sources=False,
        is_active=True,
    )
    db_session.add(row)
    db_session.commit()
    db_session.refresh(row)
    return row


def test_scope_token_claims_are_revalidated_against_current_db_state(db_session):
    row = _scope_row(db_session)
    current = {
        "kind": "scope_access",
        "scope_id": int(row.id),
        "scope_name": row.name,
        "years": [2026],
        "date_from": row.period_start.isoformat(),
        "date_to": row.period_end.isoformat(),
        "allow_transactions": True,
        "allow_sources": False,
        "iat": int(row.updated_at.timestamp()) if row.updated_at else int(datetime.utcnow().timestamp()),
    }
    assert dependencies._resolve_current_scope_payload(db_session, current) is not None

    stale = {**current, "allow_sources": True}
    assert dependencies._resolve_current_scope_payload(db_session, stale) is None

    row.is_active = False
    db_session.commit()
    assert dependencies._resolve_current_scope_payload(db_session, current) is None


def test_sync_source_scope_distinguishes_admin_empty_and_allowed(db_session):
    db_session.add_all(
        [
            Transaction(
                raw_message="first",
                transaction_date=datetime(2026, 1, 1),
                amount=-1,
                currency="UZS",
                source_chat_id=10,
                source_type="AUTO",
                transaction_type="DEBIT",
            ),
            Transaction(
                raw_message="second",
                transaction_date=datetime(2026, 1, 2),
                amount=-2,
                currency="UZS",
                source_chat_id=20,
                source_type="AUTO",
                transaction_type="DEBIT",
            ),
        ]
    )
    db_session.commit()

    admin_query = sync._apply_source_scope_to_model(
        db_session.query(Transaction), Transaction, {"role": "admin"}
    )
    assert admin_query.count() == 2

    empty_query = sync._apply_source_scope_to_model(
        db_session.query(Transaction), Transaction, {"role": "operator", "allowed_sources": []}
    )
    assert empty_query.count() == 0

    allowed_query = sync._apply_source_scope_to_model(
        db_session.query(Transaction), Transaction, {"role": "operator", "allowed_sources": [10]}
    )
    assert [row.source_chat_id for row in allowed_query.all()] == [10]


def test_manifest_cache_key_includes_identity_permissions_sources_and_forbidden_periods():
    scope_payload = {
        "scope_id": 1,
        "allow_transactions": True,
        "allow_sources": False,
        "years": [2026],
    }
    first = sync._manifest_cache_key(
        scope_payload,
        {"id": 1, "role": "operator", "permissions_version": 1, "allowed_sources": [10]},
        [],
    )
    second = sync._manifest_cache_key(
        scope_payload,
        {"id": 2, "role": "operator", "permissions_version": 2, "allowed_sources": [20]},
        [(datetime(2026, 2, 1).date(), datetime(2026, 2, 2).date())],
    )
    assert first != second
