package uz.tbsparcer.sms.ui.vm

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import uz.tbsparcer.sms.data.remote.AppUpdateManifest
import uz.tbsparcer.sms.data.repo.UpdateRepository
import uz.tbsparcer.sms.data.repo.UpdateStatus
import java.io.File
import javax.inject.Inject

sealed interface UpdateUi {
    data object Idle : UpdateUi
    data object Checking : UpdateUi
    data class UpToDate(val version: String) : UpdateUi
    data class Available(val manifest: AppUpdateManifest) : UpdateUi
    data class Downloading(val manifest: AppUpdateManifest, val percent: Int) : UpdateUi
    data class NeedsPermission(val manifest: AppUpdateManifest, val file: File) : UpdateUi
    data class Error(val message: String) : UpdateUi
}

@HiltViewModel
class UpdateViewModel @Inject constructor(
    private val repo: UpdateRepository,
) : ViewModel() {

    private val _ui = MutableStateFlow<UpdateUi>(UpdateUi.Idle)
    val ui: StateFlow<UpdateUi> = _ui.asStateFlow()

    fun check() {
        _ui.value = UpdateUi.Checking
        viewModelScope.launch {
            _ui.value = when (val s = repo.check()) {
                is UpdateStatus.UpToDate -> UpdateUi.UpToDate(s.current)
                is UpdateStatus.Available -> UpdateUi.Available(s.manifest)
                is UpdateStatus.Error -> UpdateUi.Error(s.message)
            }
        }
    }

    fun downloadAndInstall() {
        val manifest = when (val cur = _ui.value) {
            is UpdateUi.Available -> cur.manifest
            is UpdateUi.NeedsPermission -> cur.manifest
            is UpdateUi.Error -> return
            else -> return
        }
        val pendingPermission = _ui.value as? UpdateUi.NeedsPermission
        viewModelScope.launch {
            try {
                if (pendingPermission?.file?.exists() == true) {
                    if (repo.install(pendingPermission.file, manifest)) {
                        _ui.value = UpdateUi.Available(manifest)
                    }
                    return@launch
                }
                _ui.value = UpdateUi.Downloading(manifest, 0)
                val file = repo.download(manifest) { pct ->
                    _ui.value = UpdateUi.Downloading(manifest, pct)
                }
                if (repo.install(file, manifest)) _ui.value = UpdateUi.Available(manifest)
                else _ui.value = UpdateUi.NeedsPermission(manifest, file)
            } catch (e: Exception) {
                _ui.value = UpdateUi.Error(e.message?.take(160) ?: "Ошибка загрузки")
            }
        }
    }
}
