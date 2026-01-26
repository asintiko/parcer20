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
                'amount': r'[➖➕💸]\s*([\d\s\.,]+)\s*(UZS|USD)',
                'transaction_type': r'(Оплата|Пополнение|Операция|Конверсия)',
                'card': r'(?:HUMO-?CARD|HUMOCARD|💳)\s*([\d\*]{6,})',
                'operator': r'📍\s*(.+)',
                'datetime': r'[🕓🕘]\s*(?:(\d{2}:\d{2})\s+(\d{2}\.\d{2}\.\d{2,4})|(\d{2}\.\d{2}\.\d{2,4})\s+(\d{2}:\d{2}))',
                'balance': r'[💰💵]\s*([\d\s\.,]+)\s*(USD|UZS)',
                'currency': r'(USD|UZS)',
            },
            'sms_inline': {
                'operator': r'(?:Pokupka|Spisanie c karty|Popolnenie scheta|E-Com oplata|Platezh):\s*(.+?)(?:,|\s+\d{2}\.\d{2})',
                'datetime': r'(\d{2}\.\d{2}\.\d{2})\s+(\d{2}:\d{2})',
                'amount': r'summa:([\d\s\.,]+)\s*UZS',
                'card': r'karta\s*\*{3}(\d{4})',
                'balance': r'balans:([\d\s\.,]+)\s*UZS',
                'type_keyword': r'^(Pokupka|Spisanie|Popolnenie|E-Com|Platezh|OTMENA)',
            },
            'semicolon_format': {
                'card_amount': r'HUMOCARD\s*\*(\d{4}):\s*(oplata|popolnenie|operacija)\s+([\d\.]+)\s*UZS',
                'operator': r';\s*([^;]+?)\s*;',
                'datetime': r';\s*(\d{2})-(\d{2})-(\d{2})\s+(\d{2}:\d{2})',
                'balance': r'Dostupno:\s*([\d\.]+)\s*UZS',
            },
            'cardxabar': {
                'amount': r'[➖➕]\s*([\d\s\.,]+)\s*(USD|UZS)',
                'card': r'💳\s*([\d\*]{6,})',
                'operator': r'📍\s*(.+)',
                'datetime': r'🕓\s*(?:(\d{2}:\d{2})\s+(\d{2}\.\d{2}\.\d{2,4})|(\d{2}\.\d{2}\.\d{2,4})\s+(\d{2}:\d{2}))',
                'balance': r'[💰💵]\s*([\d\s\.,]+)\s*(USD|UZS)?',
                'currency': r'(USD|UZS)',
            }
        }
    
    def normalize_amount(self, amount_str: str) -> Decimal:
        """Normalize amount string to Decimal with robust thousand/decimal handling."""
        if amount_str is None:
            raise ValueError("Amount string is None")
        cleaned = amount_str.strip().replace("\u00a0", "")
        cleaned = cleaned.replace(" ", "")

        has_dot = "." in cleaned
        has_comma = "," in cleaned

        if has_dot and has_comma:
            cleaned = cleaned.replace(".", "")
            cleaned = cleaned.replace(",", ".")
        elif has_comma:
            cleaned = cleaned.replace(",", ".")

        cleaned = re.sub(r"[^0-9\.]", "", cleaned)

        if cleaned.count(".") > 1:
            parts = cleaned.split(".")
            cleaned = "".join(parts[:-1]) + "." + parts[-1]

        if cleaned == "" or cleaned == ".":
            raise ValueError(f"Invalid amount string: '{amount_str}'")

        return Decimal(cleaned)

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
                # Format: YY-MM-DD HH:MM
                year, month, day = date_str.split('-')
                full_year = f"20{year}"
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
        amount_currency = amount_match.group(2) if amount_match.lastindex and amount_match.lastindex >= 2 else None
        
        # Extract transaction type
        type_match = re.search(patterns['transaction_type'], text)
        type_map = {
            'Оплата': 'DEBIT',
            'Пополнение': 'CREDIT',
            'Операция': 'DEBIT',
            'Конверсия': 'CONVERSION'
        }
        if type_match:
            transaction_type = type_map.get(type_match.group(1), 'DEBIT')
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
        
        # Extract datetime
        datetime_match = re.search(patterns['datetime'], text)
        if not datetime_match:
            return None
        if datetime_match.group(1) and datetime_match.group(2):
            time_str = datetime_match.group(1)
            date_str = datetime_match.group(2)
        else:
            date_str = datetime_match.group(3)
            time_str = datetime_match.group(4)
        transaction_date = self.parse_date(date_str, time_str)
        
        # Extract balance
        balance_match = re.search(patterns['balance'], text)
        balance_after = self.normalize_amount(balance_match.group(1)) if balance_match else None
        
        # Extract currency
        currency = amount_currency
        if not currency:
            currency_match = re.search(patterns['currency'], text)
            currency = currency_match.group(1) if currency_match else 'UZS'
        
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
        
        # Extract operator
        operator_match = re.search(patterns['operator'], text)
        operator_raw = operator_match.group(1).strip() if operator_match else None
        
        # Extract datetime
        datetime_match = re.search(patterns['datetime'], text)
        if not datetime_match:
            return None
        date_str = datetime_match.group(1)
        time_str = datetime_match.group(2)
        transaction_date = self.parse_date(date_str, time_str)
        
        # Extract card
        card_last_4 = self.extract_card_last4(text)
        
        # Extract balance
        balance_match = re.search(patterns['balance'], text)
        balance_after = self.normalize_amount(balance_match.group(1)) if balance_match else None
        
        # Determine transaction type
        type_match = re.search(patterns['type_keyword'], text)
        if type_match:
            keyword = type_match.group(1)
            if keyword in ['Popolnenie']:
                transaction_type = 'CREDIT'
            elif keyword == 'OTMENA':
                transaction_type = 'REVERSAL'
            else:
                transaction_type = 'DEBIT'
        else:
            transaction_type = 'DEBIT'
        
        return {
            'amount': amount,
            'currency': 'UZS',
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
        transaction_type = type_map.get(op_type, 'DEBIT')
        
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
        
        transaction_date = self.parse_date(date_str, time_str, format_type='semicolon')
        
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
        """Parse CardXabar-style emoji notifications."""
        patterns = self.patterns['cardxabar']

        amount_match = re.search(patterns['amount'], text)
        if not amount_match:
            return None
        amount = self.normalize_amount(amount_match.group(1))
        currency = amount_match.group(2) if amount_match.lastindex and amount_match.lastindex >= 2 else None

        card_last_4 = self.extract_card_last4(text)

        operator_match = re.search(patterns['operator'], text)
        operator_raw = operator_match.group(1).strip() if operator_match else None

        dt_match = re.search(patterns['datetime'], text)
        if not dt_match:
            return None
        if dt_match.group(1) and dt_match.group(2):
            time_str = dt_match.group(1)
            date_str = dt_match.group(2)
        else:
            date_str = dt_match.group(3)
            time_str = dt_match.group(4)
        transaction_date = self.parse_date(date_str, time_str)

        balance_match = re.search(patterns['balance'], text)
        balance_after = self.normalize_amount(balance_match.group(1)) if balance_match and balance_match.group(1) else None
        if not currency and balance_match and balance_match.lastindex and balance_match.lastindex >= 2 and balance_match.group(2):
            currency = balance_match.group(2)
        if not currency:
            currency = 'UZS'

        upper_text = text.upper()
        if "OTMENA" in upper_text:
            transaction_type = 'REVERSAL'
        elif "КОНВЕРС" in upper_text or "CONVERS" in upper_text or "CONVERSION" in upper_text or "КОНВЕРСИЯ" in upper_text or "KONVERS" in upper_text:
            transaction_type = 'CONVERSION'
        elif '🟢' in text or '➕' in text:
            transaction_type = 'CREDIT'
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
        # CardXabar style (red/green bullets, 💵 balance)
        if any(marker in text for marker in ['CardXabar', 'NBU Card', '🔴', '🟢']):
            result = self.parse_cardxabar(text)
            if result:
                return result

        # Try Humo notification format first (most common)
        if any(emoji in text for emoji in ['💸', '💳', '📍', '🕓', '🕘']):
            result = self.parse_humo_notification(text)
            if result:
                return result
        
        # Try semicolon format
        if 'HUMOCARD *' in text and ';' in text:
            result = self.parse_semicolon_format(text)
            if result:
                return result
        
        # Try SMS inline format
        if 'summa:' in text and 'karta' in text:
            result = self.parse_sms_inline(text)
            if result:
                return result
        
        # All formats failed
        return None
