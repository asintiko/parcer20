"""
Telegram TDLib client API
- Auth state machine (phone/code/password)
- Bot-only chat listing with hidden toggle
- Messages read/send + PDF docs
- Simple WebSocket heartbeat
"""
import asyncio
import json
import logging
import os
import tempfile
import shutil
from contextlib import suppress
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Set

from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect, UploadFile, File, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from database.connection import get_db_session, SessionLocal
from database.models import (
    ChatPassword,
    MonitoredBotChat,
    ReceiptProcessingTask,
    TgChatMessage,
    Transaction,
)
from services.telegram_tdlib_manager import (
    TDLibUnavailableError,
    TelegramTDLibManager,
    get_tdlib_manager,
)
from services.history_loader import get_history_loader_service, init_history_loader_service
from services.tg_auto_monitor_service import get_auto_monitor_service, init_auto_monitor_service
from services.message_utils import (
    RECEIPT_KEYWORDS_LOWER,
    MIN_RECEIPT_TEXT_LEN,
    looks_like_receipt,
    format_tdlib_message,
    build_task_data_from_message,
)
from workers.celery_worker import queue_receipt_task
from api.dependencies import get_allowed_sources_for_user, get_current_user, require_sources_scope, require_tab_access
from services.auth_service import verify_jwt_token
from services.access_control_service import hash_password, verify_password
from services.auth_bot_service import create_chat_access_token, verify_chat_access_token
from services.auth_bot_service import register_active_session, get_redis, AUTH_EVENT_CHANNEL

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/tg",
    tags=["telegram"],
    dependencies=[Depends(require_tab_access("userbot")), Depends(require_sources_scope)],
)
ws_router = APIRouter(prefix="/api/tg", tags=["telegram-ws"])
CHAT_PASSWORD_LOCKOUT_MINUTES = int(os.getenv("CHAT_PASSWORD_LOCKOUT_MINUTES", "15"))
CHAT_PASSWORD_MAX_ATTEMPTS = int(os.getenv("CHAT_PASSWORD_MAX_ATTEMPTS", "5"))
WS_HEARTBEAT_SECONDS = max(3, int(os.getenv("TG_WS_HEARTBEAT_SECONDS", "10")))

_tg_ws_clients: Set[WebSocket] = set()
_tg_ws_lock = asyncio.Lock()


async def _broadcast_tg_event(payload: Dict[str, Any]) -> None:
    stale: List[WebSocket] = []
    async with _tg_ws_lock:
        for ws in list(_tg_ws_clients):
            try:
                await ws.send_json(payload)
            except Exception:
                stale.append(ws)
        for ws in stale:
            _tg_ws_clients.discard(ws)


_settings_listener_task: Optional[asyncio.Task] = None


async def _settings_event_listener() -> None:
    """Background task that subscribes to Redis auth events and relays settings changes to WS clients."""
    while True:
        try:
            redis_client = await get_redis()
            pubsub = redis_client.pubsub()
            await pubsub.subscribe(AUTH_EVENT_CHANNEL)
            async for message in pubsub.listen():
                if message["type"] != "message":
                    continue
                try:
                    data = json.loads(message["data"])
                except (json.JSONDecodeError, TypeError):
                    continue
                event_name = str(data.get("event") or "")
                if event_name == "settings_changed":
                    await _broadcast_tg_event({
                        "type": "settings-changed",
                        "payload": data.get("payload", {}),
                        "ts": datetime.utcnow().isoformat() + "Z",
                    })
                elif event_name == "locked_periods_changed":
                    await _broadcast_tg_event({
                        "type": "locked-periods-changed",
                        "payload": data.get("payload", {}),
                        "ts": datetime.utcnow().isoformat() + "Z",
                    })
                elif event_name == "sync_update":
                    await _broadcast_tg_event({
                        "type": "sync-update",
                        "payload": data.get("payload", {}),
                        "ts": datetime.utcnow().isoformat() + "Z",
                    })
        except asyncio.CancelledError:
            return
        except Exception:
            await asyncio.sleep(5)  # retry after transient errors


def _ensure_settings_listener() -> None:
    """Start the settings event listener if not already running."""
    global _settings_listener_task
    if _settings_listener_task is None or _settings_listener_task.done():
        _settings_listener_task = asyncio.ensure_future(_settings_event_listener())


class UserSummary(BaseModel):
    id: Optional[int] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    username: Optional[str] = None
    phone_number: Optional[str] = None


class AuthStatusResponse(BaseModel):
    state: str
    raw_state: str
    is_authorized: bool
    phone_number: Optional[str] = None
    user: Optional[UserSummary] = None
    code_type: Optional[str] = None
    code_timeout: Optional[int] = None


class PhoneRequest(BaseModel):
    phone_number: str = Field(..., description="International phone number format")


class CodeRequest(BaseModel):
    code: str = Field(..., description="Login code from Telegram")
    phone_number: Optional[str] = Field(None, description="Phone number to re-send setAuthNumber when TDLib lost it")


class PasswordRequest(BaseModel):
    password: str = Field(..., description="2FA password if enabled")


class ChatMessage(BaseModel):
    id: Optional[int] = None
    date: Optional[str] = None
    is_outgoing: bool = False
    sender_id: Optional[Any] = None
    text: Optional[str] = None
    document: Optional[Dict[str, Any]] = None
    photo: Optional[Dict[str, Any]] = None


class ChatItem(BaseModel):
    chat_id: int
    title: str
    username: Optional[str] = None
    chat_type: str  # 'bot', 'user', 'group', 'supergroup', 'channel'
    member_count: Optional[int] = None  # For groups and channels
    is_hidden: bool = False
    is_protected: bool = False
    is_monitored: Optional[bool] = False
    monitor_enabled: Optional[bool] = False
    last_message: Optional[ChatMessage] = None
    last_processed_message_id: Optional[int] = None
    last_processed_message_date: Optional[str] = None
    latest_message_id: Optional[int] = None
    latest_message_date: Optional[str] = None
    backlog_lag_messages: Optional[int] = None
    backlog_state: Optional[str] = None


class ChatListResponse(BaseModel):
    total: int
    items: List[ChatItem]


class MonitoredChat(BaseModel):
    chat_id: int
    enabled: bool
    last_processed_message_id: int
    last_error: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    last_processed_message_date: Optional[str] = None
    latest_message_id: Optional[int] = None
    latest_message_date: Optional[str] = None
    backlog_lag_messages: Optional[int] = None
    backlog_state: Optional[str] = None


class MonitorUpdateRequest(BaseModel):
    enabled: bool
    start_from_latest: bool = False
    filter_mode: str = Field(default="all", pattern="^(all|whitelist|blacklist)$")
    filter_keywords: Optional[List[str]] = None


class MonitorStatusResponse(BaseModel):
    running: bool
    queue_size: int
    workers: int


class MessageListResponse(BaseModel):
    total: int
    items: List[ChatMessage]


class HistoryLoadRequest(BaseModel):
    max_messages: Optional[int] = Field(default=None, ge=1)
    restart: bool = False
    date_from: Optional[str] = Field(default=None, description="Inclusive start date (DD/MM/YYYY or ISO)")
    date_to: Optional[str] = Field(default=None, description="Inclusive end date (DD/MM/YYYY or ISO)")
    exclude_from: Optional[str] = Field(default=None, description="Optional exclusion period start")
    exclude_to: Optional[str] = Field(default=None, description="Optional exclusion period end")


