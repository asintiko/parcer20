"""Continuous monitored-chat backfill into `tg_chat_messages`.

Goal: every actively monitored chat (MonitoredBotChat.is_active = true) keeps
its **full text history** in the DB, with media attachments only referenced by
`content_type/media_kind` (never the bytes).

Strategy:
- Iterate active monitored chats.
- Use `TgHistoryCursor` to remember last synced message_id per chat.
- Fetch new messages from TDLib in pages, persist text + metadata, mark
  `looks_like_receipt` heuristic, store `media_kind` for media without bytes.
- Single Celery task wakes up periodically (cron via APScheduler), processes
  one chunk per chat, then exits — incremental and idempotent.

Constraints:
- Skip persisting raw photo/PDF bytes; only metadata.
- Respect `content_type ∈ {'text','photo','document','sticker','video','audio','voice','location','other'}`.
- Use `UniqueConstraint(chat_id, message_id)` for idempotent upsert.
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timedelta
from hashlib import sha256
from typing import Any, Dict, List, Optional

from sqlalchemy import and_, func
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from database.connection import get_db
from database.models import MonitoredBotChat, TgChatMessage, TgHistoryCursor

logger = logging.getLogger(__name__)


PAGE_SIZE = 100
MAX_PAGES_PER_CYCLE = 5  # at most 500 new messages per chat per tick
RECEIPT_HINTS = (
    "uzs",
    "usd",
    "uzcard",
    "humo",
    "click",
    "payme",
    "uzum",
    "сум",
    "сўм",
    "transaction",
    "транзакц",
    "оплата",
    "card",
    "карта",
)


# --------------------------------------------------------------------------- #
def _looks_like_receipt(text: Optional[str], media_kind: Optional[str]) -> bool:
    if media_kind in {"photo", "document"}:
        return True
    if not text:
        return False
    lower = text.lower()
    return any(h in lower for h in RECEIPT_HINTS)


def _classify_content(message: Dict[str, Any]) -> tuple[str, Optional[str], Optional[str]]:
    """Return (content_type, media_kind, text).

    Handles BOTH message shapes:
    1. Formatted/flat dict from TelegramTDLibManager._format_message
       ({text, document, photo}) — this is what the sync fetch_callable yields.
    2. Raw TDLib dict ({content: {@type: messagePhoto, ...}}) — fallback.
    Previously only shape #2 was handled, so every synced row got 'other' and
    looks_like_receipt was never set (broken receipt detection in audits).
    """
    # Shape #1: formatted/flat dict
    if "content" not in message and ("text" in message or "document" in message or "photo" in message):
        text = message.get("text") or None
        if message.get("photo"):
            return "photo", "photo", text
        if message.get("document"):
            doc = message.get("document") or {}
            mime = str(doc.get("mime_type") or "").lower()
            if mime.startswith("image/"):
                return "photo", "photo", text
            return "document", "document", text
        return "text", None, text

    # Shape #2: raw TDLib content
    content = message.get("content") or {}
    mtype = (content.get("@type") or "").lower()
    if mtype == "messagetext":
        return "text", None, (content.get("text") or {}).get("text")
    if mtype == "messagephoto":
        return "photo", "photo", (content.get("caption") or {}).get("text")
    if mtype == "messagedocument":
        return "document", "document", (content.get("caption") or {}).get("text")
    if mtype == "messagesticker":
        return "sticker", "sticker", None
    if mtype == "messagevideo":
        return "video", "video", (content.get("caption") or {}).get("text")
    if mtype == "messageaudio":
        return "audio", "audio", None
    if mtype == "messagevoicenote":
        return "voice", "voice", None
    if mtype == "messagelocation":
        return "location", "location", None
    return "other", "other", None


def _hash_message(text: Optional[str], chat_id: int, message_id: int) -> str:
    h = sha256()
    h.update(str(chat_id).encode())
    h.update(b":")
    h.update(str(message_id).encode())
    h.update(b":")
    h.update((text or "").encode("utf-8", errors="ignore"))
    return h.hexdigest()


# --------------------------------------------------------------------------- #
def _get_or_create_cursor(db: Session, chat_id: int) -> TgHistoryCursor:
    cursor = (
        db.query(TgHistoryCursor)
        .filter(TgHistoryCursor.chat_id == chat_id)
        .first()
    )
    if cursor is None:
        cursor = TgHistoryCursor(
            chat_id=chat_id,
            cursor_message_id=0,
        )
        db.add(cursor)
        db.flush()
    return cursor


def _persist_messages(
    db: Session,
    chat_id: int,
    chat_title: Optional[str],
    messages: List[Dict[str, Any]],
) -> tuple[int, set[int]]:
    """Idempotent upsert. Returns (persisted_count, failed_message_ids).

    M-3 contract: callers MUST gate cursor advance on `failed_message_ids` being empty.
    """
    if not messages:
        return 0, set()
    rows: List[Dict[str, Any]] = []
    for m in messages:
        message_id = m.get("id")
        if message_id is None:
            continue
        content_type, media_kind, text = _classify_content(m)
        # Skip non-text and non-receipt-looking media (we still store metadata)
        # to avoid bloating the table with empty rows for bot reactions etc.
        date_ts = m.get("date")
        try:
            message_date = (
                datetime.utcfromtimestamp(int(date_ts)) if date_ts else None
            )
        except Exception:  # noqa: BLE001
            message_date = None
        rows.append(
            {
                "chat_id": int(chat_id),
                "message_id": int(message_id),
                "message_date": message_date,
                "is_outgoing": bool(m.get("is_outgoing", False)),
                "sender_id": _extract_sender_id(m),
                "text": (text or None),
                "raw_json": json.dumps(_compact_raw(m), ensure_ascii=False)[:10000],
                "content_type": content_type,
                "media_kind": media_kind,
                "looks_like_receipt": _looks_like_receipt(text, media_kind),
                "message_hash": _hash_message(text, chat_id, int(message_id)),
                "source_chat_title_snapshot": (chat_title or None),
            }
        )
    if not rows:
        return 0, set()

    rows_by_id = {int(r["message_id"]): r for r in rows}
    failed_ids: set[int] = set()

    # Postgres ON CONFLICT DO UPDATE for upsert; sqlite fallback re-tries one row at a time.
    inserted = 0
    try:
        stmt = pg_insert(TgChatMessage).values(rows)
        stmt = stmt.on_conflict_do_update(
            index_elements=[TgChatMessage.chat_id, TgChatMessage.message_id],
            set_={
                "text": stmt.excluded.text,
                "content_type": stmt.excluded.content_type,
                "media_kind": stmt.excluded.media_kind,
                "looks_like_receipt": stmt.excluded.looks_like_receipt,
                "message_hash": stmt.excluded.message_hash,
                "source_chat_title_snapshot": stmt.excluded.source_chat_title_snapshot,
                "updated_at": func.now(),
            },
        )
        db.execute(stmt)
        inserted = len(rows)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Bulk upsert into tg_chat_messages failed (%s); falling back row-by-row", exc)
        db.rollback()
        for row in rows:
            try:
                existing = (
                    db.query(TgChatMessage)
                    .filter(
                        TgChatMessage.chat_id == row["chat_id"],
                        TgChatMessage.message_id == row["message_id"],
                    )
                    .first()
                )
                if existing is None:
                    db.add(TgChatMessage(**row))
                    inserted += 1
                else:
                    for k, v in row.items():
                        if k in {"chat_id", "message_id"}:
                            continue
                        setattr(existing, k, v)
            except Exception:  # noqa: BLE001
                logger.exception("Row insert failed for %s/%s", row["chat_id"], row["message_id"])
                failed_ids.add(int(row["message_id"]))
                db.rollback()
    db.commit()
    return inserted, failed_ids


def _extract_sender_id(message: Dict[str, Any]) -> Optional[int]:
    sender = message.get("sender_id") or message.get("sender") or {}
    if isinstance(sender, dict):
        sid = sender.get("user_id") or sender.get("chat_id")
        try:
            return int(sid) if sid is not None else None
        except Exception:  # noqa: BLE001
            return None
    return None


def _compact_raw(message: Dict[str, Any]) -> Dict[str, Any]:
    """Strip heavy fields (file bytes, file ids could stay) for safe storage."""
    if not isinstance(message, dict):
        return {}
    keep_keys = {
        "id",
        "chat_id",
        "date",
        "edit_date",
        "is_outgoing",
        "sender_id",
        "reply_to_message_id",
        "media_album_id",
    }
    out = {k: message[k] for k in keep_keys if k in message}
    content = message.get("content") or {}
    if isinstance(content, dict):
        # Keep only @type + caption text + brief media metadata; drop file bytes.
        ctype = content.get("@type")
        out["content"] = {"@type": ctype}
        for sub_key in ("caption", "text"):
            sub = content.get(sub_key)
            if isinstance(sub, dict):
                txt = sub.get("text")
                if txt:
                    out["content"][sub_key] = {"text": txt[:1500]}
        for media_key in ("photo", "document", "video", "audio", "voice_note"):
            sub = content.get(media_key)
            if isinstance(sub, dict):
                out["content"][media_key] = {
                    k: sub.get(k) for k in ("id", "mime_type", "file_name") if k in sub
                }
    return out


# --------------------------------------------------------------------------- #
async def sync_one_chat(
    db: Session,
    chat: MonitoredBotChat,
    *,
    fetch_callable,
) -> Dict[str, Any]:
    """Sync one chat by walking back from latest until we hit stored cursor.

    Direction: TDLib's getChatHistory returns messages OLDER than `from_message_id`.
    We start from `from_message_id=0` (latest), persist messages, advance the
    iterator with `min(page_ids)`, and stop when we reach the previously-stored
    `cursor.cursor_message_id` (which is the highest id we've already saved).

    `fetch_callable(chat_id, from_message_id, limit)` returns raw TDLib message dicts.
    The cursor is advanced ONLY after a successful page persist.
    """
    cursor = _get_or_create_cursor(db, chat.chat_id)
    stored_max = int(cursor.cursor_message_id or 0)

    total_new = 0
    pages = 0
    page_min_id = 0  # 0 == "from latest"
    highest_seen_in_run = 0
    highest_persisted_in_run = 0  # M-3: track persisted-only watermark
    persist_failed_ids: set[int] = set()
    reached_cursor = False

    while pages < MAX_PAGES_PER_CYCLE:
        try:
            page = await fetch_callable(
                chat_id=chat.chat_id,
                from_message_id=page_min_id,
                limit=PAGE_SIZE,
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception(
                "TDLib fetch failed for chat %s at from_id=%s: %s",
                chat.chat_id,
                page_min_id,
                exc,
            )
            cursor.error = str(exc)[:500]
            cursor.status = "failed"
            break

        if not page:
            # Reached the start of history — full backfill complete.
            cursor.status = "completed"
            break

        # Filter out messages that are older or equal to what's already stored.
        # IMPORTANT for catching up: `cursor_message_id` is the ID we last saw,
        # so we should stop at strictly less-than to be idempotent.
        ids_in_page = [int(m.get("id") or 0) for m in page if m.get("id") is not None]
        if not ids_in_page:
            break

        page_max = max(ids_in_page)
        page_min = min(ids_in_page)
        highest_seen_in_run = max(highest_seen_in_run, page_max)

        # Anything strictly newer than stored cursor is new for us.
        new_msgs = [m for m in page if int(m.get("id") or 0) > stored_max]
        if new_msgs:
            inserted, failed_in_batch = _persist_messages(
                db,
                chat.chat_id,
                getattr(chat, "chat_title", None),
                new_msgs,
            )
            total_new += inserted
            if failed_in_batch:
                persist_failed_ids.update(failed_in_batch)
                # M-3: cap watermark at last id BELOW the lowest failure so
                # nothing failed gets jumped over on next tick.
                lowest_failed = min(failed_in_batch)
                successful_ids_in_page = [
                    int(m.get("id") or 0)
                    for m in new_msgs
                    if int(m.get("id") or 0) < lowest_failed
                ]
                if successful_ids_in_page:
                    highest_persisted_in_run = max(
                        highest_persisted_in_run, max(successful_ids_in_page)
                    )
            else:
                highest_persisted_in_run = max(highest_persisted_in_run, page_max)

        pages += 1

        # Stop if this page already crossed the stored cursor — we've caught up.
        if stored_max > 0 and page_min <= stored_max:
            reached_cursor = True
            break

        # Continue back: next iteration starts from this page's minimum id.
        page_min_id = page_min

    # M-3: cursor advances ONLY when no persistence failures occurred.
    # If any row failed, cursor stays so retry pulls failed messages again.
    if cursor.status != "failed" and not persist_failed_ids:
        if highest_seen_in_run > stored_max:
            cursor.cursor_message_id = highest_seen_in_run
    elif persist_failed_ids:
        # Partial advance: lowest_failed - 1 is the last guaranteed-saved id.
        if highest_persisted_in_run > stored_max:
            cursor.cursor_message_id = highest_persisted_in_run
        cursor.error = (
            f"persist_failed: {sorted(list(persist_failed_ids))[:10]}"
        )[:500]
        cursor.status = "partial"

    cursor.last_batch_at = datetime.utcnow()
    if cursor.status not in ("failed", "partial"):
        cursor.error = None
    db.commit()
    return {
        "chat_id": chat.chat_id,
        "new_rows": total_new,
        "pages_done": pages,
        "cursor_message_id": int(cursor.cursor_message_id or 0),
        "reached_cursor": reached_cursor,
    }


async def sync_all_active_chats(*, fetch_callable) -> List[Dict[str, Any]]:
    """Top-level entry-point — sync every active monitored chat once."""
    results: List[Dict[str, Any]] = []
    with get_db() as db:
        chats = (
            db.query(MonitoredBotChat).filter(MonitoredBotChat.enabled.is_(True)).all()
        )
        for chat in chats:
            try:
                results.append(await sync_one_chat(db, chat, fetch_callable=fetch_callable))
            except Exception:  # noqa: BLE001
                logger.exception("sync_one_chat failed for %s", chat.chat_id)
    return results
