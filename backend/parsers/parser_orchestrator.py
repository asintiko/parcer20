"""
Parser orchestrator - coordinates regex and GPT parsers with operator mapping
"""
import os
import re
from typing import Dict, Any, Optional
from sqlalchemy.orm import Session

from parsers.regex_parser import RegexParser
from parsers.gpt_parser import GPTParser
from parsers.operator_mapper import OperatorMapper


class ParserOrchestrator:
    """Main parsing coordinator that cascades through parsing strategies"""
    
    def __init__(self, db_session: Optional[Session], openai_api_key: Optional[str] = None, allow_missing_openai: bool = True):
        self.regex_parser = RegexParser()
        self.gpt_parser = None
        self.openai_api_key = openai_api_key or os.getenv("OPENAI_API_KEY")
        self.allow_missing_openai = allow_missing_openai
        if self.openai_api_key:
            try:
                self.gpt_parser = GPTParser(api_key=self.openai_api_key, allow_without_api_key=allow_missing_openai)
            except Exception as e:
                print(f"⚠️ GPT parser unavailable at init: {e}")
                self.gpt_parser = None
        self.operator_mapper = OperatorMapper(db_session) if db_session is not None else None
        
        # Confidence threshold for accepting regex results
        self.confidence_threshold = 0.8
    
    def process(self, raw_text: str) -> Optional[Dict[str, Any]]:
        """
        Process raw receipt text through parsing cascade
        
        Strategy:
        1. Try regex parser first (fast, deterministic)
        2. If confidence < threshold or failure, use GPT parser
        3. Apply operator mapping to normalize operator name
        4. Return fully structured transaction data
        
        Args:
            raw_text: Raw receipt text from Telegram
            
        Returns:
            Fully parsed transaction dict with all fields
        """
        if not raw_text or not raw_text.strip():
            return None
        
        parsed_data = None
        
        # Step 1: Try regex parser
        try:
            parsed_data = self.regex_parser.parse(raw_text)
            
            # Check if result meets confidence threshold
            if parsed_data and parsed_data.get('parsing_confidence', 0) >= self.confidence_threshold:
                print(f"✅ Regex parsing successful: {parsed_data['parsing_method']}")
            else:
                print(f"⚠️  Regex confidence too low or failed, falling back to GPT")
                parsed_data = None
        except Exception as e:
            print(f"❌ Regex parsing error: {e}")
            parsed_data = None
        
        # Step 2: Fallback to GPT if regex failed and key is available
        if not parsed_data:
            if not self.gpt_parser and self.openai_api_key:
                try:
                    self.gpt_parser = GPTParser(api_key=self.openai_api_key, allow_without_api_key=self.allow_missing_openai)
                except Exception as e:
                    print(f"⚠️ GPT parser instantiation failed: {e}")
                    self.gpt_parser = None

            if self.gpt_parser and self.gpt_parser.enabled:
                try:
                    parsed_data = self.gpt_parser.parse(raw_text)
                    if parsed_data:
                        print(f"✅ GPT parsing successful")
                    else:
                        print(f"❌ GPT parsing also failed")
                        return None
                except Exception as e:
                    print(f"❌ GPT parsing error: {e}")
                    return None
            else:
                # No GPT available; stay silent and return None
                parsed_data = None
        
        # Step 3: Post-validation and enrichment
        if parsed_data:
            try:
                parsed_data = self._post_validate_and_enrich(parsed_data, raw_text)
            except Exception as e:
                print(f"❌ Post-validation error: {e}")
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
                    print(f"✅ Operator mapped: '{operator_raw}' → '{match['application_name']}' ({match['match_type']})")
                else:
                    # No dictionary hit; try AI resolution if available
                    if self.gpt_parser and self.gpt_parser.enabled:
                        known_apps = self.operator_mapper.get_existing_applications()
                        hints = self.operator_mapper.get_candidate_examples(operator_raw, limit=10)
                        ai = self.gpt_parser.resolve_application(operator_raw, raw_text, known_apps, hints)

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
                            print(f"✅ AI-mapped operator: '{operator_raw}' → '{ai['application_name']}' (confidence {ai.get('confidence')})")
                        else:
                            # Heuristic fallback
                            parsed_data["application_mapped"] = None
                            parsed_data["is_p2p"] = 'P2P' in operator_raw.upper()
                            parsed_data["app_resolution"] = {"method": "HEURISTIC"}
                            print(f"⚠️  AI could not confidently map operator: '{operator_raw}'")
                    else:
                        parsed_data["application_mapped"] = None
                        parsed_data["app_resolution"] = {"method": "HEURISTIC"}
                        print(f"⚠️  No mapping found for operator and AI disabled: '{operator_raw}'")
            except Exception as e:
                print(f"❌ Operator mapping error: {e}")
                if 'application_mapped' not in parsed_data:
                    parsed_data['application_mapped'] = None

        # Step 5: Mark GPT usage
        if parsed_data:
            parsed_data['is_gpt_parsed'] = (parsed_data.get('parsing_method') == 'GPT')
        
        return parsed_data

    def _post_validate_and_enrich(self, data: Dict[str, Any], raw_text: str) -> Dict[str, Any]:
        """Ensure required fields and normalize values."""
        if not data.get('amount') or not data.get('transaction_date') or not data.get('transaction_type'):
            raise ValueError("Missing required fields")

        # amount & balance non-negative
        if data.get('amount') is not None:
            data['amount'] = abs(data['amount'])
        if data.get('balance_after') is not None:
            data['balance_after'] = abs(data['balance_after'])

        # currency uppercase, default UZS
        if data.get('currency'):
            data['currency'] = str(data['currency']).upper()
        else:
            data['currency'] = 'UZS'

        # card last4 fallback
        if not data.get('card_last_4'):
            try:
                from parsers.regex_parser import RegexParser
                fallback = RegexParser().extract_card_last4(raw_text)
                data['card_last_4'] = fallback
            except Exception:
                pass

        # is_p2p heuristic only if not already set by parser
        if data.get('is_p2p') is None:
            operator_raw = (data.get('operator_raw') or '').upper()
            data['is_p2p'] = 'P2P' in operator_raw

        # Extract receiver fields if not already set by parser
        if not data.get('receiver_name'):
            data['receiver_name'] = self._extract_receiver_name(raw_text)
        if not data.get('receiver_card'):
            data['receiver_card'] = self._extract_receiver_card(raw_text)

        return data

    def _extract_receiver_name(self, text: str) -> Optional[str]:
        """Extract receiver name from receipt text"""
        patterns = [
            r'(?:Receiver\s+name|Имя\s+получателя|Получатель)\s*:?\s*([А-ЯЁA-Z][а-яёa-zA-Z\s\-\']+)',
            r'(?:Receiver|RECEIVER)\s*:?\s*([А-ЯЁA-Z][а-яёa-zA-Z\s\-\']+)',
            r'(?:На\s+имя|Кому)\s*:?\s*([А-ЯЁA-Z][а-яёa-zA-Z\s\-\']+)',
        ]
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE | re.MULTILINE)
            if match:
                name = match.group(1).strip()
                # Filter out common false positives
                if len(name) > 3 and not name.upper() in ['CARD', 'КАРТА', 'NUMBER', 'НОМЕР']:
                    return name[:255]  # Limit to DB column size
        return None

    def _extract_receiver_card(self, text: str) -> Optional[str]:
        """Extract receiver card last 4 digits from receipt text"""
        patterns = [
            r'(?:Receiver\s+card|Receiver|Получатель|Карта\s+получателя)\s*:?\s*([^\n\r]+)',
            r'(?:на\s+карту|to\s+card)\s*:?\s*([^\n\r]+)',
        ]
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                raw_value = match.group(1).strip()
                digits = re.sub(r'\D', '', raw_value)
                if digits:
                    return digits[-4:]
                if raw_value:
                    return raw_value[:4]
        return None
