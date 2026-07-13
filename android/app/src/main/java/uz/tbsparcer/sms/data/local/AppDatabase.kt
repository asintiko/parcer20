package uz.tbsparcer.sms.data.local

import androidx.room.Database
import androidx.room.RoomDatabase
import androidx.room.migration.Migration
import androidx.sqlite.db.SupportSQLiteDatabase

@Database(entities = [SmsRecord::class], version = 3, exportSchema = false)
abstract class AppDatabase : RoomDatabase() {
    abstract fun smsDao(): SmsRecordDao
}

/** v1 → v2: retry/backoff columns + indices on the hot lookup columns. */
val MIGRATION_1_2 = object : Migration(1, 2) {
    override fun migrate(db: SupportSQLiteDatabase) {
        db.execSQL("ALTER TABLE sms_records ADD COLUMN retryCount INTEGER NOT NULL DEFAULT 0")
        db.execSQL("ALTER TABLE sms_records ADD COLUMN nextAttemptAt INTEGER")
        db.execSQL("CREATE INDEX IF NOT EXISTS index_sms_records_syncStatus ON sms_records(syncStatus)")
        db.execSQL("CREATE INDEX IF NOT EXISTS index_sms_records_fingerprint ON sms_records(fingerprint)")
    }
}

/** v2 → v3: parsed-summary columns echoed back by the backend ingest response. */
val MIGRATION_2_3 = object : Migration(2, 3) {
    override fun migrate(db: SupportSQLiteDatabase) {
        db.execSQL("ALTER TABLE sms_records ADD COLUMN pAmount TEXT")
        db.execSQL("ALTER TABLE sms_records ADD COLUMN pCurrency TEXT")
        db.execSQL("ALTER TABLE sms_records ADD COLUMN pTxnDate TEXT")
        db.execSQL("ALTER TABLE sms_records ADD COLUMN pCardLast4 TEXT")
        db.execSQL("ALTER TABLE sms_records ADD COLUMN pOperator TEXT")
        db.execSQL("ALTER TABLE sms_records ADD COLUMN pTxnType TEXT")
        db.execSQL("ALTER TABLE sms_records ADD COLUMN pBalanceAfter TEXT")
        db.execSQL("ALTER TABLE sms_records ADD COLUMN pApplication TEXT")
    }
}
