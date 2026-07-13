package uz.tbsparcer.sms

import androidx.sqlite.db.SupportSQLiteDatabase
import androidx.sqlite.db.SupportSQLiteOpenHelper
import androidx.sqlite.db.framework.FrameworkSQLiteOpenHelperFactory
import androidx.test.core.app.ApplicationProvider
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config
import uz.tbsparcer.sms.data.local.MIGRATION_1_2
import uz.tbsparcer.sms.data.local.MIGRATION_2_3

/**
 * The schema is not exported (exportSchema = false), so MigrationTestHelper can't be used.
 * Instead build the real v1 table, run [MIGRATION_1_2], and assert the new columns/indices
 * land and existing rows survive — this exercises the migration SQL itself.
 */
@RunWith(RobolectricTestRunner::class)
@Config(sdk = [34])
class MigrationTest {
    private lateinit var helper: SupportSQLiteOpenHelper
    private lateinit var db: SupportSQLiteDatabase

    private val v1Table = """
        CREATE TABLE sms_records (
            deviceSmsId TEXT NOT NULL PRIMARY KEY,
            sender TEXT NOT NULL,
            body TEXT NOT NULL,
            receivedAt INTEGER NOT NULL,
            simSlot INTEGER,
            fingerprint TEXT,
            syncStatus TEXT NOT NULL,
            backendTransactionId INTEGER,
            errorMessage TEXT,
            syncedAt INTEGER,
            createdAt INTEGER NOT NULL
        )
    """.trimIndent()

    @Before fun setUp() {
        val cfg = SupportSQLiteOpenHelper.Configuration.builder(ApplicationProvider.getApplicationContext())
            .name(null) // in-memory
            .callback(object : SupportSQLiteOpenHelper.Callback(1) {
                override fun onCreate(db: SupportSQLiteDatabase) { db.execSQL(v1Table) }
                override fun onUpgrade(db: SupportSQLiteDatabase, oldVersion: Int, newVersion: Int) {}
            })
            .build()
        helper = FrameworkSQLiteOpenHelperFactory().create(cfg)
        db = helper.writableDatabase
    }

    @After fun tearDown() = helper.close()

    @Test fun migration1to2AddsColumnsIndicesAndPreservesRows() {
        db.execSQL(
            "INSERT INTO sms_records " +
                "(deviceSmsId, sender, body, receivedAt, syncStatus, createdAt) " +
                "VALUES ('id1', 'UZCARD', 'Pokupka', 100, 'pending', 0)"
        )

        MIGRATION_1_2.migrate(db)

        // new columns with the v1 row backfilled to the declared defaults
        db.query("SELECT retryCount, nextAttemptAt FROM sms_records WHERE deviceSmsId = 'id1'").use { c ->
            assertTrue(c.moveToFirst())
            assertEquals(0, c.getInt(0))
            assertTrue(c.isNull(1))
        }

        val indices = mutableSetOf<String>()
        db.query("PRAGMA index_list(sms_records)").use { c ->
            val nameCol = c.getColumnIndexOrThrow("name")
            while (c.moveToNext()) indices += c.getString(nameCol)
        }
        assertTrue("index_sms_records_syncStatus" in indices)
        assertTrue("index_sms_records_fingerprint" in indices)
    }

    @Test fun migration1to2to3AddsParsedColumnsAndPreservesRows() {
        db.execSQL(
            "INSERT INTO sms_records " +
                "(deviceSmsId, sender, body, receivedAt, syncStatus, createdAt) " +
                "VALUES ('id1', 'UZCARD', 'Pokupka', 100, 'synced', 0)"
        )

        MIGRATION_1_2.migrate(db)
        MIGRATION_2_3.migrate(db)

        // The 8 parsed columns exist and the pre-existing row survives, backfilled to NULL.
        db.query(
            "SELECT pAmount, pCurrency, pTxnDate, pCardLast4, pOperator, pTxnType, " +
                "pBalanceAfter, pApplication FROM sms_records WHERE deviceSmsId = 'id1'"
        ).use { c ->
            assertTrue(c.moveToFirst())
            assertEquals(8, c.columnCount)
            for (i in 0 until 8) assertTrue(c.isNull(i))
        }
    }
}
