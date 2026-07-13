package uz.tbsparcer.sms

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotEquals
import org.junit.Test
import uz.tbsparcer.sms.domain.SmsLocalId

class SmsLocalIdTest {
    @Test fun sameMessageFromRealtimeAndBackfillCollides() {
        val realtime = SmsLocalId.of("UZCARD", 1_700_000_000_000, "Pokupka 44000.00 UZS ***0907")
        val backfill = SmsLocalId.of("UZCARD", 1_700_000_000_000, "Pokupka 44000.00 UZS ***0907")
        assertEquals(realtime, backfill)
    }

    @Test fun differentBodySameSenderAndTsDoesNotCollide() {
        // hashCode-only ids collided here; including the body must separate them
        val a = SmsLocalId.of("UZCARD", 1_700_000_000_000, "Pokupka 44000.00 UZS ***0907")
        val b = SmsLocalId.of("UZCARD", 1_700_000_000_000, "Spisanie 5000.00 UZS ***4862")
        assertNotEquals(a, b)
    }

    @Test fun isHexSha256() {
        val id = SmsLocalId.of("HUMO", 1L, "x")
        assertEquals(64, id.length)
        assertEquals(true, id.all { it in "0123456789abcdef" })
    }
}
