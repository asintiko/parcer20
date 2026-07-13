package uz.tbsparcer.sms

import androidx.room.Room
import androidx.test.core.app.ApplicationProvider
import kotlinx.coroutines.test.runTest
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config
import uz.tbsparcer.sms.data.local.AppDatabase
import uz.tbsparcer.sms.data.local.SmsRecord
import uz.tbsparcer.sms.data.local.SmsRecordDao
import uz.tbsparcer.sms.domain.SyncStatus

// Robolectric 4.12 has no SDK-35 image; the DAO logic under test is SDK-agnostic, so pin to 34.
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [34])
class SmsQueueTest {
    private lateinit var db: AppDatabase
    private lateinit var dao: SmsRecordDao

    private val cap = 10

    @Before fun setUp() {
        db = Room.inMemoryDatabaseBuilder(
            ApplicationProvider.getApplicationContext(), AppDatabase::class.java,
        ).allowMainThreadQueries().build()
        dao = db.smsDao()
    }

    @After fun tearDown() = db.close()

    private fun record(id: String, status: String = SyncStatus.PENDING, retry: Int = 0, receivedAt: Long = 1) =
        SmsRecord(
            deviceSmsId = id, sender = "UZCARD", body = "Pokupka 1.00 UZS karta ***0907",
            receivedAt = receivedAt, simSlot = null, fingerprint = null, syncStatus = status,
            backendTransactionId = null, errorMessage = null, syncedAt = null,
            createdAt = 0, retryCount = retry,
        )

    @Test fun pendingExcludesRowsAtOrAboveCap() = runTest {
        dao.insertAll(listOf(
            record("a", retry = 0),
            record("b", retry = cap - 1),
            record("c", retry = cap),
            record("d", retry = cap + 5),
        ))
        val ids = dao.pending(cap).map { it.deviceSmsId }.toSet()
        assertEquals(setOf("a", "b"), ids)
    }

    @Test fun pendingExcludesTerminalStatuses() = runTest {
        dao.insertAll(listOf(
            record("p", status = SyncStatus.PENDING),
            record("s", status = SyncStatus.SYNCED),
            record("f", status = SyncStatus.FAILED),
            record("e", status = SyncStatus.ERROR),
            record("x", status = SyncStatus.AUTH_ERROR),
        ))
        val ids = dao.pending(cap).map { it.deviceSmsId }.toSet()
        assertEquals(setOf("p"), ids)
    }

    @Test fun bumpRetryKeepsRowPendingAndIncrements() = runTest {
        dao.insertAll(listOf(record("a", retry = 0)))
        dao.bumpRetry("a", cap, "http_503")
        val row = dao.byId("a")!!
        assertEquals(SyncStatus.PENDING, row.syncStatus)
        assertEquals(1, row.retryCount)
        assertEquals("http_503", row.errorMessage)
        // still selectable for the next attempt
        assertTrue(dao.pending(cap).any { it.deviceSmsId == "a" })
    }

    @Test fun bumpRetryAtCapMarksFailedAndDropsFromPending() = runTest {
        dao.insertAll(listOf(record("a", retry = cap - 1)))
        dao.bumpRetry("a", cap, "http_500")
        val row = dao.byId("a")!!
        assertEquals(SyncStatus.FAILED, row.syncStatus)
        assertEquals(cap, row.retryCount)
        assertTrue(dao.pending(cap).none { it.deviceSmsId == "a" })
    }

    @Test fun pendingOrdersByReceivedAtAscending() = runTest {
        dao.insertAll(listOf(
            record("late", receivedAt = 300),
            record("early", receivedAt = 100),
            record("mid", receivedAt = 200),
        ))
        val order = dao.pending(cap).map { it.deviceSmsId }
        assertEquals(listOf("early", "mid", "late"), order)
    }

