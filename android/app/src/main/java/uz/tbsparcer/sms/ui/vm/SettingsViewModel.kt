package uz.tbsparcer.sms.ui.vm

import android.app.Application
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.launch
import uz.tbsparcer.sms.data.local.SettingsStore
import uz.tbsparcer.sms.data.repo.SmsRepository
import uz.tbsparcer.sms.work.WorkScheduler
import javax.inject.Inject

@HiltViewModel
class SettingsViewModel @Inject constructor(
    app: Application,
    val settings: SettingsStore,
    private val repo: SmsRepository,
) : AndroidViewModel(app) {
    fun save(baseUrl: String, mobileKey: String, theme: String) {
        settings.baseUrl = baseUrl.trim()
        settings.mobileKey = mobileKey.trim()
        settings.themeMode = theme
    }
    fun setBackfillDate(millis: Long) { settings.backfillSinceMillis = millis }
    fun runBackfill() = WorkScheduler.runBackfill(getApplication())
    fun runReconcile(from: Long, to: Long) = WorkScheduler.runReconcile(getApplication(), from, to)
    fun clearLocal() = viewModelScope.launch { repo.clear() }
}