class HistoryLoadStatusResponse(BaseModel):
    chat_id: int
    status: str
    cursor_message_id: int
    loaded_count: int
    error: Optional[str] = None
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    running: bool = False


class HistoryLoadStartResponse(BaseModel):
    accepted: bool
    status: HistoryLoadStatusResponse


class TelegramOverviewResponse(BaseModel):
    auth: AuthStatusResponse
    chats: ChatListResponse
    monitor: MonitorStatusResponse
    server_time: str


class SendMessageRequest(BaseModel):
    text: str


class ProcessResult(BaseModel):
    chat_id: int
    message_id: int
    task_id: Optional[str] = None
    status: str
    transaction_id: Optional[int] = None
    error: Optional[str] = None


class BatchProcessRequest(BaseModel):
    message_ids: List[int]


class HideChatPayload(BaseModel):
    hidden: bool


class HideChatResponse(BaseModel):
    chat_id: int
    hidden: bool
    updated_at: str


class ChatPasswordSetRequest(BaseModel):
    password: str = Field(..., min_length=1, max_length=500)


class ChatPasswordVerifyRequest(BaseModel):
    password: str = Field(..., min_length=1, max_length=500)


class ChatPasswordVerifyResponse(BaseModel):
    verified: bool
    session_token: Optional[str] = None
    expires_in: Optional[int] = None
    attempts_left: Optional[int] = None
    locked: Optional[bool] = None
    locked_until: Optional[str] = None


def _build_task_data_from_message(chat_id: int, message_id: int, message: Dict[str, Any]) -> Dict[str, Any]:
    """Thin wrapper around shared ``build_task_data_from_message``."""
    return build_task_data_from_message(chat_id, message_id, message)


def tdlib_manager_dep() -> TelegramTDLibManager:
    return get_tdlib_manager()


def _chat_password_status(chat_pwd: ChatPassword) -> Dict[str, Any]:
    now = datetime.utcnow()
    locked = bool(chat_pwd.locked_until and chat_pwd.locked_until > now)
    return {
        "locked": locked,
        "locked_until": chat_pwd.locked_until.isoformat() if locked and chat_pwd.locked_until else None,
    }


async def require_chat_access(
    chat_id: int,
    request: Request,
    db: Session = Depends(get_db_session),
    current_user: dict = Depends(get_current_user),
) -> None:
    _ = current_user
    chat_pwd = db.get(ChatPassword, chat_id)
    if not chat_pwd:
        return

    status = _chat_password_status(chat_pwd)
    if status["locked"]:
        raise HTTPException(status_code=423, detail={"locked": True, "locked_until": status["locked_until"]})

    token = request.headers.get("X-Chat-Access") or request.headers.get("x-chat-access")
    if not token:
        raise HTTPException(status_code=403, detail={"error": "chat_locked", "chat_id": chat_id})

    payload = verify_chat_access_token(token)
    if not payload or int(payload.get("chat_id") or 0) != int(chat_id):
        raise HTTPException(status_code=403, detail={"error": "chat_locked", "chat_id": chat_id})


def _ensure_chat_allowed(chat_id: int, current_user: Optional[dict]) -> None:
    allowed_sources = get_allowed_sources_for_user(current_user)
    if allowed_sources is None:
        return
    if int(chat_id) not in allowed_sources:
        raise HTTPException(status_code=403, detail="chat_forbidden")


def _ensure_toggle_allowed(current_user: Optional[dict]) -> None:
    role = str((current_user or {}).get("role") or "").lower()
    if role == "admin":
        return
    if bool((current_user or {}).get("can_toggle_sources")):
        return
    raise HTTPException(status_code=403, detail="source_toggle_forbidden")


def _format_message(data: Optional[Dict[str, Any]]) -> Optional[ChatMessage]:
    """Wrap shared ``format_tdlib_message`` into the local Pydantic model."""
    d = format_tdlib_message(data)
    if d is None:
        return None
    return ChatMessage(**d)


def _map_auth_state(raw: Dict[str, Any]) -> AuthStatusResponse:
    user_data = raw.get("user")
    code_info = raw.get("code_info") or {}
    return AuthStatusResponse(
        state=raw.get("state", "unknown"),
        raw_state=raw.get("raw_state", ""),
        is_authorized=raw.get("is_authorized", False),
        phone_number=raw.get("phone_number"),
        user=UserSummary(**user_data) if user_data else None,
        code_type=(code_info.get("type") or {}).get("@type"),
        code_timeout=code_info.get("timeout"),
    )


def _parse_iso_datetime(value: Optional[str]) -> Optional[datetime]:
    if not value or not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except Exception:
        return None


def _format_optional_dt(value: Optional[datetime]) -> Optional[str]:
    if not isinstance(value, datetime):
        return None
    return value.isoformat().replace("+00:00", "Z") if value.tzinfo else value.isoformat()


def _build_monitor_backlog_payload(
    monitor: Optional[MonitoredBotChat],
    *,
    latest_message_id: Optional[int] = None,
    latest_message_date: Optional[datetime] = None,
    last_processed_message_date: Optional[datetime] = None,
) -> Dict[str, Any]:
    if not monitor:
        return {
            "last_processed_message_id": None,
            "last_processed_message_date": None,
            "latest_message_id": latest_message_id,
            "latest_message_date": _format_optional_dt(latest_message_date),
            "backlog_lag_messages": None,
            "backlog_state": None,
        }

    processed_id = int(monitor.last_processed_message_id or 0)
    latest_id = int(latest_message_id or 0) if latest_message_id is not None else None
    backlog_lag_messages = None
    if latest_id is not None:
        backlog_lag_messages = max(int(latest_id) - processed_id, 0)

    backlog_state = "healthy"
    if latest_id is not None and latest_id > processed_id:
        backlog_state = "lagging"
        reference_dt = latest_message_date or monitor.last_realtime_seen_at
        if monitor.last_error:
            backlog_state = "error"
        elif reference_dt and monitor.updated_at and (reference_dt - monitor.updated_at).total_seconds() > 900:
            backlog_state = "stalled"
        elif (
            latest_message_date
            and last_processed_message_date
            and (latest_message_date - last_processed_message_date).total_seconds() > 3600
        ):
            backlog_state = "stalled"

    return {
        "last_processed_message_id": processed_id,
        "last_processed_message_date": _format_optional_dt(last_processed_message_date),
        "latest_message_id": latest_id,
        "latest_message_date": _format_optional_dt(latest_message_date),
        "backlog_lag_messages": backlog_lag_messages,
        "backlog_state": backlog_state,
    }