    @Test fun requeueRangeFlipsOnlyTerminalRowsInsideWindow() = runTest {
        dao.insertAll(listOf(
            record("in_synced", status = SyncStatus.SYNCED, retry = 3, receivedAt = 150),
            record("in_dup", status = SyncStatus.DUPLICATE, receivedAt = 160),
            record("in_failed", status = SyncStatus.FAILED, retry = 10, receivedAt = 170),
            record("in_auth", status = SyncStatus.AUTH_ERROR, retry = 0, receivedAt = 175),
            record("in_pending", status = SyncStatus.PENDING, receivedAt = 180),
            record("out_synced", status = SyncStatus.SYNCED, receivedAt = 500),
        ))
        val flipped = dao.requeueRange(from = 100, to = 200)
        assertEquals(4, flipped) // in_synced, in_dup, in_failed, in_auth

        listOf("in_synced", "in_dup", "in_failed", "in_auth").forEach { id ->
            val row = dao.byId(id)!!
            assertEquals(SyncStatus.PENDING, row.syncStatus)
            assertEquals(0, row.retryCount)
        }
        // already-pending row in window is untouched; row outside the window stays terminal
        assertEquals(SyncStatus.PENDING, dao.byId("in_pending")!!.syncStatus)
        assertEquals(SyncStatus.SYNCED, dao.byId("out_synced")!!.syncStatus)
        // idempotent on the row set — nothing inserted or deleted
        assertEquals(6, dao.allIds().size)
        assertTrue(dao.pending(cap).map { it.deviceSmsId }
            .containsAll(listOf("in_synced", "in_dup", "in_failed", "in_auth")))
    }

    @Test fun requeueAuthErrorsRecoversOnlyRowsRejectedByOldCredentials() = runTest {
        dao.insertAll(listOf(
            record("auth", status = SyncStatus.AUTH_ERROR, retry = 4),
            record("failed", status = SyncStatus.FAILED, retry = cap),
            record("pending", status = SyncStatus.PENDING, retry = 2),
        ))

        assertEquals(1, dao.requeueAuthErrors())
        val recovered = dao.byId("auth")!!
        assertEquals(SyncStatus.PENDING, recovered.syncStatus)
        assertEquals(0, recovered.retryCount)
        assertEquals(SyncStatus.FAILED, dao.byId("failed")!!.syncStatus)
        assertEquals(2, dao.byId("pending")!!.retryCount)
    }

    @Test fun updateResultPersistsParsedFields() = runTest {
        dao.insertAll(listOf(record("a", status = SyncStatus.PENDING)))
        dao.updateResult(
            "a", SyncStatus.DUPLICATE, txnId = 42L, fp = "fp-1", error = null, syncedAt = 999,
            pAmount = "1500.00", pCurrency = "UZS", pTxnDate = "2026-05-31T10:00:00", pCardLast4 = "0907",
            pOperator = "UZCARD", pTxnType = "DEBIT", pBalanceAfter = "9000.00", pApplication = "Uzcard",
        )
        val row = dao.byId("a")!!
        assertEquals(SyncStatus.DUPLICATE, row.syncStatus)
        assertEquals(42L, row.backendTransactionId)
        assertEquals("1500.00", row.pAmount)
        assertEquals("UZS", row.pCurrency)
        assertEquals("0907", row.pCardLast4)
        assertEquals("DEBIT", row.pTxnType)
        assertEquals("9000.00", row.pBalanceAfter)
        assertEquals("Uzcard", row.pApplication)
    }

    @Test fun purgeOldDeletesOnlyAcknowledgedRowsBeforeCutoff() = runTest {
        dao.insertAll(listOf(
            record("old_synced").copy(syncStatus = SyncStatus.SYNCED, syncedAt = 100),
            record("new_synced").copy(syncStatus = SyncStatus.SYNCED, syncedAt = 900),
            record("old_pending").copy(syncStatus = SyncStatus.PENDING, syncedAt = null),
        ))
        dao.purgeOld(cutoff = 500)
        val remaining = dao.allIds().toSet()
        assertEquals(setOf("new_synced", "old_pending"), remaining)
    }
}
