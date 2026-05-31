# PARCER 2.0 — ПОЛНЫЙ СПИСОК ПРАВОК (ПАРСЕР + ФРОНТЕНД + БОТ)

> **Дата аудита:** 2026-02-13
> **Файлы:** regex_parser.py, gpt_parser.py, pdf_extractor.py, receipt_processor.py, celery_worker.py, parser_orchestrator.py, App.tsx, UserbotPage.tsx, auth_bot_handler.py
> **Тест-кейсы:** test_receipts_examples.txt (30+ чеков, 7 форматов)

---

## СТАТИСТИКА (ОБЩАЯ)

| Уровень | Парсер | Фронт+Бот | Всего |
|---------|--------|------------|-------|
| 🔴 КРИТИЧЕСКИЙ | 8 | 2 | **10** |
| 🟠 ВЫСОКИЙ | 14 | 5 | **19** |
| 🟡 СРЕДНИЙ | 12 | 6 | **18** |
| 🔵 НИЗКИЙ | 7 | 4 | **11** |
| **ИТОГО** | **41** | **17** | **58** |

---

## 🔴 КРИТИЧЕСКИЕ (блокируют корректную работу)

---

### КРИТ-01 · regex_parser.py · Emoji Humo: 📍/🕓 не соответствуют реальному формату 🏪/📅

**Файл:** `backend/parsers/regex_parser.py`
**Строки:** 24-25 (patterns['humo_notification'])

**Суть:** Regex-шаблоны Humo notification используют emoji 📍 для оператора и 🕓🕘 для даты. Но реальные чеки (и test_receipts_examples.txt формат 1) используют 🏪 и 📅.

**Что сейчас:**
```python
'operator': r'📍\s*(.+)',
'datetime': r'[🕓🕘]\s*(?:(\d{2}:\d{2})\s+(\d{2}\.\d{2}\.\d{2,4})|(\d{2}\.\d{2}\.\d{2,4})\s+(\d{2}:\d{2}))',
```

**Что должно быть:**
```python
'operator': r'[📍🏪]\s*(.+)',
'datetime': r'[🕓🕘📅]\s*(?:(\d{2}:\d{2})\s+(\d{2}\.\d{2}\.\d{2,4})|(\d{2}\.\d{2}\.\d{2,4})\s+(\d{2}:\d{2}))',
```

**Последствия:** ВСЕ чеки формата 1 (Humo notification с 🏪/📅) возвращают None из regex → падают в GPT fallback → лишние API-вызовы + задержка.

**Тесты:** 1.1, 1.2, 1.3, 1.4, 1.5, 1.6 — все проваливаются на regex.

---

### КРИТ-02 · regex_parser.py · Баланс regex не учитывает текст "Баланс:" между emoji и суммой

**Файл:** `backend/parsers/regex_parser.py`
**Строка:** 26

**Суть:** Regex `[💰💵]\s*([\d\s\.,]+)\s*(USD|UZS)` ожидает цифры сразу после emoji. Но реальный формат: `💰 Баланс: 2 340 500,00 UZS` — между emoji и цифрами стоит "Баланс: ".

**Что сейчас:**
```python
'balance': r'[💰💵]\s*([\d\s\.,]+)\s*(USD|UZS)',
```

**Что должно быть:**
```python
'balance': r'[💰💵]\s*(?:Баланс|Остаток|Balance|Balans|Dostupno)?\s*:?\s*([\d\s\.,]+)\s*(USD|UZS)',
```

**Последствия:** balance_after всегда None для Humo-чеков с кириллицей. Fingerprint для дедупликации не пострадает (balance не входит), но данные неполные.

**Тесты:** 1.1, 1.2, 1.3 — баланс не извлекается.

---

### КРИТ-03 · regex_parser.py · CardXabar формат полностью не парсится

**Файл:** `backend/parsers/regex_parser.py`
**Строки:** 44-50 (patterns['cardxabar'])

**Суть:** CardXabar-шаблоны используют emoji (➖/➕/💳/📍/🕓), но реальный формат CardXabar — текстовые метки (Summa:, Karta:, Magazin:, Data:, Vremya:).

**Что сейчас:**
```python
'cardxabar': {
    'amount': r'[➖➕]\s*([\d\s\.,]+)\s*(USD|UZS)',
    'card': r'💳\s*([\d\*]{6,})',
    'operator': r'📍\s*(.+)',
    'datetime': r'🕓\s*(?:...)',
}
```

**Что должно быть — новые паттерны для текстового CardXabar:**
```python
'cardxabar': {
    'amount': r'(?:[➖➕]|Summa)\s*:?\s*([\d\s\.,]+)\s*(USD|UZS)',
    'card': r'(?:💳|Karta)\s*:?\s*([\d\*]{6,})',
    'operator': r'(?:📍|Magazin|Otpravitel)\s*:?\s*(.+)',
    'datetime_text': r'Data\s*:?\s*(\d{2}\.\d{2}\.\d{4})\s*\n?\s*Vremya\s*:?\s*(\d{2}:\d{2})',
}
```

Также необходимо добавить определение типа:
- `🔴` или `Spisanie` → DEBIT
- `🟢` или `Zachislenie` → CREDIT
- `OTMENA` → REVERSAL
- `KONVERSIJA` → CONVERSION

**Последствия:** CardXabar чеки (формат 4) не парсятся regex → GPT fallback.

**Тесты:** 4.1, 4.2, 4.3, 4.4 — все проваливаются.

---

### КРИТ-04 · regex_parser.py · SMS inline паттерны не соответствуют реальному формату

**Файл:** `backend/parsers/regex_parser.py`
**Строки:** 29-36 (patterns['sms_inline']) и 587-589 (parse cascade guard)

**Суть:** SMS regex ожидает `summa:`, `karta ***`, `balans:`, но реальные SMS (тесты 2.1-2.7) имеют формат:
```
Pokupka: XK FAMILY SHOP, 250000.00 UZS, 02.04.25 08:37 *6714 Bal:1500000.00 UZS
```

**Проблемы:**
1. Guard `'summa:' in text and 'karta' in text` — SMS не содержат этих слов → парсер даже не вызывается
2. `amount: r'summa:([\d\s\.,]+)\s*UZS'` — сумма идёт после оператора через запятую, не после "summa:"
3. `card: r'karta\s*\*{3}(\d{4})'` — карта указана как `*6714`, не `karta ***6714`
4. `balance: r'balans:([\d\s\.,]+)\s*UZS'` — баланс через `Bal:`, не `balans:`

