package uz.tbsparcer.sms.di

import android.content.Context
import androidx.room.Room
import dagger.Module
import dagger.Provides
import dagger.hilt.InstallIn
import dagger.hilt.android.qualifiers.ApplicationContext
import dagger.hilt.components.SingletonComponent
import javax.inject.Singleton
import uz.tbsparcer.sms.data.local.AppDatabase
import uz.tbsparcer.sms.data.local.SmsRecordDao

@Module
@InstallIn(SingletonComponent::class)
object DatabaseModule {
    @Provides @Singleton
    fun db(@ApplicationContext ctx: Context): AppDatabase =
        Room.databaseBuilder(ctx, AppDatabase::class.java, "tbsparcer.db").build()

    @Provides
    fun dao(db: AppDatabase): SmsRecordDao = db.smsDao()
}
