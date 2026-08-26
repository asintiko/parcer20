package uz.tbsparcer.sms.work

import android.content.Context
import androidx.work.BackoffPolicy
import androidx.work.Constraints
import androidx.work.ExistingPeriodicWorkPolicy
import androidx.work.ExistingWorkPolicy
import androidx.work.NetworkType
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.PeriodicWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.workDataOf
import java.util.concurrent.TimeUnit

object WorkScheduler {
    private const val PERIODIC_SYNC = "sms_sync"
    private const val IMMEDIATE_SYNC = "sms_sync_now"
    private const val BACKFILL = "sms_backfill"
    private const val RECONCILE = "sms_reconcile"

    private val netConstraint = Constraints.Builder()
        .setRequiredNetworkType(NetworkType.CONNECTED).build()

    fun schedulePeriodic(ctx: Context) {
        val req = PeriodicWorkRequestBuilder<SyncWorker>(15, TimeUnit.MINUTES)
            .setConstraints(netConstraint)
            .setBackoffCriteria(BackoffPolicy.EXPONENTIAL, 30, TimeUnit.SECONDS)
            .build()
        WorkManager.getInstance(ctx)
            .enqueueUniquePeriodicWork(PERIODIC_SYNC, ExistingPeriodicWorkPolicy.KEEP, req)
    }

    fun syncNow(ctx: Context) {
        val req = OneTimeWorkRequestBuilder<SyncWorker>()
            .setConstraints(netConstraint)
            .setBackoffCriteria(BackoffPolicy.EXPONENTIAL, 30, TimeUnit.SECONDS)
            .build()
        WorkManager.getInstance(ctx)
            .enqueueUniqueWork(IMMEDIATE_SYNC, ExistingWorkPolicy.REPLACE, req)
    }

    fun runBackfill(ctx: Context) {
        val req = OneTimeWorkRequestBuilder<BackfillWorker>()
            .setConstraints(netConstraint).build()
        WorkManager.getInstance(ctx)
            .enqueueUniqueWork(BACKFILL, ExistingWorkPolicy.REPLACE, req)
    }

    fun runReconcile(ctx: Context, from: Long, to: Long) {
        val req = OneTimeWorkRequestBuilder<ReconcileWorker>()
            .setConstraints(netConstraint)
            .setInputData(workDataOf(ReconcileWorker.KEY_FROM to from, ReconcileWorker.KEY_TO to to))
            .setBackoffCriteria(BackoffPolicy.EXPONENTIAL, 30, TimeUnit.SECONDS)
            .build()
        WorkManager.getInstance(ctx)
            .enqueueUniqueWork(RECONCILE, ExistingWorkPolicy.REPLACE, req)
    }

    fun pauseMonitoring(ctx: Context) {
        val workManager = WorkManager.getInstance(ctx)
        workManager.cancelUniqueWork(PERIODIC_SYNC)
        workManager.cancelUniqueWork(IMMEDIATE_SYNC)
        workManager.cancelUniqueWork(BACKFILL)
        workManager.cancelUniqueWork(RECONCILE)
    }
}