def _load_monitor_cache_snapshot(
    db: Session,
    chat_ids: List[int],
    monitored_rows: List[MonitoredBotChat],
) -> tuple[Dict[int, Optional[datetime]], Dict[int, Dict[str, Any]]]:
    if not chat_ids:
        return {}, {}

    from sqlalchemy import func as sa_func, tuple_

    processed_pairs = [
        (int(row.chat_id), int(row.last_processed_message_id))
        for row in monitored_rows
        if int(row.last_processed_message_id or 0) > 0
    ]
    processed_dates: Dict[int, Optional[datetime]] = {}
    if processed_pairs:
        processed_rows = (
            db.query(TgChatMessage.chat_id, TgChatMessage.message_date)
            .filter(tuple_(TgChatMessage.chat_id, TgChatMessage.message_id).in_(processed_pairs))
            .all()
        )
        processed_dates = {
            int(chat_id): message_date
            for chat_id, message_date in processed_rows
        }

    latest_rows = (
        db.query(
            TgChatMessage.chat_id,
            sa_func.max(TgChatMessage.message_id).label("latest_message_id"),
            sa_func.max(TgChatMessage.message_date).label("latest_message_date"),
        )
        .filter(TgChatMessage.chat_id.in_(chat_ids))
        .group_by(TgChatMessage.chat_id)
        .all()
    )
    latest_by_chat = {
        int(chat_id): {
            "latest_message_id": int(latest_message_id) if latest_message_id is not None else None,
            "latest_message_date": latest_message_date,
        }
        for chat_id, latest_message_id, latest_message_date in latest_rows
    }
    return processed_dates, latest_by_chat


_ws_hooks_registered = False
_ws_hooks_lock = asyncio.Lock()


async def _ensure_realtime_hooks(manager: TelegramTDLibManager) -> None:
    global _ws_hooks_registered
    if _ws_hooks_registered:
        return
    async with _ws_hooks_lock:
        if _ws_hooks_registered:
            return

        async def _on_new_message(message: Dict[str, Any]) -> None:
            formatted = _format_message(message)
            await _broadcast_tg_event(
                {
                    "type": "new-message",
                    "payload": formatted.dict() if formatted else message,
                    "ts": datetime.utcnow().isoformat() + "Z",
                }
            )

        manager.add_new_message_handler(_on_new_message)

        history_loader = get_history_loader_service() or init_history_loader_service(
            manager=manager,
            session_factory=SessionLocal,
        )
        history_loader.add_event_handler(_broadcast_tg_event)
        _ws_hooks_registered = True


@router.get("/status", response_model=AuthStatusResponse)
async def get_status(
    manager: TelegramTDLibManager = Depends(tdlib_manager_dep),
    current_user: dict = Depends(get_current_user),
) -> AuthStatusResponse:
    try:
        state = await manager.get_auth_state()
    except TDLibUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    return _map_auth_state(state)


@router.get("/monitors", response_model=List[MonitoredChat])
async def list_monitors(
    db: Session = Depends(get_db_session),
    current_user: dict = Depends(get_current_user),
):
    rows = db.query(MonitoredBotChat).order_by(MonitoredBotChat.chat_id.asc()).all()
    allowed_sources = get_allowed_sources_for_user(current_user)
    if allowed_sources is not None:
        rows = [row for row in rows if int(row.chat_id) in allowed_sources]
    chat_ids = [int(row.chat_id) for row in rows]
    processed_dates, latest_by_chat = _load_monitor_cache_snapshot(db, chat_ids, rows)
    return [
        MonitoredChat(
            chat_id=row.chat_id,
            enabled=row.enabled,
            last_processed_message_id=row.last_processed_message_id or 0,
            last_error=row.last_error,
            created_at=row.created_at,
            updated_at=row.updated_at,
            **_build_monitor_backlog_payload(
                row,
                latest_message_id=(latest_by_chat.get(int(row.chat_id)) or {}).get("latest_message_id"),
                latest_message_date=(latest_by_chat.get(int(row.chat_id)) or {}).get("latest_message_date"),
                last_processed_message_date=processed_dates.get(int(row.chat_id)),
            ),
        )
        for row in rows
    ]


@router.put("/monitors/{chat_id}", response_model=MonitoredChat)
async def update_monitor(
    chat_id: int,
    payload: MonitorUpdateRequest,
    db: Session = Depends(get_db_session),
    manager: TelegramTDLibManager = Depends(tdlib_manager_dep),
    current_user: dict = Depends(get_current_user),
):
    """
    Create or update monitor settings for a chat.

    Args:
        chat_id: Telegram chat ID
        payload: Monitor configuration including filtering rules
    """
    import json

    _ensure_chat_allowed(chat_id, current_user)
    _ensure_toggle_allowed(current_user)

    row = db.get(MonitoredBotChat, chat_id)
    if row is None:
        row = MonitoredBotChat(chat_id=chat_id)
        db.add(row)

    row.enabled = payload.enabled

    # Update filter settings
    row.filter_mode = payload.filter_mode
    if payload.filter_keywords:
        row.filter_keywords = json.dumps(payload.filter_keywords, ensure_ascii=False)
    else:
        row.filter_keywords = None

    # Cache chat type/title for downstream filtering (groups vs bots)
    if payload.enabled:
        try:
            info = await manager.get_chat_info(chat_id)
            if info:
                row.chat_type = info.get("chat_type", row.chat_type)
                row.chat_title = info.get("title", row.chat_title)
        except Exception as exc:  # noqa: BLE001
            # Non-fatal; just log for debugging
            logger.warning("Failed to fetch chat info for monitor %s: %s", chat_id, exc)

    if payload.enabled and payload.start_from_latest:
        try:
            msgs = await manager.get_messages(chat_id=chat_id, limit=1, from_message_id=0)
            latest = msgs.get("items", [])
            if latest:
                row.last_processed_message_id = latest[0].get("id") or row.last_processed_message_id or 0
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=400, detail=f"Failed to fetch latest message: {exc}")

    db.commit()
    db.refresh(row)

    # Auto-start history sync when monitoring is enabled and chat hasn't been synced yet
    if payload.enabled:
        try:
            history_loader = get_history_loader_service() or init_history_loader_service(
                manager=manager, session_factory=SessionLocal,
            )
            status = history_loader.get_status(chat_id)
            if status.get("status") == "idle" and status.get("loaded_count", 0) == 0:
                await history_loader.start_load(chat_id=chat_id)
                logger.info("Auto-started history sync for newly monitored chat %s", chat_id)
        except Exception:
            logger.debug("Failed to auto-start history sync for chat %s", chat_id, exc_info=True)

    return MonitoredChat(
        chat_id=row.chat_id,
        enabled=row.enabled,
        last_processed_message_id=row.last_processed_message_id or 0,
        last_error=row.last_error,
        created_at=row.created_at,
        updated_at=row.updated_at,
        **_build_monitor_backlog_payload(row),
    )


@router.get("/monitor/status", response_model=MonitorStatusResponse)
async def monitor_status(
    manager: TelegramTDLibManager = Depends(tdlib_manager_dep),
    current_user: dict = Depends(get_current_user),
):
    service = get_auto_monitor_service()
    if service is None:
        # initialize lazily if startup not yet run
        service = init_auto_monitor_service(manager=manager, session_factory=SessionLocal)
    return MonitorStatusResponse(**service.status())


@router.get("/overview", response_model=TelegramOverviewResponse)
async def get_overview(
    include_hidden: bool = Query(False),
    search: Optional[str] = Query(None),
    limit: int = Query(200, ge=1, le=500),
    offset: int = Query(0, ge=0),
    chat_types: str = Query("private,group,supergroup,channel"),
    db: Session = Depends(get_db_session),
    manager: TelegramTDLibManager = Depends(tdlib_manager_dep),
    current_user: dict = Depends(get_current_user),
) -> TelegramOverviewResponse:
    auth = await get_status(manager=manager, current_user=current_user)
    chats = await list_chats(
        search=search,
        include_hidden=include_hidden,
        limit=limit,
        offset=offset,
        chat_types=chat_types,
        db=db,
        manager=manager,
        current_user=current_user,
    )
    monitor = await monitor_status(manager=manager, current_user=current_user)
    return TelegramOverviewResponse(
        auth=auth,
        chats=chats,
        monitor=monitor,
        server_time=datetime.utcnow().isoformat() + "Z",
    )


