package uz.tbsparcer.sms.ui.vm

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import uz.tbsparcer.sms.data.repo.StatsRepository
import javax.inject.Inject

data class DiagUi(
    val checking: Boolean = false,
    val backendOk: Boolean? = null,
    val latencyMs: Long? = null,
    val version: String? = null,
    val dbStatus: String? = null,
    val keyValid: Boolean? = null,
    val message: String? = null,
)

@HiltViewModel
class DiagnosticsViewModel @Inject constructor(
    private val statsRepo: StatsRepository,
) : ViewModel() {
    private val _ui = MutableStateFlow(DiagUi())
    val ui = _ui.asStateFlow()

    fun runChecks() {
        _ui.value = DiagUi(checking = true)
        viewModelScope.launch {
            val start = System.currentTimeMillis()
            try {
                val h = statsRepo.health()
                _ui.value = DiagUi(
                    checking = false, backendOk = true,
                    latencyMs = System.currentTimeMillis() - start,
                    version = h.version, dbStatus = h.db, keyValid = true,
                )
            } catch (e: retrofit2.HttpException) {
                _ui.value = DiagUi(checking = false, backendOk = true,
                    keyValid = e.code() != 403 && e.code() != 503,
                    message = "HTTP ${e.code()}")
            } catch (e: Exception) {
                _ui.value = DiagUi(checking = false, backendOk = false, message = e.message)
            }
        }
    }
}
