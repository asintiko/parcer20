import pytest
from decimal import Decimal

from parsers.regex_parser import RegexParser


@pytest.fixture(scope="module")
def parser():
    return RegexParser()


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("6.935.000,00", Decimal("6935000.00")),
        ("6.000.000,00", Decimal("6000000.00")),
        ("10.035.000,00", Decimal("10035000.00")),
        ("351 750.00", Decimal("351750.00")),
        ("1 100.90", Decimal("1100.90")),
        ("535.000,40", Decimal("535000.40")),
        ("2 052 200,14", Decimal("2052200.14")),
    ],
)
def test_normalize_amount(parser, raw, expected):
    assert parser.normalize_amount(raw) == expected


def test_humo_big_amount(parser):
    text = """💸 Оплата
➖ 10.035.000,00 UZS
📍 ChakanaPay Humo Uzca
💳 HUMOCARD *6714
🕓 12:01 14.04.2025
💰 3.547.712,00 UZS"""
    res = parser.parse(text)
    assert res
    assert res["amount"] == Decimal("10035000.00")
    assert res["currency"] == "UZS"
    assert res["transaction_type"] == "DEBIT"


def test_conversion_usd(parser):
    text = """💸 Конверсия
➖ 1 100.90 USD
💳 532154**1744
🕓 14.04.25 10:39
💵 1 505.00 USD"""
    res = parser.parse(text)
    assert res
    assert res["currency"] == "USD"
    assert res["amount"] == Decimal("1100.90")
    assert res["transaction_type"] == "CONVERSION"
    assert res["card_last_4"] == "1744"


def test_sms_inline_purchase(parser):
    text = 'Pokupka: OOO "AGAT SYSTEM", tashkent, g tashkent Ul Gavhar 151 02.04.25 08:37 karta ***0907. summa:44000.00 UZS, balans:2607792.14 UZS'
    res = parser.parse(text)
    assert res
    assert res["amount"] == Decimal("44000.00")
    assert res["currency"] == "UZS"
    assert res["transaction_type"] == "DEBIT"


def test_sms_inline_otmena(parser):
    text = 'OTMENA Pokupka: XK FAMILY SHOP, UZ,02.04.25 11:50,karta ***0907. summa:100000.00 UZS balans:2527792.14 UZS'
    res = parser.parse(text)
    assert res
    assert res["transaction_type"] == "REVERSAL"
    assert res["amount"] == Decimal("100000.00")


def test_semicolon_popolnenie(parser):
    text = "HUMOCARD *2529: popolnenie 2300.00 UZS; TBC HUMO P2P>TASHKEN; 25-04-04 10:19;  Dostupno: 4500.00 UZS"
    res = parser.parse(text)
    assert res
    assert res["transaction_type"] == "CREDIT"
    assert res["amount"] == Decimal("2300.00")


def test_cardxabar_spisanie(parser):
    text = """🔴 Spisanie c karty
➖ 351 750.00 UZS
💳 ***4862
📍 UZCARD OTHERS 2 ANY PAYNET, 99
🕓 14.04.25 21:52
💵 6 532 215.26 UZS"""
    res = parser.parse(text)
    assert res
    assert res["transaction_type"] == "DEBIT"
    assert res["amount"] == Decimal("351750.00")
    assert res["currency"] == "UZS"


def test_cardxabar_otmena(parser):
    text = """🟢 OTMENA Pokupka
➕ 100 000.00 UZS
💳 ***0907
📍 XK FAMILY SHOP, UZ
🕓 02.04.25 11:50
💵 2 527 792.14 UZS"""
    res = parser.parse(text)
    assert res
    assert res["transaction_type"] == "REVERSAL"
    assert res["amount"] == Decimal("100000.00")


def test_balance_changed_notification(parser):
    text = """ℹ️ Счет по карте изменен
💸 6.935.000,00 UZS
💳 HUMO-CARD *6714
🕘 17:46 04.04.2025"""
    res = parser.parse(text)
    assert res
    assert res["transaction_type"] == "DEBIT"
    assert res["amount"] == Decimal("6935000.00")


def test_cash_withdrawal(parser):
    text = """🏧 Снятие наличных
➖ 505.000,00 UZS
📍 URTACHIRCHIK AT HALK
💳 HUMOCARD *4428
🕓 12:10 31.12.2025
💰 4.914,00 UZS"""
    res = parser.parse(text)
    assert res
    assert res["transaction_type"] == "DEBIT"
    assert res["operator_raw"] == "URTACHIRCHIK AT HALK"
    assert res["card_last_4"] == "4428"
    assert res["amount"] == Decimal("505000.00")

def test_card_mask_middle(parser):
    text = """💸 Конверсия
➖ 400.000,00 UZS
💳 479091**6905
📍 TEST
🕓 12:58 05.04.2025
💰 535.000,40 UZS"""
    res = parser.parse(text)
    assert res
    assert res["card_last_4"] == "6905"
    assert res["transaction_type"] == "CONVERSION"


def test_time_then_date(parser):
    text = """💸 Оплата
➖ 400.000,00 UZS
📍 TEST
💳 HUMOCARD *6714
🕓 12:58 05.04.2025
💰 535.000,40 UZS"""
    res = parser.parse(text)
    assert res
    assert res["transaction_date"].day == 5
    assert res["transaction_date"].hour == 12


