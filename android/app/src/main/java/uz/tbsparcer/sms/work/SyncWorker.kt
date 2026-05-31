package uz.tbsparcer.sms.work

import android.content.Context
import androidx.hilt.work.HiltWorker
import androidx.work.CoroutineWorker
import androidx.work.WorkerParameters
import dagger.assisted.Assisted
import dagger.assisted.AssistedInject
import uz.tbsparcer.sms.data.repo.SmsRepository
import uz.tbsparcer.sms.data.repo.SyncOutcome

@HiltWorker
class SyncWorker @AssistedInject constructor(
    @Assisted ctx: Context,
    @Assisted params: WorkerParameters,
    private val repo: SmsRepository,
) : CoroutineWorker(ctx, params) {
    override suspend fun doWork(): Result =
        when (repo.syncPending()) {
            is SyncOutcome.Retry -> Result.retry()
            else -> Result.success()
        }
}