@router.post("/auth/phone", response_model=AuthStatusResponse)
async def set_phone(
    payload: PhoneRequest,
    manager: TelegramTDLibManager = Depends(tdlib_manager_dep),
) -> AuthStatusResponse:
    try:
        await manager.set_phone_number(payload.phone_number)
        state = await manager.get_auth_state()
        return _map_auth_state(state)
    except TDLibUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"Failed to set phone number: {exc}")


@router.post("/auth/code", response_model=AuthStatusResponse)
async def check_code(
    payload: CodeRequest,
    manager: TelegramTDLibManager = Depends(tdlib_manager_dep),
) -> AuthStatusResponse:
    try:
        # TDLib can forget phone if app restarted between phone and code steps; re-set if provided
        if payload.phone_number:
            await manager.set_phone_number(payload.phone_number)
        await manager.check_code(payload.code)
        state = await manager.get_auth_state()
        return _map_auth_state(state)
    except TDLibUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"Failed to verify code: {exc}")


@router.post("/auth/resend", response_model=AuthStatusResponse)
async def resend_code(
    manager: TelegramTDLibManager = Depends(tdlib_manager_dep),
) -> AuthStatusResponse:
    try:
        await manager.resend_code()
        state = await manager.get_auth_state()
        return _map_auth_state(state)
    except TDLibUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"Failed to resend code: {exc}")


@router.post("/auth/password", response_model=AuthStatusResponse)
async def check_password(
    payload: PasswordRequest,
    manager: TelegramTDLibManager = Depends(tdlib_manager_dep),
) -> AuthStatusResponse:
    try:
        await manager.check_password(payload.password)
        state = await manager.get_auth_state()
        return _map_auth_state(state)
    except TDLibUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"Failed to verify password: {exc}")


@router.get("/chats", response_model=ChatListResponse)
async def list_chats(
    search: Optional[str] = Query(None, description="Server-side search term"),
    include_hidden: bool = Query(False, description="Include hidden chats"),
    limit: int = Query(200, ge=1, le=500),
    offset: int = Query(0, ge=0),
    chat_types: str = Query("private,group,supergroup,channel", description="Comma-separated chat types: private,group,supergroup,channel"),
    db: Session = Depends(get_db_session),
    manager: TelegramTDLibManager = Depends(tdlib_manager_dep),
    current_user: dict = Depends(get_current_user),
) -> ChatListResponse:
    """
    List Telegram chats (bots and/or groups).

    Args:
        search: Search term for filtering chats
        include_hidden: Include chats marked as hidden
        limit: Maximum number of chats to return
        offset: Number of chats to skip
        chat_types: Comma-separated list of chat types to include (e.g., "private,group,supergroup")
    """
    # Parse chat types
    types_list = [t.strip() for t in chat_types.split(",") if t.strip()]

    try:
        result = await manager.list_chats(
            db=db,
            include_hidden=include_hidden,
            search=search,
            limit=limit,
            offset=offset,
            chat_types=types_list,
        )
    except TDLibUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"Failed to fetch chats: {exc}")

    allowed_sources = get_allowed_sources_for_user(current_user)
    raw_items = result.get("items", [])
    if allowed_sources is not None:
        raw_items = [item for item in raw_items if int(item.get("chat_id") or 0) in allowed_sources]
    chat_ids = [int(item.get("chat_id")) for item in raw_items if item.get("chat_id") is not None]
    monitors: Dict[int, MonitoredBotChat] = {}
    monitor_rows: List[MonitoredBotChat] = []
    protected_ids: Set[int] = set()
    if chat_ids:
        monitor_rows = db.query(MonitoredBotChat).filter(MonitoredBotChat.chat_id.in_(chat_ids)).all()
        monitors = {int(row.chat_id): row for row in monitor_rows}
        protected_ids = {
            int(row[0])
            for row in db.query(ChatPassword.chat_id).filter(ChatPassword.chat_id.in_(chat_ids)).all()
            if row and row[0] is not None
        }
    processed_dates, latest_by_chat = _load_monitor_cache_snapshot(db, chat_ids, monitor_rows)

    return ChatListResponse(
        total=len(raw_items),
        items=[
            (lambda chat_id, formatted_last_message, monitor: ChatItem(
                chat_id=chat_id,
                title=item.get("title", ""),
                username=item.get("username"),
                chat_type=item.get("chat_type", "bot"),
                member_count=item.get("member_count"),
                is_hidden=item.get("is_hidden", False),
                is_protected=item.get("chat_id") in protected_ids,
                is_monitored=monitor is not None,
                monitor_enabled=monitor.enabled if monitor else False,
                last_message=formatted_last_message,
                **_build_monitor_backlog_payload(
                    monitor,
                    latest_message_id=(
                        formatted_last_message.id
                        if formatted_last_message and formatted_last_message.id is not None
                        else (latest_by_chat.get(chat_id) or {}).get("latest_message_id")
                    ),
                    latest_message_date=(
                        _parse_iso_datetime(formatted_last_message.date)
                        if formatted_last_message and formatted_last_message.date
                        else (latest_by_chat.get(chat_id) or {}).get("latest_message_date")
                    ),
                    last_processed_message_date=processed_dates.get(chat_id),
                ),
            ))(
                int(item.get("chat_id")),
                _format_message(item.get("last_message")),
                monitors.get(item.get("chat_id")),
            )
            for item in raw_items
        ],
    )


@router.put("/chats/{chat_id}/hidden", response_model=HideChatResponse)
async def set_chat_hidden(
    chat_id: int,
    payload: HideChatPayload,
    db: Session = Depends(get_db_session),
    manager: TelegramTDLibManager = Depends(tdlib_manager_dep),
    current_user: dict = Depends(get_current_user),
) -> HideChatResponse:
    _ensure_chat_allowed(chat_id, current_user)
    _ensure_toggle_allowed(current_user)
    try:
        if payload.hidden:
            await manager.hide_chat(chat_id=chat_id, db=db)
        else:
            await manager.unhide_chat(chat_id=chat_id, db=db)
        return HideChatResponse(
            chat_id=chat_id,
            hidden=payload.hidden,
            updated_at=datetime.utcnow().isoformat() + "Z",
        )
    except TDLibUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"Failed to update hidden flag: {exc}")


@router.post("/chats/{chat_id}/hide")
async def hide_chat(
    chat_id: int,
    db: Session = Depends(get_db_session),
    manager: TelegramTDLibManager = Depends(tdlib_manager_dep),
    current_user: dict = Depends(get_current_user),
) -> Dict[str, Any]:
    _ensure_chat_allowed(chat_id, current_user)
    _ensure_toggle_allowed(current_user)
    await set_chat_hidden(chat_id=chat_id, payload=HideChatPayload(hidden=True), db=db, manager=manager, current_user=current_user)
    return {"success": True}