**Что должно быть — переписать паттерны под реальный формат:**
```python
'sms_inline': {
    'operator': r'(?:Pokupka|Spisanie c karty|Popolnenie scheta|E-Com oplata|Platezh):\s*(.+?)(?:,\s*\d)',
    'amount': r',\s*([\d\s\.,]+)\s*(UZS|USD)',
    'datetime': r'(\d{2}\.\d{2}\.\d{2})\s+(\d{2}:\d{2})',
    'card': r'\*(\d{4})',
    'balance': r'Bal\s*:\s*([\d\s\.,]+)\s*(UZS|USD)',
    'type_keyword': r'^(Pokupka|Spisanie|Popolnenie|E-Com|Platezh|OTMENA)',
}
```

И поменять guard:
```python
# Вместо:
if 'summa:' in text and 'karta' in text:
# Должно:
sms_keywords = ['Pokupka:', 'Spisanie', 'Popolnenie', 'E-Com oplata', 'Platezh:']
if any(kw in text for kw in sms_keywords):
```

**Тесты:** 2.1-2.7 — все проваливаются.

---

### КРИТ-05 · regex_parser.py · Semicolon datetime regex не матчит YYYY-MM-DD

**Файл:** `backend/parsers/regex_parser.py`
**Строка:** 40

**Суть:** Regex `;\s*(\d{2})-(\d{2})-(\d{2})\s+(\d{2}:\d{2})` ожидает YY-MM-DD (6 цифр), но тесты показывают YYYY-MM-DD: `2025-04-02 08:37`.

При `2025-04-02`, regex захватывает: group(1)="20", group(2)="25", group(3)="04", потом ожидает `\s+` но видит `-02`. Не матчится.

**Что должно быть:**
```python
'datetime': r';\s*(\d{2,4})-(\d{2})-(\d{2})\s+(\d{2}:\d{2})',
```

И в `parse_date` (строка 278) добавить обработку 4-значного года:
```python
if format_type == 'semicolon':
    parts = date_str.split('-')
    if len(parts[0]) == 2:
        parts[0] = f"20{parts[0]}"
    full_year = parts[0]
    dt_str = f"{full_year}-{parts[1]}-{parts[2]} {time_str}"
    dt = datetime.strptime(dt_str, "%Y-%m-%d %H:%M")
```

**Тесты:** 3.1, 3.2, 3.3, 3.4 — datetime не извлекается → None.

---

### КРИТ-06 · celery_worker.py · task_time_limit=30 секунд — слишком мало для Vision API

**Файл:** `backend/workers/celery_worker.py`
**Строка:** 35

**Суть:** GPT Vision API вызов занимает 10-20 секунд. PDF OCR через Tesseract — 5-15 секунд. Суммарно при PDF + OCR + Vision = 30+ секунд. Worker убивает таск раньше завершения.

**Что должно быть:**
```python
task_time_limit=120,      # Hard limit: 2 минуты
task_soft_time_limit=90,  # Soft limit: 1.5 минуты (SoftTimeLimitExceeded)
```

**Последствия:** PDF-чеки с Vision fallback случайно обрезаются → retry → 3 retry → permanent fail.

---

### КРИТ-07 · celery_worker.py · Знак суммы: worker хранит positive, receipt_processor хранит signed

**Файл:** `backend/workers/celery_worker.py` строка 550 vs `backend/services/receipt_processor.py` строка 479

**Суть:** В receipt_processor.py:
```python
store_amount = -abs(amount) if txn_type == "DEBIT" else abs(amount)
```
В celery_worker.py:
```python
amount=amount,  # всегда positive (строка 550)
```

Один и тот же чек обработанный через TDLib endpoint и через Celery worker получит разные знаки amount в БД.

**Что должно быть в celery_worker.py (строка 549-550):**
```python
store_amount = -abs(amount) if transaction_type == "DEBIT" else abs(amount)
...
amount=store_amount,
```

---

### КРИТ-08 · receipt_processor.py · Fingerprint: Decimal precision даёт разные хэши

**Файл:** `backend/services/receipt_processor.py`
**Строка:** 40

**Суть:** `str(abs(amount))` — для `Decimal("100")` даёт `"100"`, для `Decimal("100.00")` даёт `"100.00"`. Разные строки → разные SHA256 → дубликат не обнаружен.

**Что сейчас:**
```python
amount_str = str(abs(amount)) if amount else "0"
```

**Что должно быть:**
```python
amount_str = str(abs(amount).quantize(Decimal("0.01"))) if amount else "0.00"
```

И такое же исправление в `celery_worker.py` строка 98 (дублированная функция).

---

## 🟠 ВЫСОКИЕ (искажают данные или теряют информацию)

---

### ВЫС-01 · regex_parser.py · P2P parse_sender_receiver_transfer: receiver_card не извлекает last4

**Файл:** `backend/parsers/regex_parser.py`
**Строка:** 134

**Суть:** `receiver_card = receiver_mask.group(1).strip()` возвращает полную маску (напр. `986006******1234`), а не последние 4 цифры.

**Что должно быть:**
```python
receiver_card = self.extract_card_last4(receiver_mask.group(1)) if receiver_mask else None
```

**Аналогично** в `parse_ru_transfer` строка 207:
```python
receiver_card = self.extract_card_last4(receiver_mask.group(1)) if receiver_mask else None
```

---

### ВЫС-02 · regex_parser.py · P2P логика AND vs OR: single-language P2P теряются

**Файл:** `backend/parsers/regex_parser.py`
**Строки:** 71-73

**Суть:** Условие `("sender" not in lower or "receiver" not in lower) and ("отправител" not in lower or "получател" not in lower)` корректно для ПОЛНЫХ P2P (sender+receiver), но не обрабатывает edge case 5.3 (только отправитель без получателя). Тест 5.3 ожидает `is_p2p=true`, но функция вернёт None.

**Рекомендация:** Для частичных P2P (только sender) можно добавить отдельную ветку после основного парсинга, или задокументировать что частичный P2P не поддерживается.

---

### ВЫС-03 · regex_parser.py · Дублированные regex в parse_sender_receiver_transfer

**Файл:** `backend/parsers/regex_parser.py`
**Строки:** 78-94

**Суть:** Блок `amount_match` сначала ищет по 4 паттернам (строки 80-85), затем если не нашёл — ищет по 2 паттернам (строки 88-93) которые уже входят в первый набор. Второй поиск никогда не сработает — первый уже покрыл эти паттерны.

**Что должно быть:** Удалить строки 87-94 (второй блок поиска).

---

### ВЫС-04 · regex_parser.py · parse() cascade: Humo guard не включает emoji ➖/➕

**Файл:** `backend/parsers/regex_parser.py`
**Строка:** 576

**Суть:** Guard проверяет `['💸', '💳', '📍', '🕓', '🕘']`, но не включает `➖` и `➕` которые являются основными маркерами Humo-чеков. Чек формата `➖ 150 000 UZS\n💳 HUMOCARD *4862\n🏪 ...` имеет `💳` → guard пройдёт. Но если чек пришёл без `💳` (edge case), он не попадёт в Humo парсер.

