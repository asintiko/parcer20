"""
Telegram TDLib client API
- Auth state machine (phone/code/password)
- Bot-only chat listing with hidden toggle
- Messages read/send + PDF docs
- Simple WebSocket heartbeat
"""
import asyncio
import json
import os
import tempfile
import shutil
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect, UploadFile, File
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from database.connection import get_db_session, SessionLocal
from database.models import Transaction, ReceiptProcessingTask, MonitoredBotChat
from services.telegram_tdlib_manager import (
    TDLibUnavailableError,
    TelegramTDLibManager,
    get_tdlib_manager,
)
from services.tg_auto_monitor_service import get_auto_monitor_service, init_auto_monitor_service
from workers.celery_worker import queue_receipt_task
from api.dependencies import get_current_user
from services.auth_service import verify_jwt_token

router = APIRouter(prefix="/api/tg", tags=["telegram"])


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


class BotChat(BaseModel):
    chat_id: int
    title: str
    username: Optional[str] = None
    chat_type: str  # 'bot', 'user', 'group', 'supergroup', 'channel'
    member_count: Optional[int] = None  # For groups and channels
    is_hidden: bool = False
    is_monitored: Optional[bool] = False
    monitor_enabled: Optional[bool] = False
    last_message: Optional[ChatMessage] = None


class ChatListResponse(BaseModel):
    total: int
    items: List[BotChat]


class MonitoredChat(BaseModel):
    chat_id: int
    enabled: bool
    last_processed_message_id: int
    last_error: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


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


def _build_task_data_from_message(chat_id: int, message_id: int, message: Dict[str, Any]) -> Dict[str, Any]:
    """
    Convert formatted TDLib message into task payload for Celery.
    """
    raw_text = message.get("text") or ""
    task_data: Dict[str, Any] = {
        "source_type": "AUTO",
        "source_chat_id": chat_id,
        "source_message_id": message_id,
        "raw_text": raw_text,
        "added_via": "tdlib",
    }
    document = message.get("document")
    if document and document.get("mime_type") == "application/pdf":
        task_data["document"] = {
            "file_id": document.get("file_id"),
            "file_name": document.get("file_name"),
            "mime_type": document.get("mime_type"),
            "caption": raw_text,
        }
    return task_data


def tdlib_manager_dep() -> TelegramTDLibManager:
    return get_tdlib_manager()


