import json

from services.message_utils import format_tdlib_message, looks_like_receipt


def test_format_tdlib_message_extracts_nested_content_text():
    raw = {
        "id": 123,
        "date": 1700000000,
        "content": {
            "@type": "messageText",
            "text": {"@type": "formattedText", "text": "💸 500000 UZS"},
        },
    }
    formatted = format_tdlib_message(raw)
    assert formatted is not None
    assert formatted["id"] == 123
    assert formatted["text"] == "💸 500000 UZS"


def test_format_tdlib_message_uses_caption_and_document_file():
    raw = {
        "id": 124,
        "date": 1700000000,
        "content": {
            "@type": "messageDocument",
            "caption": {"@type": "formattedText", "text": "Чек PDF"},
            "document": {
                "file_name": "check.pdf",
                "mime_type": "application/pdf",
                "document": {"id": 987654},
            },
        },
    }
    formatted = format_tdlib_message(raw)
    assert formatted is not None
    assert formatted["text"] == "Чек PDF"
    assert formatted["document"]["file_id"] == 987654
    assert formatted["document"]["mime_type"] == "application/pdf"


def test_looks_like_receipt_detects_new_keywords_and_emoji():
    assert looks_like_receipt("CardXabar summa: 250000 UZS karta: *6714", "") is True
    assert looks_like_receipt("🔴 random text without classic keywords", "") is True


def test_looks_like_receipt_detects_pdf_message_from_raw_json():
    raw_json = json.dumps(
        {
            "content": {
                "@type": "messageDocument",
                "document": {
                    "mime_type": "application/pdf",
                    "document": {"id": 999},
                },
            }
        }
    )
    assert looks_like_receipt("", raw_json) is True