**Что должно быть:**
```python
if any(emoji in text for emoji in ['💸', '💳', '📍', '🏪', '🕓', '🕘', '📅', '➖', '➕']):
```

---

### ВЫС-05 · regex_parser.py · Semicolon guard: "HUMOCARD *" не матчит "HUMOCARD*"

**Файл:** `backend/parsers/regex_parser.py`
**Строка:** 582

**Суть:** `if 'HUMOCARD *' in text` ожидает пробел между HUMOCARD и *. Но формат `HUMOCARD*4862:` (без пробела) не пройдёт guard → semicolon парсер не вызовется.

**Что должно быть:**
```python
if ('HUMOCARD*' in text or 'HUMOCARD *' in text) and ';' in text:
```

---

### ВЫС-06 · gpt_parser.py · parse_from_images: hardcoded image/png MIME type

**Файл:** `backend/parsers/gpt_parser.py`
**Строка:** 185

**Суть:** `data:image/png;base64,{img}` — жёстко ставит PNG. Но если изображение — JPEG (фото из TG, скриншот), GPT может неправильно декодировать.

**Что должно быть:**
```python
# Автоопределение MIME по заголовку base64
def _detect_mime(b64: str) -> str:
    header = base64.b64decode(b64[:32])
    if header[:3] == b'\xff\xd8\xff':
        return 'image/jpeg'
    if header[:8] == b'\x89PNG\r\n\x1a\n':
        return 'image/png'
    if header[:4] == b'RIFF' and header[8:12] == b'WEBP':
        return 'image/webp'
    return 'image/png'  # fallback
```

Или проще — GPT-4o принимает `data:image/jpeg` и `data:image/png` корректно, достаточно передавать правильный тип из caller'а.

---

### ВЫС-07 · gpt_parser.py · _extract_json: greedy regex \{.*\} захватывает лишнее

**Файл:** `backend/parsers/gpt_parser.py`
**Строка:** 152

**Суть:** `re.search(r"\{.*\}", content, re.DOTALL)` — greedy match от первого `{` до последнего `}`. Если GPT вернул текст с двумя JSON объектами или комментарий после JSON, regex захватит всё между ними → невалидный JSON.

**Что должно быть:**
```python
match = re.search(r"\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}", content, re.DOTALL)
```

Или лучше — итеративный поиск сбалансированных скобок.

---

### ВЫС-08 · celery_worker.py · source_chat_id: str(None) = "None" → int("None") → 0

**Файл:** `backend/workers/celery_worker.py`
**Строки:** 252-253, 457-459

**Суть:** `source_chat_id = str(task_data.get('source_chat_id'))` — если значение None, получится строка `"None"`. Потом `int("None")` → ValueError → catch → `chat_id_int = 0`. Транзакция сохраняется с `source_chat_id=0` вместо NULL.

**Что должно быть:**
```python
_raw_chat = task_data.get('source_chat_id')
source_chat_id = str(_raw_chat) if _raw_chat is not None else None
_raw_msg = task_data.get('source_message_id')
source_message_id = str(_raw_msg) if _raw_msg is not None else None
```

И ниже (строка 457):
```python
chat_id_int = int(source_chat_id) if source_chat_id else None  # None вместо 0
```

---

### ВЫС-09 · celery_worker.py · DPI несоответствие: 170 vs 150

**Файл:** `backend/workers/celery_worker.py` строка 357 vs `backend/services/receipt_processor.py` строка 373

**Суть:** Worker рендерит PDF при dpi=170, receipt_processor при dpi=150. Разный DPI → разное качество → потенциально разные результаты GPT Vision для одного документа.

**Что должно быть:** Унифицировать DPI в config:
```python
# config.py или .env
PDF_VISION_DPI = 200  # рекомендуемый для банковских чеков
```

---

### ВЫС-10 · celery_worker.py · compute_fingerprint дублирована из receipt_processor

**Файл:** `backend/workers/celery_worker.py` строки 95-102
**Файл:** `backend/services/receipt_processor.py` строки 38-44

**Суть:** Одна и та же функция в двух местах. Если исправить КРИТ-08 только в одном месте, fingerprints разойдутся.

**Что должно быть:** Вынести в `utils/fingerprint.py` или `services/fingerprint.py`:
```python
# services/fingerprint.py
from decimal import Decimal
import hashlib
from datetime import datetime

def compute_fingerprint(amount: Decimal, transaction_date: datetime, card_last4: str) -> str:
    amount_str = str(abs(amount).quantize(Decimal("0.01"))) if amount else "0.00"
    date_str = transaction_date.strftime("%Y-%m-%d %H:%M") if transaction_date else ""
    card_str = str(card_last4)[-4:] if card_last4 else "0000"
    data = f"{amount_str}|{date_str}|{card_str}"
    return hashlib.sha256(data.encode()).hexdigest()
```

Импортировать из обоих файлов.

---

### ВЫС-11 · parser_orchestrator.py · is_gpt_parsed не ловит GPT_VISION

**Файл:** `backend/parsers/parser_orchestrator.py`
**Строка:** 154

**Суть:**
```python
parsed_data['is_gpt_parsed'] = (parsed_data.get('parsing_method') == 'GPT')
```
Не учитывает `GPT_VISION`. Результаты Vision парсинга будут с `is_gpt_parsed=False`.

**Что должно быть:**
```python
parsed_data['is_gpt_parsed'] = (parsed_data.get('parsing_method') or '').upper().startswith('GPT')
```

---

### ВЫС-12 · regex_parser.py · normalize_amount: catastrophic backtracking потенциал

**Файл:** `backend/parsers/regex_parser.py`
**Строка:** 21

**Суть:** Паттерн `[\d\s\.,]+` может привести к exponential backtracking на строках с чередующимися пробелами и цифрами. При строке 10000+ символов (тест 6.3) regex engine может зависнуть.

**Рекомендация:** Ограничить квантификатор:
```python
'amount': r'[➖➕💸]\s*([\d\s\.,]{1,30})\s*(UZS|USD)',
```

Также добавить таймаут через `re.compile` с ограничением длины входа в `parse()`:
```python
def parse(self, text: str) -> Optional[Dict[str, Any]]:
    if not text or len(text) > 10000:
        return None
```

---

### ВЫС-13 · regex_parser.py · card regex: слишком loose паттерн

**Файл:** `backend/parsers/regex_parser.py`
**Строка:** 23

**Суть:** `([\d\*]{6,})` матчит любую комбинацию цифр и звёздочек длиной 6+. Может ложно сработать на тексте типа `123456` (просто число). Но `extract_card_last4()` вызывается отдельно и работает корректнее.

