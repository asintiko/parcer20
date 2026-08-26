"""Parser orchestrator - coordinates regex parsing and AI parsing with operator mapping."""
import os
import re
import logging
from datetime import datetime
from typing import Dict, Any, Optional
from sqlalchemy.orm import Session

from parsers.regex_parser import RegexParser
from parsers.ai_receipt_parser import ReceiptAiParser
from parsers.operator_mapper import OperatorMapper

logger = logging.getLogger(__name__)


class ParserOrchestrator:
    """Main parsing coordinator that cascades through parsing strategies."""

    def __init__(
        self,
        db_session: Optional[Session],
        ai_api_key: Optional[str] = None,
        allow_missing_ai: bool = True,
        openai_api_key: Optional[str] = None,
        allow_missing_openai: Optional[bool] = None,
        vision_api_key: Optional[str] = None,
    ):
        self.regex_parser = RegexParser()
        self.ai_parser = None
        self.ai_api_key = ai_api_key or vision_api_key or openai_api_key
        self.allow_missing_ai = allow_missing_ai if allow_missing_openai is None else bool(allow_missing_openai)
        try:
            self.ai_parser = ReceiptAiParser(api_key=self.ai_api_key, allow_without_api_key=self.allow_missing_ai)
        except Exception as e:
            logger.warning("AI parser unavailable at init: %s", e)
            self.ai_parser = None
        self.operator_mapper = OperatorMapper(db_session) if db_session is not None else None
        self.ai_application_mapping_enabled = str(
            os.getenv("AI_APPLICATION_MAPPING_ENABLED", "false")
        ).strip().lower() in {"1", "true", "yes", "on"}
        
        # Confidence threshold for accepting regex results
        self.confidence_threshold = 0.8
        self.last_rejection_reason: Optional[str] = None
    
    def process(
        self,
        raw_text: str,
        fallback_datetime: Optional[datetime] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Process raw receipt text through parsing cascade
        
        Strategy:
        1. Try regex parser first (fast, deterministic)
        2. If confidence < threshold or failure, use AI text parser
        3. Apply operator mapping to normalize operator name
        4. Return fully structured transaction data
        
        Args:
            raw_text: Raw receipt text from Telegram
            
        Returns:
            Fully parsed transaction dict with all fields
        """
        self.last_rejection_reason = None
        if not raw_text or not raw_text.strip():
            self.last_rejection_reason = "empty_input"
            return None
        
        parsed_data = None
        rejection_reasons = []
        
        # Step 1: Try regex parser
        try:
            parsed_data = self.regex_parser.parse(raw_text)
            
            # Check if result meets confidence threshold
            if parsed_data and parsed_data.get('parsing_confidence', 0) >= self.confidence_threshold:
                logger.info("Regex parsing successful: %s", parsed_data.get("parsing_method"))
            else:
                logger.info("Regex confidence too low or failed, falling back to AI parser")
                rejection_reasons.append(
                    f"regex: confidence={parsed_data.get('parsing_confidence') if parsed_data else 'None'}"
                )
                parsed_data = None
        except Exception as e:
            logger.warning("Regex parsing error: %s", e)
            rejection_reasons.append(f"regex_error: {e}")
            parsed_data = None
        
        # Step 2: Fallback to AI parser if regex failed and provider is available
        if not parsed_data:
            if not self.ai_parser:
                try:
                    self.ai_parser = ReceiptAiParser(api_key=self.ai_api_key, allow_without_api_key=self.allow_missing_ai)
                except Exception as e:
                    logger.warning("AI parser instantiation failed: %s", e)
                    rejection_reasons.append(f"ai_init_error: {e}")
                    self.ai_parser = None

            if self.ai_parser and self.ai_parser.enabled:
                try:
                    if fallback_datetime is None:
                        parsed_data = self.ai_parser.parse(raw_text)
                    else:
                        parsed_data = self.ai_parser.parse(
                            raw_text,
                            fallback_datetime=fallback_datetime,
                        )
                    if parsed_data:
                        logger.info("AI parsing successful")
                    else:
                        logger.info("AI parsing returned no data")
                        ai_error_kind = getattr(self.ai_parser, "last_error_kind", None)
                        rejection_reasons.append(
                            "ai_transient: provider unavailable"
                            if ai_error_kind == "transient"
                            else f"ai: returned None ({ai_error_kind or 'unclassified'})"
                        )
                except Exception as e:
                    logger.warning("AI parsing error: %s", e)
                    rejection_reasons.append(f"ai_error: {e}")
            else:
                rejection_reasons.append("ai: disabled (DeepSeek text parsing unavailable)")
                parsed_data = None
        
        # Step 3: Post-validation and enrichment
        if parsed_data:
            try:
                parsed_data = self._post_validate_and_enrich(parsed_data, raw_text)
            except Exception as e:
                logger.warning("Post-validation error: %s", e)
                rejection_reasons.append(f"post_validate: {e}")
                self.last_rejection_reason = "; ".join(rejection_reasons)
                return None

        # Step 4: Resolve application via reference dictionary, then AI fallback
        if parsed_data and parsed_data.get('operator_raw') and self.operator_mapper:
            operator_raw = parsed_data['operator_raw']
            try:
                match = self.operator_mapper.map_operator_details(operator_raw)
                if match and match.get("application_name"):
                    parsed_data['application_mapped'] = match["application_name"]
                    if match.get("is_p2p") is not None:
                        parsed_data['is_p2p'] = match["is_p2p"]
                    parsed_data["app_resolution"] = {
                        "method": "DICT",
                        "match_type": match.get("match_type"),
                        "reference_id": match.get("reference_id"),
                    }
                    logger.info(
                        "Operator mapped via dictionary: %s -> %s (%s)",
                        operator_raw,
                        match.get("application_name"),
                        match.get("match_type"),
                    )
                else:
                    # No dictionary hit; try AI resolution if available
                    if (
                        self.ai_application_mapping_enabled
                        and self.ai_parser
                        and self.ai_parser.enabled
                    ):
                        known_apps = self.operator_mapper.get_existing_applications()
                        hints = self.operator_mapper.get_candidate_examples(operator_raw, limit=10)
                        ai = self.ai_parser.resolve_application(operator_raw, raw_text, known_apps, hints)

                        if ai and ai.get("application_name") and ai.get("application_name") != "Unknown" and ai.get("confidence", 0) >= 0.75:
                            parsed_data["application_mapped"] = ai["application_name"]
                            parsed_data["is_p2p"] = ai.get("is_p2p", parsed_data.get("is_p2p"))
                            parsed_data["app_resolution"] = {
                                "method": "AI",
                                "confidence": ai.get("confidence"),
                                "reasoning": ai.get("reasoning"),
                                "recommended_operator_name": ai.get("recommended_operator_name"),
                            }
                            parsed_data["operator_reference_suggestion"] = {
                                "operator_name": ai.get("recommended_operator_name") or operator_raw,
                                "application_name": ai["application_name"],
                                "is_p2p": ai.get("is_p2p"),
                            }
                            logger.info(
                                "Operator mapped via AI: %s -> %s (confidence=%s)",
                                operator_raw,
                                ai.get("application_name"),
                                ai.get("confidence"),
                            )
                        else:
                            # Heuristic fallback
                            parsed_data["application_mapped"] = None
                            parsed_data["is_p2p"] = 'P2P' in operator_raw.upper()
                            parsed_data["app_resolution"] = {"method": "HEURISTIC"}
                            logger.info("AI could not confidently map operator: %s", operator_raw)
                    else:
                        parsed_data["application_mapped"] = None
                        parsed_data["app_resolution"] = {"method": "HEURISTIC"}
                        logger.info("No deterministic operator mapping found: %s", operator_raw)
            except Exception as e:
                logger.warning("Operator mapping error: %s", e)
                if 'application_mapped' not in parsed_data:
                    parsed_data['application_mapped'] = None

        # Step 5: Mark AI usage
        if parsed_data:
            parsed_with_ai = (parsed_data.get('parsing_method') or '').upper().startswith('GPT')
            parsed_data['is_gpt_parsed'] = parsed_with_ai
            parsed_data['is_ai_parsed'] = parsed_with_ai
        elif rejection_reasons:
            self.last_rejection_reason = "; ".join(rejection_reasons)

        return parsed_data

    def parse_text(
        self,
        text: str,
        fallback_datetime: Optional[datetime] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Thin wrapper for text-only ingestion paths (e.g. mobile SMS ingest).
        Keeps backward compatibility for existing process(...) callers.
        """
        return self.process(text, fallback_datetime=fallback_datetime)

    def _post_validate_and_enrich(self, data: Dict[str, Any], raw_text: str) -> Dict[str, Any]:
        """Ensure required fields and normalize values."""
        if not data.get('amount') or not data.get('transaction_date') or not data.get('transaction_type'):
            raise ValueError("Missing required fields")

        # amount & balance non-negative
        if data.get('amount') is not None:
            data['amount'] = abs(data['amount'])
            if data['amount'] == 0:
                raise ValueError("Zero amount")
        if data.get('balance_after') is not None:
            data['balance_after'] = abs(data['balance_after'])

        # currency uppercase, default UZS, whitelist enforced
        _allowed_currencies = {"UZS", "USD", "EUR", "RUB", "KZT", "GBP", "CNY"}
        _currency_synonyms = {
            "СУМ": "UZS", "СЎМ": "UZS", "SUM": "UZS",
            "TENGE": "KZT", "ТЕНГЕ": "KZT",
            "RUBLE": "RUB", "РУБЛЬ": "RUB", "РУБ": "RUB",
            "EURO": "EUR", "ЕВРО": "EUR",
            "DOLLAR": "USD", "ДОЛЛАР": "USD",
        }
        cur_raw = str(data.get('currency') or 'UZS').strip().upper()
        cur_raw = _currency_synonyms.get(cur_raw, cur_raw)
        data['currency'] = cur_raw if cur_raw in _allowed_currencies else 'UZS'

        # Sanity-checks: amount within plausible bounds, transaction_date within 5y back / 1d forward
        try:
            from datetime import datetime as _dt, timedelta as _td

            amt = data.get('amount')
            if amt is not None and (amt > 10**12 or amt < 0):
                raise ValueError("Amount out of plausible bounds")
            tx_dt = data.get('transaction_date')
            if isinstance(tx_dt, _dt):
                now = _dt.utcnow().replace(tzinfo=tx_dt.tzinfo) if tx_dt.tzinfo else _dt.utcnow()
                if tx_dt > now + _td(days=1) or tx_dt < now - _td(days=5 * 365):
                    raise ValueError("transaction_date out of plausible range")
        except ValueError:
            raise
        except Exception:  # noqa: BLE001
            pass

        # card last4 fallback
        if not data.get('card_last_4'):
            try:
                fallback = self.regex_parser.extract_card_last4(raw_text)
                data['card_last_4'] = fallback
            except Exception:
                pass

        # is_p2p heuristic only if not already set by parser
        if data.get('is_p2p') is None:
            op_upper = (data.get('operator_raw') or '').upper()
            text_upper = (raw_text or '').upper()
            p2p_markers = (
                "P2P", "CARD-TO-CARD", "CARD2CARD", "C2C",
                "ПЕРЕВОД", "PEREVOD", "TRANSFER",
                "RECEIVER", "ПОЛУЧАТЕЛ",
            )
            data['is_p2p'] = (
                any(m in op_upper for m in p2p_markers)
                or any(m in text_upper for m in p2p_markers)
            )

        # Extract receiver fields if not already set by parser
        if not data.get('receiver_name'):
            data['receiver_name'] = self._extract_receiver_name(raw_text)
        if not data.get('receiver_card'):
            data['receiver_card'] = self._extract_receiver_card(raw_text)

        return data

    def _extract_receiver_name(self, text: str) -> Optional[str]:
        """Extract receiver name from receipt text"""
        patterns = [
            r'(?:Receiver\s+name|Имя\s+получателя)\s*:?\s*([^\r\n]+)',
            r'(?:Получатель|Receiver)\s*:?\s*([^\r\n]+)',
            r'(?:На\s+имя|Кому)\s*:?\s*([^\r\n]+)',
        ]
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE | re.MULTILINE)
            if match:
                name = re.sub(r"\s+", " ", match.group(1)).strip(" ,:;-")
                # Card-only lines and numeric garbage are not person names.
                letters = re.findall(r"[A-Za-zА-Яа-яЁё]", name)
                digits = re.findall(r"\d", name)
                if (
                    len(name) > 3
                    and len(letters) >= 2
                    and len(digits) < 4
                    and name.upper() not in {'CARD', 'КАРТА', 'NUMBER', 'НОМЕР'}
                ):
                    return name[:255]  # Limit to DB column size
        return None

    def _extract_receiver_card(self, text: str) -> Optional[str]:
        """Extract receiver card last 4 digits from receipt text"""
        patterns = [
            r'(?:Receiver\s+card|Карта\s+получателя)\s*:?\s*([^\n\r]+)',
            r'(?:Receiver|Получатель)\s*:?\s*([^\n\r]+)',
            r'(?:на\s+карту|to\s+card)\s*:?\s*([^\n\r]+)',
        ]
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                raw_value = match.group(1).strip()
                digits = re.sub(r'\D', '', raw_value)
                if len(digits) >= 4:
                    return digits[-4:]
        return None
