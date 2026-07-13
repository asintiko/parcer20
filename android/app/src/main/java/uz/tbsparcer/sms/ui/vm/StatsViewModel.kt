package uz.tbsparcer.sms.ui.vm

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import uz.tbsparcer.sms.data.remote.SmsStatsResponse
import uz.tbsparcer.sms.data.remote.SourceItem
import uz.tbsparcer.sms.data.repo.SmsRepository
import uz.tbsparcer.sms.data.repo.StatsRepository
import uz.tbsparcer.sms.domain.SyncStatus
import javax.inject.Inject

data class StatsUi(
    val loading: Boolean = false,
    val error: String? = null,
    val stats: SmsStatsResponse? = null,
    val sources: List<SourceItem> = emptyList(),
    val localFailed: Int = 0,
    val source: String = "all",
    val chatId: Long? = null,
    val card: String = "",
    val dateFrom: String? = null,
    val dateTo: String? = null,
)

@HiltViewModel
class StatsViewModel @Inject constructor(
    private val statsRepo: StatsRepository,
    private val smsRepo: SmsRepository,
) : ViewModel() {
    private val _ui = MutableStateFlow(StatsUi())
    val ui = _ui.asStateFlow()

    init {
        viewModelScope.launch {
            smsRepo.statusCounts().collect { list ->
                val problematic = setOf(SyncStatus.ERROR, SyncStatus.FAILED, SyncStatus.AUTH_ERROR, SyncStatus.SKIPPED)
                val failed = list.filter { it.syncStatus in problematic }.sumOf { it.n }
                _ui.value = _ui.value.copy(localFailed = failed)
            }
        }
    }

    fun setSource(s: String) { _ui.value = _ui.value.copy(source = s, chatId = null); load() }
    fun setChat(id: Long?) { _ui.value = _ui.value.copy(chatId = id); load() }
    fun setCard(c: String) { _ui.value = _ui.value.copy(card = c); load() }
    fun setRange(from: String?, to: String?) { _ui.value = _ui.value.copy(dateFrom = from, dateTo = to); load() }

    fun load() {
        val s = _ui.value
        _ui.value = s.copy(loading = true, error = null)
        viewModelScope.launch {
            val stats = try {
                statsRepo.stats(
                    s.dateFrom, s.dateTo, s.source, s.chatId,
                    s.card.takeIf { it.length == 4 },
                )
            } catch (e: Exception) {
                _ui.value = _ui.value.copy(loading = false, error = e.message ?: "error")
                return@launch
            }
            _ui.value = _ui.value.copy(loading = false, stats = stats)
            if (_ui.value.sources.isEmpty()) {
                try {
                    val srcs = statsRepo.sources().items
                    _ui.value = _ui.value.copy(sources = srcs)
                } catch (_: Exception) {
                    // sources is secondary (Telegram bot picker); ignore failure, keep stats
                }
            }
        }
    }
}