**Рекомендация:** Ужесточить паттерн:
```python
'card': r'(?:HUMO-?CARD|HUMOCARD|💳)\s*(?:HUMO-?CARD\s*)?(\d{4,6}\*{2,}\*?\d{4}|\*{2,}\d{4})',
```

---

### ВЫС-14 · regex_parser.py · card regex на строке 23 не матчит "💳 HUMOCARD *4862"

**Файл:** `backend/parsers/regex_parser.py`
**Строка:** 23

**Суть:** Для текста `💳 HUMOCARD *4862`:
- Вариант 1: matches `💳` → expects `([\d\*]{6,})` → "HUMOCARD" содержит буквы → fail
- Вариант 2: matches `HUMOCARD` → expects `\s*([\d\*]{6,})` → " *4862" → `*4862` = 5 символов, но нужно `{6,}` → fail

Результат: card regex вообще не матчит на типичном формате. Работает только fallback `extract_card_last4(text)`.

**Что должно быть:**
```python
'card': r'(?:HUMO-?CARD|💳)\s*(?:HUMO-?CARD\s*)?\*?(\d{4})',
```

Или проще — полагаться только на `extract_card_last4()` и убрать card из patterns:
```python
# В parse_humo_notification, строка 338:
card_last_4 = self.extract_card_last4(text)  # уже так и есть
```

---

## 🟡 СРЕДНИЕ (edge cases, потенциальные проблемы)

---

### СРД-01 · gpt_parser.py · fromisoformat может упасть на нестандартном формате

**Файл:** `backend/parsers/gpt_parser.py`
**Строка:** 95

**Суть:** `datetime.fromisoformat()` не обрабатывает все ISO 8601 варианты (напр. `2025-04-02T14:37:00.123+05:00` работает в Python 3.11+, но не в 3.9). GPT может вернуть любой формат.

**Рекомендация:** Обернуть в try/except с fallback:
```python
try:
    transaction_date = datetime.fromisoformat(parsed.transaction_date_iso.replace('Z', '+00:00'))
except ValueError:
    from dateutil.parser import parse as dateutil_parse
    transaction_date = dateutil_parse(parsed.transaction_date_iso)
```

---

### СРД-02 · gpt_parser.py · max_tokens=600 может быть мало

**Файл:** `backend/parsers/gpt_parser.py`
**Строка:** 195

**Суть:** Для Vision mode, GPT может выдать длинный JSON если все поля заполнены + reasoning. 600 токенов ~= 400 слов, обычно достаточно. Но при сложных чеках (P2P с кириллицей) может обрезаться.

**Рекомендация:** Увеличить до 800-1000:
```python
max_tokens=1000,
```

---

### СРД-03 · pdf_extractor.py · PyMuPDF doc handle не закрывается при ошибке

**Файл:** `backend/parsers/pdf_extractor.py`
**Строки:** 91-104

**Суть:** Если `doc.load_page()` или `page.get_text()` выбросит исключение, `doc.close()` не вызовется (нет finally). Файловый дескриптор утечёт.

**Что должно быть:**
```python
def _extract_with_pymupdf(path: str, max_pages: int) -> str:
    try:
        doc = fitz.open(path)
        try:
            texts: List[str] = []
            for page_index in range(min(max_pages, doc.page_count)):
                page = doc.load_page(page_index)
                page_text = page.get_text("text") or ""
                if page_text.strip():
                    texts.append(page_text)
            return "\n".join(texts).strip()
        finally:
            doc.close()
    except Exception as err:
        logger.debug("PyMuPDF extraction failed: %s", err)
        return ""
```

---

### СРД-04 · pdf_extractor.py · _preprocess_for_ocr не используется в PDF OCR path

**Файл:** `backend/parsers/pdf_extractor.py`
**Строки:** 123-144, 161-168

**Суть:** Функция `_preprocess_for_ocr` (grayscale, contrast, sharpen) существует и используется для `extract_text_from_image_path`, но НЕ вызывается в `_extract_with_ocr` для PDF-страниц. PDF-скан идёт в Tesseract без препроцессинга → хуже качество OCR.

**Что должно быть в `_extract_with_ocr` строка 136:**
```python
for i, image in enumerate(images):
    prepared = _preprocess_for_ocr(image)  # добавить
    text = pytesseract.image_to_string(prepared, lang=lang)
```

---

### СРД-05 · pdf_extractor.py · _preferred_ocr_lang не используется в PDF OCR

**Файл:** `backend/parsers/pdf_extractor.py`
**Строка:** 79 vs 147-158

**Суть:** `_extract_with_ocr` вызывается с `lang='rus+eng'` (хардкод), а функция `_preferred_ocr_lang` проверяет наличие `uzb` языка но никогда не вызывается в PDF пути.

**Что должно быть на строке 79:**
```python
ocr_text = _extract_with_ocr(path, max_pages, lang=_preferred_ocr_lang())
```

---

### СРД-06 · receipt_processor.py · card_last_4 vs card_last4 naming inconsistency

**Файл:** `backend/services/receipt_processor.py`
**Строка:** 482

**Суть:** `parsed.get("card_last_4") or parsed.get("card_last4")` — два имени для одного поля. Regex parser возвращает `card_last_4`, GPT тоже `card_last_4`. Но в некоторых местах используется `card_last4` без подчёркивания.

**Рекомендация:** Стандартизировать на `card_last_4` везде. Grep + replace по проекту.

---

### СРД-07 · receipt_processor.py · Quality score не нормализован

**Файл:** `backend/services/receipt_processor.py`
**Строки:** 102-126

**Суть:** `_tx_quality_score` возвращает значение 0-155 (confidence*100 + bonuses). Порог сравнения `candidate_score > (existing_score + 0.5)` — разница 0.5 при шкале 0-155 означает что даже минимальное улучшение (доп. поле) вызывает merge. Может привести к лишним обновлениям.

**Рекомендация:** Либо нормализовать до 0-1, либо увеличить threshold:
```python
candidate_is_better = candidate_score > (existing_score + 5.0)  # минимум 5 очков разницы
```

---

### СРД-08 · regex_parser.py · Нулевая/отрицательная сумма не обрабатывается

**Файл:** `backend/parsers/regex_parser.py`
**Строка:** 227-260

**Суть:** `normalize_amount` не отклоняет нулевую сумму (тест 6.5: `0.00 UZS`). Отрицательная сумма (тест 6.6: `-150000`) — минус не в `[\d\s\.,]` → regex не захватит его, но если захватит — `Decimal("-150000")` будет отрицательным.

**Рекомендация:** В `_post_validate_and_enrich` (orchestrator строка 164):
```python
if data.get('amount') is not None:
    data['amount'] = abs(data['amount'])
    if data['amount'] == 0:
        raise ValueError("Zero amount")  # или return None
```

