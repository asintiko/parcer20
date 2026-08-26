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
    fun save(baseUrl: String, deviceId: String, mobileKey: String, theme: String): Boolean {
        val credentialsChanged = deviceId.trim() != settings.deviceId || mobileKey.trim() != settings.mobileKey
        if (!settings.saveProvisioning(deviceId, mobileKey)) return false
        settings.baseUrl = baseUrl.trim()
        settings.themeMode = theme
        if (settings.monitoringEnabled) {
            WorkScheduler.schedulePeriodic(getApplication())
            if (credentialsChanged) WorkScheduler.runBackfill(getApplication())
        }
        return true
    }

    fun saveProvisioning(deviceId: String, mobileKey: String): Boolean =
        settings.saveProvisioning(deviceId, mobileKey)

    fun completeOnboarding(): Boolean {
        if (!settings.completeOnboarding()) return false
        WorkScheduler.schedulePeriodic(getApplication())
        return true
    }

    fun setBackfillDate(millis: Long) { settings.backfillSinceMillis = millis }
    fun runBackfill() = WorkScheduler.runBackfill(getApplication())
    fun runReconcile(from: Long, to: Long) = WorkScheduler.runReconcile(getApplication(), from, to)
    fun clearLocal() = viewModelScope.launch { repo.clear() }
}
