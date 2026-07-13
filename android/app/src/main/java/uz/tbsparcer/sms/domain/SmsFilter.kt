package uz.tbsparcer.sms.domain

/**
 * Gate that decides whether an SMS is a bank receipt worth forwarding to the backend.
 *
 * Deliberately BROADER than the backend regex parser: forwarding a borderline SMS that
 * the backend then marks "skipped" is cheap, but dropping a real transaction here is
 * permanent data loss. So we accept on Latin OR Cyrillic keywords (colon-optional), or on
 * an amount paired with either a masked card or a currency token (covers cardless SMS).
 */
object SmsFilter {
    private val bankKeywords = listOf(
        // Latin (colon-optional — no trailing punctuation)
        "pokupka", "spisanie", "popolnenie", "oplata", "platezh", "otmena",
        "perevod", "humocard", "summa", "balans", "dostupno", "karta",
        // Cyrillic
        "покупка", "списание", "пополнение", "оплата", "платеж", "отмена",
        "перевод", "карта", "сумма", "баланс", "доступно", "поступление",
    )
    private val ignoredSenders = listOf(
        "google", "telegram", "viber", "whatsapp", "facebook", "instagram", "youtube",
    )

    // amount like 44000.00 / 1 234 567,89 / 250000.00
    private val amountRe = Regex("""\d{1,3}([., ]\d{3})*[.,]\d{2}""")
    // masked card like ***0907 / **6905
    private val cardRe = Regex("""\*{2,4}\d{4}""")
    // currency token (UZS / USD / сум / сўм / sum)
    private val currencyRe = Regex("""(?i)(uzs|usd|сум|сўм|sum)""")

    fun isBankSms(sender: String, body: String): Boolean {
        val s = sender.lowercase()
        if (ignoredSenders.any { s.contains(it) }) return false
        val b = body.lowercase()
        if (bankKeywords.any { b.contains(it) }) return true
        // Heuristic fallback: an amount paired with a masked card OR a currency token.
        if (!amountRe.containsMatchIn(body)) return false
        return cardRe.containsMatchIn(body) || currencyRe.containsMatchIn(body)
    }
}