---

### СРД-09 · regex_parser.py · Невалидная дата не вызывает graceful None

**Файл:** `backend/parsers/regex_parser.py`
**Строки:** 275-295

**Суть:** `parse_date` выбрасывает ValueError при невалидной дате. Вызывающий код (напр. `parse_humo_notification` строка 368) не оборачивает в try/except → unhandled exception → parse() ловит на верхнем уровне → None. Работает, но стектрейс в логах.

**Тест 6.8:** `📅 99.99.9999 25:61` → strptime упадёт → ValueError → "Date parsing error" → Exception → None. Корректно, но шумно.

**Рекомендация:** В каждом parse_* методе обернуть `parse_date` в try/except:
```python
try:
    transaction_date = self.parse_date(date_str, time_str)
except ValueError:
    return None
```

---

### СРД-10 · regex_parser.py · Карта 3 цифры: нет валидации

**Файл:** `backend/parsers/regex_parser.py`
**Строка:** 262-273

**Суть:** `extract_card_last4` вернёт любые 4+ цифры после звёздочек. Но тест 6.9 — `*486` (3 цифры). Regex `\*+(\d{4})` НЕ матчит 3 цифры → вернёт None. Это корректное поведение, но стоит задокументировать.

---

### СРД-11 · celery_worker.py · normalize_amount_positive не обрабатывает строки с пробелами

**Файл:** `backend/workers/celery_worker.py`
**Строка:** 88-92

**Суть:** `Decimal(value)` упадёт если value = "1 000,00" (с пробелами/запятыми). Regex parser возвращает уже нормализованный Decimal, но если данные приходят из GPT как строка — crash.

**Что должно быть:**
```python
def normalize_amount_positive(value) -> Optional[Decimal]:
    if value is None:
        return None
    if isinstance(value, str):
        cleaned = value.replace(" ", "").replace(",", ".")
        return abs(Decimal(cleaned))
    return abs(Decimal(str(value)))
```

---

### СРД-12 · Нет поддержки нескольких чеков в одном сообщении

**Тест:** 6.10

**Суть:** Если в одном сообщении два чека (два блока с emoji), парсер обрабатывает только первый. Второй теряется.

**Рекомендация:** Добавить split по emoji-маркерам (➖/➕/💸) и обработать каждый блок отдельно. Это feature request, не баг текущей логики.

---

## 🔵 НИЗКИЕ (стиль, оптимизация, minor)

---

### НИЗ-01 · parser_orchestrator.py · Создаёт новый RegexParser() для fallback card

**Файл:** `backend/parsers/parser_orchestrator.py`
**Строка:** 179

**Суть:** `RegexParser().extract_card_last4(raw_text)` — создаёт новый экземпляр вместо `self.regex_parser.extract_card_last4(raw_text)`.

---

### НИЗ-02 · Все парсеры используют print() вместо logging

**Файлы:** regex_parser.py, parser_orchestrator.py, celery_worker.py

**Суть:** `print(f"✅ ...")`, `print(f"❌ ...")` — в production эти сообщения не попадают в structured logs. Заменить на `logger.info()` / `logger.error()`.

---

### НИЗ-03 · gpt_parser.py · _mask_sensitive_text: phone regex слишком агрессивный

**Файл:** `backend/parsers/gpt_parser.py`
**Строка:** 91

**Суть:** `r"\+?\d[\d -]{9,14}"` может замаскировать суммы (напр. `1 234 567 890 123 UZS` → `*****0123 UZS`). Для узбекских чеков суммы с пробелами попадают под этот паттерн.

**Рекомендация:** Применять маскировку только если за числом НЕ следует UZS/USD:
```python
masked = re.sub(r"\+?\d[\d -]{9,14}(?!\s*(?:UZS|USD))", mask_digits, masked)
```

---

### НИЗ-04 · regex_parser.py · Humo card pattern: cardxabar vs humo дублирование

**Суть:** Patterns для `cardxabar` и `humo_notification` почти идентичны (те же emoji). Можно вынести общие паттерны в shared dict.

---

### НИЗ-05 · receipt_processor.py · `_has_value` — "UNKNOWN" check case-insensitive

**Файл:** `backend/services/receipt_processor.py`
**Строка:** 52

**Суть:** `normalized.upper() == "UNKNOWN"` — корректно. Но не проверяет "N/A", "None", "null", "—" которые GPT может вернуть.

---

### НИЗ-06 · celery_worker.py · Переменная processing_time объявлена до использования

**Файл:** `backend/workers/celery_worker.py`
**Строка:** 385 vs 579

**Суть:** `processing_time` вычисляется на строке 385, но если выполнение дойдёт до строки 579 (log), переменная может быть stale (не обновлена после длительных операций DB).

---

### НИЗ-07 · pdf_extractor.py · render_image_to_base64 не проверяет существование файла

**Файл:** `backend/parsers/pdf_extractor.py`
**Строка:** 200-203

**Суть:** `open(path, "rb")` без проверки существования и без информативной ошибки. Стандартный FileNotFoundError будет достаточен, но в контексте обработки чеков стоит логировать.

---

## ФИЧИ (отсутствующий функционал)

---

### ФИЧ-01 · Экспорт Excel за выбранный период

**Суть:** Нет backend endpoint для экспорта транзакций за указанный диапазон дат. Frontend (`excelExport.ts` строки 151-174) имеет pre-check на locked periods, но нет:
1. `GET /api/transactions/export-range?start=YYYY-MM-DD&end=YYYY-MM-DD` endpoint
2. Frontend UI для выбора периода (date range picker)
3. Streaming для больших выгрузок (1000+ записей)

**Что нужно:**

**Backend** (`transactions.py`):
```python
@router.get("/export-range")
async def export_transactions_range(
    start_date: date = Query(...),
    end_date: date = Query(...),
    format: str = Query("xlsx"),
    db: Session = Depends(get_db),
    scope = Depends(require_scope),
):
    # 1. Проверить locked periods
    # 2. Fetch transactions в диапазоне
    # 3. Сгенерировать Excel через openpyxl
    # 4. Вернуть StreamingResponse
```

**Frontend** — date range picker в TransactionsPage + кнопка "Экспорт за период".

---

### ФИЧ-02 · Поддержка кириллической даты

**Тест:** 6.11

**Суть:** `📅 02 апреля 2025 14:37` — regex не поддерживает словесные месяцы на русском. Нужен дополнительный datetime паттерн:
```python
MONTHS_RU = {
    'января': '01', 'февраля': '02', 'марта': '03', 'апреля': '04',
    'мая': '05', 'июня': '06', 'июля': '07', 'августа': '08',
    'сентября': '09', 'октября': '10', 'ноября': '11', 'декабря': '12',
}
```

