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
