"""
GPT-4o parser using OpenAI (text + vision)
Fallback parser for complex or irregular receipt formats
"""
from typing import Optional, Dict, Any, List
from datetime import datetime
from decimal import Decimal
import os
import json
import re
from openai import OpenAI
from pydantic import BaseModel, Field
import pytz


class TransactionSchema(BaseModel):
    """Structured output schema for GPT parsing"""
    amount: float = Field(description="Transaction amount as a number")
    currency: str = Field(default="UZS", description="Currency code (UZS, USD, etc.)")
    transaction_date_iso: str = Field(description="Transaction date and time in ISO 8601 format (YYYY-MM-DDTHH:MM:SS)")
    card_last_4: Optional[str] = Field(None, description="Last 4 digits of card number")
    operator_raw: Optional[str] = Field(None, description="Raw operator/merchant name from receipt")
    transaction_type: str = Field(description="Transaction type: DEBIT, CREDIT, CONVERSION, or REVERSAL")
    balance_after: Optional[float] = Field(None, description="Account balance after transaction")
    confidence: float = Field(description="Confidence score from 0.0 to 1.0")


class ApplicationResolveSchema(BaseModel):
    """Structured output for application resolution"""
    application_name: str
    is_p2p: bool
    confidence: float
    recommended_operator_name: Optional[str] = None
    reasoning: Optional[str] = None


class GPTParser:
    """Parser using OpenAI GPT-4o with Structured Outputs and vision fallback."""
    
    def __init__(self, api_key: Optional[str] = None, timezone: str = "Asia/Tashkent", allow_without_api_key: bool = True):
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        self.enabled = bool(self.api_key)
        if not self.enabled:
            if not allow_without_api_key:
                raise ValueError("OpenAI API key is required")
            self.client = None
        else:
            self.client = OpenAI(api_key=self.api_key)
        self.tz = pytz.timezone(timezone)
        
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

Extract all available fields with high confidence. If a field is not present, return null.
For dates, convert to ISO 8601 format (YYYY-MM-DDTHH:MM:SS).
Provide a confidence score based on data clarity.
Return ONLY a JSON object matching TransactionSchema keys."""
    
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

    def _convert_schema(self, parsed: TransactionSchema) -> Dict[str, Any]:
        transaction_date = datetime.fromisoformat(parsed.transaction_date_iso.replace('Z', '+00:00'))
        if transaction_date.tzinfo is None:
            transaction_date = self.tz.localize(transaction_date)
        else:
            transaction_date = transaction_date.astimezone(self.tz)

        return {
            'amount': Decimal(str(parsed.amount)),
            'currency': parsed.currency,
            'transaction_type': parsed.transaction_type,
            'card_last_4': parsed.card_last_4,
            'operator_raw': parsed.operator_raw,
            'transaction_date': transaction_date,
            'balance_after': Decimal(str(parsed.balance_after)) if parsed.balance_after else None,
            'parsing_method': 'GPT',
            'parsing_confidence': parsed.confidence
        }

    def parse(self, text: str) -> Optional[Dict[str, Any]]:
        """
        Parse receipt using GPT-4o with Structured Outputs.
        """
        if not self.enabled:
            print("⚠️ GPT parsing skipped: OpenAI API key not configured")
            return None
        try:
            masked_text = self._mask_sensitive_text(text or "")
            response = self.client.beta.chat.completions.parse(
                model="gpt-4o-2024-08-06",
                messages=[
                    {"role": "system", "content": self.system_prompt},
                    {"role": "user", "content": f"Parse this Uzbek financial receipt:\n\n{masked_text}"}
                ],
                response_format=TransactionSchema,
                temperature=0.1,
            )
            parsed = response.choices[0].message.parsed
            if not parsed:
                return None
            return self._convert_schema(parsed)
        except Exception as e:
            print(f"❌ GPT parsing error: {e}")
            return None

    def _extract_json(self, content: Optional[str]) -> Optional[Dict[str, Any]]:
        if not content:
            return None
        try:
            return json.loads(content)
        except Exception:
            pass
        # Try to extract JSON block from code fences
        try:
            match = re.search(r"\{.*\}", content, re.DOTALL)
            if match:
                return json.loads(match.group(0))
        except Exception:
            return None
        return None

    def parse_from_images(self, images_b64: List[str], text_hint: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """
        Vision-based parsing using GPT-4o images. Images are base64 PNG strings.
        """
        if not self.enabled:
            print("⚠️ Vision parsing skipped: OpenAI API key not configured")
            return None
        if not images_b64:
            return None

        prompt = (
            "Extract structured transaction data from these receipt images. "
            "Return ONLY a JSON object with keys: amount, currency, transaction_date_iso, "
            "card_last_4, operator_raw, transaction_type, balance_after, confidence."
        )
        user_content: List[Dict[str, Any]] = [{"type": "text", "text": prompt}]
        if text_hint:
            user_content.append(
                {
                    "type": "text",
                    "text": f"Additional text hint (masked):\n{self._mask_sensitive_text(text_hint)}",
                }
            )

        for img in images_b64:
            user_content.append({"type": "image_url", "image_url": {"url": f"data:image/png;base64,{img}"}})

        try:
            response = self.client.chat.completions.create(
                model="gpt-4o-2024-08-06",
                messages=[
                    {"role": "system", "content": self.system_prompt},
                    {"role": "user", "content": user_content},
                ],
                temperature=0.1,
                max_tokens=600,
            )
            raw_content = response.choices[0].message.content
            parsed_json = self._extract_json(raw_content)
            if not parsed_json:
                return None
            schema = TransactionSchema.model_validate(parsed_json)
            result = self._convert_schema(schema)
            # Mark vision usage explicitly
            result["parsing_method"] = "GPT_VISION"
            return result
        except Exception as e:
            print(f"❌ GPT vision parsing error: {e}")
            return None

    def resolve_application(
        self,
        operator_raw: str,
        raw_text: str,
        known_apps: List[str],
        dictionary_hints: List[Dict[str, Any]],
    ) -> Optional[Dict[str, Any]]:
        """
        Resolve application and P2P flag using GPT with structured output.
        """
        if not self.enabled:
            print("⚠️ Application resolve skipped: OpenAI API key not configured")
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
                "- Keep answers concise; reasoning is optional and brief."
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

            response = self.client.beta.chat.completions.parse(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": "\n".join(user_prompt_lines)},
                ],
                response_format=ApplicationResolveSchema,
                temperature=0.15,
            )

            parsed: ApplicationResolveSchema = response.choices[0].message.parsed  # type: ignore
            if not parsed:
                return None

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
            print(f"❌ GPT application resolve error: {e}")
            return None