def _format_message(data: Optional[Dict[str, Any]]) -> Optional[ChatMessage]:
    if not data:
        return None
    iso_date: Optional[str] = None
    timestamp = data.get("date")
    if timestamp:
        try:
            iso_date = datetime.utcfromtimestamp(timestamp).isoformat() + "Z"
        except Exception:
            iso_date = None
    return ChatMessage(
        id=data.get("id"),
        date=iso_date,
        is_outgoing=data.get("is_outgoing", False),
        sender_id=data.get("sender_id"),
        text=data.get("text"),
        document=data.get("document"),
    )


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
    return [
        MonitoredChat(
            chat_id=row.chat_id,
            enabled=row.enabled,
            last_processed_message_id=row.last_processed_message_id or 0,
            last_error=row.last_error,
            created_at=row.created_at,
            updated_at=row.updated_at,
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
    row = db.get(MonitoredBotChat, chat_id)
    if row is None:
        row = MonitoredBotChat(chat_id=chat_id)
        db.add(row)
    row.enabled = payload.enabled
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
    return MonitoredChat(
        chat_id=row.chat_id,
        enabled=row.enabled,
        last_processed_message_id=row.last_processed_message_id or 0,
        last_error=row.last_error,
        created_at=row.created_at,
        updated_at=row.updated_at,
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
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    chat_types: str = Query("private", description="Comma-separated chat types: private,group,supergroup,channel"),
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

    monitors = {row.chat_id: row for row in db.query(MonitoredBotChat).all()}
    try:
        result = await manager.list_bot_chats(
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
    return ChatListResponse(
        total=result.get("total", 0),
        items=[
            BotChat(
                chat_id=item.get("chat_id"),
                title=item.get("title", ""),
                username=item.get("username"),
                chat_type=item.get("chat_type", "bot"),
                member_count=item.get("member_count"),
                is_hidden=item.get("is_hidden", False),
                is_monitored=monitors.get(item.get("chat_id")) is not None,
                monitor_enabled=monitors.get(item.get("chat_id")).enabled if monitors.get(item.get("chat_id")) else False,
                last_message=_format_message(item.get("last_message")),
            )
            for item in result.get("items", [])
        ],
    )


@router.post("/chats/{chat_id}/hide")
async def hide_chat(
    chat_id: int,
    db: Session = Depends(get_db_session),
    manager: TelegramTDLibManager = Depends(tdlib_manager_dep),
    current_user: dict = Depends(get_current_user),
) -> Dict[str, Any]:
    try:
        await manager.hide_chat(chat_id=chat_id, db=db)
        return {"success": True}
    except TDLibUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"Failed to hide chat: {exc}")


@router.post("/chats/{chat_id}/unhide")
async def unhide_chat(
    chat_id: int,
    db: Session = Depends(get_db_session),
    manager: TelegramTDLibManager = Depends(tdlib_manager_dep),
    current_user: dict = Depends(get_current_user),
) -> Dict[str, Any]:
    try:
        await manager.unhide_chat(chat_id=chat_id, db=db)
        return {"success": True}
    except TDLibUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"Failed to unhide chat: {exc}")


@router.get("/chats/{chat_id}/messages", response_model=MessageListResponse)
async def get_messages(
    chat_id: int,
    limit: int = Query(50, ge=1, le=200),
    from_message_id: int = Query(0, ge=0, description="Start from message id (0 = latest)"),
    all: bool = Query(False, description="Fetch full history"),
    manager: TelegramTDLibManager = Depends(tdlib_manager_dep),
    current_user: dict = Depends(get_current_user),
) -> MessageListResponse:
    try:
        result = await manager.get_messages(chat_id=chat_id, limit=limit, from_message_id=from_message_id, fetch_all=all)
    except TDLibUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"Failed to get messages: {exc}")
    return MessageListResponse(
        total=result.get("total", 0),
        items=[_format_message(msg) for msg in result.get("items", []) if msg],
    )


@router.post("/chats/{chat_id}/messages", response_model=ChatMessage)
async def send_message(
    chat_id: int,
    payload: SendMessageRequest,
    manager: TelegramTDLibManager = Depends(tdlib_manager_dep),
    current_user: dict = Depends(get_current_user),
) -> ChatMessage:
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
) -> ChatMessage:
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
) -> ProcessResult:
    try:
        message = await manager.get_message(chat_id=chat_id, message_id=message_id)
    except TDLibUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    if not message:
        raise HTTPException(status_code=404, detail="Message not found")

    task_data = _build_task_data_from_message(chat_id, message_id, message)

    try:
        task_id = queue_receipt_task(task_data)
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
) -> Dict[str, Any]:
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
            task_id = queue_receipt_task(task_data)
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
) -> Dict[str, Any]:
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


@router.websocket("/ws/tg")
async def websocket_updates(
    websocket: WebSocket,
    token: Optional[str] = Query(None),
    manager: TelegramTDLibManager = Depends(tdlib_manager_dep),
) -> None:
    # Verify token before accepting connection
    if not token:
        await websocket.close(code=4001, reason="Authentication required")
        return

    user = verify_jwt_token(token)
    if not user:
        await websocket.close(code=4001, reason="Invalid or expired token")
        return

    await websocket.accept()
    try:
        state = await manager.get_auth_state()
        await websocket.send_json(
            {
                "type": "status",
                "state": state.get("state"),
                "raw_state": state.get("raw_state"),
            }
        )
        while True:
            await asyncio.sleep(10)
            await websocket.send_json({"type": "heartbeat", "ts": datetime.utcnow().isoformat() + "Z"})
    except WebSocketDisconnect:
        return
    except Exception as exc:  # noqa: BLE001
        await websocket.send_json({"type": "error", "message": "Internal error"})
        await websocket.close()
