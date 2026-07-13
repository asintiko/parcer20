package uz.tbsparcer.sms.ui.vm

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import uz.tbsparcer.sms.data.local.SettingsStore
import uz.tbsparcer.sms.data.repo.SenderInfo
import uz.tbsparcer.sms.data.repo.SmsRepository
import javax.inject.Inject

data class SenderSelectUi(
    val loading: Boolean = true,
    val senders: List<SenderInfo> = emptyList(),
    // Normalized keys (trim+lowercase) currently checked. Empty after a load with no prior choice
    // means "all" — but the UI distinguishes that via [hadPriorSelection].
    val selected: Set<String> = emptySet(),
    val saved: Boolean = false,
)

@HiltViewModel
class SenderSelectViewModel @Inject constructor(
    private val repo: SmsRepository,
    private val settings: SettingsStore,
) : ViewModel() {
    private val _ui = MutableStateFlow(SenderSelectUi())
    val ui: StateFlow<SenderSelectUi> = _ui.asStateFlow()

    init { load() }

    fun load() {
        _ui.value = _ui.value.copy(loading = true, saved = false)
        viewModelScope.launch {
            val senders = withContext(Dispatchers.IO) { repo.listInboxSenders() }
            val prior = settings.selectedSenders
            // No prior choice → preselect everything that looks like a bank, so "Готово" is a
            // sensible default the user can trim.
            val initial = if (prior.isNotEmpty()) prior
            else senders.filter { it.looksBank }.map { SmsRepository.normalizeSender(it.address) }.toSet()
            _ui.value = SenderSelectUi(loading = false, senders = senders, selected = initial)
        }
    }

    fun toggle(address: String) {
        val key = SmsRepository.normalizeSender(address)
        val cur = _ui.value.selected
        _ui.value = _ui.value.copy(
            selected = if (key in cur) cur - key else cur + key,
            saved = false,
        )
    }

    fun selectAllBanks() {
        val banks = _ui.value.senders.filter { it.looksBank }
            .map { SmsRepository.normalizeSender(it.address) }.toSet()
        _ui.value = _ui.value.copy(selected = _ui.value.selected + banks, saved = false)
    }

    fun save() {
        settings.selectedSenders = _ui.value.selected
        _ui.value = _ui.value.copy(saved = true)
    }
}