def test_cardxabar_conversion_usd(parser):
    text = """CardXabar
🟢 Konversiya
➕ 50.00 USD
💳 532154**1744
📍 TEST OPERATOR
🕓 21:10 15.04.2025
💵 1 505.00 USD"""
    res = parser.parse(text)
    assert res
    assert res["transaction_type"] == "CONVERSION"
    assert res["currency"] == "USD"


def test_sender_receiver_transfer_uzum_style(parser):
    text = """Sender 561468******4483
Sender name RAK VALENTINA PETROVNA
Receiver 491699******1116
Receiver name SVYATOSLAV LI
Transaction ID 79c9ee9b-ff97-40a9-a339-1592d6ea06b4
Transaction date 31.01.2026 11:12:51
Received date 31.01.2026 11:12:56
Receiver fee 0.00 UZS
Receiver amount 10,000,000.00 UZS
Sender fee 0.00 UZS
Sender amount 10,000,000.00 UZS"""
    res = parser.parse(text)
    assert res
    assert res["parsing_method"] == "REGEX_TRANSFER"
    assert res["operator_raw"] == "Uzum Bank"
    assert res["transaction_type"] == "DEBIT"
    assert res["currency"] == "UZS"
    assert res["amount"] == Decimal("10000000.00")
    assert res["card_last_4"] == "4483"
    assert res["receiver_card"] == "1116"
    assert res["receiver_name"] == "SVYATOSLAV LI"
    assert res["transaction_date"].year == 2026
    assert res["transaction_date"].minute == 12


def test_sender_receiver_transfer_ocr_typo_and_colons(parser):
    text = """Sender: 561468******4483
Sender name: RAK VALENTINA PETROVNA
Receiver: 491699******1116
Receiver name: SVYATOSLAV LI
Transcation date: 31.01.2026 11:12:51
Receiver amount: 10,000,000.00 UZS"""
    res = parser.parse(text)
    assert res
    assert res["parsing_method"] == "REGEX_TRANSFER"
    assert res["amount"] == Decimal("10000000.00")
    assert res["transaction_date"].second == 51


def test_humo_shop_and_calendar_emoji_with_balance_label(parser):
    text = """💸 Оплата
➖ 150 000 UZS
🏪 TEST SHOP
💳 HUMOCARD *4862
📅 02.04.2025 08:37
💰 Баланс: 2 340 500,00 UZS"""
    res = parser.parse(text)
    assert res
    assert res["operator_raw"] == "TEST SHOP"
    assert res["card_last_4"] == "4862"
    assert res["balance_after"] == Decimal("2340500.00")
    assert res["transaction_date"].year == 2025


def test_humo_notification_datetime_without_datetime_emoji(parser):
    text = """💸 Оплата
➖ 500,000 UZS
HUMOCARD *6714
TEST SHOP
12.02.2026 14:30
Баланс: 1,200,000 UZS"""
    res = parser.parse(text)
    assert res
    assert res["parsing_method"] == "REGEX_HUMO"
    assert res["transaction_date"].year == 2026
    assert res["transaction_date"].day == 12
    assert res["transaction_date"].hour == 14


def test_sms_inline_new_real_format(parser):
    text = "Pokupka: XK FAMILY SHOP, 250000.00 UZS, 02.04.25 08:37 *6714 Bal:1500000.00 UZS"
    res = parser.parse(text)
    assert res
    assert res["parsing_method"] == "REGEX_SMS"
    assert res["amount"] == Decimal("250000.00")
    assert res["card_last_4"] == "6714"
    assert res["balance_after"] == Decimal("1500000.00")


def test_sms_inline_with_iso_datetime(parser):
    text = "Pokupka: TEST SHOP, 250000.00 UZS, 2026-02-18 14:30 karta ***0907. balans:1500000.00 UZS"
    res = parser.parse(text)
    assert res
    assert res["parsing_method"] == "REGEX_SMS"
    assert res["transaction_date"].year == 2026
    assert res["transaction_date"].month == 2
    assert res["transaction_date"].day == 18
    assert res["transaction_date"].hour == 14


def test_semicolon_format_with_full_year(parser):
    text = "HUMOCARD*4862: oplata 250000.00 UZS; TEST SHOP; 2025-04-02 08:37; Dostupno: 1500000.00 UZS"
    res = parser.parse(text)
    assert res
    assert res["parsing_method"] == "REGEX_SEMICOLON"
    assert res["transaction_date"].year == 2025
    assert res["transaction_date"].month == 4
    assert res["transaction_date"].day == 2


def test_sender_receiver_transfer_supports_summa_poluchatelya(parser):
    text = """Sender: 561468******4483
Receiver: 491699******1116
Transaction date: 31.01.2026 11:12:51
Сумма получателя: 1,500,000.00 UZS"""
    res = parser.parse(text)
    assert res
    assert res["parsing_method"] == "REGEX_TRANSFER"
    assert res["amount"] == Decimal("1500000.00")


def test_cardxabar_text_labels(parser):
    text = """🔴 Spisanie
Summa: 250000.00 UZS
Karta: *6714
Magazin: XK FAMILY SHOP
Data: 02.04.2025
Vremya: 08:37
Bal: 1500000.00 UZS"""
    res = parser.parse(text)
    assert res
    assert res["parsing_method"] == "REGEX_CARDXABAR"
    assert res["transaction_type"] == "DEBIT"
    assert res["amount"] == Decimal("250000.00")
    assert res["card_last_4"] == "6714"
