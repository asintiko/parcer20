"""Shared message utilities.

Functions extracted from ``api.routes.telegram_client`` so they can be
reused by the reconciliation agent and other services.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Set


# ── Receipt detection constants ──────────────────────────────────────────────

RECEIPT_KEYWORDS_LOWER: Set[str] = {
    # Currency and money context
    "uzs",
    "usd",
    "sum",
    "сум",
    "сўм",
    "balans",
    "баланс",
    "balance",
    "dostupno",
    "остаток",
    # Card/bank markers
    "humo",
    "humocard",
    "uzcard",
    "cardxabar",
    "nbu card",
    # Receipt operation words (RU)
    "оплата",
    "пополнение",
    "перевод",
    "конверсия",
    "снятие наличных",
    # Receipt operation words (LAT)
    "oplata",
    "popolnenie",
    "pokupka",
    "spisanie",
    "transfer",
    "konversiya",
    # P2P markers
    "sender",
    "receiver",
    "отправител",
    "получател",
    # Common labels
    "receipt",
    "chek",
    "чек",
    "summa:",
    "karta:",
    "magazin:",
    # Payment systems
    "payme",
    "click",
    "apelsin",
    "terminal",
}
RECEIPT_EMOJI: Set[str] = {
    "💸",
    "💳",
    "📍",
    "🏪",
    "🕓",
    "🕘",
    "📅",
    "➖",
    "➕",
    "💰",
    "💵",
    "🔴",
    "🟢",
}
MIN_RECEIPT_TEXT_LEN: int = 20


# ── Receipt heuristic ────────────────────────────────────────────────────────

def looks_like_receipt(text: str, raw_json: str) -> bool:
    """Quick heuristic check if a history message might contain a receipt."""
    if raw_json:
        try:
            msg = json.loads(raw_json)
            content = msg.get("content") or {}
            content_type = content.get("@type", "")
            if content_type == "messageDocument":
                doc = content.get("document") or {}
                doc_file = doc.get("document") if isinstance(doc.get("document"), dict) else {}
                mime = str(doc.get("mime_type") or doc_file.get("mime_type") or "").lower()
                if mime == "application/pdf" or mime.startswith("image/"):
                    return True
            if content_type == "messagePhoto":
                return True
        except Exception:
            pass

    if not text or len(text) < MIN_RECEIPT_TEXT_LEN:
        return False

    if any(emoji in text for emoji in RECEIPT_EMOJI):
        return True

    text_lower = text.lower()
    return any(kw in text_lower for kw in RECEIPT_KEYWORDS_LOWER)


# ── TDLib message formatting ─────────────────────────────────────────────────

def format_tdlib_message(data: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Convert raw TDLib message dict into a flat ChatMessage-like dict.

    Returns a dict with keys: id, date, is_outgoing, sender_id, text,
    document, photo.  Returns ``None`` when *data* is falsy.
    """
    if not data:
        return None
    iso_date: Optional[str] = None
    timestamp = data.get("date")
    if timestamp:
        try:
            iso_date = datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat().replace("+00:00", "Z")
        except Exception:
            iso_date = None

    content = data.get("content") or {}
    content_type = content.get("@type", "")

    # TDLib text may be in root "text", root formattedText object, or content.text.text.
    text: Optional[str] = data.get("text")
    if isinstance(text, dict):
        text = text.get("text")
    if not isinstance(text, str) or not text.strip():
        content_text = content.get("text")
        if isinstance(content_text, dict):
            text = content_text.get("text")
        elif isinstance(content_text, str):
            text = content_text

    # Caption fallback for document/photo messages.
    caption = content.get("caption")
    if (not text or not str(text).strip()) and caption:
        if isinstance(caption, dict):
            text = caption.get("text")
        elif isinstance(caption, str):
            text = caption

    document = data.get("document")
    if not document and content_type == "messageDocument":
        doc = content.get("document") or {}
        doc_file = doc.get("document") if isinstance(doc.get("document"), dict) else {}
        document = {
            "file_id": doc_file.get("id") or doc_file.get("file_id") or doc.get("id") or doc.get("file_id"),
            "file_name": doc.get("file_name"),
            "mime_type": doc.get("mime_type") or doc_file.get("mime_type"),
        }

    photo = data.get("photo")
    if not photo and content_type == "messagePhoto":
        photo_content = content.get("photo") or {}
        sizes = photo_content.get("sizes") or []
        if sizes:
            biggest = max(
                sizes,
                key=lambda size: (size.get("width", 0) * size.get("height", 0)),
            )
            photo_file = biggest.get("photo") if isinstance(biggest.get("photo"), dict) else biggest
            photo = {
                "file_id": photo_file.get("id") or photo_file.get("file_id"),
                "file_name": "photo.jpg",
                "mime_type": "image/jpeg",
            }

    sender_id: Any = data.get("sender_id")
    if isinstance(sender_id, dict):
        sender_id = (
            sender_id.get("user_id")
            or sender_id.get("chat_id")
            or sender_id.get("id")
        )

    return {
        "id": data.get("id"),
        "date": iso_date,
        "is_outgoing": data.get("is_outgoing", False),
        "sender_id": sender_id,
        "text": text,
        "document": document,
        "photo": photo,
    }


# ── Task payload builder ─────────────────────────────────────────────────────

def build_task_data_from_message(
    chat_id: int,
    message_id: int,
    message: Dict[str, Any],
) -> Dict[str, Any]:
    """Convert formatted TDLib message into task payload for Celery."""
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
    elif document and str(document.get("mime_type") or "").lower().startswith("image/"):
        task_data["image"] = {
            "file_id": document.get("file_id"),
            "file_name": document.get("file_name"),
            "mime_type": document.get("mime_type"),
            "caption": raw_text,
        }
    photo = message.get("photo")
    if photo and photo.get("file_id"):
        task_data["image"] = {
            "file_id": photo.get("file_id"),
            "file_name": photo.get("file_name") or "photo.jpg",
            "mime_type": photo.get("mime_type") or "image/jpeg",
            "caption": raw_text,
        }
    return task_data
