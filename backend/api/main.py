"""
FastAPI Main Application
Entry point for REST API
"""
import time
from collections import defaultdict
from contextlib import asynccontextmanager, suppress
from typing import Any, Callable, Dict, Optional, Set
from urllib.parse import urlparse

from fastapi import FastAPI, Request, Response
from fastapi import HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.base import BaseHTTPMiddleware
import os
import logging
from dotenv import load_dotenv

load_dotenv()
from core.logging_config import setup_logging

setup_logging()

from services.root_access_config_service import (
    get_system_access_status,
    is_system_blocked,
    system_access_enforced,
    verify_system_access_token,
)
from services.auth_bot_service import verify_launch_session_token
from services.internal_api_key_service import is_valid_internal_api_key
from services.system_settings_service import get_settings
from api.response_helpers import error_response, build_error_payload

logger = logging.getLogger(__name__)
APP_VERSION = str(os.getenv("APP_VERSION", "1.4.0")).strip() or "1.4.0"

_launch_gate_cache_value: Optional[bool] = None
_launch_gate_cache_expires_at: float = 0.0
_launch_gate_cache_ttl_seconds = 7.0


def _env_launch_gate_enabled() -> bool:
    return str(os.getenv("LAUNCH_GATE_ENABLED", "false")).strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _get_launch_gate_enabled_runtime() -> bool:
    global _launch_gate_cache_value, _launch_gate_cache_expires_at

    now = time.monotonic()
    if _launch_gate_cache_value is not None and now < _launch_gate_cache_expires_at:
        return bool(_launch_gate_cache_value)

    try:
        from database.connection import SessionLocal
        from services.system_settings_service import get_settings_snapshot

        db = SessionLocal()
        try:
            snapshot = get_settings_snapshot(db)
            value = bool(snapshot.get("launch_gate_enabled", False))
        finally:
            db.close()
    except Exception:
        value = _env_launch_gate_enabled()

    _launch_gate_cache_value = bool(value)
    _launch_gate_cache_expires_at = now + _launch_gate_cache_ttl_seconds
    return bool(value)


