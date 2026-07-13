package uz.tbsparcer.sms.ui.vm

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import uz.tbsparcer.sms.data.local.SettingsStore
import uz.tbsparcer.sms.data.repo.StatsRepository
import javax.inject.Inject

data class DiagUi(
    val checking: Boolean = false,
    val backendOk: Boolean? = null,
    val latencyMs: Long? = null,
    val version: String? = null,
    val dbStatus: String? = null,
    val keyValid: Boolean? = null,
    val authError: Boolean = false,
    val message: String? = null,
)

@HiltViewModel
class DiagnosticsViewModel @Inject constructor(
    private val statsRepo: StatsRepository,
    private val settings: SettingsStore,
) : ViewModel() {
    private val _ui = MutableStateFlow(DiagUi())
    val ui = _ui.asStateFlow()

    fun runChecks() {
        _ui.value = DiagUi(checking = true, authError = settings.authError)
        viewModelScope.launch {
            val start = System.currentTimeMillis()
            try {
                val h = statsRepo.health()
                // A reachable backend with a valid health response means the key is not rejected;
                // clear any stale auth-error flag set by a previous failed sync.
                settings.authError = false
                _ui.value = DiagUi(
                    checking = false, backendOk = true,
                    latencyMs = System.currentTimeMillis() - start,
                    version = h.version, dbStatus = h.db, keyValid = true, authError = false,
                )
            } catch (e: retrofit2.HttpException) {
                val badKey = e.code() == 403
                if (badKey) settings.authError = true
                _ui.value = DiagUi(checking = false, backendOk = true,
                    keyValid = e.code() != 403 && e.code() != 503,
                    authError = settings.authError,
                    message = "HTTP ${e.code()}")
            } catch (e: Exception) {
                _ui.value = DiagUi(checking = false, backendOk = false,
                    authError = settings.authError, message = e.message)
            }
        }
    }
}
