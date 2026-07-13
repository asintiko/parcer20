package uz.tbsparcer.sms

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import uz.tbsparcer.sms.domain.SmsFilter

class SmsFilterTest {
    @Test fun acceptsPokupka() {
        assertTrue(SmsFilter.isBankSms("UZCARD",
            "Pokupka: OO \"AGAT SYSTEM\", tashkent 02.04.25 08:37 karta ***0907. summa:44000.00 UZS, balans:2607792.14 UZS"))
    }
    @Test fun acceptsSpisanie() {
        assertTrue(SmsFilter.isBankSms("HUMO",
            "Spisanie c karty: HAMKORBANK ATB, UZ,02.04.25 14:52,karta ***4862. summa:5000.00 UZS balans:138715.26 UZS"))
    }
    @Test fun acceptsHumocardSemicolon() {
        assertTrue(SmsFilter.isBankSms("HUMOCARD",
            "HUMOCARD *6921: oplata 200000.00 UZS; SmartBank P2P HUMO U; 25-04-02 15:33;  Dostupno: 1852200.28 UZS"))
    }
    @Test fun acceptsPlainAmountPlusCard() {
        // no keyword, but amount + masked card present
        assertTrue(SmsFilter.isBankSms("9860",
            "Oplata 250000.00 UZS s karty ***6714 Bal:1500000.00 UZS"))
    }
    @Test fun rejectsTelegramOtp() {
        assertFalse(SmsFilter.isBankSms("Telegram", "Login code: 12345. Do not give this code to anyone."))
    }
    @Test fun rejectsGoogle() {
        assertFalse(SmsFilter.isBankSms("Google", "G-839201 is your Google verification code."))
    }
    @Test fun rejectsPlainChat() {
        assertFalse(SmsFilter.isBankSms("+998901234567", "Privet, kak dela? Uvidimsya v 5"))
    }
    @Test fun acceptsCardlessWithCurrency() {
        // no bank keyword, no masked card — but amount + currency token (backend parses these)
        assertTrue(SmsFilter.isBankSms("9860",
            "Tranzaksiya 100000.00 UZS 02.04.25 14:52 muvaffaqiyatli"))
    }
    @Test fun acceptsColonlessSumma() {
        // "summa" without a colon must still trigger
        assertTrue(SmsFilter.isBankSms("UZCARD",
            "summa 44000.00 UZS 02.04.25 08:37"))
    }
    @Test fun acceptsCyrillic() {
        assertTrue(SmsFilter.isBankSms("UZCARD",
            "Оплата 50000.00 сум, карта ***1234, баланс 200000.00 сум"))
    }
    @Test fun rejectsAmountWithoutCurrencyOrCard() {
        // amount present but no currency token and no masked card → not a bank SMS
        assertFalse(SmsFilter.isBankSms("Promo",
            "Skidka 50.00 segodnya tolko"))
    }
    @Test fun rejectsEmptyBody() {
        assertFalse(SmsFilter.isBankSms("UZCARD", ""))
    }
    @Test fun rejectsEmptySender() {
        // empty sender is not in the ignore list, so acceptance must hinge on the body alone
        assertFalse(SmsFilter.isBankSms("", "just a normal text without money"))
    }
    @Test fun rejectsBlankBoth() {
        assertFalse(SmsFilter.isBankSms("", ""))
    }
    @Test fun rejectsDeliveryNotification() {
        // known false-positive shape: courier SMS with an order number, no amount/currency/card
        assertFalse(SmsFilter.isBankSms("BTS",
            "Vash zakaz #1234567 dostavlen v punkt vydachi. Spasibo za pokupku!"))
    }
    @Test fun rejectsTwoFactorWithDigits() {
        // 6-digit OTP must not be read as an amount/currency match
        assertFalse(SmsFilter.isBankSms("MyGov", "Kod podtverzhdeniya: 845102"))
    }
}
