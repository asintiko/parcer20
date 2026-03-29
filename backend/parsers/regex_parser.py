"""
Regex-based parser for Uzbek receipt formats
Handles three main formats: Humo Notification, SMS Inline, and Semicolon-delimited
"""
import re
from datetime import datetime
from typing import Optional, Dict, Any, List
from decimal import Decimal
import pytz


class RegexParser:
    """Parser using regex patterns for structured receipt extraction"""
    
    def __init__(self, timezone: str = "Asia/Tashkent"):
        self.tz = pytz.timezone(timezone)
        
        # Regex patterns for different formats
        self.patterns = {
            'humo_notification': {
                'amount': r'[➖➕💸]\s*([\d\s\.,]{1,30})\s*(UZS|USD|сум|сўм|sum)',
                'transaction_type': r'(Оплата|Пополнение|Операция|Конверсия|Счет по карте изменен.*|Счёт по карте изменён.*|Снятие наличных)',
                'card': r'(?:HUMO-?CARD|HUMOCARD|💳)\s*([\d\*]{6,})',
                'operator': r'[📍🏪]\s*(.+)',
                'datetime': r'[🕓🕘📅]\s*(?:(\d{2}:\d{2})\s+(\d{2}\.\d{2}\.\d{2,4})|(\d{2}\.\d{2}\.\d{2,4})\s+(\d{2}:\d{2}))',
                'datetime_fallback': r'(?<!\d)(\d{2}\.\d{2}\.\d{2,4})\s+(\d{2}:\d{2})(?!\d)',
                'balance': r'[💰💵]\s*(?:(?:Баланс|Остаток|Balance|Balans|Dostupno)\s*:?\s*)?([\d\s\.,]{1,30})\s*(USD|UZS|сум|сўм|sum)?',
                'currency': r'(USD|UZS|сум|сўм|sum)',
            },
            'sms_inline': {
                'operator': r'(?:Pokupka|Spisanie c karty|Spisanie|Popolnenie scheta|Popolnenie|E-Com oplata|Platezh|OTMENA(?:\s+Pokupka)?)\s*:?\s*(.+?)(?:,\s*[\d\s\.,]|(?:\s+\d{2}\.\d{2}\.\d{2,4})|(?:\.\s*summa))',
                'datetime': r'(\d{2}\.\d{2}\.\d{2,4})\s+(\d{2}:\d{2})',
                'datetime_iso': r'(\d{4}-\d{2}-\d{2})\s+(\d{2}:\d{2})',
                'amount': r'(?:summa\s*:?\s*|,\s*)([\d\s\.,]{1,30})\s*(UZS|USD|сум|сўм|sum)',
                'card': r'(?:karta\s*\*{0,3}|Karta\s*:?\s*)\*?(\d{4})',
                'balance': r'(?:balans|Bal|Balance)\s*:?\s*([\d\s\.,]{1,30})\s*(UZS|USD|сум|сўм|sum)?',
                'type_keyword': r'^(OTMENA|Pokupka|Spisanie|Popolnenie|E-Com|Platezh)',
            },
            'semicolon_format': {
                'card_amount': r'HUMOCARD\s*\*(\d{4}):\s*(oplata|popolnenie|operacija)\s+([\d\.]+)\s*UZS',
                'operator': r';\s*([^;]+?)\s*;',
                'datetime': r';\s*(\d{2,4})-(\d{2})-(\d{2})\s+(\d{2}:\d{2})',
                'balance': r'Dostupno:\s*([\d\.]+)\s*UZS',
            },
            'cardxabar': {
                'amount': r'(?:[➖➕]\s*|Summa\s*:?\s*)([\d\s\.,]{1,30})\s*(USD|UZS|сум|сўм|sum)',
                'card': r'(?:💳|Karta)\s*:?\s*([0-9\*]{4,20})',
                'operator': r'(?:📍|Magazin|Otpravitel)\s*:?\s*(.+)',
                'datetime': r'[🕓🕘📅]\s*(?:(\d{2}:\d{2})\s+(\d{2}\.\d{2}\.\d{2,4})|(\d{2}\.\d{2}\.\d{2,4})\s+(\d{2}:\d{2}))',
                'datetime_text': r'Data\s*:?\s*(\d{2}\.\d{2}\.\d{2,4})\s*\n?\s*Vremya\s*:?\s*(\d{2}:\d{2})',
                'balance': r'(?:[💰💵]|Balans?|Balance|Dostupno)\s*:?\s*([\d\s\.,]{1,30})\s*(USD|UZS|сум|сўм|sum)?',
                'currency': r'(USD|UZS|сум|сўм|sum)',
            }
        }

    def _search_any(self, text: str, patterns: List[str], flags: int = re.IGNORECASE):
        for pattern in patterns:
            match = re.search(pattern, text, flags)
            if match:
                return match
        return None

    def _parse_datetime_with_optional_seconds(self, date_str: str, time_str: str) -> Optional[datetime]:
        for fmt in ("%d.%m.%Y %H:%M:%S", "%d.%m.%Y %H:%M", "%d.%m.%y %H:%M"):
            try:
                return self.tz.localize(datetime.strptime(f"{date_str} {time_str}", fmt))
            except Exception:
                continue
        return None

    def _extract_name_from_party_line(self, value: Optional[str]) -> Optional[str]:
        if not value:
            return None
        cleaned = re.sub(r"(?:HUMO-?CARD|HUMOCARD|HUMO|UZCARD)", " ", value, flags=re.IGNORECASE)
        cleaned = re.sub(r"[0-9\*]{4,}", " ", cleaned)
        cleaned = re.sub(r"\s+", " ", cleaned).strip(" ,:-")
        return cleaned or None
    
    def parse_sender_receiver_transfer(self, text: str) -> Optional[Dict[str, Any]]:
        """
        Parse P2P transfer style:
        Sender 986001******7466
        Sender name LEE SVYATOSLAV
        Receiver 491699******1116
        Receiver name SVYATOSLAV LI
        Transaction date 09.01.2026 02:05:05
        Receiver amount 1,450,000.00 UZS
        """
        lines_lower = text.lower()
        if "sender" not in lines_lower and "отправител" not in lines_lower:
            return None

        amount = None
        currency = "UZS"
        amount_match = self._search_any(
            text,
            [
                r'Receiver amount\s*[:\-]?\s*([\d\s\.,]+)\s*(UZS|USD)?',
                r'Sender amount\s*[:\-]?\s*([\d\s\.,]+)\s*(UZS|USD)?',
                r'Amount\s*[:\-]?\s*([\d\s\.,]+)\s*(UZS|USD)?',
                r'Сумма(?:\s+(?:отправителя|получателя))?\s*[:\-]?\s*([\d\s\.,]+)\s*(UZS|USD)?',
            ],
        )
        if amount_match:
            try:
                amount = self.normalize_amount(amount_match.group(1))
            except Exception:
                pass
            if amount_match.lastindex and amount_match.group(2):
                currency = self.normalize_currency(amount_match.group(2))

        date_match = self._search_any(
            text,
            [
                r'Trans(?:action|cation)\s+date\s*[:\-]?\s*(\d{2}\.\d{2}\.\d{2,4})\s+(\d{2}:\d{2}(?::\d{2})?)',
                r'Date(?:\s+transaction)?\s*[:\-]?\s*(\d{2}\.\d{2}\.\d{2,4})\s+(\d{2}:\d{2}(?::\d{2})?)',
                r'Дата(?:\s+транзакции)?\s*[:\-]?\s*(\d{2}\.\d{2}\.\d{2,4})\s+(\d{2}:\d{2}(?::\d{2})?)',
            ],
        )
        transaction_date = None
        if date_match:
            transaction_date = self._parse_datetime_with_optional_seconds(
                date_match.group(1),
                date_match.group(2),
            )

        sender_mask = self._search_any(
            text,
            [
                r'\bSender\b\s*[:\-]?\s*([^\n\r]+)',
                r'Отправител[ья]?\s*[:\-]?\s*([^\n\r]+)',
            ],
        )
        receiver_mask = self._search_any(
            text,
            [
                r'\bReceiver\b\s*[:\-]?\s*([^\n\r]+)',
                r'Получател[ья]?\s*[:\-]?\s*([^\n\r]+)',
            ],
        )
        sender_line = sender_mask.group(1).strip() if sender_mask else None
        receiver_line = receiver_mask.group(1).strip() if receiver_mask else None
        card_last_4 = self.extract_card_last4(sender_line) if sender_line else self.extract_card_last4(text)
        receiver_card = self.extract_card_last4(receiver_line) if receiver_line else None

        sender_name_match = self._search_any(
            text,
            [
                r'Sender name\s*[:\-]?\s*([^\n\r]+)',
                r'Имя\s+отправителя\s*[:\-]?\s*([^\n\r]+)',
            ],
        )
        receiver_name_match = self._search_any(
            text,
            [
                r'Receiver name\s*[:\-]?\s*([^\n\r]+)',
                r'Имя\s+получател[ья]?\s*[:\-]?\s*([^\n\r]+)',
            ],
        )
        receiver_name = receiver_name_match.group(1).strip() if receiver_name_match else None
        if not receiver_name:
            receiver_name = self._extract_name_from_party_line(receiver_line)

        if not amount or not transaction_date:
            return None

        return {
            'amount': amount,
            'currency': currency,
            'transaction_type': 'DEBIT',
            'card_last_4': card_last_4,
            'receiver_card': receiver_card,
            'receiver_name': receiver_name,
            'operator_raw': 'Uzum Bank',
            'transaction_date': transaction_date,
            'balance_after': None,
            'parsing_method': 'REGEX_TRANSFER',
            'parsing_confidence': 0.9,
            'is_p2p': True,
        }

    def parse_ru_transfer(self, text: str) -> Optional[Dict[str, Any]]:
        """
        Parse Russian P2P receipts with labels "Отправителя", "Имя отправителя", "Название", "Сумма отправителя".
        """
        lower = text.lower()
        if "отправител" not in lower or "сумма" not in lower:
            return None

        sender_mask = re.search(r'Отправителя\s+([0-9\*]{6,})', text, re.IGNORECASE)
        if not sender_mask:
            sender_mask = re.search(r'Отправител[ья]?\s*[:\-]?\s*([^\n\r]+)', text, re.IGNORECASE)
        receiver_mask = re.search(r'Получател[ьяя]?\s+([0-9\*]{6,})', text, re.IGNORECASE)
        if not receiver_mask:
            receiver_mask = re.search(r'Получател[ьяя]?\s*[:\-]?\s*([^\n\r]+)', text, re.IGNORECASE)

        amount_match = re.search(r'Сумма(?:\s+отправителя)?\s*[:\-]?\s*([\d\s\.,]+)\s*(UZS|USD)?', text, re.IGNORECASE)
        amount = None
        currency = "UZS"
        if amount_match:
            try:
                amount = self.normalize_amount(amount_match.group(1))
            except Exception:
                amount = None
            if amount_match.lastindex and amount_match.group(2):
                currency = self.normalize_currency(amount_match.group(2))

        date_match = re.search(r'Дата(?:\s+транзакции)?\s*[:\-]?\s*(\d{2}\.\d{2}\.\d{2,4})\s+(\d{2}:\d{2}(?::\d{2})?)', text, re.IGNORECASE)
        transaction_date = None
        if date_match:
            transaction_date = self._parse_datetime_with_optional_seconds(
                date_match.group(1),
                date_match.group(2),
            )

        operator_raw = "Uzum Bank"

        receiver_name_match = re.search(r'(?:Receiver name|Имя\s+получател[ьяя]?|Имя\s+отправителя|Имя)\s+([^\n\r]+)', text, re.IGNORECASE)
        receiver_name = receiver_name_match.group(1).strip() if receiver_name_match else None

        sender_line = sender_mask.group(1).strip() if sender_mask else None
        receiver_line = receiver_mask.group(1).strip() if receiver_mask else None
        card_last_4 = self.extract_card_last4(sender_line) if sender_line else self.extract_card_last4(text)
        receiver_card = self.extract_card_last4(receiver_line) if receiver_line else None
        if not receiver_name:
            receiver_name = self._extract_name_from_party_line(receiver_line)

        if amount is None or transaction_date is None:
            return None

        return {
            'amount': amount,
            'currency': currency,
            'transaction_type': 'DEBIT',
            'card_last_4': card_last_4,
            'receiver_card': receiver_card,
            'receiver_name': receiver_name,
            'operator_raw': operator_raw,
            'transaction_date': transaction_date,
            'balance_after': None,
            'parsing_method': 'REGEX_TRANSFER',
            'parsing_confidence': 0.9,
            'is_p2p': True,
        }
    
    def normalize_amount(self, amount_str: str) -> Decimal:
        """Normalize amount string to Decimal with robust thousand/decimal handling."""
        if amount_str is None:
            raise ValueError("Amount string is None")
        cleaned = amount_str.strip().replace("\u00a0", "").replace(" ", "")

        has_dot = "." in cleaned
        has_comma = "," in cleaned

        if has_dot and has_comma:
            # Decide decimal separator by last occurrence
            last_dot = cleaned.rfind(".")
            last_comma = cleaned.rfind(",")
            if last_dot > last_comma:
                # dot is decimal, remove commas
                cleaned = cleaned.replace(",", "")
            else:
                # comma is decimal, remove dots then swap comma to dot
                cleaned = cleaned.replace(".", "")
                cleaned = cleaned.replace(",", ".")
        elif has_comma and not has_dot:
            cleaned = cleaned.replace(",", ".")

        # Strip all except digits and dot
        cleaned = re.sub(r"[^0-9\.]", "", cleaned)

        if cleaned.count(".") > 1:
            parts = cleaned.split(".")
            cleaned = "".join(parts[:-1]) + "." + parts[-1]

        if cleaned == "" or cleaned == ".":
            raise ValueError(f"Invalid amount string: '{amount_str}'")

        return Decimal(cleaned)

    def normalize_currency(self, currency: Optional[str]) -> str:
        if not currency:
            return "UZS"
        code = str(currency).strip().upper()
        if code in {"СУМ", "СЎМ", "SUM"}:
            return "UZS"
        return code

    def extract_card_last4(self, text: str) -> Optional[str]:
        """Extract last 4 digits of card number from various masked formats."""
        patterns = [
            r'\*+(\d{4})',                # ***4862, *6714
            r'\d+\*+(\d{4})',             # 479091**6905
            r'\d+\*+\d*(\d{4})',          # 532154**1744
        ]
        for pat in patterns:
            m = re.search(pat, text)
            if m:
                return m.group(1)
        return None
    
    def parse_date(self, date_str: str, time_str: str, format_type: str = 'standard') -> datetime:
        """Parse date and time strings to datetime object"""
        try:
            if format_type == 'semicolon':
                # Format: YY-MM-DD HH:MM or YYYY-MM-DD HH:MM
                parts = date_str.split('-')
                year = parts[0]
                month = parts[1]
                day = parts[2]
                full_year = f"20{year}" if len(year) == 2 else year
                dt_str = f"{full_year}-{month}-{day} {time_str}"
                dt = datetime.strptime(dt_str, "%Y-%m-%d %H:%M")
            else:
                # Format: DD.MM.YYYY or DD.MM.YY
                parts = date_str.split('.')
                if len(parts[2]) == 2:
                    parts[2] = f"20{parts[2]}"
                dt_str = f"{parts[0]}.{parts[1]}.{parts[2]} {time_str}"
                dt = datetime.strptime(dt_str, "%d.%m.%Y %H:%M")
            
            # Localize to Tashkent timezone
            return self.tz.localize(dt)
        except Exception as e:
            raise ValueError(f"Date parsing error: {e}")
    
    def parse_humo_notification(self, text: str) -> Optional[Dict[str, Any]]:
        """Parse Humo notification format (emoji-based, multi-line)"""
        patterns = self.patterns['humo_notification']
        
        # Extract amount
        amount_match = re.search(patterns['amount'], text)
        if not amount_match:
            return None
        amount = self.normalize_amount(amount_match.group(1))
        amount_currency = (
            self.normalize_currency(amount_match.group(2))
            if amount_match.lastindex and amount_match.lastindex >= 2 and amount_match.group(2)
            else None
        )
        
        # Extract transaction type
        type_match = re.search(patterns['transaction_type'], text, re.IGNORECASE)
        type_map = {
            'оплата': 'DEBIT',
            'пополнение': 'CREDIT',
            'операция': 'DEBIT',
            'конверсия': 'CONVERSION',
            'счет по карте изменен': 'DEBIT',
            'счёт по карте изменён': 'DEBIT',
            'снятие наличных': 'DEBIT',
        }
        if type_match:
            matched_raw = type_match.group(1).strip().lower()
            transaction_type = None
            for key, val in type_map.items():
                if matched_raw.startswith(key):
                    transaction_type = val
                    break
            if transaction_type is None:
                transaction_type = 'DEBIT'
        else:
            upper_text = text.upper()
            if "OTMENA" in upper_text:
                transaction_type = 'REVERSAL'
            elif "КОНВЕРС" in upper_text or "CONVERS" in upper_text:
                transaction_type = 'CONVERSION'
            else:
                transaction_type = 'CREDIT' if '➕' in text or '🎉' in text else 'DEBIT'
        
        # Extract card
        card_last_4 = self.extract_card_last4(text)
        
        # Extract operator
        operator_match = re.search(patterns['operator'], text)
        operator_raw = operator_match.group(1).strip() if operator_match else None
        # Fallback: если оператор не найден, но видно карту — ставим понятный ярлык
        upper_text = text.upper()
        if not operator_raw:
            if 'HUMO' in upper_text:
                operator_raw = 'HUMOCARD'
            elif 'UZCARD' in upper_text:
                operator_raw = 'UZCARD'
            elif 'ИЗМЕНЕН' in upper_text or 'ИЗМЕНЁН' in upper_text:
                operator_raw = 'BALANCE CHANGE'
        # Специальный случай: изменение счёта по карте — гарантируем понятные тип и оператор
        if 'СЧЕТ ПО КАРТЕ ИЗМЕН' in upper_text or 'СЧЁТ ПО КАРТЕ ИЗМЕН' in upper_text:
            transaction_type = 'DEBIT'
            if not operator_raw or operator_raw.upper() not in ['HUMOCARD', 'UZCARD', 'BALANCE CHANGE']:
                operator_raw = 'BALANCE CHANGE'
        
        # Extract datetime
        datetime_match = re.search(patterns['datetime'], text)
        if datetime_match:
            if datetime_match.group(1) and datetime_match.group(2):
                time_str = datetime_match.group(1)
                date_str = datetime_match.group(2)
            else:
                date_str = datetime_match.group(3)
                time_str = datetime_match.group(4)
        else:
            datetime_fallback = re.search(patterns['datetime_fallback'], text)
            if not datetime_fallback:
                return None
            date_str = datetime_fallback.group(1)
            time_str = datetime_fallback.group(2)
        try:
            transaction_date = self.parse_date(date_str, time_str)
        except ValueError:
            return None
        
        # Extract balance
        balance_match = re.search(patterns['balance'], text)
        balance_after = self.normalize_amount(balance_match.group(1)) if balance_match else None
        
        # Extract currency
        currency = amount_currency
        if not currency:
            currency_match = re.search(patterns['currency'], text)
            currency = self.normalize_currency(currency_match.group(1)) if currency_match else 'UZS'
        
        return {
            'amount': amount,
            'currency': currency,
            'transaction_type': transaction_type,
            'card_last_4': card_last_4,
            'operator_raw': operator_raw,
            'transaction_date': transaction_date,
            'balance_after': balance_after,
            'parsing_method': 'REGEX_HUMO',
            'parsing_confidence': 0.95
        }
    
    def parse_sms_inline(self, text: str) -> Optional[Dict[str, Any]]:
        """Parse SMS inline format (compact, comma-separated)"""
        patterns = self.patterns['sms_inline']
        
        # Extract amount
        amount_match = re.search(patterns['amount'], text)
        if not amount_match:
            return None
        amount = self.normalize_amount(amount_match.group(1))
        currency = (
            self.normalize_currency(amount_match.group(2))
            if amount_match.lastindex and amount_match.lastindex >= 2 and amount_match.group(2)
            else 'UZS'
        )
        
        # Extract operator
        operator_match = re.search(patterns['operator'], text)
        operator_raw = operator_match.group(1).strip() if operator_match else None
        
        # Extract datetime
        datetime_match = re.search(patterns['datetime'], text)
        format_type = 'standard'
        if not datetime_match:
            datetime_match = re.search(patterns['datetime_iso'], text)
            format_type = 'semicolon'
        if not datetime_match:
            return None
        date_str = datetime_match.group(1)
        time_str = datetime_match.group(2)
        try:
            transaction_date = self.parse_date(date_str, time_str, format_type=format_type)
        except ValueError:
            return None
        
        # Extract card
        card_last_4 = self.extract_card_last4(text)
        
        # Extract balance
        balance_match = re.search(patterns['balance'], text)
        balance_after = self.normalize_amount(balance_match.group(1)) if balance_match else None
        
        # Determine transaction type
        type_match = re.search(patterns['type_keyword'], text)
        if type_match:
            keyword = type_match.group(1)
            if keyword == 'OTMENA':
                transaction_type = 'REVERSAL'
            elif keyword in ['Popolnenie']:
                transaction_type = 'CREDIT'
            elif keyword in ['E-Com', 'Platezh', 'Pokupka', 'Spisanie']:
                transaction_type = 'DEBIT'
            else:
                transaction_type = 'DEBIT'
        else:
            transaction_type = 'DEBIT'
        
        return {
            'amount': amount,
            'currency': currency,
            'transaction_type': transaction_type,
            'card_last_4': card_last_4,
            'operator_raw': operator_raw,
            'transaction_date': transaction_date,
            'balance_after': balance_after,
            'parsing_method': 'REGEX_SMS',
            'parsing_confidence': 0.90
        }
    
    def parse_semicolon_format(self, text: str) -> Optional[Dict[str, Any]]:
        """Parse semicolon-delimited format (HUMOCARD *6921: ...)"""
        patterns = self.patterns['semicolon_format']
        
        # Extract card, type, and amount
        card_amount_match = re.search(patterns['card_amount'], text)
        if not card_amount_match:
            return None
        
        card_last_4 = card_amount_match.group(1)
        op_type = card_amount_match.group(2)
        amount = self.normalize_amount(card_amount_match.group(3))
        
        # Map operation type
        type_map = {'oplata': 'DEBIT', 'popolnenie': 'CREDIT', 'operacija': 'DEBIT'}
        transaction_type = type_map.get(op_type.lower(), 'DEBIT')
        
        # Extract operator
        operator_match = re.search(patterns['operator'], text)
        operator_raw = operator_match.group(1).strip() if operator_match else None
        
        # Extract datetime (YY-MM-DD format)
        datetime_match = re.search(patterns['datetime'], text)
        if not datetime_match:
            return None
        
        year = datetime_match.group(1)
        month = datetime_match.group(2)
        day = datetime_match.group(3)
        time_str = datetime_match.group(4)
        date_str = f"{year}-{month}-{day}"
        
        try:
            transaction_date = self.parse_date(date_str, time_str, format_type='semicolon')
        except ValueError:
            return None
        
        # Extract balance
        balance_match = re.search(patterns['balance'], text)
        balance_after = self.normalize_amount(balance_match.group(1)) if balance_match else None
        
        return {
            'amount': amount,
            'currency': 'UZS',
            'transaction_type': transaction_type,
            'card_last_4': card_last_4,
            'operator_raw': operator_raw,
            'transaction_date': transaction_date,
            'balance_after': balance_after,
            'parsing_method': 'REGEX_SEMICOLON',
            'parsing_confidence': 0.92
        }

    def parse_cardxabar(self, text: str) -> Optional[Dict[str, Any]]:
        """Parse CardXabar notifications (emoji and text-label variants)."""
        patterns = self.patterns['cardxabar']

        amount_match = re.search(patterns['amount'], text)
        if not amount_match:
            return None
        amount = self.normalize_amount(amount_match.group(1))
        currency = (
            self.normalize_currency(amount_match.group(2))
            if amount_match.lastindex and amount_match.lastindex >= 2 and amount_match.group(2)
            else None
        )

        card_last_4 = self.extract_card_last4(text)

        operator_match = re.search(patterns['operator'], text)
        operator_raw = operator_match.group(1).strip() if operator_match else None

        dt_match = re.search(patterns['datetime'], text)
        if dt_match:
            if dt_match.group(1) and dt_match.group(2):
                time_str = dt_match.group(1)
                date_str = dt_match.group(2)
            else:
                date_str = dt_match.group(3)
                time_str = dt_match.group(4)
        else:
            dt_text_match = re.search(patterns['datetime_text'], text, re.IGNORECASE)
            if not dt_text_match:
                return None
            date_str = dt_text_match.group(1)
            time_str = dt_text_match.group(2)
        try:
            transaction_date = self.parse_date(date_str, time_str)
        except ValueError:
            return None

        balance_match = re.search(patterns['balance'], text)
        balance_after = self.normalize_amount(balance_match.group(1)) if balance_match and balance_match.group(1) else None
        if not currency and balance_match and balance_match.lastindex and balance_match.lastindex >= 2 and balance_match.group(2):
            currency = self.normalize_currency(balance_match.group(2))
        if not currency:
            currency = 'UZS'

        upper_text = text.upper()
        if "OTMENA" in upper_text:
            transaction_type = 'REVERSAL'
        elif "КОНВЕРС" in upper_text or "CONVERS" in upper_text or "CONVERSION" in upper_text or "КОНВЕРСИЯ" in upper_text or "KONVERS" in upper_text:
            transaction_type = 'CONVERSION'
        elif "ZACHISLENIE" in upper_text or '🟢' in text or '➕' in text:
            transaction_type = 'CREDIT'
        elif "SPISANIE" in upper_text or '🔴' in text or '➖' in text:
            transaction_type = 'DEBIT'
        else:
            transaction_type = 'DEBIT'

        return {
            'amount': amount,
            'currency': currency,
            'transaction_type': transaction_type,
            'card_last_4': card_last_4,
            'operator_raw': operator_raw,
            'transaction_date': transaction_date,
            'balance_after': balance_after,
            'parsing_method': 'REGEX_CARDXABAR',
            'parsing_confidence': 0.93
        }
    
    def parse(self, text: str) -> Optional[Dict[str, Any]]:
        """
        Main parse method - tries all formats in cascade
        
        Args:
            text: Raw receipt text
            
        Returns:
            Parsed transaction dict or None if parsing failed
        """
        if not text or len(text) > 10000:
            return None

        lower_text = text.lower()
        upper_text = text.upper()

        # CardXabar style (red/green bullets, text labels)
        if any(marker in text for marker in ['CardXabar', 'NBU Card', '🔴', '🟢']) or any(
            marker in lower_text for marker in ['summa:', 'karta:', 'magazin:', 'otpravitel:', 'data:', 'vremya:']
        ):
            result = self.parse_cardxabar(text)
            if result:
                return result

        # Try focused transfer formats.
        result = self.parse_ru_transfer(text)
        if result:
            return result

        result = self.parse_sender_receiver_transfer(text)
        if result:
            return result

        if any(emoji in text for emoji in ['💸', '💳', '📍', '🏪', '🕓', '🕘', '📅', '➖', '➕']):
            result = self.parse_humo_notification(text)
            if result:
                return result
        
        # Try semicolon format
        if ('HUMOCARD*' in upper_text or 'HUMOCARD *' in upper_text) and ';' in text:
            result = self.parse_semicolon_format(text)
            if result:
                return result
        
        # Try SMS inline format
        sms_keywords = ['pokupka:', 'spisanie', 'popolnenie', 'e-com oplata', 'platezh:', 'otmena']
        if any(kw in lower_text for kw in sms_keywords):
            result = self.parse_sms_inline(text)
            if result:
                return result

        # Full fallback cascade for mixed/dirty formats.
        for parser_fn in (
            self.parse_cardxabar,
            self.parse_ru_transfer,
            self.parse_sender_receiver_transfer,
            self.parse_humo_notification,
            self.parse_semicolon_format,
            self.parse_sms_inline,
        ):
            try:
                result = parser_fn(text)
            except Exception:
                result = None
            if result:
                return result

        # All formats failed.
        return None
