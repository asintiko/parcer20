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
    suspend fun byId(id: String) = dao.byId(id)
    suspend fun clear() = dao.clear()

    /** Read inbox since [sinceMillis], filter bank SMS, insert new as pending. Returns inserted count. */
    suspend fun collectFromInbox(sinceMillis: Long): Int {
        val existing = dao.allIds().toHashSet()
        val cursor = ctx.contentResolver.query(
            Uri.parse("content://sms/inbox"),
            arrayOf("_id", "address", "body", "date"),
            "date >= ?", arrayOf(sinceMillis.toString()), "date DESC",
        ) ?: return 0
        val rows = mutableListOf<SmsRecord>()
        cursor.use { c ->
            val idIdx = c.getColumnIndex("_id")
            val addrIdx = c.getColumnIndex("address")
            val bodyIdx = c.getColumnIndex("body")
            val dateIdx = c.getColumnIndex("date")
            while (c.moveToNext()) {
                val id = c.getString(idIdx) ?: continue
                if (existing.contains(id)) continue
                val sender = c.getString(addrIdx) ?: ""
                val body = c.getString(bodyIdx) ?: ""
                val date = c.getLong(dateIdx)
                if (!SmsFilter.isBankSms(sender, body)) continue
                rows += SmsRecord(
                    deviceSmsId = id, sender = sender, body = body, receivedAt = date,
                    simSlot = null, fingerprint = null, syncStatus = "pending",
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
            SmsRecord(deviceSmsId, sender, body, receivedAt, null, null, "pending",
                null, null, null, System.currentTimeMillis())
        ))
    }

    /** Push pending rows to backend; write back per-item results. */
    suspend fun syncPending(): SyncOutcome {
        val pending = dao.pending(50)
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
            resp.results.forEach { r ->
                dao.updateResult(r.deviceSmsId, r.status, r.transactionId, r.fingerprint, r.error, now)
            }
            SyncOutcome.Ok(resp.created, resp.duplicates, resp.skipped, resp.errors)
        } catch (e: retrofit2.HttpException) {
            when (e.code()) {
                403 -> SyncOutcome.AuthError(403)          // bad key — won't self-heal, surface in UI
                503 -> SyncOutcome.Retry                    // key not configured server-side — transient, retry with backoff
                else -> { markError(pending, "http_${e.code()}"); SyncOutcome.Retry }
            }
        } catch (e: Exception) {
            markError(pending, e.message?.take(180)); SyncOutcome.Retry
        }
    }

    private suspend fun markError(rows: List<SmsRecord>, msg: String?) {
        val now = System.currentTimeMillis()
        rows.forEach { dao.updateResult(it.deviceSmsId, "error", null, null, msg, now) }
    }
}
