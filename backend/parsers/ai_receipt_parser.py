"""Canonical AI receipt parser using DeepSeek text extraction only."""
from typing import Optional, Dict, Any, List
from datetime import datetime
from decimal import Decimal
import re
import logging
from pydantic import BaseModel, Field, field_validator
import pytz
from config.ai_models import DEEPSEEK_TEXT_MODEL
from parsers.regex_parser import normalize_localized_decimal
from services.ai_provider import get_text_ai_provider

logger = logging.getLogger(__name__)


class TransactionSchema(BaseModel):
    """Structured output schema for AI receipt parsing."""
    amount: Decimal = Field(gt=0, description="Transaction amount as a positive decimal")
    currency: str = Field(default="UZS", description="Currency code (UZS, USD, etc.)")
    transaction_date_iso: str = Field(description="Transaction date and time in ISO 8601 format (YYYY-MM-DDTHH:MM:SS)")
    card_last_4: Optional[str] = Field(None, description="Last 4 digits of card number")
    operator_raw: Optional[str] = Field(None, description="Raw operator/merchant name from receipt")
    transaction_type: str = Field(description="Transaction type: DEBIT, CREDIT, CONVERSION, or REVERSAL")
    balance_after: Optional[Decimal] = Field(None, ge=0, description="Account balance after transaction")
    receiver_name: Optional[str] = Field(None, description="Receiver name for P2P transfers (e.g., Иван Иванов)")
    receiver_card: Optional[str] = Field(None, description="Last 4 digits of receiver card for P2P transfers")
    confidence: float = Field(ge=0.0, le=1.0, description="Confidence score from 0.0 to 1.0")

    @field_validator("transaction_type", mode="before")
    @classmethod
    def _normalize_transaction_type(cls, value: Any) -> str:
        allowed = {"DEBIT", "CREDIT", "CONVERSION", "REVERSAL"}
        if not value:
            raise ValueError("transaction_type is required")
        token = str(value).strip().upper()
        if token in allowed:
            return token
        synonyms = {
            "WITHDRAWAL": "DEBIT", "WITHDRAW": "DEBIT", "PAYMENT": "DEBIT",
            "PURCHASE": "DEBIT", "SPEND": "DEBIT", "FEE": "DEBIT", "CHARGE": "DEBIT",
            "TRANSFER": "DEBIT", "TRANSFER_OUT": "DEBIT", "OUT": "DEBIT",
            "DEPOSIT": "CREDIT", "REFUND": "CREDIT", "TRANSFER_IN": "CREDIT", "IN": "CREDIT",
            "EXCHANGE": "CONVERSION", "CONVERT": "CONVERSION",
            "CANCEL": "REVERSAL", "CANCELLED": "REVERSAL", "VOID": "REVERSAL",
        }
        normalized = synonyms.get(token)
        if normalized is None:
            raise ValueError(f"Unsupported transaction type: {value!r}")
        return normalized

    @field_validator("amount", "balance_after", mode="before")
    @classmethod
    def _coerce_amount(cls, value: Any) -> Optional[Decimal]:
        """Accept '3,000,000.00' / '3 000 000,00' / '3.000.000' / numeric."""
        if value is None or value == "":
            return None
        if isinstance(value, bool):
            raise ValueError("Boolean is not a monetary amount")
        if isinstance(value, (int, float, Decimal)):
            if Decimal(str(value)) < 0:
                raise ValueError("Monetary amount cannot be negative")
            return normalize_localized_decimal(value)
        token = str(value).strip()
        if re.match(r"^[\-−]", token):
            raise ValueError("Monetary amount cannot be negative")
        token = re.sub(
            r"\s*(?:UZS|USD|EUR|RUB|KZT|GBP|CNY|СУМ|СЎМ|SUM)\s*$",
            "",
            token,
            flags=re.IGNORECASE,
        )
        if re.search(r"[^0-9\s,.'’+]", token):
            raise ValueError("Monetary amount contains unsupported characters")
        return normalize_localized_decimal(token)

    @field_validator("transaction_date_iso", mode="before")
    @classmethod
    def _validate_transaction_date(cls, value: Any) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("transaction_date_iso is required")
        token = value.strip()
        if not re.search(r"[T ]\d{2}:\d{2}", token):
            raise ValueError("transaction_date_iso must include date and time")
        try:
            datetime.fromisoformat(token.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("transaction_date_iso must be valid ISO 8601") from exc
        return token

    @field_validator("card_last_4", "receiver_card", mode="before")
    @classmethod
    def _normalize_card_last_4(cls, value: Any) -> Optional[str]:
        if value is None or value == "":
            return None
        token = str(value).strip()
        if re.search(r"[^0-9*\s-]", token):
            raise ValueError("Card field contains unsupported characters")
        digits = re.sub(r"\D", "", token)
        if len(digits) < 4:
            raise ValueError("Card field must contain at least four digits")
        return digits[-4:]

    @field_validator("currency", mode="before")
    @classmethod
    def _normalize_currency(cls, value: Any) -> str:
        allowed = {"UZS", "USD", "EUR", "RUB", "KZT", "GBP", "CNY"}
        token = str(value or "UZS").strip().upper()
        # Common synonyms / OCR slips
        synonyms = {
            "СУМ": "UZS", "СЎМ": "UZS", "SUM": "UZS",
            "TENGE": "KZT", "ТЕНГЕ": "KZT",
            "RUBLE": "RUB", "РУБЛЬ": "RUB", "РУБ": "RUB",
            "EURO": "EUR", "ЕВРО": "EUR",
            "DOLLAR": "USD", "ДОЛЛАР": "USD",
        }
        token = synonyms.get(token, token)
        if token not in allowed:
            raise ValueError(f"Unsupported currency: {value!r}")
        return token


class ApplicationResolveSchema(BaseModel):
    """Structured output for application resolution"""
    application_name: str
    is_p2p: bool
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    recommended_operator_name: Optional[str] = None
    reasoning: Optional[str] = None


class ReceiptAiParser:
    """Parser using DeepSeek text completion for receipt extraction."""

    def __init__(self, api_key: Optional[str] = None, timezone: str = "Asia/Tashkent", allow_without_api_key: bool = True):
        self.text_provider = get_text_ai_provider()
        self.text_enabled = bool(self.text_provider.enabled)
        self.compat_api_key = api_key
        if not self.text_enabled and not allow_without_api_key:
            raise ValueError("AI provider is required")
        self.enabled = self.text_enabled
        self.tz = pytz.timezone(timezone)
        self.last_error_kind: Optional[str] = None

        self.system_prompt = """You are a financial data analyst specialized in Uzbek payment systems.

Your task is to analyze receipt text from Uzbek banks and payment systems (Uzcard, Humo, Click, Payme, etc.) and extract structured transaction data.

Context:
- Amounts are typically in UZS (Uzbek Som), sometimes in USD
- Dates follow DD.MM.YYYY or YY-MM-DD formats
- 'Operator' refers to the payment gateway or merchant (e.g., Payme, Click, Paynet, NBU, SmartBank)
- Card numbers are shown as last 4 digits with asterisks (e.g., ***6714 or *6714)
- Transaction types:
  * DEBIT: Payments, purchases, withdrawals (Оплата, Pokupka, Spisanie)
  * CREDIT: Deposits, refunds (Пополнение, Popolnenie)
  * CONVERSION: Currency exchange (Конверсия)
  * REVERSAL: Cancellation (OTMENA)
- For P2P transfers (card-to-card, person-to-person):
  * Extract receiver name if shown (e.g., "Получатель: Иван Иванов", "Receiver: John Smith")
  * Extract last 4 digits of receiver card if shown (e.g., "Карта получателя: ***1234")

Extract all available fields with high confidence. If a field is not present, return null.
For dates, convert to ISO 8601 format (YYYY-MM-DDTHH:MM:SS).
Provide a confidence score based on data clarity.

Return ONLY a JSON object with EXACTLY these keys (use null for unknown values, not omit):
- amount (number, required)
- currency (string, default "UZS")
- transaction_date_iso (string ISO 8601, required — never omit, never rename to "date")
- card_last_4 (string|null)
- operator_raw (string|null)
- transaction_type (string, one of: DEBIT, CREDIT, CONVERSION, REVERSAL — required)
- balance_after (number|null)
- receiver_name (string|null)
- receiver_card (string|null)
- confidence (number 0..1, required)"""

    def _mask_sensitive_text(self, text: str) -> str:
        """Mask long digit sequences to avoid leaking card/phone numbers."""
        if not text:
            return text

        def mask_digits(match: re.Match) -> str:
            digits = re.sub(r"\D", "", match.group(0))
            if len(digits) <= 8:
                return match.group(0)
            last4 = digits[-4:]
            return f"{'*' * max(4, len(digits) - 4)}{last4}"

        # Card numbers: 12-19 digits with optional separators
        masked = re.sub(r"(?:\d[ -]?){12,19}", mask_digits, text)
        # Phone numbers: +? with 10-15 digits
        masked = re.sub(r"\+?\d[\d -]{9,14}", mask_digits, masked)
        return masked

    def _convert_schema(self, parsed: TransactionSchema, *, date_source: str = "receipt") -> Dict[str, Any]:
        transaction_date = datetime.fromisoformat(parsed.transaction_date_iso.replace('Z', '+00:00'))
        if transaction_date.tzinfo is None:
            transaction_date = self.tz.localize(transaction_date)
        else:
            transaction_date = transaction_date.astimezone(self.tz)
        # Strip timezone info so naive local time goes to DB without UTC conversion
        transaction_date = transaction_date.replace(tzinfo=None)

        return {
            'amount': parsed.amount,
            'currency': parsed.currency,
            'transaction_type': parsed.transaction_type,
            'card_last_4': parsed.card_last_4,
            'operator_raw': parsed.operator_raw,
            'transaction_date': transaction_date,
            'balance_after': parsed.balance_after if parsed.balance_after is not None else None,
            'receiver_name': parsed.receiver_name[:255] if parsed.receiver_name else None,
            'receiver_card': parsed.receiver_card if parsed.receiver_card else None,
            # Legacy DB enum retained for backward compatibility; user-facing UI treats this as generic AI parsing.
            'parsing_method': 'GPT',
            'parsing_confidence': parsed.confidence,
            'date_source': date_source,
        }

    @staticmethod
    def _with_source_datetime(result: Any, fallback_datetime: Optional[datetime]) -> tuple[Any, str]:
        """Use trusted ingestion time only when the receipt/AI has no date."""
        if not isinstance(result, dict):
            return result, "receipt"
        if result.get("transaction_date_iso") not in (None, ""):
            return result, "receipt"
        if fallback_datetime is None:
            return result, "receipt"
        if not isinstance(fallback_datetime, datetime):
            raise ValueError("fallback_datetime must be a datetime")
        enriched = dict(result)
        enriched["transaction_date_iso"] = fallback_datetime.isoformat()
        return enriched, "source_received_at"

    def parse(self, text: str, fallback_datetime: Optional[datetime] = None) -> Optional[Dict[str, Any]]:
        """Parse receipt text via the shared DeepSeek text provider."""
        if not self.text_enabled:
            self.last_error_kind = "disabled"
            logger.info("AI text parsing skipped: DEEPSEEK_API_KEY not configured")
            return None
        self.last_error_kind = None
        masked_text = self._mask_sensitive_text(text or "")
        base_messages = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": f"Parse this Uzbek financial receipt:\n\n{masked_text}"},
        ]
        try:
            result = self.text_provider.complete_json_sync(
                model=DEEPSEEK_TEXT_MODEL,
                messages=base_messages,
                temperature=0.1,
                max_tokens=900,
                retry_count=0,
                timeout_seconds=25,
            )
            result, date_source = self._with_source_datetime(result, fallback_datetime)
            parsed = TransactionSchema.model_validate(result)
            self.last_error_kind = None
            return self._convert_schema(parsed, date_source=date_source)
        except Exception as first_exc:  # noqa: BLE001
            from pydantic import ValidationError as _PydValidationError

            if not isinstance(first_exc, _PydValidationError):
                self.last_error_kind = "transient"
                logger.warning("AI text parsing error: %s", first_exc)
                return None
            # One-shot retry with the validation error fed back to the model.
            try:
                err_msg = str(first_exc)[:600]
                retry_messages = base_messages + [
                    {
                        "role": "system",
                        "content": (
                            "Previous response failed schema validation. Return strict JSON "
                            "matching all required keys (amount as number, transaction_date_iso "
                            "as ISO 8601, transaction_type as DEBIT/CREDIT/CONVERSION/REVERSAL, "
                            "confidence 0..1). Errors: " + err_msg
                        ),
                    }
                ]
                result = self.text_provider.complete_json_sync(
                    model=DEEPSEEK_TEXT_MODEL,
                    messages=retry_messages,
                    temperature=0.05,
                    max_tokens=900,
                    retry_count=0,
                    timeout_seconds=25,
                )
                result, date_source = self._with_source_datetime(result, fallback_datetime)
                parsed = TransactionSchema.model_validate(result)
                self.last_error_kind = None
                return self._convert_schema(parsed, date_source=date_source)
            except Exception as second_exc:  # noqa: BLE001
                self.last_error_kind = (
                    "validation" if isinstance(second_exc, _PydValidationError) else "transient"
                )
                logger.warning(
                    "AI text parsing failed after retry: first=%s second=%s",
                    first_exc,
                    second_exc,
                )
                return None

    def resolve_application(
        self,
        operator_raw: str,
        raw_text: str,
        known_apps: List[str],
        dictionary_hints: List[Dict[str, Any]],
    ) -> Optional[Dict[str, Any]]:
        """
        Resolve application and P2P flag using the shared AI text provider.
        """
        if not self.text_enabled:
            logger.info("Application resolve skipped: DEEPSEEK_API_KEY not configured")
            return None

        try:
            hints_formatted = []
            for hint in dictionary_hints[:10]:
                op_name = hint.get("operator_name") or hint.get("matched_operator_name") or ""
                app_name = hint.get("application_name") or "Unknown"
                p2p_val = hint.get("is_p2p")
                hints_formatted.append(
                    f"{op_name} -> {app_name} (p2p={p2p_val})".strip()
                )

            system_prompt = (
                "You map merchant/operator strings to known applications and P2P status.\n"
                "- P2P means person-to-person transfers, card-to-card, or wallet-to-wallet between individuals.\n"
                "- If the operator clearly indicates transfers between people (e.g., P2P, card-to-card), set is_p2p=true.\n"
                "- If it is a merchant/shop/service/provider, set is_p2p=false.\n"
                "- Choose application_name from the provided known list if any matches well.\n"
                "- If none fit, return 'Unknown'.\n"
                "- Only invent a new application_name if the operator obviously represents a different app; otherwise prefer a known app or 'Unknown'.\n"
                "- Keep answers concise; reasoning is optional and brief.\n"
                "\n"
                "Return ONLY a JSON object with EXACTLY these keys:\n"
                "- application_name (string, required)\n"
                "- is_p2p (bool, required)\n"
                "- confidence (number 0..1, required — never omit)\n"
                "- recommended_operator_name (string|null)\n"
                "- reasoning (string|null)"
            )

            user_prompt_lines = [
                f"Operator raw: {operator_raw or ''}",
                f"Known applications: {', '.join(known_apps) if known_apps else '[]'}",
            ]
            if hints_formatted:
                user_prompt_lines.append("Dictionary hints:")
                for h in hints_formatted:
                    user_prompt_lines.append(f"- {h}")
            masked_text = self._mask_sensitive_text(raw_text or "")
            if masked_text:
                user_prompt_lines.append("Receipt text (masked):")
                user_prompt_lines.append(masked_text[:4000])  # keep prompt bounded

            result = self.text_provider.complete_json_sync(
                model=DEEPSEEK_TEXT_MODEL,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": "\n".join(user_prompt_lines)},
                ],
                temperature=0.15,
                max_tokens=600,
                retry_count=0,
                timeout_seconds=15,
            )
            parsed = ApplicationResolveSchema.model_validate(result)

            app_name = (parsed.application_name or "").strip()
            if not app_name:
                return None
            app_name = app_name[:200]

            confidence = parsed.confidence
            try:
                confidence = float(confidence)
            except Exception:
                confidence = 0.0
            confidence = max(0.0, min(1.0, confidence))

            result = {
                "application_name": app_name,
                "is_p2p": bool(parsed.is_p2p),
                "confidence": confidence,
                "recommended_operator_name": (parsed.recommended_operator_name or "").strip() or None,
                "reasoning": (parsed.reasoning or "").strip() or None,
            }
            return result
        except Exception as e:
            logger.warning("AI application resolve error: %s", e)
            return None


# Backward-compatible alias for legacy imports.
GPTParser = ReceiptAiParser