@router.post("/chats/{chat_id}/unhide")
async def unhide_chat(
    chat_id: int,
    db: Session = Depends(get_db_session),
    manager: TelegramTDLibManager = Depends(tdlib_manager_dep),
    current_user: dict = Depends(get_current_user),
) -> Dict[str, Any]:
    _ensure_chat_allowed(chat_id, current_user)
    _ensure_toggle_allowed(current_user)
    await set_chat_hidden(chat_id=chat_id, payload=HideChatPayload(hidden=False), db=db, manager=manager, current_user=current_user)
    return {"success": True}


@router.post("/chats/{chat_id}/password")
async def set_chat_password(
    chat_id: int,
    payload: ChatPasswordSetRequest,
    db: Session = Depends(get_db_session),
    current_user: dict = Depends(get_current_user),
) -> Dict[str, Any]:
    _ensure_chat_allowed(chat_id, current_user)
    password_hash, salt = hash_password(payload.password)
    row = db.get(ChatPassword, chat_id)
    if row is None:
        row = ChatPassword(chat_id=chat_id, password_hash=password_hash, salt=salt)
        db.add(row)
    else:
        row.password_hash = password_hash
        row.salt = salt
        row.failed_attempts = 0
        row.locked_until = None
    db.commit()
    return {"chat_id": chat_id, "protected": True}


@router.delete("/chats/{chat_id}/password")
async def remove_chat_password(
    chat_id: int,
    payload: ChatPasswordVerifyRequest,
    db: Session = Depends(get_db_session),
    current_user: dict = Depends(get_current_user),
) -> Dict[str, Any]:
    _ensure_chat_allowed(chat_id, current_user)
    row = db.get(ChatPassword, chat_id)
    if row is None:
        return {"chat_id": chat_id, "protected": False}
    if not verify_password(payload.password, row.password_hash, row.salt):
        raise HTTPException(status_code=401, detail={"verified": False, "error": "invalid_password"})
    db.delete(row)
    db.commit()
    return {"chat_id": chat_id, "protected": False}


@router.post("/chats/{chat_id}/password/verify", response_model=ChatPasswordVerifyResponse)
async def verify_chat_password(
    chat_id: int,
    payload: ChatPasswordVerifyRequest,
    db: Session = Depends(get_db_session),
    current_user: dict = Depends(get_current_user),
) -> ChatPasswordVerifyResponse:
    _ensure_chat_allowed(chat_id, current_user)
    row = db.get(ChatPassword, chat_id)
    if row is None:
        return ChatPasswordVerifyResponse(verified=True, session_token=None, expires_in=None)

    now = datetime.utcnow()
    if row.locked_until and row.locked_until > now:
        return ChatPasswordVerifyResponse(
            verified=False,
            locked=True,
            locked_until=row.locked_until.isoformat(),
        )

    if verify_password(payload.password, row.password_hash, row.salt):
        row.failed_attempts = 0
        row.locked_until = None
        db.commit()
        token = create_chat_access_token(chat_id=chat_id, user_id=current_user.get("user_id"))
        decoded = verify_chat_access_token(token) or {}
        if decoded:
            await register_active_session(
                token_payload=decoded,
                token_kind="chat_access",
                user_id=current_user.get("user_id"),
                subject=f"chat:{chat_id}",
            )
        return ChatPasswordVerifyResponse(verified=True, session_token=token, expires_in=3600)

    row.failed_attempts = int(row.failed_attempts or 0) + 1
    attempts_left = max(0, CHAT_PASSWORD_MAX_ATTEMPTS - row.failed_attempts)
    if row.failed_attempts >= CHAT_PASSWORD_MAX_ATTEMPTS:
        row.failed_attempts = 0
        row.locked_until = now + timedelta(minutes=max(1, CHAT_PASSWORD_LOCKOUT_MINUTES))
    db.commit()
    return ChatPasswordVerifyResponse(
        verified=False,
        attempts_left=attempts_left,
        locked=bool(row.locked_until and row.locked_until > now),
        locked_until=row.locked_until.isoformat() if row.locked_until else None,
    )


@router.get("/chats/{chat_id}/password/status")
async def chat_password_status(
    chat_id: int,
    db: Session = Depends(get_db_session),
    current_user: dict = Depends(get_current_user),
) -> Dict[str, Any]:
    _ensure_chat_allowed(chat_id, current_user)
    row = db.get(ChatPassword, chat_id)
    if row is None:
        return {"protected": False, "locked": False}
    status = _chat_password_status(row)
    return {"protected": True, "locked": status["locked"], "locked_until": status["locked_until"]}


@router.get("/chats/{chat_id}/messages", response_model=MessageListResponse)
async def get_messages(
    chat_id: int,
    limit: int = Query(50, ge=1, le=200),
    from_message_id: int = Query(0, ge=0, description="Start from message id (0 = latest)"),
    all: bool = Query(False, description="Fetch full history"),
    max_messages: Optional[int] = Query(
        None,
        ge=1,
        le=200000,
        description="Optional safety cap for all=true responses (use /history/load for full history)",
    ),
    manager: TelegramTDLibManager = Depends(tdlib_manager_dep),
    current_user: dict = Depends(get_current_user),
    _chat_access: None = Depends(require_chat_access),
) -> MessageListResponse:
    _ensure_chat_allowed(chat_id, current_user)
    try:
        result = await manager.get_messages(
            chat_id=chat_id,
            limit=limit,
            from_message_id=from_message_id,
            fetch_all=all,
            max_messages=max_messages,
        )
    except TDLibUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"Failed to get messages: {exc}")
    return MessageListResponse(
        total=result.get("total", 0),
        items=[_format_message(msg) for msg in result.get("items", []) if msg],
    )


@router.get("/chats/{chat_id}/messages/by-date-range", response_model=MessageListResponse)
async def get_messages_by_date_range(
    chat_id: int,
    date_from: str = Query(..., description="Start date in ISO format (e.g., 2026-01-27T00:00:00)"),
    date_to: str = Query(..., description="End date in ISO format (e.g., 2026-01-28T23:59:59)"),
    limit: int = Query(1000, ge=1, le=5000),
    manager: TelegramTDLibManager = Depends(tdlib_manager_dep),
    current_user: dict = Depends(get_current_user),
    _chat_access: None = Depends(require_chat_access),
) -> MessageListResponse:
    _ensure_chat_allowed(chat_id, current_user)
    """
    Fetch messages within a date range.
    
    Args:
        chat_id: Telegram chat ID
        date_from: Start date/time in ISO format (inclusive)
        date_to: End date/time in ISO format (inclusive)
        limit: Maximum number of messages to return (default 1000, max 5000)
    """
    try:
        # Parse ISO dates to Unix timestamps
        from_dt = datetime.fromisoformat(date_from.replace("Z", "+00:00"))
        to_dt = datetime.fromisoformat(date_to.replace("Z", "+00:00"))
        date_from_ts = int(from_dt.timestamp())
        date_to_ts = int(to_dt.timestamp())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid date format: {exc}")
    
    if date_from_ts > date_to_ts:
        raise HTTPException(status_code=400, detail="date_from must be before date_to")
    
    try:
        result = await manager.get_messages_by_date_range(
            chat_id=chat_id,
            date_from=date_from_ts,
            date_to=date_to_ts,
            limit=limit,
        )
    except TDLibUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"Failed to get messages by date range: {exc}")
    
    return MessageListResponse(
        total=result.get("total", 0),
        items=[_format_message(msg) for msg in result.get("items", []) if msg],
    )


