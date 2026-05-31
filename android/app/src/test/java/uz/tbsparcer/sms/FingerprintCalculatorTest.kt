package uz.tbsparcer.sms

import org.junit.Assert.assertEquals
import org.junit.Test
import java.math.BigDecimal
import java.time.LocalDateTime
import uz.tbsparcer.sms.domain.FingerprintCalculator

class FingerprintCalculatorTest {
    private fun sha256(s: String): String =
        java.security.MessageDigest.getInstance("SHA-256")
            .digest(s.toByteArray()).joinToString("") { "%02x".format(it) }

    @Test fun matchesBackendV1() {
        val fp = FingerprintCalculator.computeV1(
            BigDecimal("-100000"), LocalDateTime.of(2026, 5, 10, 12, 0), "0907")
        assertEquals(sha256("100000.00|2026-05-10 12:00|0907"), fp)
    }

    @Test fun absAndTwoDecimals() {
        // negative DEBIT amount is abs()'d and quantized to 2dp
        val fp = FingerprintCalculator.computeV1(
            BigDecimal("-44000"), LocalDateTime.of(2025, 4, 2, 8, 37), "0907")
        assertEquals(sha256("44000.00|2025-04-02 08:37|0907"), fp)
    }

    @Test fun nullCardBecomesZeros() {
        val fp = FingerprintCalculator.computeV1(
            BigDecimal("5000"), LocalDateTime.of(2025, 4, 2, 14, 52), null)
        assertEquals(sha256("5000.00|2025-04-02 14:52|0000"), fp)
    }

    @Test fun cardKeepsLast4FromLongerString() {
        val fp = FingerprintCalculator.computeV1(
            BigDecimal("1"), LocalDateTime.of(2025, 1, 1, 0, 0), "479091**6905")
        assertEquals(sha256("1.00|2025-01-01 00:00|6905"), fp)
    }
}
