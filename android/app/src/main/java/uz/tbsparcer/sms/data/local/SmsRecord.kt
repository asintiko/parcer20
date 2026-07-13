package uz.tbsparcer.sms.data.local

import androidx.room.Entity
import androidx.room.Index
import androidx.room.PrimaryKey

@Entity(
    tableName = "sms_records",
    indices = [Index("syncStatus"), Index("fingerprint")],
)
data class SmsRecord(
    @PrimaryKey val deviceSmsId: String,
    val sender: String,
    val body: String,
    val receivedAt: Long,
    val simSlot: Int?,
    val fingerprint: String?,
    val syncStatus: String,       // pending | synced | duplicate | skipped | error | failed | auth_error
    val backendTransactionId: Long?,
    val errorMessage: String?,
    val syncedAt: Long?,
    val createdAt: Long,
    val retryCount: Int = 0,
    val nextAttemptAt: Long? = null,
    // Parsed summary echoed back by the backend (created AND duplicate). For a duplicate this is
    // the existing receipt's data, so the row can show full info instead of a bare status.
    val pAmount: String? = null,
    val pCurrency: String? = null,
    val pTxnDate: String? = null,
    val pCardLast4: String? = null,
    val pOperator: String? = null,
    val pTxnType: String? = null,
    val pBalanceAfter: String? = null,
    val pApplication: String? = null,
)
