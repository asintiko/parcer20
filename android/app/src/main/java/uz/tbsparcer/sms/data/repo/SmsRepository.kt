package uz.tbsparcer.sms.data.repo

import android.content.Context
import android.net.Uri
import dagger.hilt.android.qualifiers.ApplicationContext
import kotlinx.coroutines.flow.Flow
import uz.tbsparcer.sms.data.local.SettingsStore
import uz.tbsparcer.sms.data.local.SmsRecord
import uz.tbsparcer.sms.data.local.SmsRecordDao
import uz.tbsparcer.sms.data.local.StatusCount
import uz.tbsparcer.sms.data.remote.SmsIngestRequest
import uz.tbsparcer.sms.data.remote.SmsMessageDto
import uz.tbsparcer.sms.di.ApiProvider
import uz.tbsparcer.sms.domain.SmsFilter
import uz.tbsparcer.sms.domain.SmsLocalId
import uz.tbsparcer.sms.domain.SyncStatus
import java.time.Instant
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import javax.inject.Inject
import javax.inject.Singleton

sealed interface SyncOutcome {
    data object Empty : SyncOutcome
    data class Ok(val created: Int, val duplicates: Int, val skipped: Int, val errors: Int) : SyncOutcome
    data class AuthError(val code: Int) : SyncOutcome
    data object Retry : SyncOutcome
}

