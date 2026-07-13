package uz.tbsparcer.sms.domain

/**
 * Single source of truth for the on-device sync state of an SMS row. Room `@Query` strings
 * must inline these literals (Room cannot reference Kotlin constants), but repository and
 * view-model logic compare against these to avoid drift.
 *
 *  - [PENDING]    not yet acknowledged; eligible for the next sync (until [retryCount] cap).
 *  - [SYNCED] / [DUPLICATE] / [SKIPPED]  terminal, backend acknowledged.
 *  - [ERROR]      legacy transient marker (kept for back-compat with v1 rows / detail UI).
 *  - [FAILED]     terminal; retry cap exceeded, no further attempts.
 *  - [AUTH_ERROR] terminal; ingest key rejected, will not self-heal without a new key.
 */
object SyncStatus {
    const val PENDING = "pending"
    const val SYNCED = "synced"
    const val DUPLICATE = "duplicate"
    const val SKIPPED = "skipped"
    const val ERROR = "error"
    const val FAILED = "failed"
    const val AUTH_ERROR = "auth_error"
}
