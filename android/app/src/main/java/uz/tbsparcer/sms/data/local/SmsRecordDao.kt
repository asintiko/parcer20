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

    @Query(
        "SELECT * FROM sms_records WHERE syncStatus = 'pending' AND retryCount < :cap " +
            "ORDER BY receivedAt ASC LIMIT :limit"
    )
    suspend fun pending(cap: Int, limit: Int = 50): List<SmsRecord>

    @Query("SELECT * FROM sms_records WHERE deviceSmsId = :id")
    suspend fun byId(id: String): SmsRecord?

    @Query("SELECT syncStatus, COUNT(*) AS n FROM sms_records GROUP BY syncStatus")
    fun statusCounts(): Flow<List<StatusCount>>

    @Query("SELECT COUNT(*) FROM sms_records")
    fun totalCount(): Flow<Int>

    @Query(
        "SELECT syncStatus, COUNT(*) AS n FROM sms_records " +
            "WHERE receivedAt BETWEEN :from AND :to GROUP BY syncStatus"
    )
    fun statusCountsInRange(from: Long, to: Long): Flow<List<StatusCount>>

    @Query("SELECT * FROM sms_records WHERE receivedAt BETWEEN :from AND :to ORDER BY receivedAt DESC")
    fun byRange(from: Long, to: Long): Flow<List<SmsRecord>>

    @Query("SELECT MAX(syncedAt) FROM sms_records WHERE syncedAt IS NOT NULL")
    fun lastSyncedAt(): Flow<Long?>

    @Query("SELECT deviceSmsId FROM sms_records")
    suspend fun allIds(): List<String>

    @Insert(onConflict = OnConflictStrategy.IGNORE)
    suspend fun insertAll(records: List<SmsRecord>): List<Long>

    @Query(
        """UPDATE sms_records SET syncStatus = :status, backendTransactionId = :txnId,
              fingerprint = :fp, errorMessage = :error, syncedAt = :syncedAt,
              pAmount = :pAmount, pCurrency = :pCurrency, pTxnDate = :pTxnDate,
              pCardLast4 = :pCardLast4, pOperator = :pOperator, pTxnType = :pTxnType,
              pBalanceAfter = :pBalanceAfter, pApplication = :pApplication
              WHERE deviceSmsId = :id"""
    )
    suspend fun updateResult(
        id: String, status: String, txnId: Long?, fp: String?, error: String?, syncedAt: Long,
        pAmount: String?, pCurrency: String?, pTxnDate: String?, pCardLast4: String?,
        pOperator: String?, pTxnType: String?, pBalanceAfter: String?, pApplication: String?,
    )

    /**
     * Record a transient failure: keep the row eligible (stays `pending`) but bump the
     * attempt counter. If the bump reaches [cap], mark it `failed` so [pending] stops
     * selecting it instead of letting it sediment forever.
     */
    @Query(
        """UPDATE sms_records
              SET retryCount = retryCount + 1,
                  syncStatus = CASE WHEN retryCount + 1 >= :cap THEN 'failed' ELSE 'pending' END,
                  errorMessage = :error
              WHERE deviceSmsId = :id"""
    )
    suspend fun bumpRetry(id: String, cap: Int, error: String?)

    @Query("UPDATE sms_records SET syncStatus = :status, errorMessage = :error WHERE deviceSmsId = :id")
    suspend fun setStatus(id: String, status: String, error: String?)

    /**
     * Reconcile a window: flip terminal rows in [from]..[to] back to `pending` so the next sync
     * re-checks them against the backend. Backend dedup makes this idempotent — already-known
     * receipts come back as `duplicate`, never re-created.
     */
    @Query(
        """UPDATE sms_records SET syncStatus = 'pending', retryCount = 0, errorMessage = NULL
              WHERE receivedAt BETWEEN :from AND :to
              AND syncStatus IN ('synced','duplicate','skipped','error','failed','auth_error')"""
    )
    suspend fun requeueRange(from: Long, to: Long): Int

    @Query(
        """UPDATE sms_records SET syncStatus = 'pending', retryCount = 0, errorMessage = NULL
              WHERE syncStatus = 'auth_error'"""
    )
    suspend fun requeueAuthErrors(): Int

    @Query(
        "DELETE FROM sms_records WHERE syncStatus IN ('synced','duplicate','skipped') " +
            "AND syncedAt IS NOT NULL AND syncedAt < :cutoff"
    )
    suspend fun purgeOld(cutoff: Long)

    @Query("DELETE FROM sms_records")
    suspend fun clear()
}
