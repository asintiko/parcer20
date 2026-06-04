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
class ReconcileWorker @AssistedInject constructor(
    @Assisted ctx: Context,
    @Assisted params: WorkerParameters,
    private val repo: SmsRepository,
) : CoroutineWorker(ctx, params) {
    override suspend fun doWork(): Result {
        val from = inputData.getLong(KEY_FROM, 0L)
        val to = inputData.getLong(KEY_TO, Long.MAX_VALUE)
        return when (repo.reconcile(from, to)) {
            is SyncOutcome.Retry -> Result.retry()
            else -> Result.success()
        }
    }

    companion object {
        const val KEY_FROM = "from"
        const val KEY_TO = "to"
    }
}