---

### ФИЧ-03 · Поддержка кириллической валюты "сум"

**Тест:** 6.11

**Суть:** Regex ожидает `UZS|USD`, но некоторые чеки используют "сум" или "сўм". Добавить в currency patterns:
```python
r'(UZS|USD|сум|сўм|sum)'
```
С нормализацией: `сум` → `UZS`, `сўм` → `UZS`.

---

## ПОРЯДОК ИСПРАВЛЕНИЙ

### Этап 1 (критические — сразу)
1. КРИТ-01: Emoji Humo ← добавить 🏪/📅
2. КРИТ-02: Balance regex ← добавить "Баланс:"
3. КРИТ-03: CardXabar patterns ← переписать под текстовые метки
4. КРИТ-04: SMS patterns ← переписать + guard
5. КРИТ-05: Semicolon datetime YYYY
6. КРИТ-06: task_time_limit → 120
7. КРИТ-07: Amount sign convention
8. КРИТ-08: Fingerprint Decimal quantize

### Этап 2 (высокие — после критических)
1. ВЫС-01: receiver_card last4
2. ВЫС-06: image MIME auto-detect
3. ВЫС-07: JSON extraction regex
4. ВЫС-08: str(None) → "None"
5. ВЫС-09: DPI unify
6. ВЫС-10: compute_fingerprint → shared module
7. ВЫС-11: is_gpt_parsed GPT_VISION
8. ВЫС-12: catastrophic backtracking guard
9. Остальные ВЫС-*

### Этап 3 (средние + низкие)
Всё остальное + тесты на test_receipts_examples.txt.

### Этап 4 (фичи)
ФИЧ-01: Excel period export
ФИЧ-02: Кириллическая дата
ФИЧ-03: Кириллическая валюта

---

## ВАЛИДАЦИЯ

После каждого этапа прогнать все 30+ примеров из `test_receipts_examples.txt`:
- Формат 1 (Humo): тесты 1.1-1.8
- Формат 2 (SMS): тесты 2.1-2.7
- Формат 3 (Semicolon): тесты 3.1-3.5
- Формат 4 (CardXabar): тесты 4.1-4.4
- Формат 5 (P2P): тесты 5.1-5.4
- Формат 6 (Edge cases): тесты 6.1-6.12
- Формат 7 (PDF): ручной QA

---

---
---

# ЧАСТЬ 2: ФРОНТЕНД + БОТ + ОПТИМИЗАЦИЯ

---

## СТАТИСТИКА (ЧАСТЬ 2)

| Уровень | Кол-во |
|---------|--------|
| 🔴 КРИТИЧЕСКИЙ | 2 |
| 🟠 ВЫСОКИЙ | 5 |
| 🟡 СРЕДНИЙ | 6 |
| 🔵 НИЗКИЙ | 4 |
| **ИТОГО** | **17** |
| **ОБЩИЙ ИТОГ (Часть 1 + 2)** | **58** |

---

## 🔴 КРИТИЧЕСКИЕ

---

### ФРОНТ-КРИТ-01 · App.tsx · Вкладка "Telegram Bots" доступна без scope-кода

**Файл:** `frontend/src/App.tsx`
**Строки:** 153-160

**Суть:** После прохождения LaunchGate (пароль запуска) все вкладки доступны без дополнительной авторизации:
```tsx
<Routes>
    <Route path="/" element={<TransactionsPage />} />
    <Route path="/userbot" element={<UserbotPage />} />  // ← нет guard
    <Route path="/logs" element={<LogsPage />} />
</Routes>
```

Backend защищает API через `require_sources_scope` (telegram_client.py строка 36), но фронтенд рендерит страницу. Пользователь видит UI, все API-вызовы падают с 403. Это сбивает с толку.

**Что должно быть — Route Guard:**
```tsx
// components/ScopeGuard.tsx
function ScopeGuard({ scopeName, children }: { scopeName: string; children: ReactNode }) {
    const { data: scopeStatus } = useQuery(['scope-check', scopeName], () => api.checkScope(scopeName));

    if (!scopeStatus?.hasAccess) {
        return <ScopeUnlockPage scopeName={scopeName} />;  // запрос OTP кода
    }
    return <>{children}</>;
}

// App.tsx
<Route path="/userbot" element={
    <ScopeGuard scopeName="sources">
        <UserbotPage />
    </ScopeGuard>
} />
```

Нужен backend endpoint `GET /api/security/scope-status/{scope_name}` который возвращает `{ hasAccess: boolean, requiresOtp: boolean }`.

**Последствия:** Заказчик зашёл на вкладку "Telegram Bots", увидел пустой экран с ошибками. Должно было попросить OTP-код.

---

### ФРОНТ-КРИТ-02 · UserbotPage.tsx · Нет контекстного меню для управления паролем чата

**Файл:** `frontend/src/pages/UserbotPage.tsx`

**Суть:** Правый клик на чат не показывает никаких опций. Нет UI для:
1. Установки пароля на чат (двухфакторка)
2. Смены пароля чата
3. Снятия пароля чата
4. Просмотра статуса защиты чата

Текущее поведение: `ChatPasswordModal.tsx` показывается только при ОТКРЫТИИ защищённого чата (проверка пароля). Нет способа НАСТРОИТЬ защиту из UI.

Backend API уже существует:
- `PUT /api/tg/chats/{chatId}/password` — установить
- `DELETE /api/tg/chats/{chatId}/password` — снять

**Что нужно:**

1. Добавить `onContextMenu` на элемент чата:
```tsx
<div
    key={chat.id}
    onContextMenu={(e) => {
        e.preventDefault();
        setContextMenu({ x: e.clientX, y: e.clientY, chatId: chat.id });
    }}
>
```

2. Компонент `ChatContextMenu.tsx`:
```tsx
<div style={{ position: 'fixed', top: y, left: x }}>
    <button onClick={() => openSetPasswordDialog(chatId)}>
        🔒 Установить пароль
    </button>
    <button onClick={() => removePassword(chatId)}>
        🔓 Снять пароль
    </button>
    <button onClick={() => toggleHide(chatId)}>
        👁 Скрыть/Показать
    </button>
</div>
```

3. Диалог `SetChatPasswordDialog.tsx` — форма с полем ввода пароля + подтверждение.

**Важно:** Показывать иконку 🔒 рядом с именем чата если пароль установлен.

---

## 🟠 ВЫСОКИЕ

---

### ФРОНТ-ВЫС-01 · auth_bot_handler.py · Команды бота слишком сложные для заказчика

**Файл:** `backend/services/auth_bot_handler.py`

**Суть:** 13 команд с техническими ID и форматами дат. Заказчик не программист — не знает chat_id, scope_id, session_id.

