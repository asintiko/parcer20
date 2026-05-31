package uz.tbsparcer.sms.work

import android.content.Context
import androidx.work.Constraints
import androidx.work.ExistingPeriodicWorkPolicy
import androidx.work.ExistingWorkPolicy
import androidx.work.NetworkType
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.PeriodicWorkRequestBuilder
import androidx.work.WorkManager
import java.util.concurrent.TimeUnit

object WorkScheduler {
    private val netConstraint = Constraints.Builder()
        .setRequiredNetworkType(NetworkType.CONNECTED).build()

    fun schedulePeriodic(ctx: Context) {
        val req = PeriodicWorkRequestBuilder<SyncWorker>(15, TimeUnit.MINUTES)
            .setConstraints(netConstraint).build()
        WorkManager.getInstance(ctx)
            .enqueueUniquePeriodicWork("sms_sync", ExistingPeriodicWorkPolicy.KEEP, req)
    }

    fun syncNow(ctx: Context) {
        val req = OneTimeWorkRequestBuilder<SyncWorker>()
            .setConstraints(netConstraint)
            .build()
        WorkManager.getInstance(ctx)
            .enqueueUniqueWork("sms_sync_now", ExistingWorkPolicy.REPLACE, req)
    }

    fun runBackfill(ctx: Context) {
        val req = OneTimeWorkRequestBuilder<BackfillWorker>()
            .setConstraints(netConstraint).build()
        WorkManager.getInstance(ctx)
            .enqueueUniqueWork("sms_backfill", ExistingWorkPolicy.REPLACE, req)
    }
}