@router.post("/chats/{chat_id}/history/load", response_model=HistoryLoadStartResponse)
async def start_history_load(
    chat_id: int,
    payload: HistoryLoadRequest,
    manager: TelegramTDLibManager = Depends(tdlib_manager_dep),
    current_user: dict = Depends(get_current_user),
    _chat_access: None = Depends(require_chat_access),
) -> HistoryLoadStartResponse:
    _ensure_chat_allowed(chat_id, current_user)
    history_loader = get_history_loader_service() or init_history_loader_service(
        manager=manager,
        session_factory=SessionLocal,
    )
    await _ensure_realtime_hooks(manager)
    try:
        status = await history_loader.start_load(
            chat_id=chat_id,
            max_messages=payload.max_messages,
            restart=payload.restart,
            date_from=payload.date_from,
            date_to=payload.date_to,
            exclude_from=payload.exclude_from,
            exclude_to=payload.exclude_to,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return HistoryLoadStartResponse(accepted=True, status=HistoryLoadStatusResponse(**status))


@router.get("/chats/{chat_id}/history/load/status", response_model=HistoryLoadStatusResponse)
async def history_load_status(
    chat_id: int,
    manager: TelegramTDLibManager = Depends(tdlib_manager_dep),
    current_user: dict = Depends(get_current_user),
    _chat_access: None = Depends(require_chat_access),
) -> HistoryLoadStatusResponse:
    _ensure_chat_allowed(chat_id, current_user)
    history_loader = get_history_loader_service() or init_history_loader_service(
        manager=manager,
        session_factory=SessionLocal,
    )
    status = history_loader.get_status(chat_id)
    return HistoryLoadStatusResponse(**status)


@router.get("/chats/{chat_id}/history/messages", response_model=MessageListResponse)
async def get_history_messages(
    chat_id: int,
    limit: int = Query(200, ge=1, le=5000),
    offset: int = Query(0, ge=0),
    search: Optional[str] = Query(None, max_length=200),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    manager: TelegramTDLibManager = Depends(tdlib_manager_dep),
    current_user: dict = Depends(get_current_user),
    _chat_access: None = Depends(require_chat_access),
) -> MessageListResponse:
    _ensure_chat_allowed(chat_id, current_user)
    history_loader = get_history_loader_service() or init_history_loader_service(
        manager=manager,
        session_factory=SessionLocal,
    )
    payload = history_loader.get_messages(
        chat_id=chat_id,
        limit=limit,
        offset=offset,
        search=search,
        date_from=date_from,
        date_to=date_to,
    )
    return MessageListResponse(
        total=int(payload.get("total") or 0),
        items=[_format_message(item) for item in payload.get("items", []) if item],
    )


class HistoryProcessReceiptsRequest(BaseModel):
    message_ids: Optional[List[int]] = Field(
        default=None,
        description="Specific message IDs to process. If omitted, scans all unprocessed messages with receipt keywords.",
    )
    max_messages: int = Field(default=500, ge=1, le=5000)
    force: bool = False


class HistoryProcessReceiptsResponse(BaseModel):
    chat_id: int
    total_scanned: int
    queued: int
    skipped: int
    errors: int
    results: List[Dict[str, Any]]


# RECEIPT_KEYWORDS_LOWER, MIN_RECEIPT_TEXT_LEN, looks_like_receipt
# imported from services.message_utils


def _looks_like_receipt(text: str, raw_json: str) -> bool:
    """Thin wrapper around shared ``looks_like_receipt``."""
    return looks_like_receipt(text, raw_json)


@router.post("/chats/{chat_id}/history/process-receipts", response_model=HistoryProcessReceiptsResponse)
async def process_history_receipts(
    chat_id: int,
    payload: HistoryProcessReceiptsRequest,
    db: Session = Depends(get_db_session),
    manager: TelegramTDLibManager = Depends(tdlib_manager_dep),
    current_user: dict = Depends(get_current_user),
    _chat_access: None = Depends(require_chat_access),
) -> HistoryProcessReceiptsResponse:
    """Process receipts from synced chat history messages."""
    _ensure_chat_allowed(chat_id, current_user)

    # Gather candidate messages from history DB
    query = db.query(TgChatMessage).filter(TgChatMessage.chat_id == int(chat_id))

    if payload.message_ids:
        # Process specific messages
        query = query.filter(TgChatMessage.message_id.in_([int(m) for m in payload.message_ids]))
    else:
        # Only unprocessed messages (no linked transaction yet)
        query = query.filter(TgChatMessage.receipt_transaction_id.is_(None))

    rows = query.order_by(TgChatMessage.message_id.asc()).limit(payload.max_messages).all()

    results: List[Dict[str, Any]] = []
    queued = 0
    skipped = 0
    errors = 0

    for row in rows:
        msg_id = int(row.message_id)

        # Skip if already linked to a transaction and not forced
        if row.receipt_transaction_id and not payload.force:
            skipped += 1
            results.append({
                "message_id": msg_id,
                "status": "already_processed",
                "transaction_id": int(row.receipt_transaction_id),
            })
            continue

        # For auto-scan mode, check if message looks like a receipt
        if not payload.message_ids and not _looks_like_receipt(row.text or "", row.raw_json or ""):
            skipped += 1
            continue

        # Check if already processed as a transaction
        existing_tx = (
            db.query(Transaction)
            .filter(
                Transaction.source_chat_id == int(chat_id),
                Transaction.source_message_id == msg_id,
            )
            .first()
        )
        if existing_tx and not payload.force:
            # Link the history message to existing transaction
            row.receipt_transaction_id = int(existing_tx.id)
            db.commit()
            skipped += 1
            results.append({
                "message_id": msg_id,
                "status": "already_exists",
                "transaction_id": int(existing_tx.id),
            })
            continue

        # Build task data from raw_json and queue for processing
        try:
            raw_msg = json.loads(row.raw_json or "{}")
        except Exception:
            raw_msg = {}

        formatted = _format_message(raw_msg)
        if not formatted:
            skipped += 1
            continue

        task_data = _build_task_data_from_message(int(chat_id), msg_id, {
            "text": formatted.text or "",
            "document": formatted.document,
            "photo": formatted.photo,
        })

        try:
            task_id = queue_receipt_task(task_data, force=payload.force)
            queued += 1
            results.append({
                "message_id": msg_id,
                "status": "queued",
                "task_id": task_id,
            })
        except ValueError:
            skipped += 1
            results.append({
                "message_id": msg_id,
                "status": "duplicate",
            })
        except Exception as exc:
            errors += 1
            results.append({
                "message_id": msg_id,
                "status": "error",
                "error": str(exc),
            })

    return HistoryProcessReceiptsResponse(
        chat_id=chat_id,
        total_scanned=len(rows),
        queued=queued,
        skipped=skipped,
        errors=errors,
        results=results,
    )


@router.get("/chats/{chat_id}/history/receipt-status")
async def history_receipt_status(
    chat_id: int,
    db: Session = Depends(get_db_session),
    current_user: dict = Depends(get_current_user),
    _chat_access: None = Depends(require_chat_access),
) -> Dict[str, Any]:
    """Get receipt processing stats for a chat's history."""
    _ensure_chat_allowed(chat_id, current_user)

    total = db.query(TgChatMessage).filter(TgChatMessage.chat_id == int(chat_id)).count()
    processed = (
        db.query(TgChatMessage)
        .filter(
            TgChatMessage.chat_id == int(chat_id),
            TgChatMessage.receipt_transaction_id.isnot(None),
        )
        .count()
    )
    # Count messages that have transactions but no link yet
    linked_via_tx = (
        db.query(Transaction)
        .filter(Transaction.source_chat_id == int(chat_id))
        .count()
    )

    return {
        "chat_id": chat_id,
        "total_messages": total,
        "processed_messages": processed,
        "total_transactions_from_chat": linked_via_tx,
    }


@router.get("/chats/{chat_id}/history/stats")
async def history_stats(
    chat_id: int,
    db: Session = Depends(get_db_session),
    manager: TelegramTDLibManager = Depends(tdlib_manager_dep),
    current_user: dict = Depends(get_current_user),
    _chat_access: None = Depends(require_chat_access),
) -> Dict[str, Any]:
    """Get comprehensive stats for a chat's synced history."""
    _ensure_chat_allowed(chat_id, current_user)

    history_loader = get_history_loader_service() or init_history_loader_service(
        manager=manager, session_factory=SessionLocal,
    )
    sync_status = history_loader.get_status(chat_id)

    total_messages = db.query(TgChatMessage).filter(TgChatMessage.chat_id == int(chat_id)).count()

    from sqlalchemy import func as sa_func
    date_range = db.query(
        sa_func.min(TgChatMessage.message_date),
        sa_func.max(TgChatMessage.message_date),
    ).filter(TgChatMessage.chat_id == int(chat_id)).first()

    oldest_date = date_range[0].isoformat() + "Z" if date_range and date_range[0] else None
    newest_date = date_range[1].isoformat() + "Z" if date_range and date_range[1] else None

    receipt_count = (
        db.query(TgChatMessage)
        .filter(
            TgChatMessage.chat_id == int(chat_id),
            TgChatMessage.receipt_transaction_id.isnot(None),
        )
        .count()
    )

    transaction_count = (
        db.query(Transaction)
        .filter(Transaction.source_chat_id == int(chat_id))
        .count()
    )

    return {
        "chat_id": chat_id,
        "sync": sync_status,
        "total_messages": total_messages,
        "oldest_message_date": oldest_date,
        "newest_message_date": newest_date,
        "linked_receipts": receipt_count,
        "total_transactions": transaction_count,
    }


@router.post("/chats/{chat_id}/messages", response_model=ChatMessage)
async def send_message(
    chat_id: int,
    payload: SendMessageRequest,
    manager: TelegramTDLibManager = Depends(tdlib_manager_dep),
    current_user: dict = Depends(get_current_user),
    _chat_access: None = Depends(require_chat_access),
) -> ChatMessage:
    _ensure_chat_allowed(chat_id, current_user)
    if not payload.text.strip():
        raise HTTPException(status_code=400, detail="Text is required")
    try:
        result = await manager.send_message(chat_id=chat_id, text=payload.text)
        return _format_message(result) or ChatMessage(text=payload.text)
    except TDLibUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"Failed to send message: {exc}")