**Текущие команды:**
```
/set_launch_password <password>
/lock_period <YYYY-MM-DD> <YYYY-MM-DD> [reason]
/unlock_period <lock_id>
/set_chat_password <chat_id> <password>
/remove_chat_password <chat_id>
/toggle_scope <scope_id>
/kill_session <session_id>
```

**Проблемы:**
1. `<chat_id>` — откуда заказчик знает ID чата? Не видно в UI
2. `<scope_id>` — аналогично
3. `<lock_id>` — надо сначала вызвать `/list_periods` и найти ID
4. `YYYY-MM-DD` — формат даты без подсказки, ошибка → "Неверный формат"
5. `<session_id>` — строка из Redis, непонятная для человека

**Что сделать:**

1. **Inline Keyboard вместо текстовых команд:**
```python
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

async def cmd_start(message: Message):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📊 Статус", callback_data="status")],
        [InlineKeyboardButton(text="🔐 Сменить пароль", callback_data="change_password")],
        [InlineKeyboardButton(text="📅 Заблокировать период", callback_data="lock_period")],
        [InlineKeyboardButton(text="🔓 Разблокировать период", callback_data="unlock_list")],
        [InlineKeyboardButton(text="💬 Пароли чатов", callback_data="chat_passwords")],
        [InlineKeyboardButton(text="📋 Сессии", callback_data="sessions")],
    ])
    await message.reply("Выберите действие:", reply_markup=kb)
```

2. **Wizard-style для lock_period:**
```
Бот: Введите дату начала блокировки (ДД.ММ.ГГГГ)
User: 01.04.2025
Бот: Введите дату окончания (ДД.ММ.ГГГГ)
User: 30.04.2025
Бот: Причина? (или /skip)
User: Закрытие отчётного периода
Бот: ✅ Период 01.04.2025 — 30.04.2025 заблокирован
```

3. **Для chat_password — показывать список чатов кнопками:**
```
Бот: Выберите чат для настройки пароля:
[💬 Чат с Джеком] [💬 Рабочий канал] [💬 Стив аналитика]
```
Это требует запроса списка чатов из TDLib через внутренний API.

4. **Для unlock_period — показывать активные блокировки кнопками:**
```
Бот: Активные блокировки:
[❌ #5: 01.04-30.04 "Отчёт"]
[❌ #8: 01.06-30.06 "Аудит"]
```

5. **Поддержать ДД.ММ.ГГГГ помимо YYYY-MM-DD:**
```python
def _parse_date(value: str) -> Optional[date]:
    for fmt in ('%Y-%m-%d', '%d.%m.%Y', '%d.%m.%y', '%d/%m/%Y'):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    return None
```

---

### ФРОНТ-ВЫС-02 · UserbotPage.tsx · 87 KB / 1534 строки — монолитный компонент

**Файл:** `frontend/src/pages/UserbotPage.tsx`

**Суть:** Один файл содержит ВСЮ логику: список чатов, список сообщений, выделение, batch processing, статусы, OTP, пароли, скрытие, автоматизация. Любое изменение рискует сломать другую часть.

**Разбить на:**
1. `ChatList.tsx` — список чатов с поиском и фильтрацией
2. `MessagePanel.tsx` — сообщения с выделением и batch-действиями
3. `MessageItem.tsx` — отдельное сообщение с иконкой статуса
4. `ChatContextMenu.tsx` — контекстное меню (новый, см. ФРОНТ-КРИТ-02)
5. `UserbotToolbar.tsx` — верхняя панель действий

---

### ФРОНТ-ВЫС-03 · UserbotPage.tsx · 300+ DOM-узлов сообщений без виртуализации

**Файл:** `frontend/src/pages/UserbotPage.tsx`
**Строка:** 80 (`MAX_MESSAGE_ITEMS = 300`)

**Суть:** Рендерятся ВСЕ 300 сообщений как DOM-элементы, даже если видно только 10-15. При скролле — тяжёлый layout. На слабых машинах — фриз.

**Что должно быть:**
```bash
npm install @tanstack/react-virtual
```
```tsx
import { useVirtualizer } from '@tanstack/react-virtual';

const virtualizer = useVirtualizer({
    count: messages.length,
    getScrollElement: () => messagesScrollRef.current,
    estimateSize: () => 80,
    overscan: 5,
});
```

---

### ФРОНТ-ВЫС-04 · UserbotPage.tsx · 3 параллельных polling-цикла

**Файл:** `frontend/src/pages/UserbotPage.tsx`

**Суть:** Одновременно работают:
1. `authStatus` useQuery — refetch каждые 15-60с
2. `monitorStatusQuery` useQuery — refetch каждые 15-30с
3. `useEffect` + `setInterval` — polling статусов чеков каждые 15с (строка 350)

Итого: до 12 HTTP-запросов в минуту только от одной страницы.

**Что должно быть:**
- Объединить polling в один `useEffect` с shared timer
- Использовать `visibility API` — не поллить если вкладка неактивна:
```tsx
useEffect(() => {
    const handler = () => {
        if (document.hidden) clearInterval(pollInterval);
        else pollInterval = setInterval(pollFn, 15000);
    };
    document.addEventListener('visibilitychange', handler);
    return () => document.removeEventListener('visibilitychange', handler);
}, []);
```

---

### ФРОНТ-ВЫС-05 · UserbotPage.tsx · Утечки памяти в useEffect + async

**Файл:** `frontend/src/pages/UserbotPage.tsx`
**Строка:** 350 (setInterval с async callback)

**Суть:** `setInterval` запускает async функцию. Если компонент unmount'ится во время fetch — state update на unmounted component.

**Что должно быть:**
```tsx
useEffect(() => {
    let cancelled = false;
    const interval = setInterval(async () => {
        if (cancelled) return;
        const data = await fetchStatuses();
        if (!cancelled) setStatuses(data);
    }, 15000);
    return () => {
        cancelled = true;
        clearInterval(interval);
    };
}, [deps]);
```

---

## 🟡 СРЕДНИЕ

---

### ФРОНТ-СРД-01 · App.tsx · Нет lazy loading для страниц

**Файл:** `frontend/src/App.tsx`
**Строки:** 9-14

**Суть:** Все страницы импортируются eagerly:
```tsx
import { TransactionsPage } from './pages/TransactionsPage';
import { UserbotPage } from './pages/UserbotPage';
```

UserbotPage (87 KB) загружается даже если пользователь никогда не заходит на эту вкладку.

**Что должно быть:**
```tsx
const UserbotPage = React.lazy(() => import('./pages/UserbotPage').then(m => ({ default: m.UserbotPage })));
const LogsPage = React.lazy(() => import('./pages/LogsPage').then(m => ({ default: m.LogsPage })));

// В Routes:
<Suspense fallback={<PageLoader />}>
    <Routes>...</Routes>
</Suspense>
```