@Singleton
class SmsRepository @Inject constructor(
    @ApplicationContext private val ctx: Context,
    private val dao: SmsRecordDao,
    private val settings: SettingsStore,
    private val apiProvider: ApiProvider,
) {
    fun recent(): Flow<List<SmsRecord>> = dao.recent()
    fun byStatus(status: String): Flow<List<SmsRecord>> = dao.byStatus(status)
    fun statusCounts(): Flow<List<StatusCount>> = dao.statusCounts()
    fun statusCountsInRange(from: Long, to: Long): Flow<List<StatusCount>> = dao.statusCountsInRange(from, to)
    fun byRange(from: Long, to: Long): Flow<List<SmsRecord>> = dao.byRange(from, to)
    fun totalCount(): Flow<Int> = dao.totalCount()
    fun lastSyncedAt(): Flow<Long?> = dao.lastSyncedAt()
    fun authError(): Boolean = settings.authError
    suspend fun byId(id: String) = dao.byId(id)
    suspend fun clear() = dao.clear()
    suspend fun purgeOld(cutoff: Long) = dao.purgeOld(cutoff)

    /** Read inbox since [sinceMillis], filter bank SMS, insert new as pending. Returns inserted count. */
    suspend fun collectFromInbox(sinceMillis: Long): Int =
        collectInbox("date >= ?", arrayOf(sinceMillis.toString()))

    /** Bounded variant for reconcile: only SMS received within [from]..[to]. */
    suspend fun collectFromInbox(from: Long, to: Long): Int =
        collectInbox("date >= ? AND date <= ?", arrayOf(from.toString(), to.toString()))

    private suspend fun collectInbox(selection: String, args: Array<String>): Int {
        val existing = dao.allIds().toHashSet()
        val cursor = ctx.contentResolver.query(
            Uri.parse("content://sms/inbox"),
            arrayOf("_id", "address", "body", "date"),
            selection, args, "date DESC",
        ) ?: return 0
        val rows = mutableListOf<SmsRecord>()
        cursor.use { c ->
            val addrIdx = c.getColumnIndex("address")
            val bodyIdx = c.getColumnIndex("body")
            val dateIdx = c.getColumnIndex("date")
            while (c.moveToNext()) {
                val sender = c.getString(addrIdx) ?: ""
                val body = c.getString(bodyIdx) ?: ""
                val date = c.getLong(dateIdx)
                val id = SmsLocalId.of(sender, date, body)
                if (existing.contains(id)) continue
                if (!SmsFilter.isBankSms(sender, body)) continue
                rows += SmsRecord(
                    deviceSmsId = id, sender = sender, body = body, receivedAt = date,
                    simSlot = null, fingerprint = null, syncStatus = SyncStatus.PENDING,
                    backendTransactionId = null, errorMessage = null, syncedAt = null,
                    createdAt = System.currentTimeMillis(),
                )
            }
        }
        if (rows.isNotEmpty()) dao.insertAll(rows)
        return rows.size
    }

    suspend fun insertRealtime(deviceSmsId: String, sender: String, body: String, receivedAt: Long) {
        if (!SmsFilter.isBankSms(sender, body)) return
        dao.insertAll(listOf(
            SmsRecord(deviceSmsId, sender, body, receivedAt, null, null, SyncStatus.PENDING,
                null, null, null, System.currentTimeMillis())
        ))
    }

    /** Push pending rows to backend; write back per-item results. */
    suspend fun syncPending(): SyncOutcome {
        val pending = dao.pending(RETRY_CAP)
        if (pending.isEmpty()) return SyncOutcome.Empty
        val req = SmsIngestRequest(
            deviceId = settings.deviceId,
            messages = pending.map {
                SmsMessageDto(
                    deviceSmsId = it.deviceSmsId, sender = it.sender, text = it.body,
                    receivedAt = Instant.ofEpochMilli(it.receivedAt)
                        .atZone(ZoneId.systemDefault()).toLocalDateTime()
                        .format(DateTimeFormatter.ISO_LOCAL_DATE_TIME),
                    simSlot = it.simSlot,
                )
            },
        )
        return try {
            val resp = apiProvider.api().ingest(req)
            val now = System.currentTimeMillis()
            val acknowledged = HashSet<String>(resp.results.size)
            resp.results.forEach { r ->
                acknowledged += r.deviceSmsId
                val p = r.parsed
                dao.updateResult(
                    r.deviceSmsId, r.status, r.transactionId, r.fingerprint, r.error, now,
                    p?.amount, p?.currency, p?.transactionDate, p?.cardLast4,
                    p?.operator, p?.transactionType, p?.balanceAfter, p?.application,
                )
            }
            // Any row we sent but the backend did not echo back must not get stuck: requeue it
            // (bumping retryCount so a persistently-dropped row eventually goes to `failed`).
            pending.filter { it.deviceSmsId !in acknowledged }
                .forEach { dao.bumpRetry(it.deviceSmsId, RETRY_CAP, "not_acknowledged") }
            settings.authError = false
            SyncOutcome.Ok(resp.created, resp.duplicates, resp.skipped, resp.errors)
        } catch (e: retrofit2.HttpException) {
            when (e.code()) {
                403 -> {
                    // Bad key — won't self-heal. Park rows terminally and surface in UI.
                    pending.forEach { dao.setStatus(it.deviceSmsId, SyncStatus.AUTH_ERROR, "http_403") }
                    SyncOutcome.AuthError(403)
                }
                // 503 = key not configured server-side; 5xx = transient. Keep rows pending, count the attempt.
                else -> { markTransient(pending, "http_${e.code()}"); SyncOutcome.Retry }
            }
        } catch (e: Exception) {
            markTransient(pending, e.message?.take(180)); SyncOutcome.Retry
        }
    }

    /** Transient failure: keep rows eligible (`pending`) and bump retry; cap → `failed`. */
    private suspend fun markTransient(rows: List<SmsRecord>, msg: String?) {
        rows.forEach { dao.bumpRetry(it.deviceSmsId, RETRY_CAP, msg) }
    }

    /**
     * Re-scan SMS for [from]..[to] and re-sync the window against the backend. Picks up messages
     * not seen before, flips already-synced rows in the window back to `pending`, then drains them.
     * Idempotent: no local duplicates (PK + OnConflict IGNORE), backend returns known receipts as
     * `duplicate`. This is the "bot was down, gap was filled via SMS" answer — it surfaces what
     * actually landed vs. what was already there (including from Telegram).
     */
    suspend fun reconcile(from: Long, to: Long): SyncOutcome {
        collectFromInbox(from, to)
        dao.requeueRange(from, to)
        var created = 0; var duplicates = 0; var skipped = 0; var errors = 0
        var sawWork = false
        repeat(RECONCILE_MAX_ITERATIONS) {
            when (val r = syncPending()) {
                is SyncOutcome.Ok -> {
                    sawWork = true
                    created += r.created; duplicates += r.duplicates
                    skipped += r.skipped; errors += r.errors
                }
                is SyncOutcome.Empty -> return if (sawWork)
                    SyncOutcome.Ok(created, duplicates, skipped, errors) else SyncOutcome.Empty
                is SyncOutcome.AuthError -> return r
                is SyncOutcome.Retry -> return@repeat
            }
        }
        return if (sawWork) SyncOutcome.Ok(created, duplicates, skipped, errors) else SyncOutcome.Retry
    }

    companion object {
        const val RETRY_CAP = 10
        const val RECONCILE_MAX_ITERATIONS = 50
    }
}
