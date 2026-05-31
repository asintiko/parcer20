package uz.tbsparcer.sms.work

import android.content.Context
import androidx.hilt.work.HiltWorker
import androidx.work.CoroutineWorker
import androidx.work.WorkerParameters
import dagger.assisted.Assisted
import dagger.assisted.AssistedInject
import uz.tbsparcer.sms.data.local.SettingsStore
import uz.tbsparcer.sms.data.repo.SmsRepository

@HiltWorker
class BackfillWorker @AssistedInject constructor(
    @Assisted ctx: Context,
    @Assisted params: WorkerParameters,
    private val repo: SmsRepository,
    private val settings: SettingsStore,
) : CoroutineWorker(ctx, params) {
    override suspend fun doWork(): Result {
        repo.collectFromInbox(settings.backfillSinceMillis)
        repo.syncPending()
        return Result.success()
    }
}
