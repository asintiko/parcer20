package uz.tbsparcer.sms.ui.vm

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.launch
import uz.tbsparcer.sms.data.local.SmsRecord
import uz.tbsparcer.sms.data.repo.SmsRepository
import javax.inject.Inject

@HiltViewModel
class SmsDetailViewModel @Inject constructor(private val repo: SmsRepository) : ViewModel() {
    val record = MutableStateFlow<SmsRecord?>(null)
    fun load(id: String) { viewModelScope.launch { record.value = repo.byId(id) } }
}