---

### ФРОНТ-СРД-02 · UserbotPage.tsx · keydown listener перерегистрируется на каждый state change

**Файл:** `frontend/src/pages/UserbotPage.tsx`
**Строка:** ~745-771

**Суть:** `useEffect` с зависимостями `[selectAllMessages, deselectAllMessages, selectedMessageIds, currentChat, processBatchMutation]` — регистрирует и снимает keyboard listener при КАЖДОМ изменении выделения. При выборе 50 сообщений — 50 перерегистраций.

**Что должно быть:**
```tsx
const handleKeyDown = useCallback((e: KeyboardEvent) => {
    // use refs instead of state in closure
}, []);

useEffect(() => {
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
}, [handleKeyDown]);
```

---

### ФРОНТ-СРД-03 · UserbotPage.tsx · Query invalidation каскад

**Файл:** `frontend/src/pages/UserbotPage.tsx`
**Строки:** ~560-613

**Суть:** Каждое действие с чатом (скрыть/показать/выбрать) инвалидирует `['tg-chats']` + `['tg-chats-all']`. Это запускает два параллельных refetch полных списков чатов.

**Что должно быть:** Оптимистичное обновление:
```tsx
onMutate: async (chatId) => {
    await queryClient.cancelQueries(['tg-chats']);
    const prev = queryClient.getQueryData(['tg-chats']);
    queryClient.setQueryData(['tg-chats'], old =>
        old.map(c => c.id === chatId ? { ...c, isHidden: true } : c)
    );
    return { prev };
},
onError: (err, vars, ctx) => {
    queryClient.setQueryData(['tg-chats'], ctx.prev);
},
```

---

### ФРОНТ-СРД-04 · auth_bot_handler.py · /list_chat_passwords показывает chat_id без имени

**Файл:** `backend/services/auth_bot_handler.py`
**Строки:** 551-556

**Суть:** Ответ бота:
```
Чаты с паролем:
-1001234567890 | attempts=0 | locked_until=-
```
Заказчик видит число `-1001234567890` и не понимает что это за чат.

**Что должно быть:** Запрашивать имя чата через TDLib API и показывать:
```
Чаты с паролем:
💬 Рабочий канал (-1001234567890) | 🔒 | попытки: 0
💬 Стив аналитика (-1009876543210) | 🔒 | попытки: 2
```

Требуется: internal API endpoint для получения имён чатов по массиву ID.

---

### ФРОНТ-СРД-05 · auth_bot_handler.py · Нет подтверждения опасных действий

**Файл:** `backend/services/auth_bot_handler.py`

**Суть:** Опасные действия (`/kill_session`, `/unlock_period`, `/remove_chat_password`, `/set_launch_password`) выполняются сразу без подтверждения. Случайный клик/отправка → необратимое действие.

**Что должно быть — подтверждение через callback:**
```python
async def cmd_kill_session(message: Message):
    session_id = parts[1].strip()
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Да, завершить", callback_data=f"confirm_kill:{session_id}"),
        InlineKeyboardButton(text="❌ Отмена", callback_data="cancel"),
    ]])
    await message.reply(f"Завершить сессию {session_id}?", reply_markup=kb)
```

---

### ФРОНТ-СРД-06 · App.tsx · LaunchGate state сбрасывается при refresh

**Файл:** `frontend/src/App.tsx`
**Строка:** 174

**Суть:** `const [launchUnlocked, setLaunchUnlocked] = useState(false)` — при обновлении страницы state сбрасывается → снова запрос пароля. Это раздражает при разработке, но может быть задумано для безопасности.

**Если нужно сохранять сессию:** Хранить `launchSessionToken` в `sessionStorage` (не localStorage!) и валидировать при старте:
```tsx
const [launchUnlocked, setLaunchUnlocked] = useState(() => {
    const token = sessionStorage.getItem('launch_session_token');
    return !!token;
});
```

**Если текущее поведение — by design:** Задокументировать и оставить.

---

## 🔵 НИЗКИЕ

---

### ФРОНТ-НИЗ-01 · UserbotPage.tsx · 25+ lucide-react иконок импортируются

**Суть:** Каждая иконка ~1-2 KB. 25 иконок = ~50 KB в бандле. Не критично, но при tree-shaking и code-splitting можно оптимизировать.

---

### ФРОНТ-НИЗ-02 · auth_bot_handler.py · _audit() создаёт новую DB сессию каждый раз

**Файл:** `backend/services/auth_bot_handler.py`
**Строка:** 68

**Суть:** Каждый вызов `_audit()` делает `SessionLocal()` → write → close. При 5 аудит-записях за одну команду — 5 открытий/закрытий сессии. Не критично при текущей нагрузке.

---

### ФРОНТ-НИЗ-03 · auth_bot_handler.py · Ответы бота на русском, а команды на английском

**Суть:** `/set_launch_password` → "Пароль запуска обновлен." Смешение языков. Для заказчика лучше всё на русском, включая названия команд. Но Telegram bot commands не поддерживают кириллицу. Решение — inline keyboard (см. ФРОНТ-ВЫС-01).

---

### ФРОНТ-НИЗ-04 · App.tsx · Settings page не показана в getPageTitle()

**Файл:** `frontend/src/App.tsx`
**Строка:** 72-87

**Суть:** `case '/settings'` отсутствует в `getPageTitle()`. При переходе на настройки заголовок покажет "Транзакции" (default case).

**Что должно быть:**
```tsx
case '/settings':
    return 'Настройки';
```

---

## ПОРЯДОК ИСПРАВЛЕНИЙ (ЧАСТЬ 2)

### Этап 1 (критические)
1. ФРОНТ-КРИТ-01: ScopeGuard для /userbot
2. ФРОНТ-КРИТ-02: Контекстное меню чатов + SetChatPasswordDialog

### Этап 2 (бот UX)
1. ФРОНТ-ВЫС-01: Inline keyboard в боте + wizard-flow
2. ФРОНТ-СРД-04: Имена чатов вместо ID
3. ФРОНТ-СРД-05: Подтверждение опасных действий

### Этап 3 (оптимизация)
1. ФРОНТ-ВЫС-02: Разбить UserbotPage.tsx
2. ФРОНТ-ВЫС-03: react-virtual для сообщений
3. ФРОНТ-ВЫС-04: Объединить polling
4. ФРОНТ-ВЫС-05: Memory leak fix
5. ФРОНТ-СРД-01: Lazy loading
6. ФРОНТ-СРД-02: useCallback для keydown
7. ФРОНТ-СРД-03: Optimistic updates

### Этап 4 (minor)
Всё остальное.

---

**КОНЕЦ ДОКУМЕНТА**
