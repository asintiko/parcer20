package uz.tbsparcer.sms.ui.vm

import android.app.Application
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.flow.*
import uz.tbsparcer.sms.data.local.SmsRecord
import uz.tbsparcer.sms.data.repo.SmsRepository
import uz.tbsparcer.sms.work.WorkScheduler
import javax.inject.Inject

@HiltViewModel
class ReconcileViewModel @Inject constructor(
    app: Application,
    private val repo: SmsRepository,
) : AndroidViewModel(app) {
    // null until the user runs a reconcile; drives the windowed report below.
    private val window = MutableStateFlow<Pair<Long, Long>?>(null)
    val started: StateFlow<Boolean> = window.map { it != null }
        .stateIn(viewModelScope, SharingStarted.WhileSubscribed(5000), false)

    @OptIn(ExperimentalCoroutinesApi::class)
    val counts: StateFlow<Map<String, Int>> = window.flatMapLatest { w ->
        if (w == null) flowOf(emptyMap())
        else repo.statusCountsInRange(w.first, w.second).map { l -> l.associate { it.syncStatus to it.n } }
    }.stateIn(viewModelScope, SharingStarted.WhileSubscribed(5000), emptyMap())

    @OptIn(ExperimentalCoroutinesApi::class)
    val records: StateFlow<List<SmsRecord>> = window.flatMapLatest { w ->
        if (w == null) flowOf(emptyList()) else repo.byRange(w.first, w.second)
    }.stateIn(viewModelScope, SharingStarted.WhileSubscribed(5000), emptyList())

    fun reconcile(from: Long, to: Long) {
        window.value = from to to
        WorkScheduler.runReconcile(getApplication(), from, to)
    }
}
