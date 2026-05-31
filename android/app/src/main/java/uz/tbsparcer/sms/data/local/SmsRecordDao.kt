package uz.tbsparcer.sms.data.local

import androidx.room.Dao
import androidx.room.Insert
import androidx.room.OnConflictStrategy
import androidx.room.Query
import kotlinx.coroutines.flow.Flow

data class StatusCount(val syncStatus: String, val n: Int)

@Dao
interface SmsRecordDao {
    @Query("SELECT * FROM sms_records ORDER BY receivedAt DESC LIMIT :limit")
    fun recent(limit: Int = 300): Flow<List<SmsRecord>>

    @Query("SELECT * FROM sms_records WHERE syncStatus = :status ORDER BY receivedAt DESC LIMIT :limit")
    fun byStatus(status: String, limit: Int = 300): Flow<List<SmsRecord>>

    @Query("SELECT * FROM sms_records WHERE syncStatus IN ('pending','error') ORDER BY receivedAt ASC LIMIT :limit")
    suspend fun pending(limit: Int = 50): List<SmsRecord>

    @Query("SELECT * FROM sms_records WHERE deviceSmsId = :id")
    suspend fun byId(id: String): SmsRecord?

    @Query("SELECT syncStatus, COUNT(*) AS n FROM sms_records GROUP BY syncStatus")
    fun statusCounts(): Flow<List<StatusCount>>

    @Query("SELECT deviceSmsId FROM sms_records")
    suspend fun allIds(): List<String>

    @Insert(onConflict = OnConflictStrategy.IGNORE)
    suspend fun insertAll(records: List<SmsRecord>): List<Long>

    @Query("""UPDATE sms_records SET syncStatus = :status, backendTransactionId = :txnId,
              fingerprint = :fp, errorMessage = :error, syncedAt = :syncedAt
              WHERE deviceSmsId = :id""")
    suspend fun updateResult(id: String, status: String, txnId: Long?, fp: String?, error: String?, syncedAt: Long)

    @Query("DELETE FROM sms_records")
    suspend fun clear()
}
