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

    fun setFilter(f: String) { filter.value = f }
    fun syncNow() = WorkScheduler.syncNow(getApplication())
}
