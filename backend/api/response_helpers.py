"""Helpers for consistent API error payloads without breaking legacy clients."""
from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

from fastapi.responses import JSONResponse


def _default_error_code(status_code: int) -> str:
    if status_code == 400:
        return "bad_request"
    if status_code == 401:
        return "unauthorized"
    if status_code == 403:
        return "forbidden"
    if status_code == 404:
        return "not_found"
    if status_code == 409:
        return "conflict"
    if status_code == 422:
        return "validation_error"
    if status_code == 429:
        return "rate_limited"
    if status_code >= 500:
        return "internal_error"
    return "request_error"


def normalize_error_fields(
    *,
    status_code: int,
    detail: Any = None,
    error: Optional[str] = None,
    error_code: Optional[str] = None,
) -> Tuple[str, str]:
    resolved_code = str(error_code or "").strip()
    resolved_error: Optional[str] = error

    if isinstance(detail, dict):
        if not resolved_code:
            resolved_code = str(detail.get("error_code") or detail.get("error") or "").strip()
        if not resolved_error:
            candidate = (
                detail.get("message")
                or detail.get("detail")
                or detail.get("error_description")
                or detail.get("error")
            )
            if candidate:
                resolved_error = str(candidate)
    elif detail and not resolved_error:
        resolved_error = str(detail)

    if not resolved_code:
        resolved_code = _default_error_code(status_code)
    if not resolved_error:
        resolved_error = "Request failed" if status_code < 500 else "Internal server error"

    return resolved_error, resolved_code


def build_error_payload(
    *,
    status_code: int,
    detail: Any = None,
    error: Optional[str] = None,
    error_code: Optional[str] = None,
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    resolved_error, resolved_code = normalize_error_fields(
        status_code=status_code,
        detail=detail,
        error=error,
        error_code=error_code,
    )
    payload: Dict[str, Any] = {
        "ok": False,
        "error": resolved_error,
        "error_code": resolved_code,
        "detail": detail if detail is not None else resolved_error,
    }
    if extra:
        payload.update(extra)
    return payload


def error_response(
    *,
    status_code: int,
    detail: Any = None,
    error: Optional[str] = None,
    error_code: Optional[str] = None,
    extra: Optional[Dict[str, Any]] = None,
) -> JSONResponse:
    payload = build_error_payload(
        status_code=status_code,
        detail=detail,
        error=error,
        error_code=error_code,
        extra=extra,
    )
    return JSONResponse(status_code=status_code, content=payload)
