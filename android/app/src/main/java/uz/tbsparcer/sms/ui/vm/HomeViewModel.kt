package uz.tbsparcer.sms.ui.vm

import android.app.Application
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.flow.*
import uz.tbsparcer.sms.data.local.SmsRecord
import uz.tbsparcer.sms.data.repo.SmsRepository
import uz.tbsparcer.sms.work.WorkScheduler
import javax.inject.Inject

/** Derived connectivity state shown in the Home status pill. */
data class HomeStatus(
    val online: Boolean,
    val authError: Boolean,
    val lastSyncedAt: Long?,
)

@HiltViewModel
class HomeViewModel @Inject constructor(
    app: Application,
    private val repo: SmsRepository,
) : AndroidViewModel(app) {
    val filter = MutableStateFlow("all")

    @OptIn(kotlinx.coroutines.ExperimentalCoroutinesApi::class)
    val records: StateFlow<List<SmsRecord>> = filter.flatMapLatest { f ->
        if (f == "all") repo.recent() else repo.byStatus(f)
    }.stateIn(viewModelScope, SharingStarted.WhileSubscribed(5000), emptyList())

    val counts = repo.statusCounts()
        .map { list -> list.associate { it.syncStatus to it.n } }
        .stateIn(viewModelScope, SharingStarted.WhileSubscribed(5000), emptyMap())

    // Re-read the (non-reactive) authError flag whenever the worker touches the DB; treat the
    // pipeline as "online" only if the key is valid AND a sync landed within the poll window.
    val status: StateFlow<HomeStatus> = repo.lastSyncedAt()
        .map { last ->
            val authError = repo.authError()
            val fresh = last != null && System.currentTimeMillis() - last < FRESH_WINDOW_MS
            HomeStatus(online = fresh && !authError, authError = authError, lastSyncedAt = last)
        }
        .stateIn(viewModelScope, SharingStarted.WhileSubscribed(5000), HomeStatus(false, false, null))

    fun setFilter(f: String) { filter.value = f }
    fun syncNow() = WorkScheduler.syncNow(getApplication())

    private companion object {
        const val FRESH_WINDOW_MS = 30L * 60 * 1000
    }
}