# Rate limiting middleware
class RateLimitMiddleware(BaseHTTPMiddleware):
    """Simple in-memory rate limiter - 100 requests per minute per IP"""

    def __init__(self, app, requests_per_minute: int = 100):
        super().__init__(app)
        self.requests_per_minute = requests_per_minute
        self.sync_requests_per_minute = max(
            self.requests_per_minute,
            int(os.getenv("SYNC_RATE_LIMIT_PER_MIN", str(requests_per_minute))),
        )
        self.requests: dict = defaultdict(list)
        self._cleanup_counter = 0

    async def _check_redis_limit(self, client_ip: str, *, bucket: str, limit: int) -> Optional[bool]:
        minute_slot = int(time.time() // 60)
        key = f"rate_limit:{bucket}:{client_ip}:{minute_slot}"
        try:
            from services.auth_bot_service import get_redis
            redis = await get_redis()
            count = await redis.incr(key)
            if count == 1:
                await redis.expire(key, 65)
            return int(count) <= int(limit)
        except Exception:
            # Fallback to local memory limiter if Redis is unavailable.
            return None

    def _check_memory_limit(self, client_key: str, current_time: float, *, limit: int) -> bool:
        minute_ago = current_time - 60
        existing = self.requests.get(client_key, [])
        filtered = [req_time for req_time in existing if req_time > minute_ago]
        if not filtered:
            self.requests.pop(client_key, None)
            filtered = []

        self._cleanup_counter += 1
        if self._cleanup_counter % 100 == 0:
            cutoff = current_time - 120
            stale_ips = [
                ip for ip, times in self.requests.items()
                if not times or max(times) < cutoff
            ]
            for ip in stale_ips:
                self.requests.pop(ip, None)

        if len(filtered) >= int(limit):
            return False

        filtered.append(current_time)
        self.requests[client_key] = filtered
        return True

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        client_ip = request.client.host if request.client else "unknown"
        path = request.url.path or ""
        is_sync_path = path.startswith("/api/sync/")
        limit = self.sync_requests_per_minute if is_sync_path else self.requests_per_minute
        bucket = "sync" if is_sync_path else "default"
        client_key = f"{bucket}:{client_ip}"

        redis_allowed = await self._check_redis_limit(client_ip, bucket=bucket, limit=limit)
        if redis_allowed is False:
            return error_response(
                status_code=429,
                detail="Too many requests. Please try again later.",
                error_code="rate_limited",
            )
        if redis_allowed is True:
            return await call_next(request)

        current_time = time.time()
        if not self._check_memory_limit(client_key, current_time, limit=limit):
            return error_response(
                status_code=429,
                detail="Too many requests. Please try again later.",
                error_code="rate_limited",
            )
        return await call_next(request)


# Error handling middleware
class ErrorHandlingMiddleware(BaseHTTPMiddleware):
    """Catch unhandled exceptions and return generic error messages"""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        try:
            return await call_next(request)
        except Exception:
            # Log the actual error for debugging
            logger.exception("Unhandled API error")
            # Return generic error to client
            return error_response(
                status_code=500,
                detail="Internal server error",
                error_code="internal_error",
            )


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Structured request logging with latency and basic client metadata."""

    def __init__(self, app):
        super().__init__(app)
        self._skip_paths = {
            "/health",
            "/",
        }

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        start = time.perf_counter()
        path = request.url.path or ""
        response = await call_next(request)
        duration_ms = (time.perf_counter() - start) * 1000

        if path not in self._skip_paths:
            logger.info(
                "HTTP %s %s -> %s (%.2fms) ip=%s ua=%s",
                request.method,
                path,
                response.status_code,
                duration_ms,
                request.client.host if request.client and request.client.host else "unknown",
                request.headers.get("user-agent", "-"),
            )
        return response


class CSRFMiddleware(BaseHTTPMiddleware):
    """
    Lightweight CSRF origin protection for mutating browser requests.
    Requests without Origin header are allowed (Electron/native/CLI flows).
    """

    SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}

    def __init__(self, app):
        super().__init__(app)
        trusted_origins: Set[str] = set()
        raw_origins = str(os.getenv("CSRF_TRUSTED_ORIGINS", "")).strip()
        if raw_origins:
            for item in raw_origins.split(","):
                value = item.strip().rstrip("/")
                if value:
                    trusted_origins.add(value.lower())

        frontend_url = str(os.getenv("FRONTEND_URL", "http://localhost:5173")).strip().rstrip("/")
        if frontend_url:
            trusted_origins.add(frontend_url.lower())

        trusted_origins.update(
            {
                "http://localhost:5173",
                "http://127.0.0.1:5173",
                "http://localhost:3000",
                "http://127.0.0.1:3000",
                "app://.",
                "file://",
            }
        )
        self._trusted_origins = trusted_origins

    def _origin_allowed(self, origin: str, request: Request) -> bool:
        normalized = origin.strip().rstrip("/").lower()
        if not normalized:
            return True
        if normalized in self._trusted_origins:
            return True

        parsed = urlparse(normalized)
        if parsed.scheme in {"http", "https"} and parsed.hostname:
            req_host = request.url.hostname
            req_scheme = request.url.scheme
            req_port = request.url.port
            origin_port = parsed.port
            expected_port = req_port
            if expected_port is None:
                expected_port = 443 if req_scheme == "https" else 80
            if origin_port is None:
                origin_port = 443 if parsed.scheme == "https" else 80
            if parsed.hostname == req_host and parsed.scheme == req_scheme and origin_port == expected_port:
                return True

        return False

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        if request.method in self.SAFE_METHODS:
            return await call_next(request)
        if not request.url.path.startswith("/api/"):
            return await call_next(request)

        # Internal service requests are authenticated by internal API key(s).
        internal_header = request.headers.get("x-internal-api-key")
        if is_valid_internal_api_key(internal_header):
            return await call_next(request)
        # First-party desktop/web clients always send X-System-Access.
        # If it is valid, skip CSRF origin check to avoid false denies on
        # cross-origin deployment topologies (nip.io, direct IP, etc.).
        system_access_header = request.headers.get("x-system-access")
        ok, _token_id, _error = verify_system_access_token(system_access_header)
        if ok:
            return await call_next(request)

        origin = request.headers.get("origin")
        if not origin:
            return await call_next(request)
        if self._origin_allowed(origin, request):
            return await call_next(request)
        return error_response(
            status_code=403,
            detail="CSRF origin denied",
            error_code="csrf_denied",
        )


class ApiVersionHeaderMiddleware(BaseHTTPMiddleware):
    """Attach backend API version to every HTTP response."""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        response = await call_next(request)
        response.headers["X-API-Version"] = APP_VERSION
        return response


def _write_system_access_audit(
    *,
    action: str,
    success: bool,
    request: Request,
    details: Optional[Dict[str, Any]] = None,
) -> None:
    try:
        from database.connection import SessionLocal
        from services.access_control_service import write_audit_log
    except Exception:
        return

    db = SessionLocal()
    try:
        write_audit_log(
            db,
            action=action,
            success=success,
            ip_address=request.client.host if request.client and request.client.host else "unknown",
            details=details or {"path": str(request.url.path)},
        )
    except Exception:
        try:
            db.rollback()
        except Exception:
            pass
    finally:
        db.close()


class SystemAccessMiddleware(BaseHTTPMiddleware):
    """
    Enforce mandatory root-access config + X-System-Access token for API routes.
    """

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        path = request.url.path or ""
        if not path.startswith("/api/"):
            return await call_next(request)

        if not system_access_enforced():
            return await call_next(request)

        # SMS ingest endpoints authenticate via X-Mobile-Ingest-Key only.
        if path.startswith("/api/sms/") or path == "/api/sms":
            return await call_next(request)

        internal_header = request.headers.get("x-internal-api-key")
        if is_valid_internal_api_key(internal_header):
            request.state.system_access = {"ok": True, "token_id": "internal-service"}
            return await call_next(request)

        blocked, reason = is_system_blocked()
        if blocked:
            _write_system_access_audit(
                action="system_config_missing",
                success=False,
                request=request,
                details={"path": path, "reason": reason},
            )
            return JSONResponse(
                status_code=503,
                content=build_error_payload(
                    status_code=503,
                    detail="System access blocked: root access config is missing or invalid",
                    error_code="system_access_blocked",
                    extra={
                        "reason": reason,
                        "path": get_system_access_status().get("path"),
                    },
                ),
            )

        token = request.headers.get("x-system-access")
        ok, token_id, error = verify_system_access_token(token)
        if not ok:
            _write_system_access_audit(
                action="system_token_invalid",
                success=False,
                request=request,
                details={"path": path, "error": error},
            )
            return error_response(
                status_code=403,
                detail=error or "System access denied",
                error_code="system_access_denied",
            )

        request.state.system_access = {"ok": True, "token_id": token_id}
        return await call_next(request)


class LaunchSessionMiddleware(BaseHTTPMiddleware):
    """Require launch-session token for API access when launch password is configured."""

    EXEMPT_PATHS = {
        "/api/auth/login",
        "/api/auth/login/2fa",
        "/api/security/app/verify-launch",
        "/api/security/app/launch-status",
        "/api/internal/app/set-launch-password",
        "/health",
        "/",
    }

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        launch_gate_enabled = _get_launch_gate_enabled_runtime()
        if not launch_gate_enabled:
            return await call_next(request)

        path = request.url.path or ""
        if not path.startswith("/api/"):
            return await call_next(request)
        if path.startswith("/api/sms/") or path == "/api/sms":
            return await call_next(request)
        if path in self.EXEMPT_PATHS:
            return await call_next(request)
        if path.startswith("/api/docs") or path.startswith("/api/openapi"):
            return await call_next(request)
        internal_header = request.headers.get("x-internal-api-key")
        if is_valid_internal_api_key(internal_header):
            return await call_next(request)

        try:
            from database.connection import get_db
            from database.models import AppLaunchConfig
        except Exception:
            return await call_next(request)

        with get_db() as db:
            launch_cfg = db.get(AppLaunchConfig, 1)
            if launch_cfg is None:
                return await call_next(request)

            token = request.headers.get("x-launch-session")
            if not token:
                return error_response(
                    status_code=403,
                    detail={"error": "launch_required"},
                    error_code="launch_required",
                )

            payload = verify_launch_session_token(token)
            if not payload:
                return error_response(
                    status_code=403,
                    detail={"error": "launch_expired"},
                    error_code="launch_expired",
                )
        return await call_next(request)


# Create FastAPI app
app = FastAPI(
    title="Uzbek Receipt Parser API",
    description="High-load financial transaction parsing system for Uzbek banking receipts",
    version=APP_VERSION,
)

# Add rate limiting middleware
app.add_middleware(
    RateLimitMiddleware,
    requests_per_minute=max(10, int(os.getenv("RATE_LIMIT_PER_MINUTE", "200"))),
)

# Add error handling middleware
app.add_middleware(ErrorHandlingMiddleware)

# Add request logging middleware
app.add_middleware(RequestLoggingMiddleware)

# Add CSRF origin checks for mutating API requests
app.add_middleware(CSRFMiddleware)

# Mandatory root-config + token gate for all /api routes
app.add_middleware(SystemAccessMiddleware)

# Launch password gate (if configured)
app.add_middleware(LaunchSessionMiddleware)

# Expose backend version in every response (used by frontend mismatch detector)
app.add_middleware(ApiVersionHeaderMiddleware)

# CORS configuration - use environment variable or sensible defaults
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:5173")
CORS_ORIGINS = os.getenv("CORS_ORIGINS", "").split(",") if os.getenv("CORS_ORIGINS") else []

# Default allowed origins — расширяем для dev/desktop, чтобы избежать ошибок preflight
allowed_origins = [
    FRONTEND_URL,
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:3000",
    "app://.",
    "null",
    "file://",
]

# Add any additional origins from environment
if CORS_ORIGINS:
    allowed_origins.extend(
        [origin.strip() for origin in CORS_ORIGINS if origin.strip() and origin.strip() != "*"]
    )
allowed_origins = list(dict.fromkeys(allowed_origins))

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    return error_response(status_code=int(exc.status_code), detail=exc.detail)


@app.exception_handler(StarletteHTTPException)
async def starlette_http_exception_handler(request: Request, exc: StarletteHTTPException):
    return error_response(status_code=int(exc.status_code), detail=exc.detail)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    return error_response(
        status_code=422,
        detail=exc.errors(),
        error="Validation failed",
        error_code="validation_error",
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager for startup and shutdown"""
    # Startup
    logger.info("Starting Uzbek Receipt Parser API...")

    from database.connection import init_db, SessionLocal
    from database.models import TgHistoryCursor
    from services.ai_agent import get_agent_scheduler_service
    from services.history_loader import init_history_loader_service
    from services.sync_deletion_service import register_sync_deletion_listeners
    from services.telegram_tdlib_manager import get_tdlib_manager
    from services.tg_auto_monitor_service import init_auto_monitor_service
    import asyncio

    async def _safe_task(coro, name: str):
        try:
            await coro
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Background task '%s' crashed", name)

    register_sync_deletion_listeners()
    init_db()
    logger.info("Database initialized")
    try:
        db = SessionLocal()
        try:
            get_settings(db)
        finally:
            db.close()
    except Exception:
        logger.exception("Failed to initialize system_settings seed row")

    # Start TDLib auto-monitor in background
    manager = get_tdlib_manager()
    agent_scheduler = get_agent_scheduler_service()
    monitor_service = init_auto_monitor_service(manager=manager, session_factory=SessionLocal)
    history_loader = init_history_loader_service(manager=manager, session_factory=SessionLocal)
    monitor_task = asyncio.create_task(
        _safe_task(monitor_service.start(), "tg-auto-monitor"),
        name="tg-auto-monitor",
    )
    try:
        with SessionLocal() as db:
            from sqlalchemy import inspect

            inspector = inspect(db.get_bind())
            if inspector.has_table(TgHistoryCursor.__tablename__):
                resume_rows = (
                    db.query(TgHistoryCursor)
                    .filter(TgHistoryCursor.status.in_(["running"]))
                    .all()
                )
            else:
                resume_rows = []
        for row in resume_rows:
            await history_loader.start_load(chat_id=int(row.chat_id), restart=False)
    except Exception:
        logger.exception("Failed to resume tg history loader tasks on startup")
    try:
        agent_scheduler.start()
    except Exception:
        logger.exception("Failed to start AI agent scheduler")

    yield

    # Shutdown
    logger.info("Shutting down API...")
    try:
        await monitor_service.stop()
    except Exception:
        logger.debug("Failed to stop monitor_service cleanly", exc_info=True)
    try:
        agent_scheduler.stop()
    except Exception:
        logger.debug("Failed to stop AI agent scheduler cleanly", exc_info=True)
    monitor_task.cancel()
    with suppress(asyncio.CancelledError, Exception):
        await monitor_task
    try:
        manager.stop()
    except Exception:
        logger.debug("Failed to stop TDLib manager cleanly", exc_info=True)
    try:
        from services.auth_bot_service import close_redis_pool as close_auth_bot_redis_pool
        await close_auth_bot_redis_pool()
    except Exception:
        pass
    try:
        from services.auth_service import close_redis_pool as close_auth_redis_pool
        await close_auth_redis_pool()
    except Exception:
        pass


# Update app with lifespan
app.router.lifespan_context = lifespan


@app.get("/")
async def root():
    """Health check endpoint"""
    return {
        "status": "ok",
        "service": "Uzbek Receipt Parser",
        "version": APP_VERSION,
    }


@app.get("/mini-app", response_class=HTMLResponse)
@app.get("/mini-app/", response_class=HTMLResponse)
async def mini_app_page():
    """Built-in Telegram Mini App page with QR camera scanner."""
    html = """<!doctype html>
<html lang="ru">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>PARCER 2.0 Mini App</title>
  <script src="https://telegram.org/js/telegram-web-app.js"></script>
  <style>
    :root { color-scheme: dark light; }
    body {
      margin: 0;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      background: var(--tg-theme-bg-color, #0f1115);
      color: var(--tg-theme-text-color, #f3f4f6);
      min-height: 100vh;
      display: flex;
      align-items: center;
      justify-content: center;
      padding: 16px;
      box-sizing: border-box;
    }
    .card {
      width: min(100%, 460px);
      border: 1px solid rgba(127, 127, 127, 0.25);
      background: var(--tg-theme-secondary-bg-color, #171a21);
      border-radius: 16px;
      padding: 20px;
      box-sizing: border-box;
    }
    .title { margin: 0 0 8px; font-size: 20px; }
    .sub { margin: 0 0 16px; font-size: 14px; opacity: .75; }
    .status {
      border-radius: 12px;
      padding: 12px 14px;
      font-size: 14px;
      line-height: 1.4;
      background: rgba(99, 102, 241, 0.12);
      border: 1px solid rgba(99, 102, 241, 0.35);
      word-break: break-word;
      margin-bottom: 12px;
    }
    .status.ok {
      background: rgba(16, 185, 129, 0.12);
      border-color: rgba(16, 185, 129, 0.35);
    }
    .status.err {
      background: rgba(239, 68, 68, 0.12);
      border-color: rgba(239, 68, 68, 0.35);
    }
    .actions {
      display: grid;
      grid-template-columns: 1fr;
      gap: 10px;
      margin-top: 6px;
    }
    button {
      border: 1px solid rgba(127, 127, 127, 0.3);
      background: rgba(99, 102, 241, 0.2);
      color: var(--tg-theme-text-color, #f3f4f6);
      border-radius: 12px;
      padding: 11px 12px;
      font-size: 14px;
      cursor: pointer;
    }
    button.secondary {
      background: rgba(127, 127, 127, 0.14);
    }
    button:disabled {
      opacity: .5;
      cursor: not-allowed;
    }
    .manual {
      margin-top: 12px;
      display: grid;
      gap: 8px;
    }
    .manual label {
      font-size: 12px;
      opacity: .8;
    }
    .manual input {
      width: 100%;
      box-sizing: border-box;
      border: 1px solid rgba(127, 127, 127, 0.35);
      border-radius: 10px;
      padding: 10px 11px;
      font-size: 13px;
      background: rgba(10, 10, 10, 0.25);
      color: var(--tg-theme-text-color, #f3f4f6);
      outline: none;
    }
  </style>
</head>
<body>
  <div class="card">
    <h1 class="title">PARCER 2.0</h1>
    <p class="sub">Подтверждение входа через Telegram Mini App</p>
    <div id="status" class="status">Инициализация...</div>
    <div class="actions">
      <button id="scanBtn" type="button">Сканировать QR камерой</button>
      <button id="scanRetryBtn" class="secondary" type="button" style="display:none;">Сканировать снова</button>
    </div>
    <div class="manual">
      <label for="manualCode">Если камера недоступна: вставьте текст/ссылку QR</label>
      <input id="manualCode" type="text" placeholder="https://t.me/...startapp=..." />
      <button id="manualConfirmBtn" class="secondary" type="button">Подтвердить по вставленному коду</button>
    </div>
  </div>
  <script>
    const statusEl = document.getElementById('status');
    const scanBtn = document.getElementById('scanBtn');
    const scanRetryBtn = document.getElementById('scanRetryBtn');
    const manualCodeEl = document.getElementById('manualCode');
    const manualConfirmBtn = document.getElementById('manualConfirmBtn');
    let busy = false;

    function setStatus(text, cls) {
      statusEl.textContent = text;
      statusEl.className = `status ${cls || ''}`.trim();
    }

    function setBusy(value) {
      busy = Boolean(value);
      scanBtn.disabled = busy;
      scanRetryBtn.disabled = busy;
      manualConfirmBtn.disabled = busy;
    }

    function parseStartParam(value) {
      if (!value || typeof value !== 'string') return null;
      const token = value.trim();
      // Strict token format only: "<session_id>__<secret>"
      // Prevent parsing entire URLs as raw tokens.
      const match = token.match(/^([A-Za-z0-9_-]{8,})__([A-Za-z0-9_-]{16,})$/);
      if (!match) return null;
      return {
        sessionId: match[1],
        secret: match[2],
      };
    }

    function parseQrPayload(value) {
      if (!value || typeof value !== 'string') return null;
      const raw = value.trim();
      if (!raw) return null;

      if (raw.startsWith('qr://')) {
        const body = raw.slice('qr://'.length);
        const fromQrSchema = parseStartParam(body.replace('/', '__'));
        if (fromQrSchema) return fromQrSchema;
      }

      const match = raw.match(/[?&](startapp|start)=([^&\\s]+)/i);
      if (match && match[2]) {
        const fromQuery = parseStartParam(decodeURIComponent(match[2]));
        if (fromQuery) return fromQuery;
      }

      try {
        const normalized = raw.startsWith('tg://')
          ? raw.replace('tg://', 'https://t.me/')
          : raw;
        const url = new URL(normalized);
        const startToken = url.searchParams.get('startapp') || url.searchParams.get('start');
        const parsed = parseStartParam(startToken || '');
        if (parsed) return parsed;
      } catch (_) {}

      const direct = parseStartParam(raw);
      if (direct) return direct;

      return null;
    }

    async function confirmQrLogin(sessionId, secret, tg) {
      if (!sessionId || !secret) {
        setStatus('QR не распознан. Сканируйте код входа из PARCER 2.0.', 'err');
        return;
      }
      if (!tg.initData) {
        setStatus('Не хватает Telegram initData. Откройте Mini App из Telegram.', 'err');
        return;
      }

      setBusy(true);
      setStatus('Подтверждаем вход...', '');
      try {
        const resp = await fetch('/api/auth/qr/confirm', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            session_id: sessionId,
            secret: secret,
            init_data: tg.initData,
          }),
        });
        if (!resp.ok) {
          let detail = `Ошибка ${resp.status}`;
          try {
            const data = await resp.json();
            if (data && data.detail) {
              detail = typeof data.detail === 'string' ? data.detail : JSON.stringify(data.detail);
            }
          } catch (_) {}
          if (resp.status === 404) {
            detail = 'QR-сессия истекла. Обновите QR-код на экране входа PARCER 2.0 и отсканируйте снова.';
          } else if (resp.status === 401) {
            detail = 'QR-код невалиден. Сгенерируйте новый QR в приложении и сканируйте заново.';
          }
          setStatus(detail, 'err');
          scanRetryBtn.style.display = '';
          return;
        }
        setStatus('Вход подтвержден. Окно закроется автоматически.', 'ok');
        setTimeout(() => {
          try { tg.close(); } catch (_) {}
        }, 1200);
      } catch (_) {
        setStatus('Не удалось связаться с сервером.', 'err');
        scanRetryBtn.style.display = '';
      } finally {
        setBusy(false);
      }
    }

    function startScanner(tg) {
      if (typeof tg.showScanQrPopup !== 'function') {
        setStatus('Сканер камеры не поддерживается в этой версии Telegram. Вставьте ссылку QR вручную.', 'err');
        return;
      }
      setStatus('Откроется камера. Наведите на QR-код входа из PARCER 2.0.', '');
      try {
        tg.showScanQrPopup({ text: 'Сканируйте QR-код входа из PARCER 2.0' }, (scannedText) => {
          try { if (typeof tg.closeScanQrPopup === 'function') tg.closeScanQrPopup(); } catch (_) {}
          const parsed = parseQrPayload(scannedText);
          confirmQrLogin(parsed && parsed.sessionId, parsed && parsed.secret, tg);
          return true;
        });
      } catch (_) {
        setStatus('Не удалось открыть камеру. Попробуйте еще раз или вставьте код вручную.', 'err');
      }
    }

    function setupManualConfirm(tg) {
      manualConfirmBtn.addEventListener('click', () => {
        const parsed = parseQrPayload(manualCodeEl.value || '');
        confirmQrLogin(parsed && parsed.sessionId, parsed && parsed.secret, tg);
      });
    }

    async function run() {
      const tg = window.Telegram && window.Telegram.WebApp;
      if (!tg) {
        setStatus('Откройте страницу через Telegram.', 'err');
        return;
      }
      tg.ready();
      try { tg.expand(); } catch (_) {}

      scanBtn.addEventListener('click', () => startScanner(tg));
      scanRetryBtn.addEventListener('click', () => startScanner(tg));
      setupManualConfirm(tg);

      const startParam = tg.initDataUnsafe && tg.initDataUnsafe.start_param;
      const fromStart = parseStartParam(startParam || '');
      if (fromStart && fromStart.sessionId && fromStart.secret) {
        await confirmQrLogin(fromStart.sessionId, fromStart.secret, tg);
        return;
      }

      setStatus('Нажмите "Сканировать QR камерой" и отсканируйте код входа с экрана PARCER 2.0.', '');
    }

    run();
  </script>
</body>
</html>"""
    return HTMLResponse(
        content=html,
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "Pragma": "no-cache",
            "Expires": "0",
        },
    )