@router.post("/chats/{chat_id}/documents", response_model=ChatMessage)
async def send_document(
    chat_id: int,
    file: UploadFile = File(...),
    caption: Optional[str] = Query("", description="Optional caption for the PDF"),
    manager: TelegramTDLibManager = Depends(tdlib_manager_dep),
    current_user: dict = Depends(get_current_user),
    _chat_access: None = Depends(require_chat_access),
) -> ChatMessage:
    _ensure_chat_allowed(chat_id, current_user)
    if file.content_type not in ("application/pdf", "application/x-pdf", "application/octet-stream"):
        raise HTTPException(status_code=400, detail="Only PDF files are supported")
    tmp_dir = tempfile.mkdtemp(prefix="tgpdf_")
    tmp_path = os.path.join(tmp_dir, file.filename or "document.pdf")
    try:
        with open(tmp_path, "wb") as out:
            shutil.copyfileobj(file.file, out)

        result = await manager.send_document(chat_id=chat_id, file_path=tmp_path, caption=caption or "")
        return _format_message(result) or ChatMessage(text=caption or "[PDF]")
    except TDLibUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"Failed to send document: {exc}")
    finally:
        try:
            os.remove(tmp_path)
            os.rmdir(tmp_dir)
        except Exception:
            pass


@router.post("/chats/{chat_id}/messages/{message_id}/process", response_model=ProcessResult)
async def process_message(
    chat_id: int,
    message_id: int,
    db: Session = Depends(get_db_session),
    manager: TelegramTDLibManager = Depends(tdlib_manager_dep),
    current_user: dict = Depends(get_current_user),
    _chat_access: None = Depends(require_chat_access),
) -> ProcessResult:
    _ensure_chat_allowed(chat_id, current_user)
    try:
        message = await manager.get_message(chat_id=chat_id, message_id=message_id)
    except TDLibUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    if not message:
        raise HTTPException(status_code=404, detail="Message not found")

    task_data = _build_task_data_from_message(chat_id, message_id, message)

    try:
        task_id = queue_receipt_task(task_data, force=False)
    except ValueError as exc:
        # Message already processed - return info about existing transaction
        raise HTTPException(status_code=409, detail=str(exc))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Failed to enqueue task: {exc}")

    db.expire_all()
    tracking = (
        db.query(ReceiptProcessingTask)
        .filter(
            ReceiptProcessingTask.chat_id == chat_id,
            ReceiptProcessingTask.message_id == message_id,
        )
        .first()
    )
    status = tracking.status if tracking else "queued"
    transaction_id = tracking.transaction_id if tracking else None
    error = tracking.error if tracking else None

    return ProcessResult(
        chat_id=chat_id,
        message_id=message_id,
        task_id=task_id,
        status=status,
        transaction_id=transaction_id,
        error=error,
    )


@router.post("/chats/{chat_id}/process-batch")
async def process_batch(
    chat_id: int,
    payload: BatchProcessRequest,
    db: Session = Depends(get_db_session),
    manager: TelegramTDLibManager = Depends(tdlib_manager_dep),
    current_user: dict = Depends(get_current_user),
    _chat_access: None = Depends(require_chat_access),
) -> Dict[str, Any]:
    _ensure_chat_allowed(chat_id, current_user)
    results: List[Dict[str, Any]] = []
    for msg_id in payload.message_ids:
        try:
            message = await manager.get_message(chat_id=chat_id, message_id=msg_id)
            if not message:
                results.append(
                    {
                        "chat_id": chat_id,
                        "message_id": msg_id,
                        "status": "not_found",
                        "error": "Message not found",
                    }
                )
                continue
            task_data = _build_task_data_from_message(chat_id, msg_id, message)
            try:
                task_id = queue_receipt_task(task_data, force=False)
            except ValueError as exc:
                # Already processed - skip this message
                results.append(
                    {
                        "chat_id": chat_id,
                        "message_id": msg_id,
                        "status": "duplicate",
                        "error": str(exc),
                    }
                )
                continue
            db.expire_all()
            tracking = (
                db.query(ReceiptProcessingTask)
                .filter(
                    ReceiptProcessingTask.chat_id == chat_id,
                    ReceiptProcessingTask.message_id == msg_id,
                )
                .first()
            )
            results.append(
                {
                    "chat_id": chat_id,
                    "message_id": msg_id,
                    "task_id": task_id,
                    "status": tracking.status if tracking else "queued",
                    "transaction_id": tracking.transaction_id if tracking else None,
                    "error": tracking.error if tracking else None,
                }
            )
        except TDLibUnavailableError as exc:
            results.append(
                {
                    "chat_id": chat_id,
                    "message_id": msg_id,
                    "status": "failed",
                    "error": str(exc),
                }
            )
        except Exception as exc:  # noqa: BLE001
            results.append(
                {
                    "chat_id": chat_id,
                    "message_id": msg_id,
                    "status": "failed",
                    "error": str(exc),
                }
            )
    return {"results": results}


