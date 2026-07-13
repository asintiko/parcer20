"""Receipt processing event logger → Telegram channel.

Streams pipeline events (received / processed / failed / duplicate /
download_failed) to a configured Telegram chat. Designed to reuse the
existing AUTH_BOT_TOKEN; the logger is fail-safe — Telegram errors never
break the worker.

Configuration via env:
    AUTH_BOT_TOKEN              - already used by auth bot, mandatory
    RECEIPT_LOG_CHAT_ID         - target channel/group id (e.g. -1001234567890)
    RECEIPT_LOG_TOPIC_ID        - optional message_thread_id (for forum groups)
    RECEIPT_LOG_PREMIUM_EMOJI   - JSON map emoji_slug → custom_emoji_id, e.g.
                                  {"success":"5237701891081234567","failed":"...",
                                   "duplicate":"...","warning":"...","money":"...",
                                   "card":"...","clock":"...","gear":"...",
                                   "chart":"...","inbox":"...","bank":"...",
                                   "person":"...","loop":"..."}

When RECEIPT_LOG_PREMIUM_EMOJI is unset, plain Unicode emoji are used.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from threading import Lock, Thread
from typing import Any, Dict, List, Optional, Tuple

import httpx

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# PII redaction helpers (defence-in-depth before sending to TG channel)
# --------------------------------------------------------------------------- #
_CARD_REGEX = re.compile(r"(?:\d[ -]?){12,19}")
_PHONE_REGEX = re.compile(r"\+?\d[\d \-]{9,14}")


def _redact_pii(text: Optional[str]) -> Optional[str]:
    if not text:
        return text

    def _mask_card(match: "re.Match[str]") -> str:
        digits = re.sub(r"\D", "", match.group(0))
        if len(digits) < 12:
            return match.group(0)
        return f"***{digits[-4:]}"

    def _mask_phone(match: "re.Match[str]") -> str:
        digits = re.sub(r"\D", "", match.group(0))
        if len(digits) < 10:
            return match.group(0)
        return f"***{digits[-4:]}"

    masked = _CARD_REGEX.sub(_mask_card, text)
    masked = _PHONE_REGEX.sub(_mask_phone, masked)
    return masked


# --------------------------------------------------------------------------- #
# Emoji catalogue: slug → unicode fallback
# --------------------------------------------------------------------------- #
EMOJI_FALLBACK: Dict[str, str] = {
    "success": "✅",
    "failed": "❌",
    "duplicate": "♻️",
    "warning": "⚠️",
    "info": "ℹ️",
    "money": "💰",
    "card": "💳",
    "clock": "🗓",
    "gear": "⚙️",
    "chart": "📊",
    "inbox": "📥",
    "bank": "🏦",
    "person": "👤",
    "loop": "🔁",
    "stopwatch": "⏱",
    "file": "📄",
}


def _load_premium_emoji_map() -> Dict[str, str]:
    raw = os.getenv("RECEIPT_LOG_PREMIUM_EMOJI", "").strip()
    if not raw:
        return {}
    try:
        data = json.loads(raw)
        if isinstance(data, dict):
            return {str(k): str(v) for k, v in data.items() if v}
    except Exception as exc:  # noqa: BLE001
        logger.warning("RECEIPT_LOG_PREMIUM_EMOJI is invalid JSON: %s", exc)
    return {}


# --------------------------------------------------------------------------- #
# HTML helpers
# --------------------------------------------------------------------------- #
def _esc(value: Any) -> str:
    """Escape text for Telegram HTML parse_mode."""
    if value is None:
        return ""
    text = str(value)
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def _format_amount(amount: Any, currency: str = "UZS") -> str:
    if amount is None:
        return "—"
    try:
        d = Decimal(str(amount))
    except Exception:  # noqa: BLE001
        return _esc(amount)
    sign = "−" if d < 0 else ""
    abs_d = abs(d)
    int_part, _, frac_part = f"{abs_d:.2f}".partition(".")
    grouped = "{:,}".format(int(int_part)).replace(",", " ")
    return f"{sign}{grouped} {currency}".strip()


def _format_dt(value: Any) -> str:
    if value is None:
        return "—"
    if isinstance(value, datetime):
        return value.strftime("%d.%m.%Y %H:%M")
    s = str(value).split("+")[0].split(".")[0].strip()
    try:
        dt = datetime.fromisoformat(s)
        return dt.strftime("%d.%m.%Y %H:%M")
    except ValueError:
        return s


def _short_card(card: Any) -> str:
    if not card:
        return "***"
    s = str(card).strip()
    digits = "".join(ch for ch in s if ch.isdigit())
    if not digits:
        return s
    return f"***{digits[-4:]}"


def humanize_error(raw: Any) -> str:
    """Map a raw error/exception string to a short, human-friendly RU phrase.

    The receipt-log channel is read by a non-technical client, so we never show
    SQL dumps, stack traces, or English internals. Unknown errors degrade to a
    generic 'не удалось обработать' rather than leaking the raw text.
    """
    s = str(raw or "").strip().lower()
    if not s:
        return "Не удалось обработать чек"
    # Duplicate (unique constraint / explicit duplicate)
    if "duplicate" in s or "uq_transactions" in s or "уже" in s or "дубл" in s:
        return "Дубликат — этот чек уже есть в базе"
    # Parse / recognition failures
    if "cannot parse" in s or "parsed data missing" in s or "parse confidence" in s or "не удалось распознать" in s:
        return "Не удалось распознать чек"
    if "empty message" in s:
        return "Пустое сообщение — нечего распознавать"
    if "screenshot" in s:
        return "Не удалось распознать чек со скриншота"
    # Download / file issues
    if "timed out downloading" in s or "timeout" in s:
        return "Превышено время загрузки файла из Telegram"
    if "failed to download" in s or "file not found" in s:
        return "Не удалось скачать файл из Telegram"
    if "unsupported document" in s:
        return "Неподдерживаемый тип файла"
    if "ocr" in s or "extract" in s or "tesseract" in s:
        return "Не удалось извлечь текст из изображения/PDF"
    # Infra
    if "message not found" in s:
        return "Сообщение не найдено в Telegram"
    if "failed to save" in s or "integrityerror" in s or "psycopg" in s:
        return "Ошибка сохранения в базу"
    if "parser initialization" in s:
        return "Парсер временно недоступен"
    # Fallback — never leak raw internals
    return "Не удалось обработать чек"


# --------------------------------------------------------------------------- #
# Background sender (httpx + dedicated thread loop, never blocks worker)
# --------------------------------------------------------------------------- #
class _BackgroundSender:
    """Owns a single asyncio loop running on a dedicated thread.

    Worker code calls `enqueue(coro)`. The loop is created lazily on first
    use, lives until process exit. Failures are logged but never re-raised.
    """

    def __init__(self) -> None:
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[Thread] = None
        self._lock = Lock()

    def _start_loop(self) -> asyncio.AbstractEventLoop:
        with self._lock:
            if self._loop is not None and self._loop.is_running():
                return self._loop
            loop = asyncio.new_event_loop()

            def _runner() -> None:
                asyncio.set_event_loop(loop)
                try:
                    loop.run_forever()
                except Exception:  # noqa: BLE001
                    logger.exception("Receipt-log loop crashed")
                finally:
                    try:
                        loop.close()
                    except Exception:  # noqa: BLE001
                        pass

            t = Thread(target=_runner, name="receipt-log-loop", daemon=True)
            t.start()
            self._loop = loop
            self._thread = t
            return loop

    def submit(self, coro) -> None:
        try:
            loop = self._start_loop()
            asyncio.run_coroutine_threadsafe(coro, loop)
        except Exception:  # noqa: BLE001
            logger.exception("Failed to schedule receipt-log task")


_sender = _BackgroundSender()


# --------------------------------------------------------------------------- #
# Public dataclass
# --------------------------------------------------------------------------- #
@dataclass
class ReceiptEvent:
    kind: str  # "received" | "processed" | "failed" | "duplicate" | "download_failed"
    task_id: Optional[int] = None
    transaction_id: Optional[int] = None
    chat_title: Optional[str] = None
    chat_id: Optional[int] = None
    message_id: Optional[int] = None
    file_name: Optional[str] = None
    amount: Any = None
    currency: str = "UZS"
    transaction_date: Any = None
    operator: Optional[str] = None
    receiver_name: Optional[str] = None
    sender_card: Optional[str] = None
    receiver_card: Optional[str] = None
    parsing_method: Optional[str] = None
    parsing_confidence: Optional[float] = None
    is_p2p: bool = False
    duration_seconds: Optional[float] = None
    duplicate_of_id: Optional[int] = None
    error_summary: Optional[str] = None
    rejection_reason: Optional[str] = None
    ocr_preview: Optional[str] = None
    request_id: Optional[str] = None
    extra: Dict[str, Any] = field(default_factory=dict)


# --------------------------------------------------------------------------- #
# Renderer
# --------------------------------------------------------------------------- #
class _Renderer:
    """Builds (text, entities) for Telegram sendMessage.

    With RECEIPT_LOG_PREMIUM_EMOJI configured, emoji_slug occurrences in the
    plain template are replaced with custom_emoji entities. Without the env,
    Unicode fallback is used and entities list is empty (Telegram still parses
    HTML <b>/<spoiler>).
    """

    def __init__(self) -> None:
        self.premium = _load_premium_emoji_map()

    # — emoji helpers —
    def _emoji(self, slug: str) -> str:
        return EMOJI_FALLBACK.get(slug, "")

    def _premium_id(self, slug: str) -> Optional[str]:
        return self.premium.get(slug)

    def _build_entities(self, text: str) -> List[Dict[str, Any]]:
        """Walk the text and emit MessageEntity for each emoji whose slug has a
        premium id. Locates emoji by Unicode fallback in the rendered text.
        """
        if not self.premium:
            return []
        entities: List[Dict[str, Any]] = []
        # Map unicode → slug for ones with premium id
        unicode_to_slug = {
            EMOJI_FALLBACK[slug]: slug
            for slug in self.premium.keys()
            if slug in EMOJI_FALLBACK
        }
        idx = 0
        # Iterate over UTF-16 code units (Telegram offsets are UTF-16)
        utf16 = text.encode("utf-16-le")
        # Walk char-by-char in Python (string), translate to utf-16 offset
        utf16_offset = 0
        for ch in text:
            ch_utf16_len = len(ch.encode("utf-16-le")) // 2
            # 1- or 2-char base emoji (some have variation selector ️=️)
            tail = text[idx : idx + 2]
            head = text[idx : idx + 1]
            matched_slug: Optional[str] = None
            matched_len_chars = 0
            matched_len_units = 0
            if tail in unicode_to_slug:
                matched_slug = unicode_to_slug[tail]
                matched_len_chars = 2
                matched_len_units = len(tail.encode("utf-16-le")) // 2
            elif head in unicode_to_slug:
                matched_slug = unicode_to_slug[head]
                matched_len_chars = 1
                matched_len_units = ch_utf16_len
            if matched_slug:
                entities.append(
                    {
                        "type": "custom_emoji",
                        "offset": utf16_offset,
                        "length": matched_len_units,
                        "custom_emoji_id": self.premium[matched_slug],
                    }
                )
                idx += matched_len_chars
                utf16_offset += matched_len_units
                continue
            idx += 1
            utf16_offset += ch_utf16_len
        # silence unused
        _ = utf16
        return entities

    # — header builder —
    def _header(self, event: ReceiptEvent) -> Tuple[str, str]:
        """Returns (icon_emoji, headline)."""
        if event.kind == "processed":
            ref = f"#{event.transaction_id}" if event.transaction_id else "—"
            return self._emoji("success"), f"{ref} · Чек обработан"
        if event.kind == "duplicate":
            ref = (
                f"#{event.transaction_id}"
                if event.transaction_id
                else (f"#{event.duplicate_of_id}" if event.duplicate_of_id else "—")
            )
            return self._emoji("duplicate"), f"{ref} · Дубликат пропущен"
        if event.kind == "failed":
            ref = f"#{event.task_id} · " if event.task_id else ""
            return self._emoji("failed"), f"{ref}Чек не обработан"
        if event.kind == "download_failed":
            ref = f"#{event.task_id} · " if event.task_id else ""
            return self._emoji("failed"), f"{ref}Не удалось скачать файл"
        if event.kind == "received":
            ref = f"#{event.task_id} · " if event.task_id else ""
            return self._emoji("inbox"), f"{ref}Принят в обработку"
        return self._emoji("info"), event.kind

    # — body —
    def _body(self, event: ReceiptEvent) -> List[str]:
        lines: List[str] = []
        clock = self._emoji("clock")
        bank = self._emoji("bank")
        money = self._emoji("money")
        loop_e = self._emoji("loop")
        card = self._emoji("card")
        person = self._emoji("person")
        gear = self._emoji("gear")
        chart = self._emoji("chart")
        inbox = self._emoji("inbox")
        watch = self._emoji("stopwatch")
        file_e = self._emoji("file")

        if event.kind in ("processed", "duplicate"):
            line1 = f"{clock} {_esc(_format_dt(event.transaction_date))}"
            if event.operator:
                line1 += f"  ·  {bank} {_esc(event.operator)}"
            lines.append(line1)

            line2 = f"{money} {_esc(_format_amount(event.amount, event.currency))}"
            if event.is_p2p:
                line2 += f"  ·  {loop_e} P2P"
            lines.append(line2)

            cards = []
            if event.sender_card:
                cards.append(_short_card(event.sender_card))
            if event.receiver_card and event.receiver_card != event.sender_card:
                cards.append(_short_card(event.receiver_card))
            if cards:
                arrow_line = f"{card} {' → '.join(_esc(c) for c in cards)}"
                if event.receiver_name:
                    arrow_line += f"  ·  {person} {_esc(event.receiver_name)}"
                lines.append(arrow_line)

            method_line = []
            if event.parsing_method:
                method_line.append(f"{gear} {_esc(event.parsing_method)}")
            if event.parsing_confidence is not None:
                method_line.append(f"{chart} conf {event.parsing_confidence:.2f}")
            if method_line:
                lines.append("  ·  ".join(method_line))

            tail = []
            if event.chat_title or event.chat_id:
                tail.append(f"{inbox} {_esc(event.chat_title or event.chat_id)}")
            if event.duration_seconds is not None:
                tail.append(f"{watch} {event.duration_seconds:.1f}s")
            if tail:
                lines.append("  ·  ".join(tail))

            if event.kind == "duplicate" and event.duplicate_of_id:
                lines.append(f"{loop_e} Дубликат записи #{event.duplicate_of_id}")

        elif event.kind == "failed":
            reason = humanize_error(event.rejection_reason or event.error_summary)
            lines.append(f"<b>{_esc(reason)}</b>")
            lines.append("Нажмите «🔁 Повторно обработать», чтобы попробовать ещё раз.")
            tail = []
            if event.chat_title or event.chat_id:
                tail.append(f"{inbox} {_esc(event.chat_title or event.chat_id)}")
            if event.file_name:
                tail.append(f"{file_e} {_esc(event.file_name)}")
            if tail:
                lines.append("  ·  ".join(tail))

        elif event.kind == "download_failed":
            lines.append(f"<b>{_esc(humanize_error(event.error_summary or 'failed to download'))}</b>")
            lines.append("Нажмите «🔁 Повторно обработать», чтобы попробовать ещё раз.")
            tail = []
            if event.chat_title or event.chat_id:
                tail.append(f"{inbox} {_esc(event.chat_title or event.chat_id)}")
            if event.file_name:
                tail.append(f"{file_e} {_esc(event.file_name)}")
            if tail:
                lines.append("  ·  ".join(tail))

        elif event.kind == "received":
            tail = []
            if event.chat_title or event.chat_id:
                tail.append(f"{inbox} {_esc(event.chat_title or event.chat_id)}")
            if event.file_name:
                tail.append(f"{file_e} {_esc(event.file_name)}")
            if tail:
                lines.append("  ·  ".join(tail))

        return lines

    # — OCR spoiler —
    def _ocr_block(self, event: ReceiptEvent) -> str:
        text = (event.ocr_preview or "").strip()
        if not text:
            return ""
        text = _redact_pii(text) or ""
        # Limit to ~1500 chars; Telegram message hard-limit is 4096.
        if len(text) > 1500:
            text = text[:1500].rstrip() + "…"
        return f"\n<blockquote expandable>{_esc(text)}</blockquote>"

    # — request id footer —
    def _footer(self, event: ReceiptEvent) -> str:
        bits: List[str] = []
        if event.request_id:
            bits.append(f"req <code>{_esc(event.request_id)}</code>")
        if event.message_id and event.chat_id:
            bits.append(f"msg <code>{event.chat_id}/{event.message_id}</code>")
        return "\n<i>" + "  ·  ".join(bits) + "</i>" if bits else ""

    def render(self, event: ReceiptEvent) -> Tuple[str, List[Dict[str, Any]]]:
        icon, headline = self._header(event)
        head_line = f"{icon} <b>{_esc(headline)}</b>"
        body_lines = self._body(event)
        text = head_line + "\n\n" + "\n".join(body_lines) if body_lines else head_line
        text += self._ocr_block(event)
        text += self._footer(event)
        # Cap at 4096 chars (Telegram limit) including HTML tags
        if len(text) > 4096:
            text = text[:4090] + "\n…"
        entities = self._build_entities(text)
        return text, entities


# --------------------------------------------------------------------------- #
# Telegram client
# --------------------------------------------------------------------------- #
class _TelegramClient:
    def __init__(self) -> None:
        self.token = os.getenv("AUTH_BOT_TOKEN", "").strip()
        self.chat_id = int(os.getenv("RECEIPT_LOG_CHAT_ID", "0") or 0) or None
        self.topic_id = int(os.getenv("RECEIPT_LOG_TOPIC_ID", "0") or 0) or None
        self.timeout = float(os.getenv("RECEIPT_LOG_TIMEOUT", "10") or 10)
        self._http: Optional[httpx.AsyncClient] = None

    @property
    def configured(self) -> bool:
        return bool(self.token and self.chat_id)

    def _get_http(self) -> httpx.AsyncClient:
        if self._http is None or self._http.is_closed:
            self._http = httpx.AsyncClient(
                timeout=httpx.Timeout(self.timeout, connect=5.0),
                limits=httpx.Limits(max_keepalive_connections=4, max_connections=8),
            )
        return self._http

    async def send(self, text: str, entities: List[Dict[str, Any]], reply_markup: Optional[Dict[str, Any]] = None) -> None:
        if not self.configured:
            return
        url = f"https://api.telegram.org/bot{self.token}/sendMessage"
        payload: Dict[str, Any] = {
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }
        if self.topic_id:
            payload["message_thread_id"] = self.topic_id
        if entities:
            payload["entities"] = entities
            # When entities[] is supplied, parse_mode is ignored — but
            # custom_emoji entities can coexist with HTML if we pre-render
            # HTML to plain text. To keep it simple, when premium emoji are
            # configured we still send parse_mode=HTML; Telegram allows
            # mixing custom_emoji entities with HTML/markdown.
        if reply_markup:
            payload["reply_markup"] = reply_markup
        try:
            client = self._get_http()
            resp = await client.post(url, json=payload)
            if resp.status_code >= 400:
                logger.warning(
                    "Receipt-log Telegram send failed: %s %s",
                    resp.status_code,
                    resp.text[:300],
                )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Receipt-log Telegram send raised: %s", exc)


_client = _TelegramClient()
_renderer = _Renderer()


def post_plain(text: str) -> None:
    """Post a pre-rendered HTML message to the receipt-log channel. Non-blocking.

    Fail-safe: no-op when the channel is unconfigured, never raises. Used by
    other services (e.g. agent notifications) to mirror events into the same
    Telegram channel where receipt logs go.
    """
    try:
        if not _client.configured or not (text or "").strip():
            return
        _sender.submit(_client.send(text, []))
    except Exception:  # noqa: BLE001
        logger.debug("post_plain failed", exc_info=True)


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #
def log_event(event: ReceiptEvent) -> None:
    """Schedule sending of a receipt-log event to Telegram. Non-blocking."""
    if not _client.configured:
        return
    # Auto-attach request_id from contextvar if not provided explicitly.
    if not event.request_id:
        try:
            from core.logging_config import get_request_id

            rid = get_request_id()
            if rid:
                event.request_id = rid
        except Exception:  # noqa: BLE001
            pass
    try:
        text, entities = _renderer.render(event)
    except Exception:  # noqa: BLE001
        logger.exception("Receipt-log render failed; skipping")
        return
    reply_markup = _build_reply_markup(event)
    _sender.submit(_client.send(text, entities, reply_markup))


def _build_reply_markup(event: ReceiptEvent) -> Optional[Dict[str, Any]]:
    """Attach a 'reprocess' inline button to failure messages.

    callback_data format: `rcpt:repro:{chat_id}:{message_id}` (< 64 bytes:
    prefix 11 + two int64 ~ 40 max). Pressed in the log channel, handled by the
    auth bot which calls the backend internal reprocess endpoint.
    """
    if event.kind not in ("failed", "download_failed"):
        return None
    if event.chat_id is None or event.message_id is None:
        return None
    cb = f"rcpt:repro:{int(event.chat_id)}:{int(event.message_id)}"
    if len(cb.encode("utf-8")) > 64:
        return None
    return {"inline_keyboard": [[{"text": "🔁 Повторно обработать", "callback_data": cb}]]}


def log_received(*, task_id, chat_id, chat_title, message_id, request_id=None) -> None:
    log_event(
        ReceiptEvent(
            kind="received",
            task_id=task_id,
            chat_id=chat_id,
            chat_title=chat_title,
            message_id=message_id,
            request_id=request_id,
        )
    )


def log_processed(
    *,
    task_id,
    transaction_id,
    chat_id,
    chat_title,
    message_id,
    amount,
    currency="UZS",
    transaction_date,
    operator,
    receiver_name=None,
    sender_card=None,
    receiver_card=None,
    parsing_method,
    parsing_confidence=None,
    is_p2p=False,
    duration_seconds=None,
    file_name=None,
    ocr_preview=None,
    request_id=None,
) -> None:
    log_event(
        ReceiptEvent(
            kind="processed",
            task_id=task_id,
            transaction_id=transaction_id,
            chat_id=chat_id,
            chat_title=chat_title,
            message_id=message_id,
            amount=amount,
            currency=currency,
            transaction_date=transaction_date,
            operator=operator,
            receiver_name=receiver_name,
            sender_card=sender_card,
            receiver_card=receiver_card,
            parsing_method=parsing_method,
            parsing_confidence=parsing_confidence,
            is_p2p=is_p2p,
            duration_seconds=duration_seconds,
            file_name=file_name,
            ocr_preview=ocr_preview,
            request_id=request_id,
        )
    )


def log_duplicate(
    *,
    task_id,
    transaction_id,
    duplicate_of_id,
    chat_id,
    chat_title,
    message_id,
    amount,
    currency="UZS",
    transaction_date,
    operator,
    request_id=None,
) -> None:
    log_event(
        ReceiptEvent(
            kind="duplicate",
            task_id=task_id,
            transaction_id=transaction_id,
            duplicate_of_id=duplicate_of_id,
            chat_id=chat_id,
            chat_title=chat_title,
            message_id=message_id,
            amount=amount,
            currency=currency,
            transaction_date=transaction_date,
            operator=operator,
            request_id=request_id,
        )
    )


def log_failed(
    *,
    task_id,
    chat_id=None,
    chat_title=None,
    message_id=None,
    file_name=None,
    rejection_reason=None,
    error_summary=None,
    ocr_preview=None,
    duration_seconds=None,
    request_id=None,
) -> None:
    log_event(
        ReceiptEvent(
            kind="failed",
            task_id=task_id,
            chat_id=chat_id,
            chat_title=chat_title,
            message_id=message_id,
            file_name=file_name,
            rejection_reason=rejection_reason,
            error_summary=error_summary,
            ocr_preview=ocr_preview,
            duration_seconds=duration_seconds,
            request_id=request_id,
        )
    )


def log_download_failed(
    *,
    task_id,
    chat_id=None,
    chat_title=None,
    file_name=None,
    error_summary=None,
    request_id=None,
) -> None:
    log_event(
        ReceiptEvent(
            kind="download_failed",
            task_id=task_id,
            chat_id=chat_id,
            chat_title=chat_title,
            file_name=file_name,
            error_summary=error_summary,
            request_id=request_id,
        )
    )
