package uz.tbsparcer.sms.domain

import java.math.BigDecimal
import java.math.RoundingMode
import java.security.MessageDigest
import java.time.LocalDateTime
import java.time.format.DateTimeFormatter

object FingerprintCalculator {
    private val minuteFmt = DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm")

    fun computeV1(amount: BigDecimal?, date: LocalDateTime?, cardLast4: String?): String {
        val amountStr = (amount?.abs()?.setScale(2, RoundingMode.HALF_UP) ?: BigDecimal("0.00"))
            .toPlainString()
        val dateStr = date?.format(minuteFmt) ?: ""
        val digits = cardLast4?.filter { it.isDigit() } ?: ""
        val cardStr = if (digits.isEmpty()) "0000" else digits.takeLast(4).padStart(4, '0')
        val raw = "$amountStr|$dateStr|$cardStr"
        return MessageDigest.getInstance("SHA-256")
            .digest(raw.toByteArray(Charsets.UTF_8))
            .joinToString("") { "%02x".format(it) }
    }
}
