package uz.tbsparcer.sms.ui.vm

import android.app.Application
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.flow.flow
import kotlinx.coroutines.flow.stateIn
import uz.tbsparcer.sms.data.repo.SmsRepository
import uz.tbsparcer.sms.data.repo.StatsRepository
import uz.tbsparcer.sms.domain.SyncStatus
import uz.tbsparcer.sms.work.WorkScheduler
import javax.inject.Inject

/** Live counters derived from the local Room queue — the phone's own view of the pipeline. */
data class DashboardUi(
    val total: Int = 0,
    val synced: Int = 0,
    val duplicate: Int = 0,
    val skipped: Int = 0,
    val errors: Int = 0,
    val pending: Int = 0,
    val accuracyPct: Int = 0,
    val online: Boolean = false,
    val authError: Boolean = false,
    val lastSyncedAt: Long? = null,
)

/** Server-side money totals (all sources), refreshed on a slow poll. */
data class MoneyUi(
    val loading: Boolean = true,
    val totalVolume: String? = null,
    val debitVolume: String? = null,
    val creditVolume: String? = null,
    val currency: String = "UZS",
    val error: String? = null,
)

@HiltViewModel
class DashboardViewModel @Inject constructor(
    app: Application,
    private val repo: SmsRepository,
    private val statsRepo: StatsRepository,
) : AndroidViewModel(app) {

    val ui: StateFlow<DashboardUi> = combine(
        repo.statusCounts(), repo.totalCount(), repo.lastSyncedAt(),
    ) { counts, total, last ->
        val m = counts.associate { it.syncStatus to it.n }
        val synced = m[SyncStatus.SYNCED] ?: 0
        val duplicate = m[SyncStatus.DUPLICATE] ?: 0
        val skipped = m[SyncStatus.SKIPPED] ?: 0
        val errors = (m[SyncStatus.ERROR] ?: 0) + (m[SyncStatus.FAILED] ?: 0) + (m[SyncStatus.AUTH_ERROR] ?: 0)
        val pending = m[SyncStatus.PENDING] ?: 0
        val processed = synced + duplicate
        val denom = processed + skipped + errors
        val authError = repo.authError()
        val fresh = last != null && System.currentTimeMillis() - last < FRESH_WINDOW_MS
        DashboardUi(
            total = total, synced = synced, duplicate = duplicate, skipped = skipped,
            errors = errors, pending = pending,
            accuracyPct = if (denom > 0) processed * 100 / denom else 0,
            online = fresh && !authError, authError = authError, lastSyncedAt = last,
        )
    }.stateIn(viewModelScope, SharingStarted.WhileSubscribed(5000), DashboardUi())

    // Network money totals on a 60s poll. Keep the last good values across a transient failure
    // (only overlay loading=false + error) so the figures don't blank out when offline.
    private var lastMoney = MoneyUi()
    val money: StateFlow<MoneyUi> = flow {
        while (true) {
            lastMoney = try {
                val s = statsRepo.stats(null, null, "all", null, null)
                MoneyUi(false, s.totalVolume, s.debitVolume, s.creditVolume, s.currency)
            } catch (e: Exception) {
                lastMoney.copy(loading = false, error = e.message?.take(120))
            }
            emit(lastMoney)
            delay(REFRESH_MS)
        }
    }.stateIn(viewModelScope, SharingStarted.WhileSubscribed(5000), MoneyUi())

    fun syncNow() = WorkScheduler.syncNow(getApplication())

    private companion object {
        const val FRESH_WINDOW_MS = 30L * 60 * 1000
        const val REFRESH_MS = 60_000L
    }
}
