"""Shared receipt processing logic for TDLib messages."""
import asyncio
from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, Optional, TYPE_CHECKING

import pytz
from fastapi import HTTPException
from sqlalchemy.orm import Session

from database.models import Transaction
from parsers.parser_orchestrator import ParserOrchestrator
from parsers.pdf_extractor import extract_text_from_pdf, render_pdf_pages_to_png_base64
from services.telegram_tdlib_manager import TDLibUnavailableError, TelegramTDLibManager

if TYPE_CHECKING:
    # Avoid runtime circular import
    from api.routes.transactions import ProcessReceiptResponse, ParsingInfo


async def process_tdlib_message(
    chat_id: int,
    message_id: int,
    force: bool,
    db: Session,
    manager: TelegramTDLibManager,
) -> "ProcessReceiptResponse":
    """Process a Telegram message into a Transaction, reusing existing logic."""
    # Late imports to break circular dependency
    from api.routes.transactions import (
        ProcessReceiptResponse,
        ParsingInfo,
        infer_transaction_type,
        build_transaction_response,
    )
    # Duplicate check
    existing = (
        db.query(Transaction)
        .filter(
            Transaction.source_chat_id == str(chat_id),
            Transaction.source_message_id == str(message_id),
        )
        .first()
    )
    if existing and not force:
        return ProcessReceiptResponse(
            created=False,
            duplicate=True,
            transaction=build_transaction_response(existing),
            parsing=ParsingInfo(
                method=getattr(existing, "parsing_method", None),
                confidence=None,
                notes="Already processed",
            ),
        )

    # Fetch message
    try:
        message = await manager.get_message(chat_id, message_id)
    except TDLibUnavailableError as exc:  # pragma: no cover - infra errors
        raise HTTPException(status_code=503, detail=str(exc))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Failed to fetch message: {exc}")

    if not message:
        raise HTTPException(status_code=404, detail="Message not found")

    text: str = (message.get("text") or "").strip()
    file_id: Optional[int] = None
    mime_type: Optional[str] = None
    file_name: Optional[str] = None
    parsing_notes: Optional[str] = None
    caption = text

    document = message.get("document") or {}
    if document:
        mime_type = document.get("mime_type")
        file_name = document.get("file_name")
        file_id = document.get("file_id")
        text = text or ""
        if mime_type and mime_type != "application/pdf":
            raise HTTPException(status_code=400, detail=f"Unsupported document type: {mime_type}")

    try:
        orchestrator = ParserOrchestrator(db)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Parser initialization failed: {exc}")

    gpt_parser = orchestrator.gpt_parser

    raw_text_for_parser = text
    parsed: Optional[Dict[str, Any]] = None
    vision_used = False

    # Handle PDF documents
    is_pdf = (mime_type or "").lower() == "application/pdf" or (file_name or "").lower().endswith(".pdf")
    extracted_text: Optional[str] = None
    pdf_path: Optional[str] = None

    if is_pdf and file_id:
        try:
            pdf_path = await manager.download_file(file_id)
        except TDLibUnavailableError as exc:
            raise HTTPException(status_code=503, detail=str(exc))
        except asyncio.TimeoutError:
            raise HTTPException(status_code=504, detail="Timed out downloading PDF from TDLib")
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=f"Failed to download PDF: {exc}")

        if not pdf_path:
            raise HTTPException(status_code=404, detail="PDF file not found")

        try:
            extracted_text = extract_text_from_pdf(pdf_path, max_pages=2)
        except ImportError as exc:
            raise HTTPException(status_code=500, detail=str(exc))
        except Exception as exc:  # noqa: BLE001
            parsing_notes = f"PDF text extraction failed: {exc}"
            extracted_text = ""

        combined_text = "\n\n".join([p for p in [caption, extracted_text] if p]).strip()
        raw_text_for_parser = combined_text or caption or ""

        # Try text-first parsing when we have meaningful text
        if extracted_text and len(extracted_text) >= 80:
            parsed = orchestrator.process(raw_text_for_parser)
            conf = parsed.get("parsing_confidence") if parsed else None
            if conf is None or conf < 0.75:
                parsing_notes = (parsing_notes + "; " if parsing_notes else "") + "Text parse confidence low, trying vision"
                parsed = None

        # Vision fallback if text absent/short or parsing low confidence
        if not parsed:
            vision_used = True
            try:
                images_b64 = render_pdf_pages_to_png_base64(pdf_path, max_pages=2, dpi=150)
            except ImportError as exc:
                raise HTTPException(status_code=500, detail=str(exc))
            except Exception as exc:  # noqa: BLE001
                raise HTTPException(status_code=500, detail=f"Failed to render PDF: {exc}")

            if not gpt_parser or not getattr(gpt_parser, "enabled", False):
                raise HTTPException(
                    status_code=503,
                    detail="OpenAI API key not configured; cannot run vision parsing for PDF receipt",
                )

            parsed = gpt_parser.parse_from_images(images_b64, caption or extracted_text or "")
            if not parsed:
                raise HTTPException(status_code=422, detail="Cannot parse receipt from PDF images")

            # Apply operator mapping manually for vision path
            if parsed.get("operator_raw") and orchestrator.operator_mapper:
                try:
                    match = orchestrator.operator_mapper.map_operator_details(parsed["operator_raw"])
                    if match:
                        parsed["application_mapped"] = match.get("application_name")
                        if match.get("is_p2p") is not None:
                            parsed["is_p2p"] = match.get("is_p2p")
                    else:
                        parsed["application_mapped"] = None
                except Exception:
                    parsed["application_mapped"] = None

            if not raw_text_for_parser:
                raw_text_for_parser = caption or "[vision parsed PDF]"

    else:
        raw_text_for_parser = text
        if not raw_text_for_parser:
            raise HTTPException(status_code=422, detail="Empty message content")
        parsed = orchestrator.process(raw_text_for_parser)

    if not parsed:
        raise HTTPException(status_code=422, detail="Cannot parse receipt")

    transaction_date = parsed.get("transaction_date")
    if isinstance(transaction_date, str):
        try:
            transaction_date = datetime.fromisoformat(transaction_date)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=422, detail=f"Invalid transaction_date: {exc}")
    if not transaction_date:
        raise HTTPException(status_code=422, detail="Parsed data missing transaction_date")

    tz = pytz.timezone("Asia/Tashkent")
    if transaction_date.tzinfo:
        transaction_date = transaction_date.astimezone(tz)
    else:
        transaction_date = tz.localize(transaction_date)

    amount_val = parsed.get("amount")
    if amount_val is None:
        raise HTTPException(status_code=422, detail="Parsed data missing amount")
    amount = Decimal(str(amount_val))

    txn_type = infer_transaction_type(parsed.get("transaction_type"), raw_text_for_parser)
    store_amount = -abs(amount) if txn_type == "DEBIT" else abs(amount)

    operator_raw = parsed.get("operator_raw") or "Unknown"
    card_last4 = parsed.get("card_last_4") or parsed.get("card_last4") or "0000"
    balance_after = parsed.get("balance_after")
    application_mapped = parsed.get("application_mapped")
    currency = parsed.get("currency") or "UZS"

    is_gpt_parsed = (parsed.get("parsing_method") or "").upper().startswith("GPT")
    parsed_is_p2p = parsed.get("is_p2p")

    txn = Transaction(
        transaction_date=transaction_date,
        operator_raw=operator_raw,
        application_mapped=application_mapped,
        amount=store_amount,
        balance_after=balance_after,
        card_last_4=card_last4,
        is_p2p=parsed_is_p2p if parsed_is_p2p is not None else "P2P" in operator_raw.upper(),
        transaction_type=txn_type,
        currency=currency,
        source_type="AUTO",
        raw_message=raw_text_for_parser,
        parsing_method=parsed.get("parsing_method"),
        parsing_confidence=parsed.get("parsing_confidence"),
        is_gpt_parsed=is_gpt_parsed,
        source_chat_id=str(chat_id),
        source_message_id=str(message_id),
    )

    try:
        db.add(txn)
        db.commit()
        db.refresh(txn)
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to save transaction: {exc}")

    parsing_info = ParsingInfo(
        method=parsed.get("parsing_method"),
        confidence=parsed.get("parsing_confidence"),
        notes=parsing_notes,
    )

    return ProcessReceiptResponse(
        created=True,
        duplicate=False,
        transaction=build_transaction_response(txn),
        parsing=parsing_info,
    )
