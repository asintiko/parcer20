package uz.tbsparcer.sms.domain

import java.security.MessageDigest

/**
 * Stable local primary key for an SMS, derived from its content. Realtime delivery and
 * inbox backfill compute the SAME id for the same message, so a row seen by both paths
 * collides and is deduped by [androidx.room.OnConflictStrategy.IGNORE] on insert. Hashing
 * the body (not just sender+timestamp) avoids hashCode collisions across distinct messages.
 */
object SmsLocalId {
    fun of(sender: String, tsMillis: Long, body: String): String {
        val raw = "$sender|$tsMillis|$body"
        return MessageDigest.getInstance("SHA-256")
            .digest(raw.toByteArray(Charsets.UTF_8))
            .joinToString("") { "%02x".format(it) }
    }
}
