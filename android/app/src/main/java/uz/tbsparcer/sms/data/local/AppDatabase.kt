package uz.tbsparcer.sms.data.local

import androidx.room.Database
import androidx.room.RoomDatabase

@Database(entities = [SmsRecord::class], version = 1, exportSchema = false)
abstract class AppDatabase : RoomDatabase() {
    abstract fun smsDao(): SmsRecordDao
}
