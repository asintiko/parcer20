package uz.tbsparcer.sms.data.local

import androidx.room.Entity
import androidx.room.PrimaryKey

@Entity(tableName = "sms_records")
data class SmsRecord(
    @PrimaryKey val deviceSmsId: String,
    val sender: String,
    val body: String,
    val receivedAt: Long,
    val simSlot: Int?,
    val fingerprint: String?,
    val syncStatus: String,       // pending | synced | duplicate | skipped | error
    val backendTransactionId: Long?,
    val errorMessage: String?,
    val syncedAt: Long?,
    val createdAt: Long,
)