@router.get("/chats/{chat_id}/receipt-status")
async def receipt_status(
    chat_id: int,
    message_ids: str = Query(..., description="Comma-separated list of message ids"),
    db: Session = Depends(get_db_session),
    current_user: dict = Depends(get_current_user),
    _chat_access: None = Depends(require_chat_access),
) -> Dict[str, Any]:
    _ensure_chat_allowed(chat_id, current_user)
    ids: List[int] = []
    for part in message_ids.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            ids.append(int(part))
        except ValueError:
            continue

    statuses: List[Dict[str, Any]] = []
    for msg_id in ids:
        transaction = (
            db.query(Transaction)
            .filter(
                Transaction.source_chat_id == chat_id,
                Transaction.source_message_id == msg_id,
            )
            .first()
        )
        if transaction:
            statuses.append(
                {
                    "chat_id": chat_id,
                    "message_id": msg_id,
                    "status": "done",
                    "transaction_id": transaction.id,
                }
            )
            continue

        tracking = (
            db.query(ReceiptProcessingTask)
            .filter(
                ReceiptProcessingTask.chat_id == chat_id,
                ReceiptProcessingTask.message_id == msg_id,
            )
            .first()
        )
        if tracking:
            # If tracking says "done" but transaction doesn't exist, reset tracking
            if tracking.status == "done" and tracking.transaction_id:
                tx_exists = (
                    db.query(Transaction.id)
                    .filter(Transaction.id == tracking.transaction_id)
                    .scalar()
                )
                if not tx_exists:
                    # Transaction was deleted, reset tracking
                    db.delete(tracking)
                    db.commit()
                    statuses.append(
                        {
                            "chat_id": chat_id,
                            "message_id": msg_id,
                            "status": "not_processed",
                        }
                    )
                    continue

            statuses.append(
                {
                    "chat_id": chat_id,
                    "message_id": msg_id,
                    "status": tracking.status,
                    "task_id": tracking.task_id,
                    "transaction_id": tracking.transaction_id,
                    "error": tracking.error,
                }
            )
            continue

        statuses.append(
            {
                "chat_id": chat_id,
                "message_id": msg_id,
                "status": "not_processed",
            }
        )

    return {"results": statuses}


@router.get("/files/{file_id}")
async def download_file(
    file_id: int,
    filename: Optional[str] = Query(None, description="Override filename in Content-Disposition"),
    manager: TelegramTDLibManager = Depends(tdlib_manager_dep),
    current_user: dict = Depends(get_current_user),
):
    try:
        auth_state = await manager.get_auth_state()
    except TDLibUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Failed to get TDLib state: {exc}")

    if auth_state.get("state") == "tdlib_unavailable":
        raise HTTPException(status_code=503, detail=f"TDLib unavailable: {auth_state.get('raw_state')}")

    if not auth_state.get("is_authorized"):
        detail_state = auth_state.get("state") or auth_state.get("raw_state")
        raise HTTPException(status_code=401, detail=f"TDLib client is not authorized (state={detail_state})")

    try:
        file_path = await manager.download_file(file_id, synchronous=True)
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail="Timed out downloading file from TDLib")
    except TDLibUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Failed to download file: {exc}")

    if not file_path or not os.path.isfile(file_path):
        raise HTTPException(status_code=404, detail="File not found")

    safe_filename = os.path.basename(filename or "") or os.path.basename(file_path) or "document.pdf"
    media_type = "application/pdf"
    response = FileResponse(file_path, media_type=media_type, filename=safe_filename)
    response.headers["Content-Disposition"] = f'inline; filename="{safe_filename}"'
    return response


@ws_router.websocket("/ws/tg")
async def websocket_updates(
    websocket: WebSocket,
    token: Optional[str] = Query(None),
    manager: TelegramTDLibManager = Depends(tdlib_manager_dep),
) -> None:
    await websocket.accept()
    ws_token = token
    if not ws_token:
        auth_header = websocket.headers.get("authorization") or websocket.headers.get("Authorization")
        if auth_header and auth_header.lower().startswith("bearer "):
            ws_token = auth_header[7:].strip()

    if not ws_token:
        with suppress(Exception):
            await websocket.send_json({"type": "error", "message": "Authentication required"})
        await websocket.close(code=4401, reason="Authentication required")
        return

    user = verify_jwt_token(ws_token)
    if not user:
        with suppress(Exception):
            await websocket.send_json({"type": "error", "message": "Invalid or expired token"})
        await websocket.close(code=4401, reason="Invalid or expired token")
        return

    await _ensure_realtime_hooks(manager)
    _ensure_settings_listener()
    async with _tg_ws_lock:
        _tg_ws_clients.add(websocket)
    previous_auth: Optional[Dict[str, Any]] = None
    previous_monitor: Optional[Dict[str, Any]] = None
    try:
        while True:
            state = await manager.get_auth_state()
            auth_payload = {
                "type": "auth-state",
                "state": state.get("state"),
                "raw_state": state.get("raw_state"),
                "is_authorized": bool(state.get("is_authorized")),
                "ts": datetime.utcnow().isoformat() + "Z",
            }
            if auth_payload != previous_auth:
                await websocket.send_json(auth_payload)
                previous_auth = auth_payload

            monitor_service = get_auto_monitor_service()
            if monitor_service is None:
                monitor_service = init_auto_monitor_service(manager=manager, session_factory=SessionLocal)
            monitor_state = monitor_service.status()
            monitor_payload = {
                "type": "monitor-state",
                "running": bool(monitor_state.get("running")),
                "queue_size": int(monitor_state.get("queue_size") or 0),
                "workers": int(monitor_state.get("workers") or 0),
                "ts": datetime.utcnow().isoformat() + "Z",
            }
            if monitor_payload != previous_monitor:
                await websocket.send_json(monitor_payload)
                previous_monitor = monitor_payload

            await websocket.send_json({"type": "heartbeat", "ts": datetime.utcnow().isoformat() + "Z"})
            await asyncio.sleep(WS_HEARTBEAT_SECONDS)
    except WebSocketDisconnect:
        return
    except Exception:
        try:
            await websocket.send_json({"type": "error", "message": "Internal error"})
        except Exception:
            pass
        with suppress(Exception):
            await websocket.close()
    finally:
        async with _tg_ws_lock:
            _tg_ws_clients.discard(websocket)