@app.get("/health")
async def health_check():
    """Detailed health check"""
    from database.connection import engine
    from sqlalchemy import text

    try:
        # Test database connection
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        db_status = "connected"
    except Exception:
        db_status = "error"

    return {
        "status": "healthy" if db_status == "connected" else "degraded",
        "database": db_status,
        "version": APP_VERSION,
    }


# Import and register routes
from api.routes import (
    admin,
    ai_agent,
    analytics,
    audit,
    auth,
    automation,
    logs,
    periods,
    reconciliation,
    reference,
    security,
    sms,
    sync,
    system_settings,
    telegram_client,
    transactions,
    two_factor,
    userbot,
)

app.include_router(auth.router, tags=["Authentication"])
app.include_router(admin.router, tags=["Admin"])
app.include_router(ai_agent.router, tags=["Agent"])
app.include_router(transactions.router, prefix="/api/transactions", tags=["Transactions"])
app.include_router(analytics.router, prefix="/api/analytics", tags=["Analytics"])
app.include_router(reference.router, prefix="/api/reference", tags=["Reference"])
app.include_router(logs.router, prefix="/api/logs", tags=["Logs"])
app.include_router(automation.router, tags=["Automation"])
app.include_router(reconciliation.router, tags=["Automation"])
app.include_router(userbot.router, tags=["Userbot"])
app.include_router(telegram_client.router, tags=["Telegram"])
app.include_router(telegram_client.ws_router, tags=["Telegram"])
app.include_router(security.router, tags=["Security"])
app.include_router(security.internal_router, tags=["SecurityInternal"])
app.include_router(periods.router, tags=["Periods"])
app.include_router(system_settings.router, tags=["SystemSettings"])
app.include_router(two_factor.router, tags=["TwoFactor"])
app.include_router(audit.router, tags=["Audit"])
app.include_router(sync.router, tags=["Sync"])
app.include_router(sms.router, tags=["SMS"])
