package uz.tbsparcer.sms.work

import android.content.Context
import androidx.hilt.work.HiltWorker
import androidx.work.CoroutineWorker
import androidx.work.WorkerParameters
import dagger.assisted.Assisted
import dagger.assisted.AssistedInject
import uz.tbsparcer.sms.data.local.SettingsStore
import uz.tbsparcer.sms.data.repo.SmsRepository
import uz.tbsparcer.sms.data.repo.SyncOutcome

@HiltWorker
class SyncWorker @AssistedInject constructor(
    @Assisted ctx: Context,
    @Assisted params: WorkerParameters,
    private val repo: SmsRepository,
    private val settings: SettingsStore,
) : CoroutineWorker(ctx, params) {
    override suspend fun doWork(): Result {
        if (!settings.monitoringEnabled) return Result.success()
        val result = when (repo.syncPending()) {
            is SyncOutcome.AuthError -> {
                // Known-bad key won't self-heal; don't hammer the server. Surface it in the UI.
                settings.authError = true
                Result.success()
            }
            is SyncOutcome.Retry -> Result.retry()
            else -> Result.success()
        }
        // Drop acknowledged SMS bodies after a retention window to limit on-device PII.
        repo.purgeOld(System.currentTimeMillis() - RETENTION_MILLIS)
        return result
    }

    private companion object {
        const val RETENTION_MILLIS = 14L * 24 * 60 * 60 * 1000
    }
}
