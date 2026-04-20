"""Shared fingerprint utilities for transaction deduplication."""
from __future__ import annotations

import hashlib
import os
from datetime import datetime
from decimal import Decimal
from typing import List, Optional


def _normalized_amount(amount: Optional[Decimal]) -> str:
    if amount is None:
        return "0.00"
    return str(abs(Decimal(str(amount))).quantize(Decimal("0.01")))


def _normalized_card(card_last4: Optional[str]) -> str:
    if not card_last4:
        return "0000"
    digits = "".join(ch for ch in str(card_last4) if ch.isdigit())
    if not digits:
        return "0000"
    return digits[-4:].zfill(4)


def _normalized_operator(operator_raw: Optional[str]) -> str:
    return (operator_raw or "").strip().lower()


def _bool_env(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _dedup_mode() -> str:
    mode = (os.getenv("FINGERPRINT_DEDUP_MODE", "dual") or "dual").strip().lower()
    if mode not in {"legacy", "dual", "v2"}:
        return "dual"
    return mode


def compute_fingerprint_v1(
    amount: Optional[Decimal],
    transaction_date: Optional[datetime],
    card_last4: Optional[str],
) -> str:
    """Legacy hash: amount + minute + card_last4."""
    amount_str = _normalized_amount(amount)
    date_str = transaction_date.strftime("%Y-%m-%d %H:%M") if transaction_date else ""
    card_str = _normalized_card(card_last4)
    data = f"{amount_str}|{date_str}|{card_str}"
    return hashlib.sha256(data.encode()).hexdigest()


def compute_fingerprint_v2(
    amount: Optional[Decimal],
    transaction_date: Optional[datetime],
    card_last4: Optional[str],
    operator_raw: Optional[str] = None,
    *,
    include_operator: bool = True,
    use_seconds: bool = True,
) -> str:
    """Extended hash: amount + datetime(+seconds) + card_last4 + operator(optional)."""
    amount_str = _normalized_amount(amount)
    if transaction_date:
        if use_seconds:
            date_str = transaction_date.strftime("%Y-%m-%d %H:%M:%S")
        else:
            date_str = transaction_date.strftime("%Y-%m-%d %H:%M")
    else:
        date_str = ""
    card_str = _normalized_card(card_last4)
    operator_part = _normalized_operator(operator_raw) if include_operator else ""
    data = f"{amount_str}|{date_str}|{card_str}|{operator_part}"
    return hashlib.sha256(data.encode()).hexdigest()


def compute_fingerprint_candidates(
    amount: Optional[Decimal],
    transaction_date: Optional[datetime],
    card_last4: Optional[str],
    operator_raw: Optional[str] = None,
    *,
    mode: Optional[str] = None,
) -> List[str]:
    """
    Return fingerprint candidates in priority order.

    - `legacy`: [v1]
    - `v2`: [v2]
    - `dual`: [v2, v1]
    """
    effective_mode = (mode or _dedup_mode()).lower()
    include_operator = _bool_env("FINGERPRINT_V2_INCLUDE_OPERATOR", True)
    use_seconds = _bool_env("FINGERPRINT_V2_USE_SECONDS", True)

    fp_v1 = compute_fingerprint_v1(amount, transaction_date, card_last4)
    fp_v2 = compute_fingerprint_v2(
        amount,
        transaction_date,
        card_last4,
        operator_raw=operator_raw,
        include_operator=include_operator,
        use_seconds=use_seconds,
    )

    if effective_mode == "legacy":
        return [fp_v1]
    if effective_mode == "v2":
        return [fp_v2]
    # dual default
    if fp_v2 == fp_v1:
        return [fp_v2]
    return [fp_v2, fp_v1]


def compute_fingerprint(
    amount: Optional[Decimal],
    transaction_date: Optional[datetime],
    card_last4: Optional[str],
    operator_raw: Optional[str] = None,
) -> str:
    """Compatibility wrapper: returns primary fingerprint for current mode."""
    return compute_fingerprint_candidates(
        amount=amount,
        transaction_date=transaction_date,
        card_last4=card_last4,
        operator_raw=operator_raw,
    )[0]
